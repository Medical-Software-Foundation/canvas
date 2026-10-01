from unittest.mock import MagicMock, patch

from note_lifecycle_example.handlers import event_handlers
from note_lifecycle_example.handlers.event_handlers import (
    ReloadFooterOnCommandChange,
    ReloadFooterOnNoteStateChange,
)

from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


def _handler(
    cls: type[BaseHandler], target_id: str | None = None, context: dict | None = None
) -> BaseHandler:
    """Build a handler instance whose event carries the given target id and context."""
    event = MagicMock()
    event.target.id = target_id
    event.context = context or {}
    return cls(event=event)


def test_command_change_responds_to_command_lifecycle_events() -> None:
    """The reload handler subscribes to command originate, remove, and commit events.

    POST_ORIGINATE is the important one: adding a command to the note must reload the footer
    so SignNoteButton can hide while the note has uncommitted commands.
    """
    events = ReloadFooterOnCommandChange.RESPONDS_TO
    assert events
    allowed_suffixes = (
        "_COMMAND__POST_ORIGINATE",
        "_COMMAND__POST_DELETE",
        "_COMMAND__POST_COMMIT",
    )
    assert all(name.endswith(allowed_suffixes) for name in events)
    assert EventType.Name(EventType.PLAN_COMMAND__POST_ORIGINATE) in events
    assert EventType.Name(EventType.PLAN_COMMAND__POST_COMMIT) in events


def test_command_change_reloads_the_note_from_context() -> None:
    """A command change reloads the footer for the note carried in the event context.

    The note id is read from the context (``note.uuid``), not by looking up the command — a
    deleted command can't be queried, so a lookup-based reload would never fire on delete.
    """
    handler = _handler(
        ReloadFooterOnCommandChange, context={"note": {"uuid": "note-key"}}
    )

    with patch.object(event_handlers, "ReloadNoteActionButtonsEffect") as reload_effect:
        result = handler.compute()

    reload_effect.assert_called_once_with(id="note-key")
    assert result == [reload_effect.return_value.apply.return_value]


def test_command_change_no_effect_without_note_in_context() -> None:
    """No reload is emitted when the event context carries no note."""
    handler = _handler(ReloadFooterOnCommandChange, context={})

    with patch.object(event_handlers, "ReloadNoteActionButtonsEffect") as reload_effect:
        assert handler.compute() == []

    reload_effect.assert_not_called()


def test_note_state_change_responds_to_created() -> None:
    """The note-state reload handler subscribes to the state-change-created event."""
    assert (
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)
        == ReloadFooterOnNoteStateChange.RESPONDS_TO
    )


def test_note_state_change_reloads_the_note() -> None:
    """A note state change reloads the footer for that note (id from the event context)."""
    handler = _handler(ReloadFooterOnNoteStateChange, context={"note_id": "note-key"})

    with patch.object(event_handlers, "ReloadNoteActionButtonsEffect") as reload_effect:
        result = handler.compute()

    reload_effect.assert_called_once_with(id="note-key")
    assert result == [reload_effect.return_value.apply.return_value]


def test_note_state_change_no_effect_without_note_id() -> None:
    """No reload is emitted when the event context carries no note id."""
    handler = _handler(ReloadFooterOnNoteStateChange, context={})

    with patch.object(event_handlers, "ReloadNoteActionButtonsEffect") as reload_effect:
        assert handler.compute() == []

    reload_effect.assert_not_called()
