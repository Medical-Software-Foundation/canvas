"""Guards against code that imports fine but fails inside Canvas's sandbox.

Canvas runs plugin code under RestrictedPython, which forbids attribute access
on a plugin's own modules:

    from canvas_theme_kit import store
    store.get_theme(slug)
    # AttributeError: "canvas_theme_kit.store.get_theme" is an invalid
    #                 attribute name (not in ALLOWED_MODULES)

This bit in production on 2026-09-17: every admin and asset route that reached
through `store` returned an empty error response on the instance.

Nothing else catches it. `canvas validate` only proves the handlers *import*,
and the unit tests run under plain CPython where the access is perfectly legal.
So the check has to be structural — scan the source for the import shape that
leads to it.

Import functions by name instead:

    from canvas_theme_kit.store import get_theme
"""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "canvas_theme_kit"
PACKAGE_NAME = "canvas_theme_kit"


def plugin_sources() -> list[Path]:
    return sorted(
        p for p in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in p.parts
    )


def test_there_are_sources_to_check() -> None:
    # A silent empty glob would make every check below vacuously pass.
    assert len(plugin_sources()) >= 5


@pytest.mark.parametrize("source", plugin_sources(), ids=lambda p: p.name)
def test_no_submodule_imports_from_own_package(source: Path) -> None:
    """Reject `from canvas_theme_kit import <submodule>`.

    That binds a module object, and any use of it is attribute access the
    sandbox rejects at runtime. Importing the names directly is equivalent and
    works in both environments.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    submodules = {p.stem for p in plugin_sources()} | {
        d.name for d in PACKAGE_ROOT.iterdir() if d.is_dir()
    }

    offenders = [
        f"line {node.lineno}: from {node.module} import {alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == PACKAGE_NAME
        for alias in node.names
        if alias.name in submodules
    ]

    assert not offenders, (
        f"{source.name} imports a submodule object from its own package:\n  "
        + "\n  ".join(offenders)
        + "\n\nCanvas's RestrictedPython sandbox forbids attribute access on a "
        "plugin's own modules, so calling anything through that name fails at "
        "runtime even though it imports cleanly and passes `canvas validate`.\n"
        f"Import the names directly instead: from {PACKAGE_NAME}.<module> import <name>"
    )


@pytest.mark.parametrize("source", plugin_sources(), ids=lambda p: p.name)
def test_no_plain_import_of_own_package(source: Path) -> None:
    """Reject `import canvas_theme_kit[...]`, which has the same failure mode."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    offenders = [
        f"line {node.lineno}: import {alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == PACKAGE_NAME or alias.name.startswith(PACKAGE_NAME + ".")
    ]

    assert not offenders, (
        f"{source.name} imports its own package as a module:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse `from canvas_theme_kit.<module> import <name>` instead."
    )
