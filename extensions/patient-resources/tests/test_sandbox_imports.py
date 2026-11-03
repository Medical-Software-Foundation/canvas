"""Every import must pass the plugin sandbox allowlist.

pytest never checks this: tests/conftest.py fabricates canvas_sdk, so a module
the sandbox refuses still imports cleanly here and only fails on an instance.
The allowlist is read in a subprocess so the real SDK never meets the stubs.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_NAME = "patient_resources"
SOURCES = sorted((Path(__file__).parent.parent / PACKAGE_NAME).rglob("*.py"))


def _allowed_modules() -> dict[str, list[str]]:
    script = (
        "import json\n"
        "from plugin_runner.sandbox import ALLOWED_MODULES\n"
        "print(json.dumps({k: sorted(v) for k, v in ALLOWED_MODULES.items()}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    # The real SDK is a dev dependency, so a failure here is a broken env, not a skip.
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def allowed() -> dict[str, list[str]]:
    return _allowed_modules()


def test_there_are_source_files_to_check():
    assert SOURCES


@pytest.mark.parametrize(
    "path", SOURCES, ids=lambda p: str(p.relative_to(p.parents[1]))
)
def test_all_imports_are_sandbox_allowed(path, allowed):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            pairs = [(alias.name, None) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            pairs = [(node.module, [alias.name for alias in node.names])]
        else:
            continue
        for module, names in pairs:
            if module == PACKAGE_NAME or module.startswith(PACKAGE_NAME + "."):
                continue
            assert module in allowed, f"{path}:{node.lineno}: {module} not allowed"
            for name in names or []:
                assert name in allowed[module], (
                    f"{path}:{node.lineno}: {module}.{name} not allowed"
                )
