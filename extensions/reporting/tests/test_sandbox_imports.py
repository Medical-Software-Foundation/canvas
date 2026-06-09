"""Guard: no module-level forbidden Django ORM imports (sandbox allowlist).

pytest stubs django.db.models, so it cannot catch a forbidden import at runtime.
We scan the plugin source statically instead. The ONLY allowed django.db.models
import is `Count, Q`, and it must be deferred inside a function (indented), never
at module top.
"""

from __future__ import annotations

import pathlib

_PKG = pathlib.Path(__file__).resolve().parent.parent / "reporting"
_FORBIDDEN = ("Sum", "Avg", "Max", "Min", "Trunc", "ExpressionWrapper", "OuterRef", "Subquery")


def _py_files() -> list[pathlib.Path]:
    return list(_PKG.rglob("*.py"))


def test_no_module_level_django_import():
    offenders = []
    for path in _py_files():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if line.startswith("from django") or line.startswith("import django"):
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, f"Module-level Django import(s) found (must be deferred): {offenders}"


def test_no_forbidden_orm_imports():
    offenders = []
    for path in _py_files():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if "import" in stripped and "django" in stripped:
                for name in _FORBIDDEN:
                    if name in stripped:
                        offenders.append(f"{path}:{i}: forbidden '{name}': {stripped}")
    assert not offenders, offenders
