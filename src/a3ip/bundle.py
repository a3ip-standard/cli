#!/usr/bin/env python3
"""
A3IP Creator -- bundle.py
Generates a .a3ip.bundle file from a package directory.

Usage:
    python3 bundle.py <package_dir> [output_path] [--spec <spec_file>]

Options:
    --spec <path>   OFFLINE ONLY. Embed the full A3IP spec document inside the
                    bundle for airgapped or offline distribution. Not recommended
                    for normal use -- the spec is fetched via spec_url: instead.
"""

import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".whl", ".exe", ".dll",
    ".ttf", ".woff", ".woff2", ".eot",
}
TEXT_EXTENSIONS = {
    ".md", ".yaml", ".yml", ".json", ".py", ".ps1", ".sh",
    ".txt", ".html", ".js", ".css", ".ts", ".tsx", ".jsx",
    ".xml", ".toml", ".ini", ".cfg", ".env", ".bat", ".cmd",
}

SPEC_BASE_URL = "https://raw.githubusercontent.com/a3ip-standard/spec/main/docs"


def is_binary(path):
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return False
    try:
        path.read_text(encoding="utf-8")
        return False
    except Exception:
        return True


def get_package_name(pkg_dir):
    name = pkg_dir.name
    if name.endswith(".a3ip"):
        name = name[:-5]
    return name


def get_package_version(pkg_dir):
    manifest = pkg_dir / "manifest.yaml"
    if not manifest.exists():
        return "1.0.0"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return "1.0.0"


