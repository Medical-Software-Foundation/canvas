"""Shared test fixtures for recent-patients."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

# Ensure the plugin container directory is on sys.path so `import recent_patients`
# resolves regardless of the cwd pytest was invoked from.
_CONTAINER_DIR = Path(__file__).resolve().parent.parent
if str(_CONTAINER_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTAINER_DIR))


@pytest.fixture
def make_event() -> Any:
    """Build a minimal SimpleNamespace event with .target.id and .context."""

    def _build(target_id: str = "tgt-1", context: dict | None = None) -> Any:
        return SimpleNamespace(
            target=SimpleNamespace(id=target_id),
            context=context or {},
        )

    return _build


@pytest.fixture
def patch_record(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Capture calls to the tracking `_record` helper.

    Yields a list that each handler appends a (staff_id, patient_id, type)
    tuple to. Avoids touching the DB so handler tests are unit-level.
    """
    captured: list[tuple[str | None, str | None, str]] = []

    def fake_record(staff_id: Any, patient_id: Any, interaction_type: str) -> None:
        captured.append((staff_id, patient_id, interaction_type))

    monkeypatch.setattr(
        "recent_patients.protocols.track_interactions._record", fake_record
    )
    return captured
