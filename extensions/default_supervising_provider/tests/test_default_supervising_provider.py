"""Tests for the default-supervising-provider reference handler.

Each test is wrapped in a transaction that is rolled back at the end.
"""

import json
from unittest.mock import MagicMock

import pytest

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import NoteFactory, StaffFactory

from default_supervising_provider.handlers.default_supervising_provider import (
    DefaultSupervisingProvider,
)


def _handler_for(note_id: str) -> DefaultSupervisingProvider:
    event = MagicMock()
    event.type = EventType.NOTE_CREATED
    event.target.id = str(note_id)
    return DefaultSupervisingProvider(event=event, secrets={})


@pytest.mark.django_db
def test_defaults_supervising_provider_from_provider() -> None:
    """A provider with a default supervising provider populates the note's supervising provider."""
    supervising = StaffFactory()
    provider = StaffFactory(default_supervising_provider=supervising)
    note = NoteFactory(provider=provider)

    effects = _handler_for(note.id).compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.UPDATE_NOTE
    data = json.loads(effects[0].payload)["data"]
    assert data["instance_id"] == str(note.id)
    assert data["supervising_provider_id"] == str(supervising.id)


@pytest.mark.django_db
def test_noop_when_provider_has_no_default() -> None:
    """No default on the provider → no effect."""
    note = NoteFactory(provider=StaffFactory(default_supervising_provider=None))

    assert _handler_for(note.id).compute() == []


@pytest.mark.django_db
def test_does_not_override_existing_supervising_provider() -> None:
    """An already-set supervising provider is left untouched."""
    supervising = StaffFactory()
    already = StaffFactory()
    provider = StaffFactory(default_supervising_provider=supervising)
    note = NoteFactory(provider=provider, supervising_provider=already)

    assert _handler_for(note.id).compute() == []


def test_noop_when_note_has_no_provider() -> None:
    """A note with no rendering provider yields no effect."""
    handler = _handler_for("note-id")
    note = MagicMock()
    note.provider = None
    handler.event.target.id = "note-id"

    from unittest.mock import patch

    with patch(
        "default_supervising_provider.handlers.default_supervising_provider.Note.objects.get",
        return_value=note,
    ):
        assert handler.compute() == []
