"""Every plugin module must load in the plugin runner's sandbox, as it will on install."""

from pathlib import Path

import pytest
from plugin_runner.sandbox import sandbox_from_module

BASE = Path(__file__).parents[1]
MODULES = sorted(
    ".".join(path.relative_to(BASE).with_suffix("").parts)
    for path in (BASE / "my_schedule").rglob("*.py")
    if path.name != "__init__.py"
)


@pytest.mark.parametrize("module", MODULES)
def test_module_loads_in_sandbox(module: str) -> None:
    sandbox_from_module(BASE, module).execute()
