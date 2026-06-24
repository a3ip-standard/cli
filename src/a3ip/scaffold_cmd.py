#!/usr/bin/env python3
"""
A3IP Creator — scaffold.py
Generates a complete A3IP package directory from an intake.json file.

Usage:
    python3 scaffold.py <intake.json> <output_dir>

The package is created at: <output_dir>/<name>.a3ip/
"""

import json
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  created  {path}")


def kebab(s: str) -> str:
    return s.lower().replace(" ", "-").replace("_", "-")


def snake(s: str) -> str:
    return s.lower().replace(" ", "_").replace("-", "_")


def yaml_str(s: str, indent: int = 0) -> str:
    """Wrap a string for YAML — use block scalar if it contains newlines."""
    if "\n" in s or len(s) > 80:
        lines = textwrap.indent(s.strip(), "  " + " " * indent)
        return f">\n{lines}\n"
    return yaml_scalar(s)


def yaml_scalar(s: str) -> str:
    """Quote a single-line YAML scalar safely.

    Picks the quote style based on what the value contains:
      - no `"` and no `'`             → double-quoted (cleanest)
      - contains `"` but not `'`      → single-quoted (avoids escapes)
      - contains `'` but not `"`      → double-quoted (avoids escapes)
      - contains both                 → double-quoted with `"` escaped as `\"`

    This guards against the failure mode where a placeholder or default
    value contains an unescaped `"` (e.g. a JSON-shaped example like
    `[{"owner": "acme"}]`) that breaks the outer double-quoted scalar
    and makes the whole manifest.yaml fail yaml.safe_load.
    """
    if not isinstance(s, str):
        s = str(s)
    has_double = '"' in s
    has_single = "'" in s
    if has_double and not has_single:
        return f"'{s}'"
    if has_double and has_single:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f'"{s}"'


def yaml_list(items: list, indent: int = 2) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}- {json.dumps(item)}" for item in items)


# ─────────────────────────────────────────────────────────────
# manifest.yaml
# ─────────────────────────────────────────────────────────────

def _uses_v12_features(pkg: dict) -> bool:
    """Return True if the package declares any v1.2-specific fields."""
    scripts = pkg.get("scripts", [])
    for sc in scripts:
        if sc.get("trust_level"):
            return True
    if pkg.get("permissions"):
        return True
    for ck in pkg.get("configuration", []):
        if ck.get("storage"):
            return True
    return False



def ensure_spec_required_keys(pkg: dict, platform_config=None) -> None:
    """
    Inject config keys that the A3IP spec requires every package to declare.
    Mutates pkg in place. Idempotent.

    Currently:
      - install_dir: the directory where config.json, installed.json, and
        scripts live. Required by spec v1.2+ INSTALL.md template. The
        description tells the install AI to expand ~ to an absolute path
        before persisting (file-reading tools at runtime do not expand
        tildes, so storing the literal "~/..." breaks the runtime config
        lookup).

    platform_config (a3ip.platform_config.PlatformConfig | None):
      When provided and non-empty, the install_dir description lists each
      configured platform's default install_dir resolved with the package
      name substituted. When None or empty, the description uses a neutral
      TODO marker.
    """
    config_keys = pkg.get("configuration", [])
    name = pkg.get("name", "package")

    if not any(ck.get("key") == "install_dir" for ck in config_keys):
        # Build a platform-aware description from platform_config (if any).
        if platform_config is not None and not platform_config.is_empty():
            per_platform = [
                "  - " + p.display_name + ": " + p.resolved_config_dir(name)
                for p in platform_config.ordered_entries()
            ]
            defaults_block = (
                "Default depends on the target platform:\n"
                + "\n".join(per_platform)
            )
            # Use the first listed platform's default as the placeholder.
            first = platform_config.ordered_entries()[0]
            default = first.resolved_config_dir(name)
        else:
            defaults_block = (
                "TODO: provide platform-specific default install_dir values via "
                "`a3ip scaffold --platform-config <path>`. Without that flag, the "
                "scaffolder cannot recommend a default per platform."
            )
            default = "~/" + name + "/"

        install_dir_key = {
            "key": "install_dir",
            "label": "Installation directory",
            "description": (
                "Directory where " + name + "'s config.json, installed.json, and "
                "scripts will be stored. " + defaults_block + ". "
                "IMPORTANT for the install AI: expand the user-typed value to an "
                "absolute path before writing to config.json or installed.json. "
                "The path-expansion mechanism is host-runtime-specific -- consult "
                "adapters/runtime/<your-platform>/install-skill.md for the file-tool "
                "that expands `~` correctly on this host. The runtime AI reads the "
                "stored value as-is, so storing a literal `~` breaks the runtime "
                "config lookup. Strip trailing separators (slash or backslash) "
                "before storing."
            ),
            "type": "string",
            "required": True,
            "when": "before",
            "default": default,
            "placeholder": default,
            # v1.10: install_dir itself is meaningless after uninstall;
            # purge it silently rather than asking the user.
            "preserve_on_uninstall": False,
        }
        # Prepend so install_dir is asked first in the wizard
        pkg["configuration"] = [install_dir_key] + config_keys



# Adapter skeletons (v1.7 two-tier model)

WINDOWS_FILE_OPS = """# Windows file operations -- OS-level conventions

This adapter governs filesystem operations on a Windows host. It contains
ONLY OS-axis facts (path conventions, home-variable, expansion behavior).
Runtime-axis concerns -- which specific file tool to use for `~`-prefixed
paths, how a particular AI runtime sandboxes file access, what to do when
the runtime's bash sandbox conflicts with Windows paths -- live in
`adapters/runtime/<runtime>/install-skill.md`, NOT here.

## User home

On Windows, the user home directory is typically `C:/Users/<user>/`.
The environment variable is `%USERPROFILE%`. OneDrive-redirected home
folders are normal -- the resolved path may be under
`C:/Users/<user>/OneDrive/` rather than `C:/Users/<user>/`. Use whatever
resolved path the OS returns at install time.

## Path separator

In JSON files and most modern APIs, forward slashes are accepted.
Native Windows tooling (legacy APIs, batch scripts) prefers backslashes.
Strip trailing `/` and `\\` from any user-provided directory path before
storing it -- the spec's path-separator normalization rule applies on
every host OS.

## Persistent locations

Persistent install directories on Windows usually live under
`%USERPROFILE%/.<runtime>/packages/<name>/`. The exact subdirectory under
the user home is runtime-specific -- see the runtime adapter for the
target platform.

## Path expansion behavior

A bare `~` is NOT expanded by all file-reading APIs. Some tools auto-expand
it to `%USERPROFILE%`; others treat it as a literal directory named `~`.
The install adapter MUST resolve `~` to its absolute Windows path before
persisting any value to `config.json` or `installed.json`. Storing a
literal `~` breaks the runtime config lookup on any tool that does not
expand it.

Which specific tool/method to use for this expansion is a runtime concern
-- consult `adapters/runtime/<runtime>/install-skill.md` for that
platform's recommended approach.
"""

POSIX_FILE_OPS = """# POSIX (macOS / Linux) file operations -- OS-level conventions

This adapter governs filesystem operations on a POSIX host. It contains
ONLY OS-axis facts. Runtime-axis concerns -- which file tool, which
sandboxing model -- live in `adapters/runtime/<runtime>/install-skill.md`,
NOT here.

## User home

On POSIX systems, the user home is `/home/<user>/` on Linux and
`/Users/<user>/` on macOS. The environment variable is `$HOME`.

## Path separator

Forward slashes throughout.

## Persistent locations

Persistent install directories on POSIX usually live under
`~/.<runtime>/packages/<name>/`. The exact subdirectory under the home is
runtime-specific -- see the runtime adapter for the target platform.

## Path expansion behavior

Most POSIX file-reading APIs handle `~` natively (shell expansion, Python's
`os.path.expanduser`, etc.). Even so, the install adapter SHOULD resolve
`~` to an absolute path before persisting any value -- different tools at
runtime may treat `~` differently, and storing the expanded value makes the
file portable to runtimes that do not expand.

Strip trailing `/` from any user-provided directory path before storing it.
"""


def write_adapter_skeletons(pkg_dir, pkg):
    """Emit adapters/os/{windows,posix}/file-ops.md per spec v1.7."""
    write(pkg_dir / "adapters" / "os" / "windows" / "file-ops.md", WINDOWS_FILE_OPS)
    write(pkg_dir / "adapters" / "os" / "posix" / "file-ops.md", POSIX_FILE_OPS)


