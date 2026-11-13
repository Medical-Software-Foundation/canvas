"""Every import must be one the plugin sandbox allows.

pytest and `canvas validate` never run the sandbox's import check, so a
disallowed import would pass here and then stop the handler from loading on a
real instance. This reads the SDK's own allowlist, so it tracks the real rules.
"""

import ast
from pathlib import Path

import pytest
from plugin_runner.sandbox import ALLOWED_MODULES

PACKAGE = Path(__file__).parent.parent / "auto_fax"
SOURCES = sorted(PACKAGE.rglob("*.py"))


def _imports(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, None
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.lineno, node.module, [alias.name for alias in node.names]


def test_there_are_source_files_to_check():
    assert SOURCES


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_all_imports_are_sandbox_allowed(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for lineno, module, names in _imports(tree):
        if module == "auto_fax" or module.startswith("auto_fax."):
            continue
        assert module in ALLOWED_MODULES, (
            f"{path.name}:{lineno}: `{module}` is not an allowed sandbox import"
        )
        for name in names or []:
            assert name in ALLOWED_MODULES[module], (
                f"{path.name}:{lineno}: `{name}` is not importable from `{module}`"
            )
