from unittest.mock import MagicMock, patch

from note_lifecycle_example.handlers import event_handlers
from note_lifecycle_example.handlers.event_handlers import (
    ReloadFooterOnCommandCommit,
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


def test_command_commit_responds_to_every_command_post_commit() -> None:
    """The reload handler subscribes to all command POST_COMMIT events and nothing else."""
    events = ReloadFooterOnCommandCommit.RESPONDS_TO
    assert events
    assert all(name.endswith("_COMMAND__POST_COMMIT") for name in events)
    assert EventType.Name(EventType.PLAN_COMMAND__POST_COMMIT) in events
    assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT) in events


def test_command_commit_reloads_the_commands_note() -> None:
    """Committing a command reloads the footer for that command's note."""
    handler = _handler(ReloadFooterOnCommandCommit, target_id="command-key")
    command = MagicMock()
    command.note.id = "note-key"

    with (
        patch.object(event_handlers.Command, "objects") as objects,
        patch.object(event_handlers, "ReloadNoteActionButtonsEffect") as reload_effect,
    ):
        objects.filter.return_value.first.return_value = command
        result = handler.compute()

    objects.filter.assert_called_once_with(id="command-key")
    reload_effect.assert_called_once_with(id="note-key")
    assert result == [reload_effect.return_value.apply.return_value]


def test_command_commit_no_effect_when_command_missing() -> None:
    """No reload is emitted when the committed command can't be found."""
    handler = _handler(ReloadFooterOnCommandCommit, target_id="missing")

    with (
        patch.object(event_handlers.Command, "objects") as objects,
        patch.object(event_handlers, "ReloadNoteActionButtonsEffect") as reload_effect,
    ):
        objects.filter.return_value.first.return_value = None
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