def build_manifest(pkg: dict) -> str:
    name = pkg["name"]
    version = pkg.get("version", "1.0.0")
    description = pkg.get("description", "")
    author = pkg.get("author", "")
    license_ = pkg.get("license", "proprietary")
    platforms = pkg.get("platforms", [])
    v12 = _uses_v12_features(pkg)

    now_date = datetime.utcnow().strftime("%Y-%m-%d")
    spec_ver = "1.10"
    lines = [
        "# ─────────────────────────────────────────",
        "# A3IP Manifest",
        f"# Generated by A3IP Creator on {now_date}",
        "# ─────────────────────────────────────────",
        "",
        f'a3ip: "{spec_ver}"',
        f'min_a3ip_spec: "{spec_ver}"',
        f"latest_change: {now_date}",
        f'name: "{name}"',
        f'version: "{version}"',
        f"description: >",
        f"  {description}",
        f'author: "{author}"',
        f'license: "{license_}"',
        "",
    ]

    # ── Components ──────────────────────────────────
    lines += ["# ─────────────────────────────────────────",
              "# Components",
              "# ─────────────────────────────────────────",
              "",
              "components:"]

    # Skills
    skills = pkg.get("skills", [])
    if skills:
        lines.append("  skills:")
        for s in skills:
            sname = kebab(s["name"])
            lines.append(f"    - path: components/skills/{sname}")
            lines.append(f'      description: "{s["description"]}"')
    else:
        lines.append("  skills: []")

    # Artifacts
    artifacts = pkg.get("artifacts", [])
    if artifacts:
        lines.append("")
        lines.append("  artifacts:")
        for a in artifacts:
            aname = kebab(a["name"])
            lines.append(f"    - path: components/artifacts/{aname}")
            lines.append(f'      description: "{a["description"]}"')
    else:
        lines.append("")
        lines.append("  artifacts: []")

    # Protocols
    protocols = pkg.get("protocols", [])
    if protocols:
        lines.append("")
        lines.append("  protocols:")
        for p in protocols:
            pname = kebab(p["name"])
            lines.append(f"    - path: components/protocols/{pname}.md")
            lines.append(f'      description: "{p["description"]}"')
    else:
        lines.append("")
        lines.append("  protocols: []")

    # Prompts
    prompts = pkg.get("prompts", [])
    if prompts:
        lines.append("")
        lines.append("  prompts:")
        for pr in prompts:
            prname = kebab(pr["name"])
            lines.append(f"    - path: components/prompts/{prname}.md")
            lines.append(f'      description: "{pr["description"]}"')
    else:
        lines.append("")
        lines.append("  prompts: []")

    # Scripts
    scripts = pkg.get("scripts", [])
    if scripts:
        lines += [
            "",
            "  scripts:",
            "    # Scripts follow a primary-plus-adapters pattern.",
            "    # 'any' platform = Python cross-platform default.",
            "    # 'windows' platform = PowerShell adapter in adapters/windows/scripts/.",
        ]
        for sc in scripts:
            key = sc["key"]
            desc = sc.get("description", "")
            params = sc.get("parameters", [])
            plats = sc.get("platforms", ["any"])
            trust = sc.get("trust_level", "")

            lines.append(f"")
            lines.append(f"    - key: {key}")
            lines.append(f'      description: "{desc}"')
            if params:
                params_str = ", ".join(f'"{p}"' for p in params)
                lines.append(f"      parameters: [{params_str}]")
            lines.append("      implementations:")
            if "any" in plats:
                lines.append(f"        - file: scripts/{key}.py")
                lines.append(f"          platform: any")
                if trust:
                    lines.append(f"          trust_level: {trust}")
            if "windows" in plats:
                lines.append(f"        - file: adapters/windows/scripts/{key}.ps1")
                lines.append(f"          platform: windows")
                if trust:
                    lines.append(f"          trust_level: {trust}")
                lines.append(f"          preferred: true")
    else:
        lines.append("")
        lines.append("  scripts: []")

    # ── Dependencies ────────────────────────────────
    deps = pkg.get("dependencies", {})
    mcp_deps = deps.get("mcp", [])
    tool_deps = deps.get("tools", [])

    lines += [
        "",
        "# ─────────────────────────────────────────",
        "# External dependencies",
        "# ─────────────────────────────────────────",
        "",
        "dependencies:",
    ]

    if mcp_deps:
        lines.append("  mcp:")
        for m in mcp_deps:
            req = str(m.get("required", True)).lower()
            lines.append(f"    - name: {m['name']}")
            lines.append(f"      required: {req}")
            lines.append(f'      purpose: "{m.get("purpose", "")}"')
            if m.get("registry"):
                lines.append(f'      registry: "{m["registry"]}"')
            if m.get("fallback"):
                lines.append(f'      fallback: "{m["fallback"]}"')
    else:
        lines.append("  mcp: []")

    if tool_deps:
        lines.append("")
        lines.append("  tools:")
        for t in tool_deps:
            req = str(t.get("required", True)).lower()
            lines.append(f"    - name: {t['name']}")
            if t.get("version"):
                lines.append(f'      version: "{t["version"]}"')
            lines.append(f"      required: {req}")
            lines.append(f'      purpose: "{t.get("purpose", "")}"')
            if t.get("fallback"):
                lines.append(f'      fallback: "{t["fallback"]}"')
    else:
        lines.append("")
        lines.append("  tools: []")

    # ── Permissions (v1.2) ───────────────────────────
    perms = pkg.get("permissions", {})
    # Auto-derive shell permissions from shell-exec scripts if not explicitly declared
    shell_exec_scripts = [sc for sc in scripts if sc.get("trust_level") == "shell-exec"]
    if perms or shell_exec_scripts:
        lines += [
            "",
            "# ─────────────────────────────────────────",
            "# Permissions (v1.2)",
            "# Declared for the AI installer to show the user before starting.",
            "# ─────────────────────────────────────────",
            "",
            "permissions:",
        ]
        fs_perms = perms.get("filesystem", [])
        if fs_perms:
            lines.append("  filesystem:")
            for fp in fs_perms:
                lines.append(f"    - path: \"{fp['path']}\"")
                lines.append(f"      access: {fp.get('access', 'read-write')}")
                lines.append(f"      reason: \"{fp.get('reason', 'TODO: describe why')}\"")
        net_perms = perms.get("network", [])
        if net_perms:
            lines.append("  network:")
            for np in net_perms:
                lines.append(f"    - domain: \"{np['domain']}\"")
                lines.append(f"      reason: \"{np.get('reason', 'TODO: describe why')}\"")
        mcp_perms = perms.get("mcp", [])
        if not mcp_perms and mcp_deps:
            # Auto-derive from declared MCP dependencies
            mcp_perms = [{"name": m["name"], "reason": m.get("purpose", "TODO: describe why")} for m in mcp_deps]
        if mcp_perms:
            lines.append("  mcp:")
            for mp in mcp_perms:
                lines.append(f"    - name: {mp['name']}")
                lines.append(f"      reason: \"{mp.get('reason', 'TODO: describe why')}\"")
        shell_perms = perms.get("shell", [])
        if not shell_perms and shell_exec_scripts:
            shell_perms = [{"command": "python3", "reason": "Runs package scripts."}]
        if shell_perms:
            lines.append("  shell:")
            for sp in shell_perms:
                lines.append(f"    - command: {sp['command']}")
                lines.append(f"      reason: \"{sp.get('reason', 'TODO: describe why')}\"")

    # ── Configuration ────────────────────────────────
    config_keys = pkg.get("configuration", [])
    lines += [
        "",
        "# ─────────────────────────────────────────",
        "# Configuration schema",
        "# Values collected during installation wizard.",
        "# Referenced as {{config.<key>}} in protocols, prompts, and scripts.",
        "# ─────────────────────────────────────────",
        "",
        "configuration:",
    ]

    if config_keys:
        for ck in config_keys:
            key = ck["key"]
            label = ck.get("label", key)
            desc = ck.get("description", "")
            type_ = ck.get("type", "string")
            required = str(ck.get("required", True)).lower()
            sensitive = ck.get("sensitive", False)
            when = ck.get("when", "before")
            default = ck.get("default")
            placeholder = ck.get("placeholder", "")
            validation = ck.get("validation")
            condition = ck.get("condition")
            options = ck.get("options")

            lines.append(f"  - key: {key}")
            lines.append(f"    label: {yaml_scalar(label)}")
            lines.append(f"    description: {yaml_scalar(desc)}")
            lines.append(f"    type: {type_}")
            lines.append(f"    required: {required}")
            if sensitive:
                lines.append(f"    sensitive: true          # installer must not log or display this value")
                storage = ck.get("storage", "config-file")
                lines.append(f"    storage: {storage}")
            if default is not None:
                if isinstance(default, str):
                    lines.append(f"    default: {yaml_scalar(default)}")
                else:
                    lines.append(f"    default: {json.dumps(default)}")
            if placeholder:
                lines.append(f"    placeholder: {yaml_scalar(placeholder)}")
            if validation:
                lines.append(f"    validation: {yaml_scalar(validation)}")
            lines.append(f"    when: {when}")
            refresh = ck.get("refresh")
            if refresh and refresh != "never":
                lines.append(f"    refresh: {refresh}")
                refresh_script = ck.get("refresh_script")
                if refresh_script:
                    lines.append(f'    refresh_script: "{refresh_script}"')
            # v1.10: per-key uninstall policy.
            # Emit only when set (omitted means "ask", which is the default).
            if "preserve_on_uninstall" in ck:
                pou = ck["preserve_on_uninstall"]
                if pou is True:
                    lines.append("    preserve_on_uninstall: true")
                elif pou is False:
                    lines.append("    preserve_on_uninstall: false")
                else:
                    lines.append('    preserve_on_uninstall: "ask"')
            if condition:
                lines.append(f'    condition: "{condition}"')
            if options:
                lines.append("    options:")
                for opt in options:
                    if isinstance(opt, dict):
                        lines.append(f"      - value: {opt['value']}")
                        lines.append(f"        label: \"{opt.get('label', opt['value'])}\"")
                        if "default" in opt:
                            lines.append(f"        default: {str(opt['default']).lower()}")
                    else:
                        lines.append(f"      - value: {opt}")
            lines.append("")
    else:
        lines.append("  # No configuration required.")

    # ── Platforms ────────────────────────────────────
    lines += [
        "",
        "# ─────────────────────────────────────────",
        "# Platform compatibility",
        "# ─────────────────────────────────────────",
        "",
    ]
    if platforms:
        lines += [
            "platforms:",
            "  tested:",
        ]
        for p in platforms:
            lines.append(f"    - {p}")
    else:
        lines += [
            "# TODO(a3ip-creator): list the platforms this package has been tested on.",
            "# Example: cowork, codex, claude-code, cursor.",
            "platforms:",
            "  tested: []",
        ]

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# CONFIGURE.md — question text generation
# ─────────────────────────────────────────────────────────────

