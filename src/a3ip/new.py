"""
A3IP new — scaffold a minimal valid A3IP package.

Creates a directory at <name>/ containing all required files.
The scaffolded package passes `a3ip validate` on the first run.
"""

import sys
from pathlib import Path

_MANIFEST_TEMPLATE = """\
$schema: https://a3ip.dev/schema/v1.5/manifest.json

name: {name}
version: "1.0.0"
description: "Describe what this workflow does."
min_a3ip_spec: "1.5"
trust_level: read-only

# Declare every external resource this package uses.
# Remove sections that don't apply.
#
# permissions:
#   filesystem:
#     - path: "./output/"
#       access: write
#       reason: "Stores generated files."
#   network:
#     - domain: "api.example.com"
#       reason: "Fetches data from the API."
#   mcp:
#     - name: example-mcp
#       reason: "Reads and writes to the connected service."

components:
  skills:
    - path: components/skills/{name}.md
  # artifacts:
  #   - path: components/artifacts/output.md
  # prompts:
  #   - path: components/prompts/main.md
  # scripts:
  #   - key: run
  #     implementations:
  #       - file: scripts/run.py
  #         platform: any
  #         trust_level: read-only

# configuration:
#   - key: api_token
#     label: "API Token"
#     type: string
#     sensitive: true
#     storage: env
"""

_CONFIGURE_TEMPLATE = """\
# CONFIGURE.md — {name}
# Ask the user these questions before starting the install.
# Answers fill in {{{{config.*}}}} placeholders in INSTALL.md.
# Remove this file entirely if the package needs no configuration.

## Questions

**1. (Example) Which workspace should the workflow use?**
- Prompt: "Enter the path to your workspace directory:"
- Key: `workspace_dir`
- Type: directory_path
- Default: `./workspace`
"""

_INSTALL_TEMPLATE = """\
# INSTALL.md — {name}

## Overview

Brief description of what gets installed and what the user will be able to do.

## Pre-flight checklist

- [ ] (List any requirements the user must have ready before starting)

## Steps

### Step 1: (First action)

Describe what to do here. Reference config values like {{{{config.workspace_dir}}}}.

- [ ] Task A
- [ ] Task B

### Step 2: Verify

- [ ] Confirm the workflow is working as expected.

## Done

The `{name}` workflow is now installed.
"""

_SKILL_TEMPLATE = """\
# {name}

## Overview

Describe what this skill does and when to invoke it.

## Usage

Explain how to use the skill, what inputs it needs, and what output to expect.

## Steps

1. (First step)
2. (Second step)
3. Confirm the result.

## Notes

Any caveats, limitations, or tips.
"""

_README_TEMPLATE = """\
# {name}

> One-line description of what this workflow does.

## What it does

Describe the workflow in 2–3 sentences. What problem does it solve?

## Requirements

- (List any tools, accounts, or credentials needed)

## Quick start

```
a3ip bundle {name}/
# Drop the resulting .a3ip.bundle file into a conversation with an A3IP-compatible AI.
```

## Configuration

| Key | Description | Required |
|-----|-------------|----------|
| (example) `api_token` | API token for the connected service | Yes |

## License

[Apache 2.0](LICENSE) — or replace with your chosen license.
"""


def scaffold(name: str, output_dir: str | None = None) -> Path:
    """
    Create a new A3IP package directory at output_dir/name (or ./name).
    Returns the path to the created directory.
    Raises FileExistsError if the directory already exists.
    """
    base = Path(output_dir) if output_dir else Path(".")
    pkg_dir = base / name

    if pkg_dir.exists():
        raise FileExistsError("Directory already exists: " + str(pkg_dir))

    # Validate name (must match manifest.yaml name pattern)
    import re
    if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', name):
        raise ValueError(
            "Package name must be lowercase alphanumeric with hyphens "
            "(e.g. 'my-workflow'), got: " + repr(name)
        )

    # Create directory tree
    (pkg_dir / "components" / "skills").mkdir(parents=True)
    (pkg_dir / "scripts").mkdir()

    # Write files
    (pkg_dir / "manifest.yaml").write_text(
        _MANIFEST_TEMPLATE.format(name=name), encoding="utf-8"
    )
    (pkg_dir / "CONFIGURE.md").write_text(
        _CONFIGURE_TEMPLATE.format(name=name), encoding="utf-8"
    )
    (pkg_dir / "INSTALL.md").write_text(
        _INSTALL_TEMPLATE.format(name=name), encoding="utf-8"
    )
    (pkg_dir / "README.md").write_text(
        _README_TEMPLATE.format(name=name), encoding="utf-8"
    )
    (pkg_dir / "components" / "skills" / (name + ".md")).write_text(
        _SKILL_TEMPLATE.format(name=name), encoding="utf-8"
    )

    # Placeholder .gitkeep so scripts/ is committed empty
    (pkg_dir / "scripts" / ".gitkeep").write_text("", encoding="utf-8")

    return pkg_dir
