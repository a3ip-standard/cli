"""
A3IP validate — runs all 10 normative checks on a package directory.

Exit code: 0 if all checks pass (errors == 0), 1 otherwise.
Warnings do not affect the exit code.
"""

import re
from pathlib import Path

try:
    import yaml as _yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ──────────────────────────────────────────────────────────
# Manifest loading
# ──────────────────────────────────────────────────────────

def load_manifest(pkg_dir: Path) -> dict:
    manifest_path = pkg_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError("manifest.yaml not found in " + str(pkg_dir))
    content = manifest_path.read_text(encoding="utf-8")
    if HAS_YAML:
        return _yaml.safe_load(content)
    return _parse_manifest_minimal(content)


def _parse_manifest_minimal(text: str) -> dict:
    """Minimal YAML parser — handles only what validation needs."""
    result: dict = {"configuration": [], "components": {"scripts": []}}
    current_section = None
    current_item = None
    current_script = None
    current_impl = None

    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^permissions:", stripped):
            result["_has_permissions"] = True
        m = re.match(r'^min_a3ip_spec:\s*["\']?([0-9.]+)["\']?', stripped)
        if m:
            result["min_a3ip_spec"] = m.group(1)
        m2 = re.match(r'^version:\s*["\']?([^"\']+)["\']?', stripped)
        if m2:
            result["version"] = m2.group(1).strip()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("configuration:"):
            current_section = "configuration"
            continue

        if "components:" in stripped and not stripped.startswith("-"):
            current_section = "components"
            continue

        if stripped.startswith("permissions:"):
            current_section = "permissions"
            continue

        if current_section == "configuration":
            m = re.match(r"^\s*- key:\s*(\S+)", line)
            if m:
                key = m.group(1)
                current_item = {"key": key}
                result["configuration"].append(current_item)
            elif current_item and re.match(r"^\s+sensitive:\s*true", line):
                current_item["sensitive"] = True

        if current_section == "components":
            if re.match(r"^\s+scripts:", line):
                current_section = "scripts"
            continue

        if current_section == "scripts":
            m = re.match(r"^\s*- key:\s*(\S+)", line)
            if m:
                current_script = {"key": m.group(1), "implementations": []}
                result["components"]["scripts"].append(current_script)
            m2 = re.match(r"^\s+- file:\s*(\S+)", line)
            if m2 and current_script is not None:
                current_impl = {"file": m2.group(1)}
                current_script["implementations"].append(current_impl)
            m3 = re.match(r"^\s+platform:\s*(\S+)", line)
            if m3 and current_impl is not None:
                current_impl["platform"] = m3.group(1)
            m4 = re.match(r"^\s+trust_level:\s*(\S+)", line)
            if m4 and current_impl is not None:
                current_impl["trust_level"] = m4.group(1)

    return result


# ──────────────────────────────────────────────────────────
# Check 1 — Config coverage (non-script files only)
# ──────────────────────────────────────────────────────────

_CONFIG_REF_RE = re.compile(r"\{\{config\.([a-zA-Z_][a-zA-Z0-9_]*)\}\}")
_SKILL_FILES_TO_SKIP = {"SKILL.md"}
_TEMPLATE_EXTENSIONS = {".md", ".yaml", ".yml", ".json", ".txt", ".html", ".js", ".css"}
_SCRIPT_EXTENSIONS = {".py", ".ps1", ".sh"}


def check_config_coverage(pkg_dir: Path, declared_keys: set) -> tuple[list, list]:
    errors, warnings = [], []
    undeclared: dict = {}

    for fpath in sorted(pkg_dir.rglob("*")):
        if not fpath.is_file():
            continue
        if "docs" in fpath.relative_to(pkg_dir).parts:
            continue
        if fpath.name in _SKILL_FILES_TO_SKIP:
            continue
        if fpath.suffix.lower() not in _TEMPLATE_EXTENSIONS:
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for ref in _CONFIG_REF_RE.findall(text):
            if ref not in declared_keys:
                undeclared.setdefault(ref, []).append(str(fpath.relative_to(pkg_dir)))

    for key, files in sorted(undeclared.items()):
        errors.append(
            "Config key '{{config." + key + "}}' used in ["
            + ", ".join(files) + "] but not declared in manifest configuration."
        )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 2 — Script existence