def _generate_question_text(ck: dict) -> str:
    """
    Auto-generate a natural-language question from a config key's
    label and description fields, tailored by type and constraints.
    """
    label = ck.get("label", ck["key"])
    desc = ck.get("description", "")
    type_ = ck.get("type", "string")
    sensitive = ck.get("sensitive", False)
    required = ck.get("required", True)
    default = ck.get("default")
    placeholder = ck.get("placeholder", "")

    label_clean = label.rstrip("?.")

    # ── Strip action-verb prefixes from boolean labels ──────
    # Prevents "Should enable X be enabled?" redundancy.
    _ACTION_PREFIXES = (
        ("enable ", False),
        ("disable ", True),
        ("use ", False),
        ("allow ", False),
        ("show ", False),
        ("hide ", True),
        ("include ", False),
        ("exclude ", True),
    )

    # ── Base question by type ────────────────────────────────
    desc_clean = desc.strip().rstrip(".")
    label_norm = label_clean.lower()

    if type_ == "boolean":
        # Strip verb prefix so we don't get "Should enable X be enabled?"
        label_for_q = label_clean
        negate = False
        for prefix, is_negative in _ACTION_PREFIXES:
            if label_norm.startswith(prefix):
                label_for_q = label_clean[len(prefix):]
                negate = is_negative
                break
        if negate:
            verb = "disabled"
        else:
            verb = "enabled"
        question = f"Should {label_for_q.lower()} be {verb}?"
        # Append description before the default hint
        if desc_clean and desc_clean.lower() != label_norm:
            question += f" {desc_clean}."
        if default is not None:
            default_word = "yes" if default else "no"
            question += f" (default: {default_word})"

    elif type_ in ("select", "multi-select"):
        question = f"Which {label_clean.lower()} should be used?"
        if desc_clean and desc_clean.lower() != label_norm:
            question += f" {desc_clean}."
        if not required:
            question += " (optional — press enter to skip)"

    elif type_ == "list<string>":
        question = f"Please list your {label_clean.lower()}, separated by commas."
        if desc_clean and desc_clean.lower() != label_norm:
            question += f" {desc_clean}."
        if not required:
            question += " (optional)"

    elif type_ == "number":
        question = f"What value should {label_clean.lower()} be set to?"
        if desc_clean and desc_clean.lower() != label_norm:
            question += f" {desc_clean}."
        if not required:
            if default is not None:
                question += f" (optional; default: {default})"
            else:
                question += " (optional — leave blank to skip)"

    else:
        # string (most common)
        question = f"What is your {label_clean}?"
        if desc_clean and desc_clean.lower() != label_norm:
            question += f" {desc_clean}."
        if not required:
            if default is not None:
                question += f" (optional; default: {default})"
            else:
                question += " (optional — leave blank to skip)"

    # ── Placeholder hint ─────────────────────────────────────
    if placeholder and not sensitive:
        question += f" For example: {placeholder}"

    # ── Sensitive note ───────────────────────────────────────
    if sensitive:
        question += " I won't display this value back to you."

    return question.strip()


# ─────────────────────────────────────────────────────────────
# CONFIGURE.md
# ─────────────────────────────────────────────────────────────

def build_configure(pkg: dict) -> str:
    name = pkg["name"]
    config_keys = pkg.get("configuration", [])
    v12 = _uses_v12_features(pkg)

    before_keys = [k for k in config_keys if k.get("when", "before") == "before"]
    during_keys = [k for k in config_keys if k.get("when") == "during"]
    after_keys = [k for k in config_keys if k.get("when") == "after"]

    spec_ver = "1.10"
    parts = [
        "---",
        "format: a3ip-configure",
        f'spec: "{spec_ver}"',
        f"package: {name}",
        "---",
        "",
        f"# Configuration Wizard: {name}",
        "",
        "You are setting up this workflow. Ask the questions below in order.",
        "Be conversational — no need to present them as a rigid form.",
        "Collect all required values before moving to installation.",
        "",
    ]

    q_num = 0

    def render_question(ck: dict, num: int) -> list:
        key = ck["key"]
        label = ck.get("label", key)
        desc = ck.get("description", "")
        type_ = ck.get("type", "string")
        sensitive = ck.get("sensitive", False)
        required = ck.get("required", True)
        default = ck.get("default")
        placeholder = ck.get("placeholder", "")
        validation = ck.get("validation")
        condition = ck.get("condition")
        options = ck.get("options")

        q = [f"---", f"", f"### {num}. {label}"]

        if condition:
            q.append(f"*(Only ask if: {condition})*")
            q.append("")

        question_text = _generate_question_text(ck)
        q.append(f'Ask:')
        q.append(f'> "{question_text}"')
        q.append("")

        q.append(f"- Key: `{key}`")
        q.append(f"- Type: {type_}")
        q.append(f"- Required: {'yes' if required else 'no (optional)'}")

        if sensitive:
            storage = ck.get("storage", "config-file")
            storage_desc = {
                "keychain": "the OS keychain",
                "env-var": "an environment variable",
                "config-file": "config.json (access-controlled)",
            }.get(storage, f"`{storage}`")
            q.append(f"- **Sensitive** — do NOT echo the value back to the user.")
            q.append(f'  Once received, confirm only: "✅ {label} received and will be stored securely in {storage_desc}."')
            q.append(f"  Do NOT include `{{{{config.{key}}}}}` in the confirmation summary.")

        if default is not None:
            q.append(f"- Default: `{default}`")

        if placeholder:
            q.append(f"- Example: `{placeholder}`")

        if validation:
            q.append(f"- Validation: {validation}")

        if options:
            q.append(f"- Options:")
            for opt in options:
                if isinstance(opt, dict):
                    dflt = " (default)" if opt.get("default") else ""
                    q.append(f"  - `{opt['value']}` — {opt.get('label', opt['value'])}{dflt}")
                else:
                    q.append(f"  - `{opt}`")

        if not required:
            q.append(f"- If blank or skipped: store as empty/default, skip related steps during protocol execution.")

        return q

    if before_keys:
        parts += ["## Before Installation — ask these first", ""]
        for ck in before_keys:
            q_num += 1
            parts += render_question(ck, q_num)
            parts.append("")

    if during_keys:
        parts += ["## During Installation — ask inline at relevant steps", ""]
        for ck in during_keys:
            q_num += 1
            parts += render_question(ck, q_num)
            parts.append("")

    if after_keys:
        parts += ["## After Installation — optional fine-tuning", ""]
        for ck in after_keys:
            q_num += 1
            parts += render_question(ck, q_num)
            parts.append("")

    # Confirmation block
    confirm_lines = ["## Confirmation", "",
                     "Before proceeding to installation, summarize everything and ask the user to confirm:",
                     "", "---", "Here's what I'll configure:", ""]

    sensitive_keys = {k["key"] for k in config_keys if k.get("sensitive")}
    for ck in config_keys:
        key = ck["key"]
        label = ck.get("label", key)
        if key in sensitive_keys:
            confirm_lines.append(f"- **{label}**: ✅ received (not displayed)")
        else:
            confirm_lines.append(f"- **{label}**: {{{{config.{key}}}}}")

    confirm_lines += ["", "Shall I proceed with installation?", "---", "",
                      "Wait for explicit confirmation before moving to INSTALL.md."]

    parts += confirm_lines

    return "\n".join(parts) + "\n"


