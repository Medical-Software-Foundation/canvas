"""Websocket, note-lock handler, app, settings and helpers."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest
from canvas_sdk.effects import EffectType

from canvas__ondemand_provider_queue.applications.queue_app import QUEUE_URL, ProviderQueueApp
from canvas__ondemand_provider_queue.handlers.common import age_in_years, notify
from canvas__ondemand_provider_queue.handlers.note_locked import CompleteOnNoteLock
from canvas__ondemand_provider_queue.handlers.websocket import QueueWebSocket
from canvas__ondemand_provider_queue.settings import Settings
from canvas__ondemand_provider_queue.storage.canvas_store import CanvasQueueStore

ON = {"QUEUE_ENABLED": "true"}


def websocket(channel: str, user: dict[str, str] | None, secrets: dict[str, str]) -> Any:
    handler = QueueWebSocket(MagicMock(), secrets)
    handler.websocket = MagicMock(channel=channel, logged_in_user=user)
    return handler


def test_websocket_allows_staff_on_queue_channel_only() -> None:
    staff = {"type": "Staff", "id": "s1"}
    assert websocket("queue", staff, ON).authenticate()
    assert not websocket("other", staff, ON).authenticate()
    assert not websocket("queue", None, ON).authenticate()
    assert not websocket("queue", {"type": "Patient", "id": "p"}, ON).authenticate()
    assert not websocket("queue", staff, {}).authenticate()  # off by default
    allow = {**ON, "QUEUE_STAFF_IDS": "s2"}
    assert not websocket("queue", staff, allow).authenticate()


def note_event(context: dict[str, Any] | None, secrets: dict[str, str] = ON) -> Any:
    event = MagicMock()
    event.context = context
    return CompleteOnNoteLock(event, secrets)


def test_locking_the_visit_note_completes_the_entry() -> None:
    store = CanvasQueueStore()
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "s", "n")
    store.start_entry(entry.id, "note-1")

    effects = note_event({"state": "LKD", "note_id": "note-1", "patient_id": "pat-1"}).compute()
    assert len(effects) == 1 and entry.id in effects[0].payload
    assert store.get_entry(entry.id).status == "complete"  # type: ignore[union-attr]
    # The same event again changes nothing.
    assert note_event({"state": "LKD", "note_id": "note-1"}).compute() == []


def test_note_handler_ignores_other_events() -> None:
    store = CanvasQueueStore()
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "s", "n")
    store.start_entry(entry.id, "note-1")
    assert note_event({"state": "NEW", "note_id": "note-1"}).compute() == []
    assert note_event({"state": "LKD"}).compute() == []
    assert note_event(None).compute() == []
    assert note_event({"state": "LKD", "note_id": "note-1"}, secrets={}).compute() == []
    s3 = {**ON, "QUEUE_STORAGE": "s3"}
    assert note_event({"state": "LKD", "note_id": "note-1"}, secrets=s3).compute() == []
    assert store.get_entry(entry.id).status == "in_progress"  # type: ignore[union-attr]


def test_app_opens_queue_page_with_relative_url() -> None:
    effect = ProviderQueueApp(MagicMock()).on_open()
    assert effect.type == EffectType.LAUNCH_MODAL
    assert QUEUE_URL in effect.payload and "canvasmedical.com" not in effect.payload


def test_settings_defaults_are_safe() -> None:
    settings = Settings.from_secrets({})
    assert not settings.enabled and not settings.demo_mode
    assert settings.api_key == "" and settings.staff_ids == frozenset()
    assert settings.storage == "canvas"
    assert settings.s3_object_key == "ondemand-provider-queue/queue.json"
    tuned = Settings.from_secrets(
        {"QUEUE_ENABLED": " Yes ", "DEMO_PATIENT_IDS": "a, ,b", "QUEUE_STORAGE": "other"}
    )
    assert tuned.enabled and tuned.demo_patient_ids == {"a", "b"} and tuned.storage == "canvas"


@pytest.mark.parametrize(
    ("born", "today", "age"),
    [
        (date(2000, 6, 15), date(2026, 6, 14), 25),
        (date(2000, 6, 15), date(2026, 6, 15), 26),
        (None, date(2026, 1, 1), None),
    ],
)
def test_age_in_years(born: date | None, today: date, age: int | None) -> None:
    assert age_in_years(born, today) == age


def test_broadcast_carries_ids_only() -> None:
    entry, _ = CanvasQueueStore().create_entry("pat-1", "Private reason")
    effect = notify("ENTRY_ADDED", entry)
    assert "Private reason" not in effect.payload and entry.id in effect.payload
    assert "pat-1" not in effect.payload


def test_settings_repr_hides_secrets() -> None:
    text = repr(
        Settings.from_secrets(
            {"QUEUE_API_KEY": "k-123", "AWS_ACCESS_KEY": "a-456", "AWS_SECRET_KEY": "s-789"}
        )
    )
    assert not any(secret in text for secret in ("k-123", "a-456", "s-789"))