def get_min_spec(pkg_dir):
    manifest = pkg_dir / "manifest.yaml"
    if not manifest.exists():
        return "1.5"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("min_a3ip_spec:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return "1.5"


def build_spec_url(min_spec):
    return SPEC_BASE_URL + "/A3IP-SPEC-v" + min_spec + ".md"


def collect_files(pkg_dir):
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


def embed_file(lines, rel_path, fpath):
    if is_binary(fpath):
        encoded = base64.b64encode(fpath.read_bytes()).decode("ascii")
        lines.append("=== FILE: " + rel_path + " ===")
        lines.append("# encoding: base64")
        lines.append(encoded)
    else:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        lines.append("=== FILE: " + rel_path + " ===")
        lines.append(content)
    lines.append("=== END FILE ===")
    lines.append("")


def hash_file(fpath):
    h = hashlib.sha256()
    h.update(fpath.read_bytes())
    return "sha256:" + h.hexdigest()


def write_source_manifest(pkg_dir, pkg_files, name, version, now):
    files_hashes = {}
    for fpath in pkg_files:
        rel = str(fpath.relative_to(pkg_dir)).replace("\\", "/")
        files_hashes[rel] = hash_file(fpath)

    source_manifest = {
        "package": name,
        "version": version,
        "bundled_at": now,
        "files": files_hashes,
    }

    dest = pkg_dir / ".a3ip-source.json"
    dest.write_text(json.dumps(source_manifest, indent=2), encoding="utf-8")
    return dest


def build_bundle(pkg_dir, output_path, spec_path=None):
    name = get_package_name(pkg_dir)
    version = get_package_version(pkg_dir)
    min_spec = get_min_spec(pkg_dir)
    spec_url = build_spec_url(min_spec)
    pkg_files = collect_files(pkg_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    spec_embedded = spec_path is not None and spec_path.exists()
    total_files = len(pkg_files) + (1 if spec_embedded else 0)

    lines = [
        "---",
        'a3ip-bundle: "1.1"',
        "package: " + name,
        'version: "' + version + '"',
        "generated: " + now,
        "files: " + str(total_files),
        "spec_url: " + spec_url,
    ]

    if spec_embedded:
        lines.append("spec_embedded: true")

    lines += [
        "---",
        "",
        "# ================================================================",
        "# A3IP BUNDLE -- AI INSTALLATION INSTRUCTIONS",
        "# ================================================================",
        "#",
        "# This file is an A3IP (AI Infrastructure Installation Package) bundle.",
        "# It contains a complete AI workflow that you can install into your workspace.",
        "#",
        "# IF YOU ARE NOT FAMILIAR WITH A3IP:",
        "#   Fetch the spec from: " + spec_url,
        "#   Read it, then return here and follow INSTALL.md to install this package.",
        "#",
        "# IF YOU KNOW A3IP:",
        "#   Read manifest.yaml, then follow INSTALL.md.",
        "#",
        "# ================================================================",
        "",
    ]

    if spec_embedded:
        spec_content = spec_path.read_text(encoding="utf-8", errors="replace")
        lines.append("=== FILE: A3IP-SPEC.md ===")
        lines.append(spec_content)
        lines.append("=== END FILE ===")
        lines.append("")

    for fpath in pkg_files:
        rel = str(fpath.relative_to(pkg_dir)).replace("\\", "/")
        embed_file(lines, rel, fpath)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    write_source_manifest(pkg_dir, pkg_files, name, version, now)
    return {"file_count": len(pkg_files), "spec_embedded": spec_embedded, "spec_url": spec_url}


def parse_args(argv):
    positional = []
    spec_path = None
    i = 1
    while i < len(argv):
        if argv[i] == "--spec" and i + 1 < len(argv):
            spec_path = Path(argv[i + 1])
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    if not positional:
        return None, None, None
    pkg_dir = Path(positional[0])
    output_path = Path(positional[1]) if len(positional) >= 2 else None
    return pkg_dir, output_path, spec_path


def main():
    pkg_dir, output_path, spec_path = parse_args(sys.argv)
    if pkg_dir is None:
        print("Usage: python3 bundle.py <package_dir> [output_path] [--spec <spec_file>]")
        print()
        print("  --spec <path>   Offline/airgapped only: embed the spec inside the bundle.")
        print("                  Normally omit this -- spec_url: in the frontmatter handles it.")
        sys.exit(1)

    if not pkg_dir.is_dir():
        print("Error: '" + str(pkg_dir) + "' is not a directory.")
        sys.exit(1)

    if spec_path and not spec_path.exists():
        print("Warning: spec file '" + str(spec_path) + "' not found -- bundling without it.")
        spec_path = None

    name = get_package_name(pkg_dir)
    version = get_package_version(pkg_dir)
    if output_path is None:
        output_path = pkg_dir.parent / (name + "-v" + version + ".a3ip.bundle")

    mode = "offline/embedded spec" if spec_path else "standard (spec_url)"
    print("Building bundle (" + mode + "): " + str(pkg_dir) + " -> " + str(output_path))

    result = build_bundle(pkg_dir, output_path, spec_path)
    size_kb = output_path.stat().st_size / 1024

    print("Bundle created: " + str(output_path))
    print("   Package files: " + str(result["file_count"]))
    print("   Spec URL:      " + result["spec_url"])
    if result["spec_embedded"]:
        print("   Spec embedded: yes (offline mode)")
    print("   Total size:    " + f"{size_kb:.1f} KB")
    print("   Source manifest written: .a3ip-source.json (baseline for sync.py)")


if __name__ == "__main__":
    main()


def bundle(pkg_dir_str: str, output_path_str: str = None, spec_path_str: str = None):
    """Programmatic entry point called by cli.py."""
    pkg_dir = Path(pkg_dir_str)
    if not pkg_dir.is_dir():
        raise ValueError("Not a directory: " + str(pkg_dir))

    spec_path = Path(spec_path_str) if spec_path_str else None
    if spec_path and not spec_path.exists():
        print("Warning: spec file '" + str(spec_path) + "' not found -- bundling without it.")
        spec_path = None

    name = get_package_name(pkg_dir)
    version = get_package_version(pkg_dir)
    output_path = Path(output_path_str) if output_path_str else pkg_dir.parent / (name + "-v" + version + ".a3ip.bundle")

    mode = "offline/embedded spec" if spec_path else "standard (spec_url)"
    print("Building bundle (" + mode + "): " + str(pkg_dir) + " -> " + str(output_path))

    result = build_bundle(pkg_dir, output_path, spec_path)
    size_kb = output_path.stat().st_size / 1024

    print("Bundle created: " + str(output_path))
    print("   Package files: " + str(result["file_count"]))
    print("   Spec URL:      " + result["spec_url"])
    if result["spec_embedded"]:
        print("   Spec embedded: yes (offline mode)")
    print("   Total size:    " + f"{size_kb:.1f} KB")
    print("   Source manifest written: .a3ip-source.json (baseline for sync.py)")