# ─────────────────────────────────────────────────────────────
# INSTALL.md
# ─────────────────────────────────────────────────────────────

def _needs_plan_section(scripts: list) -> bool:
    """True if any script requires write-local or shell-exec trust level."""
    elevated = {"write-local", "shell-exec"}
    return any(sc.get("trust_level", "") in elevated for sc in scripts)


def build_install(pkg: dict, platform_config=None) -> str:
    """Generate INSTALL.md content for the package.

    platform_config (a3ip.platform_config.PlatformConfig | None):
      Platform metadata used to emit per-platform routing in Steps 5/6/7
      and the "Platform-Specific Notes" section. When None or empty, the
      template inserts TODO markers in place of platform routing.
    """
    from a3ip.platform_config import PlatformConfig
    if platform_config is None:
        platform_config = PlatformConfig.empty()

    name = pkg["name"]
    protocols = pkg.get("protocols", [])
    scripts = pkg.get("scripts", [])
    skills = pkg.get("skills", [])
    artifacts = pkg.get("artifacts", [])
    prompts = pkg.get("prompts", [])
    deps = pkg.get("dependencies", {})
    mcp_deps = deps.get("mcp", [])
    tool_deps = deps.get("tools", [])
    auth_flows = pkg.get("auth_flows", [])
    needs_plan = _needs_plan_section(scripts)
    v12 = _uses_v12_features(pkg)

    has_windows_scripts = any("windows" in sc.get("platforms", []) for sc in scripts)

    # Intersect the intake's platforms.tested list with the platform-config
    # entries -- we only emit per-platform routing for platforms the config
    # knows about. Anything in intake but not in config produces a TODO marker.
    intake_platforms = [p.lower() for p in pkg.get("platforms", [])]
    known_entries = [
        platform_config.get(pid) for pid in intake_platforms
        if pid in platform_config.platforms
    ]
    unknown_platform_ids = [
        pid for pid in intake_platforms if pid not in platform_config.platforms
    ]
    has_any_platform_routing = bool(known_entries) or bool(unknown_platform_ids)

    step = 0

    def s(title: str) -> str:
        nonlocal step
        step += 1
        return f"## {step}. {title}"

    spec_ver = "1.10"
    lines = [
        "---",
        "format: a3ip-install",
        f'spec: "{spec_ver}"',
        f"package: {name}",
        "---",
        "",
        f"# Installation Guide: {name}",
        "",
        s("Check for Existing Installation"),
        "",
        "*Tier: 2 (required outcome -- adapter procedure)*",
        "",
        "After this step, the AI MUST know whether a prior installation of this",
        "package exists on the host, and if so where its `config_dir` lives.",
        "",
        "The discovery mechanism is host-runtime-specific -- read",
        "`adapters/runtime/<platform>/install-skill.md` for how to locate prior",
        "installs on the current platform. The adapter is responsible for",
        "whatever lookup is idiomatic on its platform (scanning a conventional",
        "package home, reading a per-runtime index, following pointer files for",
        "custom install locations, etc.). This spec does not prescribe a single",
        "detection path.",
        "",
        "**Result:**",
        "- **Found:** the adapter returns the `config_dir` of the existing install.",
        "  Read `installed.json` at that path for the installed version, then go",
        "  directly to the [## Upgrading](#upgrading) section at the end of this",
        "  document. Apply only the changelog steps for versions after the installed",
        "  version.",
        "- **Not found:** proceed with the full install steps below. The configure",
        "  wizard (Step 4) collects a NEW `install_dir` from the user.",
        "",
    ]

    # Plan section (required for write-local / shell-exec scripts under v1.2)
    if needs_plan:
        net_scripts = [sc for sc in scripts if sc.get("trust_level") == "network"]
        write_scripts = [sc for sc in scripts if sc.get("trust_level") == "write-local"]
        shell_scripts = [sc for sc in scripts if sc.get("trust_level") == "shell-exec"]
        perms = pkg.get("permissions", {})
        net_domains = perms.get("network", [])
        mcp_perms = perms.get("mcp", [])

        lines += [
            "## Plan",
            "",
            "Before beginning installation, this package will take the following actions.",
            "Please review and confirm before proceeding.",
            "",
        ]
        lines += [
            "**Files written:**",
            "- TODO: list every file that will be written during install",
            "  (e.g. `{{config.<dir>}}/config.json`, `{{config.<dir>}}/installed.json`)",
            "",
        ]
        if net_domains:
            lines.append("**Network calls:**")
            for nd in net_domains:
                lines.append(f"- `{nd['domain']}` — {nd.get('reason', 'TODO: describe why')}")
            lines.append("")
        elif net_scripts:
            lines += [
                "**Network calls:**",
                "- TODO: list external API domains contacted during install",
                "",
            ]
        if mcp_perms:
            lines.append("**MCP tools used:**")
            for mp in mcp_perms:
                lines.append(f"- `{mp['name']}` — {mp.get('reason', 'TODO: describe why')}")
            lines.append("")
        elif mcp_deps:
            lines += [
                "**MCP tools used:**",
            ]
            for m in mcp_deps:
                lines.append(f"- `{m['name']}` — {m.get('purpose', 'TODO')}")
            lines.append("")
        if shell_scripts:
            lines.append("**Shell commands run:**")
            for sc in shell_scripts:
                lines.append(f"- `python3 scripts/{sc['key']}.py` — {sc.get('description', '')}")
            lines.append("")
        lines.append("**Confirm to proceed.**")
        lines.append("")

    lines += [
        s("What This Package Installs"),
        "",
        "TODO: describe the workflows this package provides.",
        "",
    ]

    if protocols:
        for p in protocols:
            lines.append(f"**\"{p['trigger']}\"** — {p['description']}")
        lines.append("")

    # Dependency check
    lines.append(s("Dependency Check"))
    lines.append("")
    lines.append("Verify the following before proceeding. Tell the user exactly what's missing.")
    lines.append("")

    req_mcps = [m for m in mcp_deps if m.get("required", True)]
    opt_mcps = [m for m in mcp_deps if not m.get("required", True)]
    req_tools = [t for t in tool_deps if t.get("required", True)]
    opt_tools = [t for t in tool_deps if not t.get("required", True)]

    if req_mcps:
        lines.append("**Required MCPs:**")
        for m in req_mcps:
            fallback = m.get("fallback", "Cannot proceed without this.")
            lines.append(f"- [ ] **{m['name']} MCP** — {m.get('purpose', '')}.")
            lines.append(f"  If unavailable: {fallback}")
        lines.append("")

    if opt_mcps:
        lines.append("**Optional MCPs:**")
        for m in opt_mcps:
            fallback = m.get("fallback", "Graceful degradation applies.")
            lines.append(f"- [ ] **{m['name']} MCP** — {m.get('purpose', '')}.")
            lines.append(f"  If unavailable: {fallback}")
        lines.append("")

    if req_tools:
        lines.append("**Required tools:**")
        for t in req_tools:
            ver = t.get("version", "")
            lines.append(f"- [ ] **{t['name']}{' ' + ver if ver else ''}** — {t.get('purpose', '')}.")
        lines.append("")

    if opt_tools:
        lines.append("**Optional tools:**")
        for t in opt_tools:
            ver = t.get("version", "")
            fallback = t.get("fallback", "")
            lines.append(f"- [ ] **{t['name']}{' ' + ver if ver else ''}** — {t.get('purpose', '')}.")
            if fallback:
                lines.append(f"  If unavailable: {fallback}")
        lines.append("")

    if not mcp_deps and not tool_deps:
        lines.append("No external dependencies required.")
        lines.append("")

    # Config wizard
    lines += [
        s("Run Configuration Wizard"),
        "",
        "Read and follow CONFIGURE.md to collect all user-specific values.",
        "Do not proceed until the user has confirmed the configuration summary.",
        "",
        "All `{{config.*}}` references in subsequent steps are substituted with",
        "the values collected here.",
        "",
    ]

    # Resolve install_dir to absolute path (path-expansion gate)
    lines += [
        s("Resolve install_dir to an absolute path"),
        "",
        "Before writing any file or storing the value, expand `{{config.install_dir}}`",
        "to a host-native absolute path:",
        "",
        "- **Windows hosts:** if the value contains `~`, replace it with the user's",
        "  Windows home (typically the path under `C:/Users/USERNAME/`). Use the",
        "  platform's native separator and double backslashes inside JSON files.",
        "- **POSIX hosts (macOS / Linux):** if the value contains `~`, replace it",
        "  with `$HOME` or `os.path.expanduser('~')`.",
        "",
        "Example expansion: `~/.claude/packages/" + name + "/` -> the absolute",
        "path under the user's home directory followed by",
        "`.claude/packages/" + name + "/` (or whichever path the runtime adapter",
        "specifies for this platform).",
        "",
        "From this point on, treat `{{config.install_dir}}` as the absolute expanded",
        "path. Persist the expanded value (not the user-typed literal) when you write",
        "config.json (Step 6) and installed.json (Step 10). The runtime AI reads these",
        "files via tools that do not expand `~`, so a literal tilde breaks runtime",
        "config lookup.",
        "",
    ]

    # OS detection (only if there are Windows scripts)
    if has_windows_scripts:
        lines += [
            s("Detect OS and Select Script Implementations"),
            "",
            "Determine the user's operating system:",
            "",
            "```",
            'python3 -c "import platform; print(platform.system())"',
            "```",
            "",
            "Based on the result, select the script implementation to use:",
            "- **Windows**: prefer `adapters/windows/scripts/<name>.ps1` if PowerShell is available.",
            "  Fall back to `scripts/<name>.py` if not.",
            "- **macOS / Linux / other**: always use `scripts/<name>.py`.",
            "",
            "Remember this selection — use it consistently in every subsequent step.",
            "",
        ]

    # Install scripts (if any)
    if scripts:
        lines += [
            s("Install Scripts"),
            "",
            "Create `{{config.install_dir}}` if it does not exist.",
            "Copy script files from `scripts/` in this bundle to",
            "`{{config.install_dir}}/scripts/`.",
            "",
        ]
        if has_windows_scripts:
            lines += [
                "On Windows with PowerShell: copy both `scripts/` and `adapters/windows/scripts/`.",
                "On other OSes: copy only `scripts/`.",
                "",
            ]
        for sc in scripts:
            key = sc["key"]
            desc = sc.get("description", "")
            lines.append(f"- **`{key}`** — {desc}")
        lines.append("")

    # Auth flows
    if auth_flows:
        for af in auth_flows:
            skey = af.get("script_key", "")
            lines += [
                s(f"Authenticate — {af['name']} (one-time)"),
                "",
                af["description"],
                "",
                f"Run the auth script:",
                "```",
                f"script {skey}",
                "```",
                "",
                "This is a one-time step. The token is written to config.json and",
                "re-used on subsequent runs until it expires.",
                "",
            ]

    # Install skills
    if skills:
        lines += [
            s("Make skills discoverable to the host runtime"),
            "*Tier: 2 (required outcome -- adapter procedure)*",
            "",
            "After this step, the host runtime MUST be able to load each skill",
            "in `components/skills/` when its trigger phrases appear. The",
            "procedure depends on the runtime -- consult",
            "`adapters/runtime/<your-platform>/install-skill.md` for platform",
            "conventions and a worked example.",
            "",
        ]
        if has_any_platform_routing:
            lines += [
                "**Platform routing:**",
                "",
            ]
            for entry in known_entries:
                if entry.adapter_file_authored:
                    lines.append(
                        f"- **{entry.display_name}** ({entry.description}): "
                        f"follow `adapters/runtime/{entry.id}/install-skill.md`."
                    )
                else:
                    lines.append(
                        f"- **{entry.display_name}** ({entry.description}): "
                        f"`adapters/runtime/{entry.id}/install-skill.md` is a "
                        f"stub -- adapt the generic procedure below until the "
                        f"adapter is authored."
                    )
            for pid in unknown_platform_ids:
                lines.append(
                    f"- **{pid}**: <!-- TODO(a3ip-creator): add platform_config "
                    f"entry for '{pid}' or remove from package platforms list. -->"
                )
            lines += [
                "",
                "If the install AI takes a platform-specific adapter path above, do",
                "NOT also run the generic file-copy lines below -- doing both may",
                "produce duplicate registration prompts and a partial install.",
                "",
                "**Generic fallback (any platform without an adapter route above):**",
                "",
            ]
        for sk in skills:
            sname = kebab(sk["name"])
            lines.append(
                f"Copy `components/skills/{sname}/` into the host runtime's "
                f"skills directory. The exact location is platform-specific -- "
                f"consult the runtime's documentation."
            )
        lines.append("")

    # Set up artifacts
    if artifacts:
        lines += [
            s("Make artifacts available on the host runtime"),
            "*Tier: 2 (required outcome -- adapter procedure)*",
            "",
            "After this step, each artifact declared in the package MUST be in a",
            "form the user can open and the runtime can update. On HTML-capable",
            "runtimes this typically means an artifact card; on text-only",
            "runtimes it means the markdown fallback file is in place. Consult",
            "`adapters/runtime/<your-platform>/install-skill.md` for the",
            "platform's artifact mechanism.",
            "",
        ]
        if has_any_platform_routing:
            lines += [
                "**Platform routing:**",
                "",
            ]
            for entry in known_entries:
                if entry.adapter_file_authored:
                    lines.append(
                        f"- **{entry.display_name}**: handled by "
                        f"`adapters/runtime/{entry.id}/install-skill.md`. "
                        f"Skip the per-artifact instructions below if the "
                        f"adapter covers this outcome."
                    )
                else:
                    lines.append(
                        f"- **{entry.display_name}**: "
                        f"`adapters/runtime/{entry.id}/install-skill.md` is a "
                        f"stub -- use the per-artifact fallback instructions "
                        f"below."
                    )
            for pid in unknown_platform_ids:
                lines.append(
                    f"- **{pid}**: <!-- TODO(a3ip-creator): add platform_config "
                    f"entry for '{pid}' or remove from package platforms list. -->"
                )
            lines.append("")
        lines += [
            "**Per-artifact fallback (any platform without an adapter route above):**",
            "",
        ]
        for a in artifacts:
            aname = kebab(a["name"])
            lines += [
                f"**{a['name']}** (`components/artifacts/{aname}/`)",
                "",
                "- **HTML-capable platforms:**",
                f"  Create a new artifact using `artifact.html`. Name it \"{a['name']}\".",
                "",
                "- **Text-only platforms:**",
                "  Use the description in `artifact.md` to maintain an equivalent",
                "  file-based structure (e.g. a markdown table).",
                "",
            ]

    # Register protocols
    if protocols:
        lines += [
            s("Make protocols invocable on the host runtime"),
            "*Tier: 2 (required outcome -- adapter procedure)*",
            "",
            "After this step, each protocol's trigger phrase MUST be recognized",
            "by the host runtime. The registration mechanism depends on the",
            "runtime -- slash commands, remembered instructions, AGENTS.md",
            "stanzas, or skill-level trigger declarations. Apply registration",
            "per `adapters/runtime/<your-platform>/install-skill.md`.",
            "",
        ]
        if has_any_platform_routing:
            lines += [
                "**Platform routing:**",
                "",
            ]
            for entry in known_entries:
                if entry.adapter_file_authored:
                    lines.append(
                        f"- **{entry.display_name}**: registration is handled "
                        f"by `adapters/runtime/{entry.id}/install-skill.md`. "
                        f"Skip the manual registration steps below if the "
                        f"adapter covers this outcome."
                    )
                else:
                    lines.append(
                        f"- **{entry.display_name}**: "
                        f"`adapters/runtime/{entry.id}/install-skill.md` is a "
                        f"stub -- register each protocol manually using the "
                        f"instructions below."
                    )
            for pid in unknown_platform_ids:
                lines.append(
                    f"- **{pid}**: <!-- TODO(a3ip-creator): add platform_config "
                    f"entry for '{pid}' or remove from package platforms list. -->"
                )
            lines += [
                "",
                "**Manual registration fallback (any platform without an adapter "
                "route above):**",
                "",
                "Read each protocol file and register it:",
                "",
            ]
        else:
            lines.append("Read each protocol file and register it:")
            lines.append("")
        for p in protocols:
            pname = kebab(p["name"])
            trigger = p["trigger"]
            aliases = p.get("aliases", [])
            lines.append(f"**`{pname}.md`**")
            lines.append(f'- Trigger: "{trigger}"')
            if aliases:
                for al in aliases:
                    lines.append(f'- Alias: "{al}"')
            lines.append("- Register as a slash command, skill, or remembered instruction.")
            lines.append("")

    # Load prompts
    if prompts:
        lines += [
            s("Load Prompt Templates"),
            "",
        ]
        for pr in prompts:
            prname = kebab(pr["name"])
            lines.append(f"Load `components/prompts/{prname}.md` as a named template or persistent AI context.")
        lines.append("")

    # Confirm installation
    lines += [
        s("Confirm Installation"),
        "",
        "Summarize to the user:",
        "",
    ]
    if scripts:
        lines.append("- ✅ Scripts installed")
    if skills:
        lines.append("- ✅ Skill(s) installed")
    if artifacts:
        lines.append("- ✅ Artifact(s) set up")
    if protocols:
        for p in protocols:
            lines.append(f"- ✅ Protocol registered: \"{p['trigger']}\"")
    if prompts:
        lines.append("- ✅ Prompt templates loaded")
    lines += [
        "- Any missing dependencies and their impact on the workflow",
        "",
        "**How to use:**",
    ]
    for p in protocols:
        lines.append(f"- Say **\"{p['trigger']}\"** to trigger the {p['name']} workflow.")

    # Write installed.json (spec template)
    lines += [
        "",
        s("Write installed.json"),
        "",
        "Write `{{config.install_dir}}/installed.json` with:",
        "",
        "```json",
        "{",
        f'  "package": "{name}",',
        f'  "version": "{pkg.get("version", "1.0.0")}",',
        '  "installed_at": "<current ISO-8601 timestamp>",',
        '  "platform": "<detected platform id — e.g. cowork, codex, claude-code, cursor>",',
        f'  "a3ip_spec": "{spec_ver}",',
        '  "config_dir": "{{config.install_dir}}"',
        "}",
        "```",
        "",
        "This is the canonical install record. The next install/upgrade of this",
        "package looks for this file at `{{config.install_dir}}/installed.json` —",
        "if present, it runs the Upgrading flow instead of a fresh install.",
        "",
    ]

    lines += [
        "",
        "---",
        "",
        "## Platform-Specific Notes",
        "",
    ]
    if has_any_platform_routing:
        for entry in known_entries:
            lines += [
                f"### {entry.display_name}",
                entry.description + ".",
                (
                    f"See `adapters/runtime/{entry.id}/install-skill.md` for "
                    "registration mechanics, artifact handling, and any "
                    "platform-specific quirks."
                    if entry.adapter_file_authored
                    else f"`adapters/runtime/{entry.id}/install-skill.md` is a "
                    "stub -- fill it in before relying on this platform."
                ),
                "",
            ]
        for pid in unknown_platform_ids:
            lines += [
                f"### {pid}",
                f"<!-- TODO(a3ip-creator): describe {pid} support, or remove "
                f"this platform from the package's platforms list. -->",
                "",
            ]
        lines += [
            "### Other platforms",
            "Core protocols and components are platform-neutral; adapt as needed.",
            "",
        ]
    else:
        lines += [
            "<!-- TODO(a3ip-creator): no platform_config was supplied at scaffold "
            "time. Document the platforms this package supports here, or "
            "re-run `a3ip scaffold --platform-config <path>` to populate this "
            "section automatically. -->",
            "",
            "### Other platforms",
            "Core protocols and components are platform-neutral; adapt as needed.",
            "",
        ]
    lines += [
        "---",
        "",
        "## Upgrading",
        "",
        "When `installed.json` is found at `{{config.install_dir}}/installed.json`,",
        "follow these steps instead of the full install.",
        "",
        "### Step U1 — Read installed version",
        "Read `{{config.install_dir}}/installed.json`. Note the `version` field.",
        "",
        "### Step U2 — Apply CHANGELOG steps",
        "Find all version entries in `CHANGELOG.md` newer than the installed version.",
        "Apply them in order from oldest to newest. For each version entry:",
        "1. Check `### Breaking changes` — if any, tell the user before proceeding.",
        "2. Check `### Config changes` — if new required keys, run the config wizard",
        "   for those keys only.",
        "3. Follow `### Upgrade steps` exactly.",
        "",
        "### Step U3 — Update installed.json",
        "After all upgrade steps complete, overwrite `{{config.install_dir}}/installed.json`",
        "with the new `version` and `installed_at` timestamp. Preserve the existing",
        "`platform`, `a3ip_spec`, and `config_dir` fields.",
        "",
        "### Step U4 — Confirm",
        "Tell the user the versions upgraded from and to, and the changes applied.",
        "",
        "Do **not** run the full install sequence during an upgrade.",
        "Apply only the delta steps listed in CHANGELOG.md.",
        "",
        "## Uninstalling",
        "",
        "Triggered when the user says \"uninstall " + name + "\", \"remove " + name + "\",",
        "or equivalent. Uninstall is idempotent -- running it when the package is",
        "not installed is a no-op (Step UN1 exits cleanly), not an error.",
        "",
        "### Step UN1 -- Locate the existing install",
        "*Tier: 2 (required outcome -- adapter procedure)*",
        "",
        "After this step, the AI MUST know whether this package is installed on",
        "the host, and if so where its `config_dir` lives. The discovery mechanism",
        "is host-runtime-specific -- read `adapters/runtime/<platform>/uninstall-skill.md`",
        "for how to locate prior installs on the current platform. This is the",
        "symmetric counterpart of INSTALL.md Step 1.",
        "",
        "- **Not found:** tell the user there is nothing to uninstall and exit",
        "  cleanly. Steps UN2 onward are skipped.",
        "- **Found:** read the `version`, `platform`, `config_dir`, and `install_method`",
        "  fields from `installed.json`. They drive every subsequent step.",
        "",
        "### Step UN2 -- Show the Uninstall Plan and resolve per-key config policy",
        "*Tier: 1 (mechanical)*",
        "",
        "Present an Uninstall Plan that lists, item by item:",
        "",
        "- The skill files that will be removed (paths derived per the platform's adapter).",
        "- The artifacts that will be removed (artifact names and their host-runtime mechanism).",
        "- Any host-runtime registrations that will be reverted (e.g. on Codex: the",
        "  `<!-- a3ip:" + name + ":start --> ... <!-- a3ip:" + name + ":end -->`",
        "  block in `~/.codex/AGENTS.md`).",
        "- The per-key disposition of every configuration value (see below).",
        "- The `installed.json` file that will be removed.",
        "",
        "**Resolving the config-key policy.** Walk every entry in the `configuration:`",
        "block of `manifest.yaml` and consult its `preserve_on_uninstall:` field:",
        "",
        "- `true` -- silently classified as *preserve*. The user is NOT asked.",
        "- `false` -- silently classified as *purge*. The user is NOT asked.",
        "- `ask` (or field omitted) -- the AI MUST ask the user, per key, whether to",
        "  preserve or remove that value.",
        "",
        "End with **Confirm to proceed.** If the user declines, abort -- nothing is removed.",
        "",
        "### Step UN3 -- Make skills un-discoverable to the host runtime",
        "*Tier: 2 (required outcome -- adapter procedure)*",
        "",
        "After this step, the host runtime MUST NOT load any skill from",
        "`components/skills/` in response to its trigger phrases. The procedure",
        "depends on how skills were made discoverable in install Step 5 -- read",
        "`adapters/runtime/<platform>/uninstall-skill.md` for the platform-specific",
        "procedure.",
        "",
        "### Step UN4 -- Remove artifacts from the host runtime",
        "*Tier: 2 (required outcome -- adapter procedure)*",
        "",
        "After this step, the host runtime MUST NOT surface any artifact this",
        "package created in install Step 6.",
        "",
        "### Step UN5 -- Make protocols no longer invocable",
        "*Tier: 2 (required outcome -- adapter procedure)*",
        "",
        "After this step, the host runtime MUST NOT recognize this package's",
        "protocol trigger phrases.",
        "",
        "### Step UN6 -- Remove install_dir contents",
        "*Tier: 1 (mechanical)*",
        "",
        "Apply the per-key decisions resolved in Step UN2:",
        "",
        "1. Read the current `{{config.install_dir}}/config.json`.",
        "2. Construct a new version containing ONLY the keys whose disposition is *preserve*.",
        "3. Write the trimmed object back, OR remove the file if no keys survive.",
        "4. For each *purge* key whose `storage:` is non-config-file (e.g. `keychain`),",
        "   remove it from that storage too (read the uninstall adapter for the",
        "   platform's keychain/credential-removal mechanism).",
        "5. Delete every other file and subdirectory in `{{config.install_dir}}`",
        "   EXCEPT `config.json` (if preserved) and `installed.json`.",
        "",
        "### Step UN7 -- Remove installed.json",
        "*Tier: 1 (mechanical)*",
        "",
        "Remove `{{config.install_dir}}/installed.json`. If the install directory",
        "is empty after this, the AI SHOULD remove the empty directory too.",
        "",
        "### Step UN8 -- Confirm to the user",
        "*Tier: 1 (mechanical)*",
        "",
        "Tell the user the uninstall completed. Name the version that was",
        "uninstalled, which configuration keys were preserved (with their locations),",
        "which were purged, and any leftover state the user may want to know about.",
    ]

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# README.md
# ─────────────────────────────────────────────────────────────

