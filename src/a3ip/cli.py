"""
a3ip -- CLI for the A3IP package format.
*Pronounced "ay-trip"*

Commands:
  a3ip new <name>              Scaffold a new package that passes validate immediately
  a3ip validate <package_dir>  Run 10 normative checks + 3 v1.9 advisory warnings
  a3ip bundle <package_dir>    Build a .a3ip.bundle file ready for distribution
  a3ip platforms               Print detected platform context (host OS + AI runtime)
  a3ip export --format <fmt>   Export to another format (cowork-plugin, apm) [planned v0.2]

See https://a3ip.dev for the full specification.
"""

import argparse
import json
import os
import sys
from pathlib import Path

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


# --------------------------------------------------------------------
# `a3ip platforms` -- platform context detection (spec v1.9)
# --------------------------------------------------------------------
#
# This command prints what an A3IP installer would derive as the host
# operating system and the active AI runtime, per the "Detecting platform
# context" section of A3IP spec v1.9. It is a heuristic; the installing AI
# remains the authoritative judge of platform context at install time.
#
# Intended consumers:
#   - Humans diagnosing "which adapter would be selected here?"
#   - Tools like the A3IP Creator, which calls `a3ip platforms --json` to
#     pre-fill its Phase 0.5 platform-detection step.

def _detect_host_os() -> str:
    """Return 'windows' or 'posix' per spec v1.7+ adapter convention."""
    if os.name == "nt":
        return "windows"
    return "posix"


def _detect_user_home() -> Path:
    """Return the user's home directory, expanding ~ via OS-appropriate envs."""
    candidate = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if candidate:
        return Path(candidate)
    return Path.home()


def _detect_runtime_signals() -> list:
    """Return a list of (signal, runtime, source) tuples ordered by strength.

    Signal strength:
      - 'directory' (strong): runtime-specific config dir exists
      - 'project'   (medium): convention file present in CWD
      - 'env'       (weak):   environment variable hint
    """
    signals = []
    home = _detect_user_home()
    cwd = Path.cwd()

    # Strong: runtime config directories
    if (home / ".codex").is_dir():
        signals.append(("directory", "codex", str(home / ".codex")))
    if (home / ".claude").is_dir():
        signals.append(("directory", "claude-code-or-cowork", str(home / ".claude")))
    if (home / ".cursor").is_dir():
        signals.append(("directory", "cursor", str(home / ".cursor")))

    # Medium: project-level convention files
    if (cwd / "AGENTS.md").is_file():
        signals.append(("project", "codex", str(cwd / "AGENTS.md")))
    if (cwd / "CLAUDE.md").is_file():
        signals.append(("project", "claude-code-or-cowork", str(cwd / "CLAUDE.md")))

    # Weak: environment variables
    if os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        signals.append(("env", "codex-or-openai", "OPENAI/CODEX_API_KEY set"))
    if os.environ.get("ANTHROPIC_API_KEY"):
        signals.append(("env", "claude-family", "ANTHROPIC_API_KEY set"))

    return signals


def _summarize_runtime(signals: list) -> str:
    """Pick the most likely runtime label from the strongest signals.

    Returns 'unknown' if there's nothing to go on, which is the right answer --
    the installing AI MUST ask the user when context is ambiguous.
    """
    if not signals:
        return "unknown"
    # Prefer directory signals; among them, the first one wins.
    for strength in ("directory", "project", "env"):
        for sig_strength, runtime, _ in signals:
            if sig_strength == strength:
                return runtime
    return "unknown"


def _cmd_platforms(args: argparse.Namespace) -> int:
    host_os = _detect_host_os()
    home = _detect_user_home()
    cwd = Path.cwd()
    signals = _detect_runtime_signals()
    runtime_label = _summarize_runtime(signals)

    if args.json:
        result = {
            "spec_version": __spec_version__,
            "host_os": host_os,
            "runtime": runtime_label,
            "home": str(home),
            "cwd": str(cwd),
            "signals": [
                {"strength": s, "runtime": r, "source": src}
                for (s, r, src) in signals
            ],
        }
        print(json.dumps(result, indent=2))
        return 0

    print("A3IP platform context (per spec v" + __spec_version__ + ")")
    print()
    print("  Host OS:          " + host_os)
    print("  User home:        " + str(home))
    print("  Working dir:      " + str(cwd))
    print("  Runtime (likely): " + runtime_label)

    if signals:
        print()
        print("  Detection signals:")
        for strength, runtime, source in signals:
            label = ("    [" + strength + "]").ljust(16)
            print(label + runtime + "  <-  " + source)
    else:
        print()
        print("  No detection signals found. The installing AI MUST ask the user.")

    print()
    print("Note: this is a heuristic per spec v1.9 'Detecting platform context'.")
    print("The installing AI remains authoritative -- it may know better from its")
    print("tool surface than this CLI can see from filesystem alone.")
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
        help="Run 10 normative checks plus 3 v1.9 advisory warnings",
        description=(
            "Validate an A3IP package against the spec.\n\n"
            "Runs 10 normative checks (errors block install):\n"
            "   1. Config coverage          -- {{config.*}} refs match manifest declarations\n"
            "   2. Script existence         -- declared script files exist on disk\n"
            "   3. Script config reads      -- scripts only read declared config keys\n"
            "   4. Cross-platform           -- Windows scripts have a cross-platform fallback\n"
            "   5. Auth flows               -- auth scripts are referenced in INSTALL.md\n"
            "   6. Changelog present        -- CHANGELOG.md required for version > 1.0.0\n"
            "   7. Refresh scripts          -- refresh_script keys declared in manifest\n"
            "   8. Trust->permissions       -- elevated trust requires a permissions block\n"
            "   9. Trust->plan section      -- write/shell trust requires ## Plan in INSTALL.md\n"
            "  10. INSTALL.md spec          -- install_dir + installed.json wiring correct\n"
            "\n"
            "Plus 3 v1.9 advisory warnings (do not block install; harden to errors in v2.0):\n"
            "  11. Adapter outcome coverage -- runtime adapters address Step 5/6/7 outcomes\n"
            "  12. INSTALL.md tier shape    -- Tier 2 steps free of procedure-language leakage\n"
            "  13. Adapter knowledge-shape  -- adapters are more prose than code (>= 2:1 ratio)\n"
            "\n"
            "Exit code: 0 if all errors are zero (warnings present or absent), 1 otherwise."
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

    # -- platforms ------------------------------------------------------------
    p_plat = sub.add_parser(
        "platforms",
        help="Print detected platform context (host OS + AI runtime)",
        description=(
            "Print the platform context an A3IP installer would derive here:\n"
            "host operating system (windows/posix) and the AI runtime (cowork,\n"
            "codex, claude-code, cursor, ...).\n\n"
            "This is a heuristic per A3IP spec v1.9 'Detecting platform context'.\n"
            "Useful for diagnosing 'which adapter would be selected?' and for tools\n"
            "(like the A3IP Creator) that want to pre-fill platform information.\n\n"
            "Use --json for a machine-readable report."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_plat.add_argument(
        "--json", action="store_true",
        help="Print a JSON report instead of the human-readable summary",
    )
    p_plat.set_defaults(func=_cmd_platforms)

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
