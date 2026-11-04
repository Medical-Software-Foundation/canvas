"""Checks every import against the plugin runner's real sandbox allowlist.

pytest and `canvas validate` do not enforce the allowlist, so a disallowed import passes
locally and fails at load time on an instance.
"""

import ast
from pathlib import Path

import pytest

from plugin_runner.sandbox import ALLOWED_MODULES

PACKAGE = Path(__file__).parent.parent / "supervisor_cosign"
SOURCES = sorted(PACKAGE.rglob("*.py"))


def test_there_are_source_files_to_check():
    assert SOURCES


def _iter_imports(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, None
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.lineno, node.module, [alias.name for alias in node.names]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_all_imports_are_sandbox_allowed(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for lineno, module, names in _iter_imports(tree):
        if module == "supervisor_cosign" or module.startswith("supervisor_cosign."):
            continue
        assert module in ALLOWED_MODULES, f"{path}:{lineno}: {module} is not an allowed import"
        for name in names or []:
            assert name in ALLOWED_MODULES[module], f"{path}:{lineno}: {module}.{name} is not an allowed import"