def build_readme(pkg: dict) -> str:
    name = pkg["name"]
    description = pkg.get("description", "")
    author = pkg.get("author", "")
    protocols = pkg.get("protocols", [])
    platforms = pkg.get("platforms", [])

    lines = [
        f"# {name}",
        "",
        description,
        "",
        "## Workflows",
        "",
    ]
    for p in protocols:
        lines.append(f"- **\"{p['trigger']}\"** — {p['description']}")

    lines += [
        "",
        "## Installation",
        "",
        "This is an A3IP package. To install it, give the `.a3ip.bundle` file to",
        "your AI assistant and ask it to install the package.",
        "",
        "The AI will guide you through the configuration wizard and set everything up.",
        "",
        "## Platforms",
        "",
    ]
    if platforms:
        for p in platforms:
            lines.append(f"- {p}")
    else:
        lines.append("_TODO(a3ip-creator): list the platforms this package has been tested on._")

    lines += [
        "",
        f"## Author",
        "",
        author,
    ]

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# CHANGELOG.md
# ─────────────────────────────────────────────────────────────

def build_changelog(pkg: dict) -> str:
    name = pkg["name"]
    version = pkg.get("version", "1.0.0")

    lines = [
        "---",
        "format: a3ip-changelog",
        'spec: "1.1"',
        f"package: {name}",
        "---",
        "",
        f"# Changelog: {name}",
        "",
        "This file documents changes between versions of this package.",
        "Each version section contains:",
        "- A human-readable **Summary** of what changed",
        "- **Upgrade steps** — AI-readable instructions for applying this version's changes",
        "  (written exactly like INSTALL.md steps; apply only what changed)",
        "- **Breaking changes** — config keys renamed/removed, new required MCPs, etc.",
        "  (an AI receiving an upgrade must re-run the wizard for any affected fields)",
        "",
        "New version entries go at the **top** of this file (newest first).",
        "",
        "---",
        "",
        f"## {version}",
        "",
        f"*Released: TODO*",
        "",
        "### Summary",
        "",
        "Initial release.",
        "",
        "### Upgrade steps",
        "",
        "*(No prior version — this is the initial release. Run the full INSTALL.md.)*",
        "",
        "### Breaking changes",
        "",
        "None (initial release).",
    ]

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# Component stubs
# ─────────────────────────────────────────────────────────────

