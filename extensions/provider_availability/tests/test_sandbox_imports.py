"""Every import must be one the plugin sandbox allows.

pytest and `canvas validate` never run the sandbox's import check, so a
disallowed import passes here and then stops the plugin's handlers from loading
on a real instance. `from collections.abc import Iterable` in engine/expired.py
did exactly that in 0.23.13 to 0.23.15: the API handlers failed to load and the
instance kept serving the previous version. This reads the SDK's own allowlist,
so it tracks the real rules rather than a copy of them.
"""

import ast
from pathlib import Path

import pytest

from plugin_runner.sandbox import ALLOWED_MODULES

PACKAGE = Path(__file__).parent.parent / "provider_availability"
SOURCES = sorted(PACKAGE.rglob("*.py"))


def test_there_are_source_files_to_check():
    assert SOURCES, "expected Python sources under provider_availability/"


def _imports(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, None
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.lineno, node.module, [alias.name for alias in node.names]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_all_imports_are_sandbox_allowed(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for lineno, module, names in _imports(tree):
        if module == "provider_availability" or module.startswith("provider_availability.") or module == "__future__":
            continue
        assert module in ALLOWED_MODULES, f"{path.name}:{lineno}: `{module}` is not an allowed sandbox import"
        for name in names or []:
            assert name in ALLOWED_MODULES[module], f"{path.name}:{lineno}: `{name}` is not importable from `{module}`"