# ──────────────────────────────────────────────────────────

def check_script_existence(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []
    scripts = (manifest.get("components") or {}).get("scripts") or []
    for sc in scripts:
        key = sc.get("key", "?")
        for impl in sc.get("implementations") or []:
            rel_file = impl.get("file", "")
            if rel_file and not (pkg_dir / rel_file).exists():
                errors.append(
                    "Script '" + key + "': declared file '" + rel_file + "' does not exist."
                )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 3 — Script config reads
# ──────────────────────────────────────────────────────────

_SCRIPT_CONFIG_PATTERNS = [
    re.compile(r'config\["([a-zA-Z_][a-zA-Z0-9_]*)"\]'),
    re.compile(r"config\['([a-zA-Z_][a-zA-Z0-9_]*)'\]"),
    re.compile(r'config\.get\("([a-zA-Z_][a-zA-Z0-9_]*)"\)'),
    re.compile(r"config\.get\('([a-zA-Z_][a-zA-Z0-9_]*)'\)"),
    re.compile(r'\$config\.([a-zA-Z_][a-zA-Z0-9_]*)'),
]


def check_script_config_reads(pkg_dir: Path, declared_keys: set) -> tuple[list, list]:
    errors, warnings = [], []
    for fpath in sorted(pkg_dir.rglob("*")):
        if not fpath.is_file() or fpath.suffix.lower() not in _SCRIPT_EXTENSIONS:
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        read_keys: set = set()
        for pattern in _SCRIPT_CONFIG_PATTERNS:
            read_keys.update(pattern.findall(text))
        rel = str(fpath.relative_to(pkg_dir))
        for key in sorted(read_keys):
            if key not in declared_keys:
                errors.append(
                    "Script '" + rel + "' reads config key '" + key
                    + "' which is not declared in manifest configuration."
                )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 4 — Cross-platform coverage
# ──────────────────────────────────────────────────────────

def check_cross_platform(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []
    scripts = (manifest.get("components") or {}).get("scripts") or []
    for sc in scripts:
        key = sc.get("key", "?")
        impls = sc.get("implementations") or []
        platforms = {(impl.get("platform") or "").lower() for impl in impls}
        has_any = "any" in platforms
        has_windows = "windows" in platforms

        if has_windows and not has_any:
            errors.append(
                "Script '" + key + "' has a Windows (PS1) implementation but no "
                "cross-platform (any/Python) fallback. Add a Python implementation."
            )
        if has_windows and not (pkg_dir / ("adapters/windows/scripts/" + key + ".ps1")).exists():
            warnings.append(
                "Script '" + key + "' declares a windows implementation but "
                "adapters/windows/scripts/" + key + ".ps1 does not exist."
            )
        if has_any and not (pkg_dir / ("scripts/" + key + ".py")).exists():
            warnings.append(
                "Script '" + key + "' declares an 'any' implementation but "
                "scripts/" + key + ".py does not exist."
            )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 5 — Auth flows referenced in INSTALL.md
# ──────────────────────────────────────────────────────────

def check_auth_flows(pkg_dir: Path) -> tuple[list, list]:
    errors, warnings = [], []
    auth_scripts = (
        list(pkg_dir.glob("scripts/auth_*.py"))
        + list(pkg_dir.glob("adapters/windows/scripts/auth_*.ps1"))
    )
    if not auth_scripts:
        return errors, warnings
    install_path = pkg_dir / "INSTALL.md"
    if not install_path.exists():
        return errors, warnings
    install_text = install_path.read_text(encoding="utf-8", errors="replace").lower()
    for apath in auth_scripts:
        if apath.stem.lower() not in install_text and "authenticate" not in install_text:
            warnings.append(
                "Auth script '" + apath.name + "' exists but INSTALL.md does not mention "
                "an authentication step. Add an 'Authenticate' step to INSTALL.md."
            )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 6 — CHANGELOG.md required for v > 1.0.0
# ──────────────────────────────────────────────────────────

def check_changelog_present(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []
    version_str = str(manifest.get("version", "1.0.0")).strip('"').strip("'")
    try:
        parts = [int(x) for x in version_str.split(".")]
        is_initial = (parts == [1, 0, 0] or parts == [1, 0])
    except (ValueError, AttributeError):
        is_initial = False

    changelog_path = pkg_dir / "CHANGELOG.md"
    if not is_initial and not changelog_path.exists():
        errors.append(
            "Package version is '" + version_str + "' (not 1.0.0) but CHANGELOG.md is missing. "
            "Every version after the initial release must include a changelog."
        )
    elif not changelog_path.exists():
        warnings.append(
            "CHANGELOG.md not found. It will be needed when you release version 1.0.1 or higher."
        )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 7 — refresh_script keys must exist in manifest
# ──────────────────────────────────────────────────────────

def check_refresh_scripts(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []
    config_entries = manifest.get("configuration") or []
    scripts = (manifest.get("components") or {}).get("scripts") or []
    declared_script_keys = {sc.get("key") for sc in scripts if sc.get("key")}
    for ck in config_entries:
        rs = ck.get("refresh_script")
        if rs and rs not in declared_script_keys:
            errors.append(
                "Config key '" + str(ck.get("key")) + "' has refresh_script: '" + str(rs)
                + "' but no script with that key is declared in the manifest."
            )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 8 — Trust level → permissions block required (v1.2)
# ──────────────────────────────────────────────────────────

_ELEVATED_TRUST = {"network", "write-local", "shell-exec"}
_WRITE_TRUST = {"write-local", "shell-exec"}


def _get_all_trust_levels(manifest: dict) -> list[tuple[str, str]]:
    trust_levels = []
    scripts = (manifest.get("components") or {}).get("scripts") or []
    for sc in scripts:
        for impl in sc.get("implementations") or []:
            tl = impl.get("trust_level", "")
            if tl:
                trust_levels.append((sc.get("key", "?"), tl))
    return trust_levels


def check_trust_permissions(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []
    elevated = [(k, tl) for k, tl in _get_all_trust_levels(manifest) if tl in _ELEVATED_TRUST]
    if not elevated:
        return errors, warnings
    has_permissions = (
        bool(manifest.get("permissions"))
        if HAS_YAML
        else manifest.get("_has_permissions", False)
    )
    if not has_permissions:
        names = ", ".join("'" + k + "' (" + tl + ")" for k, tl in elevated)
        errors.append(
            "Script(s) [" + names + "] have trust_level network or higher but the manifest "
            "has no 'permissions:' block. Declare every file path, network domain, MCP, "
            "and shell command this package uses."
        )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 9 — Trust level → ## Plan in INSTALL.md (v1.2)
# ──────────────────────────────────────────────────────────

def check_plan_section(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []
    write_scripts = [(k, tl) for k, tl in _get_all_trust_levels(manifest) if tl in _WRITE_TRUST]
    if not write_scripts:
        return errors, warnings
    install_path = pkg_dir / "INSTALL.md"
    if not install_path.exists():
        return errors, warnings
    install_text = install_path.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"^##\s+Plan\b", install_text, re.MULTILINE | re.IGNORECASE):
        names = ", ".join("'" + k + "' (" + tl + ")" for k, tl in write_scripts)
        errors.append(
            "Script(s) [" + names + "] have trust_level write-local or shell-exec but "
            "INSTALL.md has no '## Plan' section. Add a ## Plan section listing every file "
            "written, network call, MCP, and shell command. The AI must show this to the user "
            "and get confirmation before starting."
        )
    return errors, warnings


# ──────────────────────────────────────────────────────────
# Check 10 — INSTALL.md spec compliance (spec v1.2+)
# ──────────────────────────────────────────────────────────
#
# Confirms two things mandated by the A3IP spec INSTALL.md template:
#   (a) manifest declares a required `install_dir` config key
#   (b) INSTALL.md Step 1 (or some Step) checks `installed.json` at
#       `{{config.install_dir}}` — that is the canonical detection signal
#       for fresh-install vs upgrade.
#
# Packages that pass earlier checks but skip these produce non-functional
# installs (the AI can't tell fresh from upgrade), so this is a hard error.

def check_install_dir_spec(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []

    # (a) install_dir declared as a required config key
    config_entries = manifest.get("configuration") or []
    install_dir_entry = next(
        (ck for ck in config_entries if ck.get("key") == "install_dir"),
        None,
    )
    if install_dir_entry is None:
        errors.append(
            "Spec compliance: manifest configuration: block is missing the required "
            "'install_dir' key. Every A3IP package must declare install_dir so the "
            "AI installer can substitute {{config.install_dir}} in INSTALL.md. "
            "Add it via scaffold.py (auto-injected on new packages) or manually."
        )
    else:
        req = install_dir_entry.get("required")
        if req is False or (isinstance(req, str) and req.lower() == "false"):
            errors.append(
                "Spec compliance: config key 'install_dir' must have required: true. "
                "Without it the installer has nowhere to write config.json or installed.json."
            )

    # (b) INSTALL.md Step 1 uses installed.json + install_dir for detection
    install_path = pkg_dir / "INSTALL.md"
    if not install_path.exists():
        return errors, warnings

    install_text = install_path.read_text(encoding="utf-8", errors="replace")

    has_installed_json_ref = "installed.json" in install_text
    has_install_dir_template = "{{config.install_dir}}" in install_text

    if not has_installed_json_ref:
        errors.append(
            "Spec compliance: INSTALL.md does not mention `installed.json`. "
            "Step 1 of the spec INSTALL.md template requires checking for installed.json "
            "to distinguish fresh install from upgrade."
        )
    if not has_install_dir_template:
        errors.append(
            "Spec compliance: INSTALL.md does not reference `{{config.install_dir}}`. "
            "The spec INSTALL.md template uses {{config.install_dir}} for installed.json "
            "lookup (Step 1), script location (Install Scripts), and installed.json write "
            "(Step 8). Without it the installer doesn't know where state lives."
        )

    return errors, warnings


# ──────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────

def validate(pkg_dir_str: str) -> dict:
    """Run all 10 checks. Returns {'ok': bool, 'errors': [...], 'warnings': [...]}."""
    pkg_dir = Path(pkg_dir_str)
    if not pkg_dir.is_dir():
        return {"ok": False, "errors": ["Not a directory: " + pkg_dir_str], "warnings": []}

    try:
        manifest = load_manifest(pkg_dir)
    except FileNotFoundError as e:
        return {"ok": False, "errors": [str(e)], "warnings": []}

    config_entries = manifest.get("configuration") or []
    declared_keys = {entry.get("key") for entry in config_entries if entry.get("key")}

    checks = [
        ("config coverage",     lambda: check_config_coverage(pkg_dir, declared_keys)),
        ("script existence",    lambda: check_script_existence(pkg_dir, manifest)),
        ("script config reads", lambda: check_script_config_reads(pkg_dir, declared_keys)),
        ("cross-platform",      lambda: check_cross_platform(pkg_dir, manifest)),
        ("auth flows",          lambda: check_auth_flows(pkg_dir)),
        ("changelog present",   lambda: check_changelog_present(pkg_dir, manifest)),
        ("refresh scripts",     lambda: check_refresh_scripts(pkg_dir, manifest)),
        ("trust->permissions",   lambda: check_trust_permissions(pkg_dir, manifest)),
        ("trust->plan section",  lambda: check_plan_section(pkg_dir, manifest)),
        ("install_dir spec",    lambda: check_install_dir_spec(pkg_dir, manifest)),
    ]

    all_errors: list = []
    all_warnings: list = []

    print("Validating: " + str(pkg_dir))
    if declared_keys:
        print("Config keys: " + str(sorted(declared_keys)))
    print()

    for i, (name, fn) in enumerate(checks, 1):
        errs, warns = fn()
        all_errors += errs
        all_warnings += warns
        label = ("Check " + str(i) + " (" + name + "):").ljust(36)
        print(label + str(len(errs)) + " error(s)  " + str(len(warns)) + " warning(s)")

    ok = len(all_errors) == 0
    print()
    if ok and not all_warnings:
        print("[OK] Validation passed - no errors or warnings.")
    elif ok:
        print("[OK] Validation passed with " + str(len(all_warnings)) + " warning(s).")
        for w in all_warnings:
            print("  WARNING: " + w)
    else:
        print("[FAIL] Validation FAILED - " + str(len(all_errors)) + " error(s), "
              + str(len(all_warnings)) + " warning(s).")
        for e in all_errors:
            print("  ERROR: " + e)
        for w in all_warnings:
            print("  WARNING: " + w)

    return {"ok": ok, "errors": all_errors, "warnings": all_warnings}