def build_skill_md(skill: dict, pkg_name: str) -> str:
    sname = skill["name"]
    desc = skill.get("description", "")
    return f"""---
name: {kebab(sname)}
description: "{desc}"
version: "1.0.0"
---

# {sname}

## When to use this skill

TODO: Describe when the AI should apply this skill.

## Instructions

TODO: Write the step-by-step instructions for this skill.

## Notes

- This skill is part of the `{pkg_name}` A3IP package.
- Generated by A3IP Creator — fill in the instructions above.
"""


def build_artifact_md(artifact: dict) -> str:
    aname = artifact["name"]
    desc = artifact.get("description", "")
    atype = artifact.get("type", "ui-view")
    return f"""---
name: {kebab(aname)}
description: "{desc}"
type: {atype}
refresh: on-demand
---

## Purpose

{desc}

## Data Sources

TODO: List the data sources this artifact reads from (MCPs, files, etc.).

## Fields

| Field | Source | Description |
|---|---|---|
| TODO | TODO | TODO |

## Fallback (no HTML artifact support)

Maintain a markdown file with the same columns.
Update it each time the relevant protocol runs.
"""


def build_artifact_html(artifact: dict) -> str:
    aname = artifact["name"]
    desc = artifact.get("description", "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{aname}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; padding: 1rem; }}
    h1 {{ font-size: 1.2rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f5f5f5; }}
  </style>
</head>
<body>
  <h1>{aname}</h1>
  <p>{desc}</p>
  <!-- TODO: implement the artifact view -->
  <table>
    <thead>
      <tr><th>Column 1</th><th>Column 2</th><th>Column 3</th></tr>
    </thead>
    <tbody>
      <tr><td colspan="3"><em>No data yet.</em></td></tr>
    </tbody>
  </table>
</body>
</html>
"""


def build_protocol_md(protocol: dict, config_keys: list) -> str:
    pname = protocol["name"]
    trigger = protocol["trigger"]
    aliases = protocol.get("aliases", [])
    desc = protocol.get("description", "")
    steps = protocol.get("steps", [])

    alias_lines = "\n".join(f'  - "{a}"' for a in aliases) if aliases else "  # none"

    lines = [
        "---",
        f"name: {kebab(pname)}",
        f'trigger: "{trigger}"',
    ]
    if aliases:
        lines.append("aliases:")
        for a in aliases:
            lines.append(f'  - "{a}"')
    lines += [
        "---",
        "",
        f"## What this protocol does",
        "",
        desc,
        "",
        "## Steps",
        "",
    ]

    if steps:
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
    else:
        lines += [
            "TODO: Fill in the step-by-step instructions for this protocol.",
            "",
            "Tips:",
            "- Reference config values as `{{config.key_name}}`",
            "- Reference scripts as `run script <key>` (never hardcoded paths)",
            "- Mark optional steps with: *Skip if [condition]*",
        ]

    # Add config refs summary
    if config_keys:
        lines += [
            "",
            "## Config values used",
            "",
        ]
        for ck in config_keys:
            lines.append(f"- `{{{{config.{ck['key']}}}}}` — {ck.get('label', ck['key'])}")

    lines += [
        "",
        "## Outputs",
        "",
        "TODO: List what this protocol produces (files written, messages sent, etc.)",
    ]

    return "\n".join(lines) + "\n"


def build_prompt_md(prompt: dict) -> str:
    pname = prompt["name"]
    desc = prompt.get("description", "")
    variables = prompt.get("variables", [])

    lines = [
        "---",
        f"name: {kebab(pname)}",
        f'description: "{desc}"',
    ]
    if variables:
        lines.append("variables:")
        for v in variables:
            lines.append(f"  - {v}    # runtime variable — filled each time the protocol runs")
    lines += [
        "# Note: config.* values are substituted at install time using double-brace syntax.",
        "# Runtime variables are substituted each time the protocol executes.",
        "---",
        "",
        "## Template",
        "",
        "TODO: Write the prompt template here.",
        "",
        "# Syntax reminders (replace angle brackets with actual names):",
        "# - Runtime value:      {{ <variable_name> }}",
        "# - Install-time value: {{ config.<key_name> }}",
    ]
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# Script stubs
# ─────────────────────────────────────────────────────────────

def build_python_stub(sc: dict, pkg_name: str) -> str:
    key = sc["key"]
    desc = sc.get("description", "")
    params = sc.get("parameters", [])

    param_list = ", ".join(f'"{p}"' for p in params) if params else ""
    param_args = ", ".join(p.lower().replace(" ", "_") for p in params) if params else ""

    lines = [
        "#!/usr/bin/env python3",
        f'"""',
        f"{pkg_name} — {key}.py",
        f"{desc}",
        "",
        "Usage:",
        f"    python3 {key}.py <config_json_path>" + (f" {param_args}" if param_args else ""),
        '"""',
        "",
        "import json",
        "import sys",
        "from pathlib import Path",
        "",
        "",
        "def main():",
        "    if len(sys.argv) < 2:",
        '        print(f"Usage: python3 {key}.py <config_json_path>")',
        "        sys.exit(1)",
        "",
        "    config_path = Path(sys.argv[1])",
        "    with open(config_path) as f:",
        "        config = json.load(f)",
        "",
    ]

    if params:
        lines.append(f"    # Parameters: {', '.join(params)}")
        for i, p in enumerate(params, 2):
            pvar = p.lower().replace(" ", "_")
            lines.append(f"    {pvar} = sys.argv[{i}] if len(sys.argv) > {i} else None")
        lines.append("")

    lines += [
        "    # TODO: implement this script",
        "    # Access config values like: config[<key_name>]",
        "    raise NotImplementedError('TODO: implement this script')",
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
    ]

    return "\n".join(lines) + "\n"


