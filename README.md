# a3ip CLI
*Pronounced "ay-trip"*

[![PyPI](https://img.shields.io/pypi/v/a3ip)](https://pypi.org/project/a3ip)
[![Spec](https://img.shields.io/badge/spec-v1.5-blue)](https://a3ip.dev)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)

Command-line tool for creating, validating, and bundling [A3IP](https://a3ip.dev) packages.

---

## Install

```bash
pip install a3ip
```

**Optional:** install with YAML support for faster, more reliable manifest parsing:

```bash
pip install "a3ip[yaml]"
```

---

## Commands

### `a3ip new <name>`

Scaffold a new package that passes `a3ip validate` on the first run.

```bash
a3ip new my-workflow
```

Creates `my-workflow/` with:

```
my-workflow/
├── manifest.yaml          ← package metadata, permissions, components
├── CONFIGURE.md           ← questions to ask the user at install time
├── INSTALL.md             ← step-by-step install guide for the AI
├── README.md              ← human-facing description
├── components/
│   └── skills/
│       └── my-workflow.md ← the main skill file
└── scripts/               ← Python/PowerShell automation scripts go here
```

---

### `a3ip validate <package_dir>`

Run 9 normative checks against the A3IP spec.

```bash
a3ip validate my-workflow/
```

```
Validating: my-workflow/

Check 1 (config coverage):     0 error(s)  0 warning(s)
Check 2 (script existence):    0 error(s)  0 warning(s)
...
Check 9 (trust→plan section):  0 error(s)  0 warning(s)

✓ Validation passed — no errors or warnings.
```

Exit code `0` if clean, `1` if any errors. Warnings don't affect the exit code.

Add `--json` to get a machine-readable report alongside the human output.

---

### `a3ip bundle <package_dir>`

Build a `.a3ip.bundle` file ready to distribute.

```bash
a3ip bundle my-workflow/
# → my-workflow.a3ip.bundle
```

The bundle is a plain-text file containing every package file. Drop it into a
conversation with any A3IP-compatible AI and ask it to install.

To include the spec for recipients who may not know A3IP:

```bash
a3ip bundle my-workflow/ --spec path/to/A3IP-SPEC-v1.5.md
```

---

## Full example

```bash
pip install "a3ip[yaml]"

a3ip new code-review-flow
cd code-review-flow
# ... edit manifest.yaml, INSTALL.md, skills/ ...
a3ip validate .
a3ip bundle .
# → ../code-review-flow.a3ip.bundle
```

---

## Links

- **Specification:** [a3ip.dev](https://a3ip.dev) — [github.com/a3ip-standard/spec](https://github.com/a3ip-standard/spec)
- **Example packages:** [github.com/a3ip-standard/packages](https://github.com/a3ip-standard/packages)
- **PyPI:** [pypi.org/project/a3ip](https://pypi.org/project/a3ip)

---

## License

[Apache 2.0](LICENSE) — use freely in commercial and open source projects. Includes explicit patent grant.

*A3IP CLI v1.0.0 · © 2026 Maksym Prydorozhko*
