"""Shared helpers for charting_tools tests. ORM access is patched per test."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from canvas_sdk.events import EventType


def make_event(event_type: int, **context: Any) -> SimpleNamespace:
    """Mimic a handler Event with ``type`` and ``context``."""
    return SimpleNamespace(
        type=event_type, name=EventType.Name(event_type), context=context, target=SimpleNamespace(id="p1")
    )


def make_template(**overrides: Any) -> SimpleNamespace:
    """Mimic a NoteTemplate row."""
    fields: dict[str, Any] = {
        "template_id": "tmpl1",
        "name": "Annual visit",
        "active": True,
        "kind": "template",
        "show_in_menu": True,
        "show_in_panel": False,
        "note_types": [],
        "diagnosis_sources": [],
        "diagnosis_match_codes": [],
        "tags": [],
        "commands": [],
        "updated_at": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def make_note() -> SimpleNamespace:
    """Mimic a Note row."""
    return SimpleNamespace(
        id="a" * 32, dbid=42, patient_id=7, datetime_of_service="2026-09-01T10:00:00Z"
    )


def make_request(json_body: Any = None, path_params: dict[str, str] | None = None) -> MagicMock:
    """Mimic a SimpleAPI request from a logged-in staff member."""
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": "staff1"}
    request.path_params = path_params or {}
    # The admin page sends every change as JSON.
    request.content_type = "application/json"
    if isinstance(json_body, Exception):
        request.json.side_effect = json_body
    else:
        request.json.return_value = json_body
    return request


def payload(effect: Any) -> dict[str, Any]:
    """Decode an Effect's JSON payload."""
    return json.loads(effect.payload)