def build_ps1_stub(sc: dict, pkg_name: str) -> str:
    key = sc["key"]
    desc = sc.get("description", "")
    params = sc.get("parameters", [])

    param_decls = "\n".join(f"    [string]${p.replace(' ', '')}," for p in params) if params else ""

    lines = [
        f"# {pkg_name} — {key}.ps1",
        f"# {desc}",
        "#",
        f"# Usage: .\\{key}.ps1 -ConfigPath <path>" + (f" -{' -'.join(params)}" if params else ""),
        "",
        "[CmdletBinding()]",
        "param (",
        "    [Parameter(Mandatory=$true)]",
        "    [string]$ConfigPath",
    ]

    for p in params:
        pname = p.replace(" ", "")
        lines.append(f"    [string]${pname}")

    lines += [
        ")",
        "",
        "$config = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json",
        "",
        "# TODO: implement this script",
        "# Access config values like: $config.<key_name>",
        "throw 'TODO: implement this script'",
    ]

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def scaffold(intake_path: str, output_dir: str, platform_config=None):
    """Generate a complete A3IP package from intake.json.

    platform_config is an optional a3ip.platform_config.PlatformConfig instance.
    When None, scaffolded content uses neutral placeholders / TODO markers in
    place of platform-specific values (paths, display names, install_method,
    etc.). When provided, builders fill those placeholders from the config.
    """
    from a3ip.platform_config import PlatformConfig
    if platform_config is None:
        platform_config = PlatformConfig.empty()

    with open(intake_path, encoding="utf-8") as f:
        pkg = json.load(f)

    # Inject spec-required config keys (install_dir, etc.) before any builder runs.
    ensure_spec_required_keys(pkg, platform_config=platform_config)

    name = pkg["name"]
    pkg_dir = Path(output_dir) / f"{name}.a3ip"

    if pkg_dir.exists():
        print(f"WARNING: {pkg_dir} already exists — files will be overwritten.")

    print("\nScaffolding " + name + ".a3ip -> " + str(pkg_dir) + "\n")

    # ── Core files ──────────────────────────────────
    write(pkg_dir / "manifest.yaml",  build_manifest(pkg))
    write(pkg_dir / "INSTALL.md",     build_install(pkg, platform_config=platform_config))
    write(pkg_dir / "README.md",      build_readme(pkg))
    write(pkg_dir / "CHANGELOG.md",   build_changelog(pkg))

    # v1.7: emit two-tier adapter skeletons
    write_adapter_skeletons(pkg_dir, pkg)

    config_keys = pkg.get("configuration", [])
    if config_keys:
        write(pkg_dir / "CONFIGURE.md", build_configure(pkg))

    # ── Components ──────────────────────────────────
    for sk in pkg.get("skills", []):
        sname = kebab(sk["name"])
        write(pkg_dir / "components" / "skills" / sname / "SKILL.md",
              build_skill_md(sk, name))

    for a in pkg.get("artifacts", []):
        aname = kebab(a["name"])
        write(pkg_dir / "components" / "artifacts" / aname / "artifact.md",
              build_artifact_md(a))
        write(pkg_dir / "components" / "artifacts" / aname / "artifact.html",
              build_artifact_html(a))

    for p in pkg.get("protocols", []):
        pname = kebab(p["name"])
        write(pkg_dir / "components" / "protocols" / f"{pname}.md",
              build_protocol_md(p, config_keys))

    for pr in pkg.get("prompts", []):
        prname = kebab(pr["name"])
        write(pkg_dir / "components" / "prompts" / f"{prname}.md",
              build_prompt_md(pr))

    # ── Scripts ─────────────────────────────────────
    for sc in pkg.get("scripts", []):
        plats = sc.get("platforms", ["any"])
        if "any" in plats:
            write(pkg_dir / "scripts" / f"{sc['key']}.py",
                  build_python_stub(sc, name))
        if "windows" in plats:
            write(pkg_dir / "adapters" / "windows" / "scripts" / f"{sc['key']}.ps1",
                  build_ps1_stub(sc, name))

    # ── Copy intake.json ────────────────────────────
    import shutil
    shutil.copy2(intake_path, pkg_dir / "intake.json")
    print(f"  copied   intake.json")

    # ── Summary ─────────────────────────────────────
    total = sum(1 for _ in pkg_dir.rglob("*") if _.is_file())
    print("\nDone. " + str(total) + " files created in " + str(pkg_dir) + "\n")
    print("Next steps:")
    print("  1. Run `a3ip validate " + str(pkg_dir) + "` to check for errors")
    print("  2. Fill in the TODO sections in script stubs and protocol files")
    print("  3. Run `a3ip bundle " + str(pkg_dir) + "` to generate the distributable bundle")


