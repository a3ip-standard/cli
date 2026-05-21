"""
A3IP validate -- runs all 10 normative checks plus 3 v1.9 advisory warnings
on a package directory.

Checks 1-10 are normative (errors block install). Checks 11-13 are v1.9
advisory warnings about the spec re-alignment to outcome-shaped INSTALL.md
and knowledge-shaped adapters; they never block install in v1.9, but WILL
become errors in spec v2.0.

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


# --------------------------------------------------------------------
# Manifest loading
# --------------------------------------------------------------------

def load_manifest(pkg_dir: Path) -> dict:
    manifest_path = pkg_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError("manifest.yaml not found in " + str(pkg_dir))
    content = manifest_path.read_text(encoding="utf-8")
    if HAS_YAML:
        return _yaml.safe_load(content)
    return _parse_manifest_minimal(content)


def _parse_manifest_minimal(text: str) -> dict:
    """Minimal YAML parser -- handles only what validation needs."""
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


def _extract_tested_platforms(pkg_dir: Path, manifest: dict) -> list:
    """Return list of platform names from manifest.platforms.tested.

    Tries PyYAML path first; falls back to a manifest-text regex scan.
    Returns [] if nothing parseable.
    """
    if HAS_YAML:
        platforms_block = manifest.get("platforms")
        if isinstance(platforms_block, dict):
            tested = platforms_block.get("tested")
            if isinstance(tested, list):
                return [str(p) for p in tested]

    manifest_path = pkg_dir / "manifest.yaml"
    if not manifest_path.exists():
        return []

    text = manifest_path.read_text(encoding="utf-8", errors="replace")
    in_platforms_block = False
    in_tested_list = False
    platforms = []

    for line in text.splitlines():
        stripped = line.rstrip()
        if re.match(r"^platforms:\s*$", stripped):
            in_platforms_block = True
            in_tested_list = False
            continue

        if in_platforms_block:
            if re.match(r"^\s+tested:\s*$", stripped):
                in_tested_list = True
                continue
            if in_tested_list:
                m = re.match(r"^\s+-\s+([\w\-]+)", stripped)
                if m:
                    platforms.append(m.group(1))
                    continue
                # Sub-key like `untested:` ends the tested list but stays in platforms block
                if re.match(r"^\s+\w+:", stripped):
                    in_tested_list = False
                    continue
            # Any non-indented line ends the platforms block
            if stripped and not stripped.startswith((" ", "\t")):
                in_platforms_block = False
                in_tested_list = False

    return platforms


# --------------------------------------------------------------------
# Check 1 -- Config coverage (non-script files only)
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 2 -- Script existence
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 3 -- Script config reads
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 4 -- Cross-platform coverage
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 5 -- Auth flows referenced in INSTALL.md
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 6 -- CHANGELOG.md required for v > 1.0.0
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 7 -- refresh_script keys must exist in manifest
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 8 -- Trust level -> permissions block required (v1.2)
# --------------------------------------------------------------------

_ELEVATED_TRUST = {"network", "write-local", "shell-exec"}
_WRITE_TRUST = {"write-local", "shell-exec"}


def _get_all_trust_levels(manifest: dict) -> list:
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


# --------------------------------------------------------------------
# Check 9 -- Trust level -> ## Plan in INSTALL.md (v1.2)
# --------------------------------------------------------------------

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


# --------------------------------------------------------------------
# Check 10 -- INSTALL.md spec compliance (spec v1.2+)
# --------------------------------------------------------------------

def check_install_dir_spec(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []

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


# --------------------------------------------------------------------
# Check 11 -- Adapter outcome coverage (spec v1.9, advisory warning)
# --------------------------------------------------------------------
#
# Each platform in platforms.tested whose adapter exists at
# adapters/runtime/<X>/install-skill.md SHOULD reference each Tier 2 outcome
# it influences (skills/artifacts/protocols).
#
# Heuristic. Designed to catch the v1.2.x Codex bug class where adapters
# placed files but didn't address the registration outcome.

_OUTCOME_KEYWORDS = {
    "skill":     ["skill", "discover", "load", "register"],
    "artifact":  ["artifact", "render", "view", "display"],
    "protocol":  ["protocol", "trigger", "command", "invoke"],
}


def check_adapter_outcome_coverage(pkg_dir: Path, manifest: dict) -> tuple[list, list]:
    errors, warnings = [], []

    platforms_tested = _extract_tested_platforms(pkg_dir, manifest)
    if not platforms_tested:
        return errors, warnings

    # Which outcomes does THIS package need addressed?
    components = manifest.get("components") or {}
    has_skills = bool(components.get("skills"))
    has_artifacts = bool(components.get("artifacts"))
    has_protocols = bool(components.get("protocols"))

    # Fallback for the minimal parser, which only stores scripts under components
    if not (has_skills or has_artifacts or has_protocols):
        manifest_path = pkg_dir / "manifest.yaml"
        if manifest_path.exists():
            text = manifest_path.read_text(encoding="utf-8", errors="replace")
            has_skills = bool(re.search(r"^\s+skills:\s*$", text, re.MULTILINE))
            has_artifacts = bool(re.search(r"^\s+artifacts:\s*$", text, re.MULTILINE))
            has_protocols = bool(re.search(r"^\s+protocols:\s*$", text, re.MULTILINE))

    needed = []
    if has_skills:
        needed.append(("skill", "make skills discoverable to the host runtime"))
    if has_artifacts:
        needed.append(("artifact", "make artifacts available on the host runtime"))
    if has_protocols:
        needed.append(("protocol", "make protocols invocable on the host runtime"))

    if not needed:
        return errors, warnings

    for platform in platforms_tested:
        adapter_path = pkg_dir / "adapters" / "runtime" / platform / "install-skill.md"
        if not adapter_path.exists():
            continue

        text = adapter_path.read_text(encoding="utf-8", errors="replace").lower()

        for outcome_key, outcome_label in needed:
            keywords = _OUTCOME_KEYWORDS[outcome_key]
            if not any(kw in text for kw in keywords):
                warnings.append(
                    "Adapter '" + str(adapter_path.relative_to(pkg_dir))
                    + "' does not address Tier 2 outcome: " + outcome_label + ". "
                    "Each runtime adapter should describe its mechanism for this outcome. "
                    "See A3IP spec v1.9, 'Writing Adapter Documents'."
                )

    return errors, warnings


# --------------------------------------------------------------------
# Check 12 -- INSTALL.md tier shape (spec v1.9, advisory warning)
# --------------------------------------------------------------------
#
# Steps declared *Tier: 2 (...)* SHOULD NOT contain procedure-language leakage
# (raw shell code blocks; imperative "Run X" / "Execute Y" verbs at sentence
# start). Tier 1 mechanical steps are exempt.
#
# Fallback: INSTALL.md files without tier markers get a softer check on step
# header verbs.

_TIER2_PROCEDURE_VERBS_RE = re.compile(
    r"(?m)^\s*(?:Run|Execute|Copy|Move|Install)\s+(?!the\b|each\b|all\b)\S",
)
_TIER2_SHELL_FENCE_RE = re.compile(
    r"```(?:powershell|bash|sh|ps1|pwsh|cmd|batch)\b",
    re.IGNORECASE,
)
_TIER_MARKER_RE = re.compile(r"^\s*\*Tier:\s*(\d+)\b", re.MULTILINE)
_PROCEDURE_HEADER_PREFIXES = ("Install ", "Set Up ", "Register ", "Run ", "Execute ")


def check_install_tier_shape(pkg_dir: Path) -> tuple[list, list]:
    errors, warnings = [], []
    install_path = pkg_dir / "INSTALL.md"
    if not install_path.exists():
        return errors, warnings

    text = install_path.read_text(encoding="utf-8", errors="replace")

    # Split by ## headings to get sections. First chunk is preamble.
    chunks = re.split(r"(?m)^##\s+", text)
    if len(chunks) <= 1:
        return errors, warnings

    sections = chunks[1:]
    any_tier_markers = bool(_TIER_MARKER_RE.search(text))

    for section in sections:
        lines = section.splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        body = "\n".join(lines[1:])

        # Find tier marker in the first 3 body lines
        tier = None
        for line in lines[1:4]:
            m = re.match(r"\s*\*Tier:\s*(\d+)", line)
            if m:
                tier = int(m.group(1))
                break

        if tier == 2:
            if _TIER2_SHELL_FENCE_RE.search(body):
                warnings.append(
                    "INSTALL.md step '" + header + "' is marked Tier 2 but contains a raw "
                    "shell code block. Tier 2 steps describe outcomes; procedural commands "
                    "belong in adapters/runtime/<X>/install-skill.md."
                )
            if _TIER2_PROCEDURE_VERBS_RE.search(body):
                warnings.append(
                    "INSTALL.md step '" + header + "' (Tier 2) contains imperative-verb "
                    "sentences at line start ('Run X' / 'Execute Y' / 'Copy Z'). Tier 2 "
                    "steps describe outcomes (\"Make X be Y\"); procedures belong in adapters."
                )
        elif tier is None and not any_tier_markers:
            # Fallback: no tier markers anywhere. Check header verb heuristics.
            for prefix in _PROCEDURE_HEADER_PREFIXES:
                # Match after the leading number + period
                header_after_num = re.sub(r"^\d+\.\s*", "", header)
                if header_after_num.startswith(prefix):
                    warnings.append(
                        "INSTALL.md step '" + header + "' looks procedure-shaped. Consider "
                        "re-framing as an outcome (e.g. 'Make skills discoverable to the host "
                        "runtime') and adding a tier marker (*Tier: 2 (required outcome -- "
                        "adapter procedure)*). See A3IP spec v1.9 INSTALL.md template."
                    )
                    break

    return errors, warnings


# --------------------------------------------------------------------
# Check 13 -- Adapter knowledge-shape (spec v1.9, advisory warning)
# --------------------------------------------------------------------
#
# Adapter install-skill.md files SHOULD be more prose than code. Ratio of
# non-code-block prose lines to code-block lines should be at least 2:1.
# Adapters under this threshold are likely script-shaped rather than
# knowledge-shaped.

def check_adapter_knowledge_shape(pkg_dir: Path) -> tuple[list, list]:
    errors, warnings = [], []
    adapters_runtime = pkg_dir / "adapters" / "runtime"
    if not adapters_runtime.exists():
        return errors, warnings

    for platform_dir in sorted(adapters_runtime.iterdir()):
        if not platform_dir.is_dir():
            continue
        adapter_path = platform_dir / "install-skill.md"
        if not adapter_path.exists():
            continue

        text = adapter_path.read_text(encoding="utf-8", errors="replace")
        in_fence = False
        code_lines = 0
        prose_lines = 0

        for line in text.splitlines():
            if re.match(r"^\s*```", line):
                in_fence = not in_fence
                continue
            if in_fence:
                if line.strip():
                    code_lines += 1
            else:
                if line.strip():
                    prose_lines += 1

        if code_lines == 0:
            continue

        ratio = prose_lines / code_lines
        if ratio < 2.0:
            warnings.append(
                "Adapter '" + str(adapter_path.relative_to(pkg_dir)) + "' looks more "
                "script-shaped than knowledge-shaped (prose:code ratio = "
                + ("%.1f" % ratio) + ", threshold >= 2.0). Adapters are Tier 3 "
                "platform-knowledge artifacts -- describe conventions, mark code blocks as "
                "illustrative. See A3IP spec v1.9, 'Writing Adapter Documents'."
            )

    return errors, warnings


# --------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------

def validate(pkg_dir_str: str) -> dict:
    """Run all 10 normative checks plus 3 v1.9 advisory warnings.

    Returns {'ok': bool, 'errors': [...], 'warnings': [...]}.
    """
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
        ("config coverage",          lambda: check_config_coverage(pkg_dir, declared_keys)),
        ("script existence",         lambda: check_script_existence(pkg_dir, manifest)),
        ("script config reads",      lambda: check_script_config_reads(pkg_dir, declared_keys)),
        ("cross-platform",           lambda: check_cross_platform(pkg_dir, manifest)),
        ("auth flows",               lambda: check_auth_flows(pkg_dir)),
        ("changelog present",        lambda: check_changelog_present(pkg_dir, manifest)),
        ("refresh scripts",          lambda: check_refresh_scripts(pkg_dir, manifest)),
        ("trust->permissions",       lambda: check_trust_permissions(pkg_dir, manifest)),
        ("trust->plan section",      lambda: check_plan_section(pkg_dir, manifest)),
        ("install_dir spec",         lambda: check_install_dir_spec(pkg_dir, manifest)),
        ("adapter outcome coverage", lambda: check_adapter_outcome_coverage(pkg_dir, manifest)),
        ("install.md tier shape",    lambda: check_install_tier_shape(pkg_dir)),
        ("adapter knowledge-shape",  lambda: check_adapter_knowledge_shape(pkg_dir)),
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
        label = ("Check " + str(i) + " (" + name + "):").ljust(40)
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
