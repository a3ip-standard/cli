"""
A3IP bundle — generates a .a3ip.bundle file from a package directory.
"""

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".whl", ".exe", ".dll",
    ".ttf", ".woff", ".woff2", ".eot",
}
_TEXT_EXTENSIONS = {
    ".md", ".yaml", ".yml", ".json", ".py", ".ps1", ".sh",
    ".txt", ".html", ".js", ".css", ".ts", ".tsx", ".jsx",
    ".xml", ".toml", ".ini", ".cfg", ".env", ".bat", ".cmd",
}


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return True
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        return False
    try:
        path.read_text(encoding="utf-8")
        return False
    except Exception:
        return True


def _get_package_name(pkg_dir: Path) -> str:
    name = pkg_dir.name
    if name.endswith(".a3ip"):
        name = name[:-5]
    return name


def _get_package_version(pkg_dir: Path) -> str:
    manifest = pkg_dir / "manifest.yaml"
    if not manifest.exists():
        return "1.0.0"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return "1.0.0"


def _collect_files(pkg_dir: Path) -> list[Path]:
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


def _embed_file(lines: list, rel_path: str, fpath: Path) -> None:
    lines.append("=== FILE: " + rel_path + " ===")
    if _is_binary(fpath):
        lines.append("# encoding: base64")
        lines.append(base64.b64encode(fpath.read_bytes()).decode("ascii"))
    else:
        lines.append(fpath.read_text(encoding="utf-8", errors="replace"))
    lines.append("=== END FILE ===")
    lines.append("")


def _hash_file(fpath: Path) -> str:
    h = hashlib.sha256()
    h.update(fpath.read_bytes())
    return "sha256:" + h.hexdigest()


def _write_source_manifest(pkg_dir: Path, pkg_files: list, name: str, version: str, now: str) -> None:
    files_hashes = {
        str(f.relative_to(pkg_dir)).replace("\\", "/"): _hash_file(f)
        for f in pkg_files
    }
    source = {"package": name, "version": version, "bundled_at": now, "files": files_hashes}
    (pkg_dir / ".a3ip-source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")


def build_bundle(pkg_dir: Path, output_path: Path, spec_path: Path | None = None) -> dict:
    """Build a .a3ip.bundle file. Returns stats dict."""
    name = _get_package_name(pkg_dir)
    version = _get_package_version(pkg_dir)
    pkg_files = _collect_files(pkg_dir)
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
        "spec_embedded: " + ("true" if spec_embedded else "false"),
        "---",
        "",
        "# ================================================================",
        "# A3IP BUNDLE — AI INSTALLATION INSTRUCTIONS",
        "# ================================================================",
        "#",
        "# This file is an A3IP (AI Infrastructure Installation Package) bundle.",
        "# It contains a complete AI workflow you can install into your workspace.",
        "#",
    ]

    if spec_embedded:
        lines += [
            "# IF YOU ARE NOT FAMILIAR WITH A3IP:",
            "#   1. Read the embedded spec first (A3IP-SPEC.md, the first FILE block below).",
            "#   2. Read manifest.yaml to understand what this package contains.",
            "#   3. Follow INSTALL.md to install it.",
            "#",
            "# IF YOU KNOW A3IP: Read manifest.yaml, then follow INSTALL.md.",
        ]
    else:
        lines += [
            "# Read manifest.yaml to understand what this package contains.",
            "# Follow INSTALL.md to install it.",
            "#",
            "# Note: This bundle does not include the A3IP spec.",
            "# If you are unfamiliar with A3IP, ask for the spec before proceeding.",
        ]

    lines += ["#", "# ================================================================", ""]

    if spec_embedded:
        lines.append("=== FILE: A3IP-SPEC.md ===")
        lines.append(spec_path.read_text(encoding="utf-8", errors="replace"))
        lines.append("=== END FILE ===")
        lines.append("")

    for fpath in pkg_files:
        rel = str(fpath.relative_to(pkg_dir)).replace("\\", "/")
        _embed_file(lines, rel, fpath)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    _write_source_manifest(pkg_dir, pkg_files, name, version, now)

    return {"file_count": len(pkg_files), "spec_embedded": spec_embedded, "output": output_path}


def bundle(pkg_dir_str: str, output_path_str: str | None = None, spec_path_str: str | None = None) -> dict:
    """Public API: bundle a package. Returns stats dict or raises on error."""
    pkg_dir = Path(pkg_dir_str)
    if not pkg_dir.is_dir():
        raise ValueError("Not a directory: " + pkg_dir_str)

    spec_path = Path(spec_path_str) if spec_path_str else None
    if spec_path and not spec_path.exists():
        print("Warning: spec file '" + spec_path_str + "' not found — bundling without it.")
        spec_path = None

    name = _get_package_name(pkg_dir)
    output_path = Path(output_path_str) if output_path_str else pkg_dir.parent / (name + ".a3ip.bundle")

    mode = "with spec" if spec_path else "without spec"
    print("Building bundle (" + mode + "): " + str(pkg_dir) + " → " + str(output_path))

    result = build_bundle(pkg_dir, output_path, spec_path)
    size_kb = output_path.stat().st_size / 1024

    print("Bundle created: " + str(output_path))
    print("  Package files: " + str(result["file_count"]))
    if result["spec_embedded"]:
        print("  Spec embedded: yes (" + spec_path.name + ")")
    else:
        print("  Spec embedded: no  (use --spec to include for external distribution)")
    print("  Total size:    " + f"{size_kb:.1f} KB")

    return result
