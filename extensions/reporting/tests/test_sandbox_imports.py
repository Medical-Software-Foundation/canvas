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


def test_dataclass_modules_avoid_future_annotations():
    """`@dataclass` + `from __future__ import annotations` crashes in the Canvas sandbox.

    With future annotations the dataclass decorator resolves string annotations via
    `sys.modules.get(cls.__module__).__dict__`, which is None in the sandbox's module
    loader (AttributeError at import). Modules defining a dataclass must therefore use
    real (evaluated) annotations, not the future-import form.
    """
    offenders = []
    for path in _py_files():
        text = path.read_text()
        if "@dataclass" in text and "from __future__ import annotations" in text:
            offenders.append(str(path))
    assert not offenders, (
        "These modules combine @dataclass with `from __future__ import annotations`, "
        f"which fails in the sandbox: {offenders}"
    )


def test_no_self_package_imports():
    """`from reporting.<pkg> import <sub>` re-evaluates that package in the sandbox.

    The sandbox has no sys.modules caching, so importing a submodule via its parent
    package (rather than its full dotted path) re-executes the package __init__ and,
    when done from inside that __init__, recurses infinitely. Internal imports must use
    full submodule paths (e.g. `from reporting.datasets.appointments import DATASET`).
    """
    offenders = []
    for path in _py_files():
        parts = path.relative_to(_PKG).parts[:-1]  # package dirs above this file
        self_pkg = "reporting" + ("." + ".".join(parts) if parts else "")
        bad = f"from {self_pkg} import "  # importing a name FROM one's own package
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith(bad):
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, (
        "Self-package imports found (use full submodule paths instead): " f"{offenders}"
    )
