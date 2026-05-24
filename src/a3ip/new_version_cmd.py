"""
a3ip new-version -- cut a new package version.

Bumps `version:` (and `latest_change:`) in manifest.yaml and prepends a
CHANGELOG.md entry. If `.a3ip-sync-report.json` is present (written by
`a3ip sync`), the '### Files changed' section is auto-populated from the
report and the report is consumed (deleted).

Promoted from the Creator's scripts/new_version.py in CLI v1.5.0.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def bump_manifest(pkg_dir: Path, new_version: str) -> str:
    """Update version: and latest_change: in manifest.yaml. Returns old version."""
    manifest_path = pkg_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError("manifest.yaml not found in " + str(pkg_dir))

    text = manifest_path.read_text(encoding="utf-8")

    old_version = "unknown"
    m = re.search(r'^version:\s*["\']?([^"\'\n]+)["\']?', text, re.MULTILINE)
    if m:
        old_version = m.group(1).strip()

    text = re.sub(
        r'^(version:\s*)["\']?[^"\'\n]+["\']?',
        'version: "' + new_version + '"',
        text,
        count=1,
        flags=re.MULTILINE,
    )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if re.search(r'^latest_change:', text, re.MULTILINE):
        text = re.sub(
            r'^latest_change:.*',
            'latest_change: ' + today,
            text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        text = re.sub(
            r'^(version:.*)',
            r'\1\nlatest_change: ' + today,
            text,
            count=1,
            flags=re.MULTILINE,
        )

    manifest_path.write_text(text, encoding="utf-8")
    print("  updated  manifest.yaml  (version: " + old_version + " -> " + new_version + ")")
    return old_version


def load_sync_report(pkg_dir: Path):
    report_path = pkg_dir / ".a3ip-sync-report.json"
    if report_path.exists():
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def consume_sync_report(pkg_dir: Path):
    report_path = pkg_dir / ".a3ip-sync-report.json"
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        report_path.unlink()
    except Exception:
        pass
    return report


def prepend_changelog(pkg_dir: Path, new_version: str) -> str:
    """Prepend a changelog entry for new_version. Returns the entry text."""
    changelog_path = pkg_dir / "CHANGELOG.md"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sync = consume_sync_report(pkg_dir)

    # manifest.yaml and CHANGELOG.md are always modified by this command itself.
    always_changed = (
        "- `manifest.yaml` - bumped\n"
        "- `CHANGELOG.md` - replaced"
    )

    if sync and sync.get("changelog_files_changed"):
        sync_files = "\n".join(sync["changelog_files_changed"])
        files_changed_block = always_changed + "\n" + sync_files
        files_changed_note = ""
    else:
        files_changed_block = (
            always_changed + "\n"
            "TODO: List every other file that changed.\n"
            "Format: `path/to/file.ext` - replaced | added | deleted"
        )
        files_changed_note = (
            "\n*(Run `a3ip sync` before `a3ip new-version` to auto-populate this section.)*"
        )

    entry = (
        "## " + new_version + "\n\n"
        "*Released: " + today + "*\n\n"
        "### Summary\n\n"
        "TODO: Describe what changed in this version and why.\n\n"
        "### Upgrade steps\n\n"
        "TODO: Write concise INSTALL.md-style steps for only what changed.\n"
        "For example:\n"
        "- Replace `components/artifacts/<name>/artifact.html` with the new version.\n"
        "- Re-register the artifact in your platform.\n\n"
        '*(If nothing requires active upgrade steps, write: '
        '"No action required - non-breaking update.")*\n\n'
        "### Breaking changes\n\n"
        "TODO: List any breaking changes. For each one, state:\n"
        "- What was renamed, removed, or added\n"
        "- What the AI must do (re-ask config wizard for affected keys, re-copy scripts, etc.)\n\n"
        '*(If none, write: "None.")*\n\n'
        "### Files changed\n\n"
        + files_changed_block + files_changed_note + "\n\n"
    )

    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")
        lines = existing.splitlines(keepends=True)
        in_frontmatter = False
        header_end = 0
        for i, line in enumerate(lines):
            if line.strip() == "---":
                if i == 0:
                    in_frontmatter = True
                    continue
                elif in_frontmatter:
                    in_frontmatter = False
                    header_end = i + 1
                    break

        first_version_line = None
        for i in range(header_end, len(lines)):
            if lines[i].startswith("## "):
                first_version_line = i
                break

        if first_version_line is not None:
            new_content = (
                "".join(lines[:first_version_line])
                + "---\n\n"
                + entry
                + "".join(lines[first_version_line:])
            )
        else:
            new_content = existing.rstrip("\n") + "\n\n---\n\n" + entry

        changelog_path.write_text(new_content, encoding="utf-8")
        print("  updated  CHANGELOG.md  (prepended entry for " + new_version + ")")
    else:
        header = (
            "---\n"
            'format: a3ip-changelog\n'
            'spec: "1.1"\n'
            "---\n\n"
            "# Changelog\n\n"
            "New version entries go at the **top** of this file (newest first).\n\n"
            "---\n\n"
        )
        changelog_path.write_text(header + entry, encoding="utf-8")
        print("  created  CHANGELOG.md  (first entry: " + new_version + ")")

    return entry


def run(pkg_dir_str: str, new_version: str) -> int:
    """Cut a new version. Returns exit code."""
    pkg_dir = Path(pkg_dir_str)

    if not pkg_dir.is_dir():
        print("Error: '" + str(pkg_dir) + "' is not a directory.")
        return 1

    if not re.match(r'^\d+\.\d+(\.\d+)?$', new_version):
        print("Error: '" + new_version + "' is not a valid version (expected x.y or x.y.z).")
        return 1

    print()
    print("Cutting version " + new_version + " for: " + str(pkg_dir))
    print()

    sync = load_sync_report(pkg_dir)
    if sync:
        suggested = sync.get("suggested_bump_type", "").upper()
        n_changed = (
            len(sync.get("modified", []))
            + len(sync.get("added", []))
            + len(sync.get("deleted", []))
        )
        print("  sync report found: " + str(n_changed) + " file(s) changed since last bundle")
        if suggested:
            print("  suggested bump type: " + suggested)
        print("  '### Files changed' will be auto-populated from the sync report")
        print()

    try:
        old_version = bump_manifest(pkg_dir, new_version)
    except FileNotFoundError as e:
        print("Error: " + str(e))
        return 1

    entry = prepend_changelog(pkg_dir, new_version)

    print()
    print("Version bumped: " + old_version + " -> " + new_version)
    print()
    print("CHANGELOG.md entry added (fill in the TODOs):")
    print("-" * 60)
    print(entry)
    print("-" * 60)
    print()
    print("Next steps:")
    print("  1. Edit CHANGELOG.md - fill in Summary, Upgrade steps, Breaking changes")
    print("     ('### Files changed' is already populated if `a3ip sync` ran first)")
    print("  2. Make the actual file changes the version describes")
    print("  3. Run `a3ip validate` to check for errors")
    print("  4. Run `a3ip bundle` to generate the updated distributable bundle")
    return 0
