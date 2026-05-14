"""
a3ip -- CLI for the A3IP package format.
*Pronounced "ay-trip"*

Commands:
  a3ip new <name>              Scaffold a new package that passes validate immediately
  a3ip validate <package_dir>  Run 9 normative checks; exit 0 if clean
  a3ip bundle <package_dir>    Build a .a3ip.bundle file ready for distribution
  a3ip export --format <fmt>   Export to another format (cowork-plugin, apm) [planned v0.2]

See https://a3ip.dev for the full specification.
"""

import argparse
import sys

from a3ip import __version__, __spec_version__


def _cmd_new(args: argparse.Namespace) -> int:
    from a3ip.new import scaffold
    try:
        pkg_dir = scaffold(args.name, args.output_dir)
    except FileExistsError as e:
        print("Error: " + str(e), file=sys.stderr)
        return 1
    except ValueError as e:
        print("Error: " + str(e), file=sys.stderr)
        return 1

    print("Created package: " + str(pkg_dir))
    print()
    print("  " + str(pkg_dir / "manifest.yaml"))
    print("  " + str(pkg_dir / "CONFIGURE.md"))
    print("  " + str(pkg_dir / "INSTALL.md"))
    print("  " + str(pkg_dir / "README.md"))
    print("  " + str(pkg_dir / "components" / "skills" / (args.name + ".md")))
    print()
    print("Next steps:")
    print("  1. Edit manifest.yaml -- fill in description, permissions, components.")
    print("  2. Edit INSTALL.md -- describe the install steps.")
    print("  3. Run:  a3ip validate " + args.name + "/")
    print("  4. Run:  a3ip bundle " + args.name + "/")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    from a3ip.validate import validate
    report = validate(args.package_dir)
    if args.json:
        import json
        print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def _cmd_bundle(args: argparse.Namespace) -> int:
    from a3ip.bundle import bundle
    try:
        bundle(
            pkg_dir_str=args.package_dir,
            output_path_str=args.output,
            spec_path_str=args.spec,
        )
    except (ValueError, OSError) as e:
        print("Error: " + str(e), file=sys.stderr)
        return 1
    return 0


_EXPORT_FORMATS = {
    "cowork-plugin": (
        "Target: Anthropic Cowork Plugin (.plugin bundle)\n"
        "\n"
        "A3IP packages map cleanly to Cowork plugins: skills become skill files,\n"
        "permissions become connector declarations, configuration becomes plugin settings.\n"
        "A3IP acts as the portability and security layer around the plugin ecosystem --\n"
        "packages authored once can target Cowork, Codex, Cursor, and others.\n"
        "\n"
        "Planned for a3ip v0.2. Track: https://github.com/a3ip-standard/cli/issues"
    ),
    "apm": (
        "Target: Microsoft APM (Agent Package Manifest)\n"
        "\n"
        "A3IP is a superset of APM -- every A3IP package can emit a valid APM manifest.\n"
        "The converter preserves components, dependencies, and context declarations.\n"
        "\n"
        "Planned for a3ip v0.2. Track: https://github.com/a3ip-standard/cli/issues"
    ),
}


