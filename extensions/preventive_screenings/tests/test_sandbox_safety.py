"""Structural checks for things the plugin sandbox refuses at RUN time.

The sandbox's refusals are the most expensive class of bug in this project, and
they divide in two:

* **Load-time** refusals - a disallowed import, a bare builtin in an evaluated
  annotation. ``canvas validate`` catches these, because it loads every handler
  in a real sandbox. Four were caught that way while this plugin was built.
* **Run-time** refusals - ``canvas validate`` does **not** catch these, because
  it loads handlers without invoking them. They pass validate, pass mypy, pass
  every test, deploy cleanly, and then raise on the first real event.

One of those shipped: ``sweep_store.load_state()``, where ``sweep_store`` was an
imported module object. ``_safe_getattr`` rejects attribute access on a module
unless it is in ALLOWED_MODULES, so the scheduled sweep raised on its first run
while everything else reported green.

These tests read the plugin's own source for that shape. They are cheap, and
they are the only automated cover for a failure whose other symptom is a
screening that quietly never updates.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "preventive_screenings"
SOURCES = sorted(path for path in PACKAGE.rglob("*.py") if "__pycache__" not in str(path))


def test_there_is_source_to_check() -> None:
    """A globbing mistake would make every test below pass vacuously."""
    assert len(SOURCES) > 10


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_module_is_imported_as_an_object(path: Path) -> None:
    """``from x.y import z``, never ``from x import y`` then ``y.z()``.

    The sandbox raises AttributeError on the second form, at run time, in
    production only. Importing the names directly is the whole fix.
    """
    tree = ast.parse(path.read_text())

    # Only names that are really modules. `from ...models import ScreeningConfig`
    # imports a class, and reaching attributes on a class is fine - it is
    # reaching them on a *module* the sandbox refuses.
    imported_modules = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if not module.startswith("preventive_screenings"):
            continue
        parent = PACKAGE.parent.joinpath(*module.split("."))
        for alias in node.names:
            is_module = (
                (parent / f"{alias.name}.py").exists()
                or (parent / alias.name / "__init__.py").exists()
            )
            if is_module:
                imported_modules.add(alias.asname or alias.name)

    used_as_object = {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in imported_modules
    }

    assert not used_as_object, (
        f"{path.name} reaches attributes on {sorted(used_as_object)}, which the sandbox "
        "refuses at run time. Import the names directly instead."
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_blocked_stdlib_imports(path: Path) -> None:
    """The refusals already paid for once, kept out by name.

    ``collections.abc`` is the trap: ``collections`` is allowed and
    ``collections.abc`` is not. ``django.utils`` is blocked outright, which is
    why this plugin uses ``datetime.now(UTC)`` rather than ``timezone.now()``.
    """
    blocked = ("collections.abc", "django.utils.timezone", "zoneinfo.ZoneInfo")
    tree = ast.parse(path.read_text())

    for node in ast.walk(tree):
        module = node.module if isinstance(node, ast.ImportFrom) else None
        if isinstance(node, ast.Import):
            module = node.names[0].name
        if module:
            assert module not in blocked, f"{path.name} imports blocked module {module}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_bare_builtin_in_an_evaluated_annotation(path: Path) -> None:
    """``type[X]`` and ``object`` in an annotation are evaluated at class
    creation, and the sandbox withholds those builtins.

    ``from __future__ import annotations`` defers evaluation and makes them
    safe, so a file is only at fault without it. Both of these shipped once.
    """
    source = path.read_text()
    if "from __future__ import annotations" in source:
        return

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.arg) or node.annotation is None:
            continue
        rendered = ast.unparse(node.annotation)
        for risky in ("type[", "object"):
            assert risky not in rendered, (
                f"{path.name} annotates with {rendered!r}; the sandbox does not define "
                f"{risky!r} at class-creation time. Add `from __future__ import "
                "annotations` or annotate Any."
            )
