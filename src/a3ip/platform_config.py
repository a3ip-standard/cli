"""
a3ip.platform_config -- parse and validate platform-config JSON files passed
to `a3ip scaffold --platform-config <path>`.

The JSON shape is documented in cli-repo/docs/platform-config.schema.json.
This module is the runtime loader. It validates the JSON manually (no
external jsonschema dependency) and returns typed objects the scaffold
templates iterate over.

The platform-config is an INTERNAL contract between the a3ip CLI and any
A3IP authoring tool (such as the a3ip-creator skill). It is not part of
the A3IP spec; alternative authoring tools may have entirely different
internal APIs.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


_KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass
class PlatformEntry:
    """Parameters describing one target platform."""

    id: str
    display_name: str
    default_config_dir: str        # contains the "{{name}}" placeholder
    install_method: str            # e.g. "cowork-skill", "generic-copy"
    host_os_default: str           # "windows" | "posix"
    description: str
    adapter_file_authored: bool

    def resolved_config_dir(self, package_name: str) -> str:
        """Return default_config_dir with the {{name}} placeholder substituted."""
        return self.default_config_dir.replace("{{name}}", package_name)


@dataclass
class PlatformConfig:
    """A loaded platform-config: maps platform-id -> PlatformEntry."""

    version: str = "1.0"
    platforms: Dict[str, PlatformEntry] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """True when no platforms are configured."""
        return not self.platforms

    def ordered_entries(self) -> List[PlatformEntry]:
        """Return platforms sorted alphabetically by id (stable iteration)."""
        return [self.platforms[k] for k in sorted(self.platforms.keys())]

    def get(self, platform_id: str) -> PlatformEntry:
        """Look up by id; KeyError if absent."""
        return self.platforms[platform_id]

    @classmethod
    def empty(cls) -> "PlatformConfig":
        """Empty config -- scaffolder emits neutral content with TODO markers."""
        return cls(version="1.0", platforms={})

    @classmethod
    def load(cls, path: Path) -> "PlatformConfig":
        """Load and validate a platform-config JSON file. Raises ValueError on any problem."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError("platform-config file not found: " + str(path))

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError("platform-config: invalid JSON at " + str(path) + ": " + str(e))

        return cls._from_dict(data, source=str(path))

    @classmethod
    def from_dict(cls, data: dict) -> "PlatformConfig":
        """Build a PlatformConfig from an in-memory dict (e.g. constructed programmatically)."""
        return cls._from_dict(data, source="<in-memory dict>")

    # -- Internal -------------------------------------------------------------

    @classmethod
    def _from_dict(cls, data, source: str) -> "PlatformConfig":
        if not isinstance(data, dict):
            raise ValueError(_err(source, "top-level must be a JSON object"))

        version = data.get("version", "1.0")
        if not isinstance(version, str):
            raise ValueError(_err(source, "'version' must be a string"))

        platforms_dict = data.get("platforms")
        if platforms_dict is None:
            raise ValueError(_err(source, "'platforms' field is required"))
        if not isinstance(platforms_dict, dict):
            raise ValueError(_err(source, "'platforms' must be an object"))
        if not platforms_dict:
            raise ValueError(_err(source, "'platforms' must contain at least one entry"))

        # Validate no unexpected top-level keys (be lenient on $schema)
        allowed_top = {"$schema", "version", "platforms"}
        unknown = set(data.keys()) - allowed_top
        if unknown:
            raise ValueError(_err(source, "unknown top-level fields: " + ", ".join(sorted(unknown))))

        platforms = {}
        for platform_id, entry_data in platforms_dict.items():
            if not isinstance(platform_id, str):
                raise ValueError(_err(source, "platform id must be a string"))
            if not _KEBAB_CASE_RE.match(platform_id):
                raise ValueError(_err(
                    source,
                    "platform id '" + platform_id + "' must be kebab-case "
                    "(lowercase letters, digits, hyphens; starts with a letter)",
                ))
            platforms[platform_id] = cls._parse_entry(platform_id, entry_data, source=source)

        return cls(version=version, platforms=platforms)

    @staticmethod
    def _parse_entry(platform_id: str, data, source: str) -> PlatformEntry:
        prefix = "platforms['" + platform_id + "']"

        if not isinstance(data, dict):
            raise ValueError(_err(source, prefix + " must be an object"))

        required_fields = (
            ("display_name", str),
            ("default_config_dir", str),
            ("install_method", str),
            ("host_os_default", str),
            ("description", str),
            ("adapter_file_authored", bool),
        )

        for field_name, expected_type in required_fields:
            if field_name not in data:
                raise ValueError(_err(source, prefix + "." + field_name + " is required"))
            value = data[field_name]
            if not isinstance(value, expected_type) or (expected_type is bool and not isinstance(value, bool)):
                # The bool isinstance check is special: bool is a subclass of int,
                # so we accept only true bools (not 0/1 integers).
                raise ValueError(_err(
                    source,
                    prefix + "." + field_name + " must be a " + expected_type.__name__,
                ))
            if expected_type is str and not value:
                raise ValueError(_err(source, prefix + "." + field_name + " must not be empty"))

        # Validate placeholder presence in default_config_dir
        if "{{name}}" not in data["default_config_dir"]:
            raise ValueError(_err(
                source,
                prefix + ".default_config_dir must contain the literal '{{name}}' placeholder",
            ))

        # Validate host_os_default enum
        if data["host_os_default"] not in ("windows", "posix"):
            raise ValueError(_err(
                source,
                prefix + ".host_os_default must be 'windows' or 'posix' (got '"
                + data["host_os_default"] + "')",
            ))

        # Validate no unexpected per-entry keys
        allowed_entry_keys = {name for name, _ in required_fields}
        unknown = set(data.keys()) - allowed_entry_keys
        if unknown:
            raise ValueError(_err(source, prefix + " has unknown fields: " + ", ".join(sorted(unknown))))

        return PlatformEntry(
            id=platform_id,
            display_name=data["display_name"],
            default_config_dir=data["default_config_dir"],
            install_method=data["install_method"],
            host_os_default=data["host_os_default"],
            description=data["description"],
            adapter_file_authored=data["adapter_file_authored"],
        )


def _err(source: str, message: str) -> str:
    return "platform-config " + source + ": " + message
