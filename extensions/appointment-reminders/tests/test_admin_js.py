"""Runs the JavaScript assertions in tests/js under node.

The admin page's save logic is JavaScript embedded in a Python string, so the
Python suite can only assert on its *shape*. That is exactly what let the
note-type bug through: the structure was right and the values were wrong. These
execute the real extracted logic instead.

Skipped when node is unavailable so the suite still runs everywhere.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

_JS_DIR = pathlib.Path(__file__).parent / "js"


@pytest.mark.parametrize(
    "script", sorted(p.name for p in _JS_DIR.glob("test_*.mjs")) or ["<none found>"]
)
def test_javascript_assertions(script: str) -> None:
    assert script != "<none found>", "no JS tests found — did tests/js move?"
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    result = subprocess.run(
        [node, str(_JS_DIR / script)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"{script} failed:\n{result.stdout}\n{result.stderr}"
    )