def run(intake_path: str, output_dir: str = None, platform_config_path: str = None) -> int:
    """CLI entry point. Returns 0 on success, 1 on error.

    Wraps scaffold() with error handling so the cli.py dispatcher can return
    an exit code without relying on sys.exit calls inside the scaffolder.

    platform_config_path is the optional path to a platform-config JSON file
    (per docs/platform-config.schema.json). When None, scaffold() emits
    neutral content with TODO markers in place of platform-specific values.
    """
    if output_dir is None:
        output_dir = "."

    # Load platform-config if provided
    platform_cfg = None
    if platform_config_path:
        from a3ip.platform_config import PlatformConfig
        try:
            platform_cfg = PlatformConfig.load(Path(platform_config_path))
        except (FileNotFoundError, ValueError) as e:
            print("Error: " + str(e))
            return 1

    try:
        scaffold(intake_path, output_dir, platform_config=platform_cfg)
    except FileNotFoundError as e:
        print("Error: " + str(e))
        return 1
    except json.JSONDecodeError as e:
        print("Error: intake JSON could not be parsed: " + str(e))
        return 1
    except KeyError as e:
        print("Error: intake JSON missing required key: " + str(e))
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 scaffold.py <intake.json> <output_dir>")
        sys.exit(1)
    scaffold(sys.argv[1], sys.argv[2])
