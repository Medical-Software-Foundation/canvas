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


# The sandbox also checks names read off an imported module (`uuid.uuid5`),
# which the import scan above cannot see.
#
# uuid.uuid5 is missing from the allowlist in this SDK copy, yet the deployed
# runner allows it: calendars on the support-team instance carry the exact
# uuid5 ids engine/admin_calendar.py computes (checked 2026-10-08).
_VERIFIED_ON_INSTANCE = {("uuid", "uuid5")}


def _module_attribute_reads(tree: ast.Module):
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            yield node.lineno, aliases[node.value.id], node.attr


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_module_attributes_are_sandbox_allowed(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for lineno, module, attr in _module_attribute_reads(tree):
        if module.startswith("provider_availability") or (module, attr) in _VERIFIED_ON_INSTANCE:
            continue
        assert attr in ALLOWED_MODULES.get(module, ()), f"{path.name}:{lineno}: `{module}.{attr}` is not allowed in the sandbox"


def test_the_attribute_scan_can_fail():
    tree = ast.parse("import json\nimport datetime as dt\njson.loadz('x')\ndt.datetime.now()\n")
    reads = list(_module_attribute_reads(tree))
    assert (3, "json", "loadz") in reads
    assert (4, "datetime", "datetime") in reads
    assert "loadz" not in ALLOWED_MODULES["json"]