def _cmd_export(args: argparse.Namespace) -> int:
    fmt = args.format
    details = _EXPORT_FORMATS[fmt]
    print("a3ip export --format " + fmt)
    print()
    print("  Status: planned for a3ip v0.2")
    print()
    for line in details.splitlines():
        print(("  " + line) if line else "")
    print()
    print("  Until this converter ships, install the package natively:")
    print("  Drop the .a3ip.bundle into any A3IP-compatible AI and ask it to install.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="a3ip",
        description=(
            "A3IP -- AI Infrastructure Installation Package (pronounced 'ay-trip')\n"
            "Package, validate, and bundle portable AI agent workflows.\n\n"
            "Spec:  https://a3ip.dev\n"
            "Docs:  https://github.com/a3ip-standard/spec"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version",
        version="a3ip " + __version__ + " (spec " + __spec_version__ + ")"
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # -- new ------------------------------------------------------------------
    p_new = sub.add_parser(
        "new",
        help="Scaffold a new package that passes validate on first run",
        description=(
            "Create a new A3IP package directory with all required files.\n"
            "The scaffolded package passes `a3ip validate` immediately."
        ),
    )
    p_new.add_argument("name", help="Package name (lowercase, hyphens, e.g. my-workflow)")
    p_new.add_argument(
        "--output-dir", metavar="DIR", dest="output_dir", default=None,
        help="Parent directory to create the package in (default: current directory)",
    )
    p_new.set_defaults(func=_cmd_new)

    # -- validate -------------------------------------------------------------
    p_val = sub.add_parser(
        "validate",
        help="Run 9 normative checks on a package directory",
        description=(
            "Validate an A3IP package against the spec.\n\n"
            "Runs 9 checks:\n"
            "  1. Config coverage     -- {{config.*}} refs match manifest declarations\n"
            "  2. Script existence    -- declared script files exist on disk\n"
            "  3. Script config reads -- scripts only read declared config keys\n"
            "  4. Cross-platform      -- Windows scripts have a cross-platform fallback\n"
            "  5. Auth flows          -- auth scripts are referenced in INSTALL.md\n"
            "  6. Changelog present   -- CHANGELOG.md required for version > 1.0.0\n"
            "  7. Refresh scripts     -- refresh_script keys declared in manifest\n"
            "  8. Trust->permissions  -- elevated trust requires a permissions block\n"
            "  9. Trust->plan section -- write/shell trust requires ## Plan in INSTALL.md\n\n"
            "Exit code: 0 if all checks pass, 1 if any errors found.\n"
            "Warnings do not affect the exit code."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_val.add_argument("package_dir", help="Path to the package directory to validate")
    p_val.add_argument(
        "--json", action="store_true",
        help="Print a JSON report in addition to the human-readable output",
    )
    p_val.set_defaults(func=_cmd_validate)

    # -- bundle ---------------------------------------------------------------
    p_bun = sub.add_parser(
        "bundle",
        help="Build a .a3ip.bundle file ready for distribution",
        description=(
            "Bundle a package directory into a single .a3ip.bundle file.\n\n"
            "The bundle contains every file in the package in a plain-text format\n"
            "that any A3IP-compatible AI can read and install.\n\n"
            "Binary files are base64-encoded. Hidden files and __pycache__ are excluded."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_bun.add_argument("package_dir", help="Path to the package directory to bundle")
    p_bun.add_argument(
        "--output", "-o", metavar="PATH",
        help="Output path for the bundle (default: <package_dir>/../<name>.a3ip.bundle)",
    )
    p_bun.add_argument(
        "--spec", metavar="PATH",
        help=(
            "Embed the A3IP spec file into the bundle. "
            "Use this when distributing to recipients who may not know A3IP."
        ),
    )
    p_bun.set_defaults(func=_cmd_bundle)

    # -- export ---------------------------------------------------------------
    p_exp = sub.add_parser(
        "export",
        help="Export to another format: cowork-plugin, apm [planned v0.2]",
        description=(
            "Convert an A3IP package to another agent package format.\n\n"
            "A3IP is designed as an interoperability layer -- packages can be exported\n"
            "to platform-native formats without losing permissions or component structure.\n\n"
            "Available formats:\n"
            "  cowork-plugin   Anthropic Cowork Plugin bundle\n"
            "  apm             Microsoft Agent Package Manifest\n\n"
            "These commands are documented now so tooling and CI scripts can reference them.\n"
            "They will print a roadmap notice until the converters ship in v0.2."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_exp.add_argument("package_dir", help="Path to the package directory to export")
    p_exp.add_argument(
        "--format", "-f", required=True,
        choices=list(_EXPORT_FORMATS.keys()),
        metavar="FORMAT",
        help="Target format: " + ", ".join(_EXPORT_FORMATS.keys()),
    )
    p_exp.set_defaults(func=_cmd_export)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
