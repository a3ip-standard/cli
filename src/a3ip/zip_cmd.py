"""
a3ip zip -- generate a .a3ip.zip file from a package directory.

The zip archive is a human-friendly distribution format (alongside the
canonical .a3ip.bundle, which is the AI-readable format). Use the zip for
email / cloud-drive transfer to humans; use the bundle for AI-to-AI transfer.

Promoted from the Creator's scripts/zip_package.py in CLI v1.5.0.
"""

import zipfile
from pathlib import Path


def get_package_name(pkg_dir: Path) -> str:
    name = pkg_dir.name
    if name.endswith(".a3ip"):
        name = name[:-5]
    return name


def build_zip(pkg_dir: Path, output_path: Path) -> int:
    """Generate the .a3ip.zip file. Returns total file count."""
    file_count = 0
    pkg_name = pkg_dir.name  # e.g. "my-workflow.a3ip"

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(pkg_dir.rglob("*")):
            if not fpath.is_file():
                continue
            parts = fpath.relative_to(pkg_dir).parts
            if any(p.startswith(".") for p in parts):
                continue
            if "__pycache__" in parts:
                continue

            arcname = pkg_name + "/" + "/".join(parts)
            zf.write(fpath, arcname)
            file_count += 1

    return file_count


def run(pkg_dir_str: str, output_str: str = None) -> int:
    """Run `a3ip zip`. Returns exit code."""
    pkg_dir = Path(pkg_dir_str)
    if not pkg_dir.is_dir():
        print("Error: '" + str(pkg_dir) + "' is not a directory.")
        return 1

    name = get_package_name(pkg_dir)

    if output_str:
        output_path = Path(output_str)
    else:
        output_path = pkg_dir.parent / (name + ".a3ip.zip")

    print("Building zip: " + str(pkg_dir) + " -> " + str(output_path))

    file_count = build_zip(pkg_dir, output_path)
    size_kb = output_path.stat().st_size / 1024

    print("Zip created: " + str(output_path))
    print("  Files: " + str(file_count))
    print("  Size:  " + ("%.1f KB" % size_kb))
    return 0
