"""Every import must pass the plugin sandbox's allowlist.

pytest and mypy never run the sandbox's import check, so a forbidden import passes
both and then stops every handler from loading on a real instance. 0.1.15 shipped
``from django.db.models import QuerySet`` this way.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from plugin_runner.sandbox import ALLOWED_MODULES

PACKAGE_NAME = "failed_fax_dashboard"
PACKAGE = Path(__file__).parent.parent / PACKAGE_NAME
SOURCES = sorted(PACKAGE.rglob("*.py"))


def _imports(tree: ast.Module) -> Iterator[tuple[int, str, list[str] | None]]:
    """(line, module, names) for each import; names is None for a plain ``import X``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, None
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module is not None:
            yield node.lineno, node.module, [alias.name for alias in node.names]


def test_there_are_source_files_to_check() -> None:
    assert len(SOURCES) > 10


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(PACKAGE)))
def test_every_import_is_sandbox_allowed(path: Path) -> None:
    rejected = []
    for line, module, names in _imports(ast.parse(path.read_text(), filename=str(path))):
        if module == PACKAGE_NAME or module.startswith(f"{PACKAGE_NAME}."):
            continue
        if module not in ALLOWED_MODULES:
            rejected.append(f"line {line}: import {module}")
            continue
        rejected += [
            f"line {line}: from {module} import {name}"
            for name in names or []
            if name not in ALLOWED_MODULES[module]
        ]
    assert rejected == []
