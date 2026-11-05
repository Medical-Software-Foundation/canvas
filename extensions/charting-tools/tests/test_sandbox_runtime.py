"""Run plugin code inside the plugin runner's sandbox.

Unit tests import the plugin normally, so they miss what the sandbox blocks
only when code runs (``canvas validate`` only loads modules). For example,
reading an SDK class's attributes through ``__class__`` passes every unit test
and fails in production.
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from canvas_sdk.commands import LabOrderCommand, PlanCommand
from plugin_runner.sandbox import sandbox_from_module

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def restore_plugin_modules() -> Iterator[None]:
    """Put the plugin's modules back after a sandbox load.

    Loading through the sandbox can replace the plugin's entries in
    ``sys.modules``; left in place, later tests would patch those copies while
    the code under test kept using the originals.
    """
    saved = {name: module for name, module in sys.modules.items() if name.split(".")[0] == "charting_tools"}
    yield
    for name in [n for n in sys.modules if n.split(".")[0] == "charting_tools"]:
        if name not in saved:
            del sys.modules[name]
    sys.modules.update(saved)


def _scope(module: str) -> dict[str, Any]:
    return sandbox_from_module(PLUGIN_ROOT, module, {}).execute()


def test_link_assessment_runs_in_the_sandbox() -> None:
    scope = _scope("charting_tools.api.panel_api")
    plan = PlanCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    lab = LabOrderCommand(note_uuid="a" * 32, command_uuid="c" * 32)
    scope["link_assessment"]([plan, lab], "5c1f0e2a-6b7d-4e8f-9a0b-1c2d3e4f5a6b")
    assert str(plan.assessment_id) == "5c1f0e2a-6b7d-4e8f-9a0b-1c2d3e4f5a6b"
    assert str(lab.assessment_id) == "5c1f0e2a-6b7d-4e8f-9a0b-1c2d3e4f5a6b"


def test_lab_order_form_sets_the_lab_in_the_sandbox() -> None:
    from datetime import date

    scope = _scope("charting_tools.command_forms")
    lab = LabOrderCommand(note_uuid="a" * 32, command_uuid="c" * 32)
    scope["apply_form"](lab, {}, date.today(), "4b0e2c1a-3d5f-4a6b-8c9d-0e1f2a3b4c5d")
    assert str(lab.lab_partner) == "4b0e2c1a-3d5f-4a6b-8c9d-0e1f2a3b4c5d"


def test_export_and_matching_run_in_the_sandbox() -> None:
    from types import SimpleNamespace

    scope = _scope("charting_tools.portability")
    row = SimpleNamespace(
        template_id="t1", name="Annual visit", kind="template", active=True, show_in_menu=True,
        show_in_panel=False, note_types=[], diagnosis_sources=[], diagnosis_match_codes=[], tags=[],
        rule=None, commands=[{"schema_key": "task", "fields": {"title": "Call", "assignee": {"to": "unassigned"}}}],
    )
    doc = scope["export_document"]([row], "2026-10-12T00:00:00Z")
    items, error = scope["read_document"](doc)
    assert error is None
    body, problems, warnings = scope["remap_item"](items[0], scope["Resolver"]())
    assert problems == [] and warnings == []
    assert body["commands"][0]["fields"]["assignee"] == {"to": "unassigned"}
    assert body is not items[0]  # a copy, not the uploaded item itself


def test_note_provider_is_set_in_the_sandbox() -> None:
    from types import SimpleNamespace

    scope = _scope("charting_tools.insertion")
    lab = LabOrderCommand(note_uuid="a" * 32, command_uuid="d" * 32)
    scope["set_note_provider"](lab, SimpleNamespace(provider=SimpleNamespace(id="e110d34f-e9a3-4878-a052-650eb5f54681")))
    assert lab.ordering_provider_key == "e110d34f-e9a3-4878-a052-650eb5f54681"
