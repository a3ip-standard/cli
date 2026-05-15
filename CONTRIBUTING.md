# Contributing to a3ip CLI

## Keeping up with spec versions

The CLI has two version references that must be maintained independently:

### `__spec_version__` in `src/a3ip/__init__.py`
The latest A3IP spec version this CLI fully implements.
Bump this whenever the CLI adds support for a new spec version.

### `min_a3ip_spec` in `src/a3ip/new.py`
The minimum spec version stamped into newly scaffolded packages.
**Do not blindly set this to `__spec_version__`.**

The rule:
- New spec adds **normative requirements** (new validate checks, new required fields) → bump both `__spec_version__` AND `min_a3ip_spec`
- New spec adds **optional features** (e.g. v1.6 `spec_url:`) → bump only `__spec_version__`; `min_a3ip_spec` stays at whatever the scaffold template actually requires

### Example
v1.6 added `spec_url:` (optional bundle field, no new validate checks).
Result: `__spec_version__ = "1.6"`, `min_a3ip_spec: "1.5"` in new.py — correct.

If v1.7 added a new required manifest field with a new validate check:
Result: `__spec_version__ = "1.7"`, `min_a3ip_spec: "1.7"` in new.py — both bump.
