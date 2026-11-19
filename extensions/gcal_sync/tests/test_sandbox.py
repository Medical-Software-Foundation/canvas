"""Load the shipped modules and run the day splitter inside the real plugin sandbox."""

import json
import sys
from pathlib import Path

import pytest
from plugin_runner.sandbox import sandbox_from_module

BASE = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((BASE / "gcal_sync" / "CANVAS_MANIFEST.json").read_text())
MODULES = sorted(
    {
        component["class"].split(":")[0]
        for kind in ("protocols", "applications")
        for component in MANIFEST["components"][kind]
    }
)


@pytest.fixture(autouse=True)
def restore_plugin_modules():
    """The sandbox reloads already-imported plugin modules in place; restore them for later tests."""
    saved = {name: dict(m.__dict__) for name, m in sys.modules.items() if name.startswith("gcal_sync")}
    yield
    for name, namespace in saved.items():
        sys.modules[name].__dict__.clear()
        sys.modules[name].__dict__.update(namespace)


@pytest.mark.parametrize("module", MODULES)
def test_manifest_module_loads_in_sandbox(module: str) -> None:
    sandbox_from_module(BASE, module).execute()


def test_day_spans_run_in_sandbox() -> None:
    scope = sandbox_from_module(BASE, "gcal_sync.inbound_holds").execute()
    event = {
        "id": "pto",
        "start": {"dateTime": "2026-10-30T00:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-11-09T00:00:00-05:00", "timeZone": "America/New_York"},
    }

    spans = scope["event_day_spans"](event)

    assert [span.date for span in spans] == [
        "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03",
        "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08",
    ]
    assert spans[2].duration_minutes == 1499
