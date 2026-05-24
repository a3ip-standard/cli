"""
a3ip sync -- detect changes in a package directory since the last bundle.

Reads .a3ip-source.json from the package directory (written by `a3ip bundle`
at bundle time). Compares current file states against that baseline.

Reports modified / added / deleted files, suggests a semver bump (patch /
minor / major) with reasoning, and writes .a3ip-sync-report.json so that
`a3ip new-version` can populate the CHANGELOG's '### Files changed' section
automatically.

Promoted from the Creator's scripts/sync.py in CLI v1.5.0 (was previously
called directly by Creator phases). The Creator now invokes this command
instead of its own copy.
"""

import hashlib
import json
from pathlib import Path
from typing import List, Tuple


# --- File collection (mirrors bundle.py) ------------------------------------

def collect_files(pkg_dir: Path) -> List[Path]:
    """Collect all non-hidden, non-pycache files in the package directory."""
    files = []
    for fpath in sorted(pkg_dir.rglob("*")):
        if not fpath.is_file():
            continue
        parts = fpath.relative_to(pkg_dir).parts
        if any(p.startswith(".") for p in parts):
            continue
        if "__pycache__" in parts:
            continue
        files.append(fpath)
    return files


def hash_file(fpath: Path) -> str:
    h = hashlib.sha256()
    h.update(fpath.read_bytes())
    return "sha256:" + h.hexdigest()


# --- Bump-type heuristic ----------------------------------------------------

def suggest_bump(added, modified, deleted) -> Tuple[str, List[str]]:
    """Suggest a semver bump type from the diff. Returns (bump, reasons)."""
    reasons: List[str] = []
    bump = "patch"

    def upgrade(to: str, reason: str) -> None:
        nonlocal bump
        reasons.append(reason)
        if to == "major" or (to == "minor" and bump == "patch"):
            bump = to

    if not added and not modified and not deleted:
        return "none", []

    for f in deleted:
        if any(seg in f for seg in ("scripts/", "components/", "adapters/")):
            upgrade("minor", "'" + f + "' deleted - verify if this is a breaking removal (-> major)")
        else:
            upgrade("patch", "'" + f + "' deleted")

    for f in added:
        if any(seg in f for seg in ("scripts/", "components/", "adapters/")):
            upgrade("minor", "'" + f + "' added - new component")
        else:
            upgrade("patch", "'" + f + "' added")

    for f in modified:
        if f == "manifest.yaml":
            upgrade("minor", "manifest.yaml changed - check for config/dependency additions (minor) or removals/renames (major)")
        elif "SKILL.md" in f or "protocols/" in f or "prompts/" in f:
            upgrade("minor", "'" + f + "' changed - behavior or instructions updated")
        elif "scripts/" in f or "adapters/" in f:
            upgrade("patch", "'" + f + "' changed - script updated (patch if interface unchanged)")
        elif "artifacts/" in f:
            upgrade("patch", "'" + f + "' changed - artifact updated")
        elif f in ("INSTALL.md", "CONFIGURE.md"):
            upgrade("patch", "'" + f + "' changed - install/config instructions updated")
        else:
            upgrade("patch", "'" + f + "' changed")

    return bump, reasons


# --- Entry point ------------------------------------------------------------

def run(pkg_dir_str: str) -> int:
    """Run `a3ip sync` against a package directory. Returns exit code."""
    pkg_dir = Path(pkg_dir_str)
    if not pkg_dir.is_dir():
        print("Error: '" + str(pkg_dir) + "' is not a directory.")
        return 1

    source_manifest_path = pkg_dir / ".a3ip-source.json"
    if not source_manifest_path.exists():
        print("No .a3ip-source.json found in " + str(pkg_dir))
        print()
        print("This file is written by `a3ip bundle` when a bundle is produced.")
        print("Run `a3ip bundle` first to establish a baseline, then make your changes,")
        print("then run `a3ip sync` to see what changed.")
        return 1

    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    baseline_files = source_manifest["files"]
    baseline_version = source_manifest.get("version", "unknown")
    bundled_at = source_manifest.get("bundled_at", "unknown")
    package_name = source_manifest.get("package", pkg_dir.name)

    current_files = collect_files(pkg_dir)
    current_hashes = {}
    for fpath in current_files:
        rel = str(fpath.relative_to(pkg_dir)).replace("\\", "/")
        current_hashes[rel] = hash_file(fpath)

    baseline_set = set(baseline_files.keys())
    current_set = set(current_hashes.keys())

    added = sorted(current_set - baseline_set)
    deleted = sorted(baseline_set - current_set)
    modified = sorted(
        f for f in (current_set & baseline_set)
        if current_hashes[f] != baseline_files[f]
    )

    total = len(added) + len(modified) + len(deleted)

    print()
    print("Sync: " + package_name + "  (baseline: v" + baseline_version + ", bundled " + bundled_at + ")")
    print("-" * 60)

    if total == 0:
        print("No changes since last bundle.")
        print()
        print("Nothing to release. Make your changes, then run `a3ip sync` again.")
        return 0

    print(str(total) + " file(s) changed - " + str(len(modified)) + " modified, " + str(len(added)) + " added, " + str(len(deleted)) + " deleted")
    print()

    if modified:
        print("Modified:")
        for f in modified:
            print("  ~ " + f)
    if added:
        print("Added:")
        for f in added:
            print("  + " + f)
    if deleted:
        print("Deleted:")
        for f in deleted:
            print("  - " + f)

    bump_type, reasons = suggest_bump(added, modified, deleted)
    print()
    print("Suggested bump type: " + bump_type.upper())
    for r in reasons:
        print("  - " + r)

    changelog_lines = []
    for f in modified:
        changelog_lines.append("- `" + f + "` - replaced")
    for f in added:
        changelog_lines.append("- `" + f + "` - added")
    for f in deleted:
        changelog_lines.append("- `" + f + "` - deleted")

    print()
    print("### Files changed  (paste into CHANGELOG.md)")
    print("-" * 60)
    for line in changelog_lines:
        print(line)
    print("-" * 60)

    report = {
        "package": package_name,
        "baseline_version": baseline_version,
        "modified": modified,
        "added": added,
        "deleted": deleted,
        "suggested_bump_type": bump_type,
        "changelog_files_changed": changelog_lines,
    }
    report_path = pkg_dir / ".a3ip-sync-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print("Sync report written: .a3ip-sync-report.json")
    print("Run `a3ip new-version` to cut a release - it will read the report automatically.")
    print()
    print("Next:")
    print("  a3ip new-version " + str(pkg_dir) + " <new_version>")

    return 0
