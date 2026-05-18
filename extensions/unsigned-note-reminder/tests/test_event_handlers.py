import json
from unittest.mock import Mock

import arrow
from canvas_sdk.effects.task import TaskStatus
from canvas_sdk.test_utils.factories import NoteFactory, NoteTypeFactory, PatientFactory, StaffFactory
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.task import Task

from unsigned_note_reminder.handlers.event_handlers import UnsignedNoteReminderTask


def _make_handler(secrets: dict[str, str] | None = None) -> UnsignedNoteReminderTask:
    """Create a handler instance with optional secrets override."""
    mock_event = Mock()
    mock_event.type = "cron"
    handler = UnsignedNoteReminderTask(event=mock_event)
    handler.secrets = secrets or {}
    return handler


def _create_unsigned_note(hours_ago: int = 72, note_type_name: str = "Office visit") -> Note:
    """Create an unsigned note with a provider, dated hours_ago hours in the past."""
    provider = StaffFactory.create()
    patient = PatientFactory.create()
    note_type = NoteTypeFactory.create(name=note_type_name)
    note = NoteFactory.create(
        note_type_version=note_type,
        patient=patient,
        provider=provider,
        datetime_of_service=arrow.utcnow().shift(hours=-hours_ago).datetime,
    )
    return note


def _lock_note(note: Note) -> None:
    """Mark a note as locked (signed)."""
    CurrentNoteStateEvent.objects.create(note=note, state=NoteStates.LOCKED)


def _parse_effect_payload(effect: object) -> dict:
    """Parse an effect's JSON string payload."""
    return json.loads(effect.payload)


def test_creates_task_for_unsigned_overdue_note() -> None:
    """An unsigned note past the threshold should produce a reminder task."""
    note = _create_unsigned_note(hours_ago=72)
    handler = _make_handler()

    effects = handler.execute()

    assert len(effects) == 1
    payload = _parse_effect_payload(effects[0])
    assert "Sign note for" in payload["data"]["title"]
    assert payload["data"]["assignee"]["id"] == str(note.provider.id)
    assert payload["data"]["patient"]["id"] == str(note.patient.id)


def test_skips_locked_notes() -> None:
    """A locked (signed) note should not produce any effects."""
    note = _create_unsigned_note(hours_ago=72)
    _lock_note(note)
    handler = _make_handler()

    effects = handler.execute()

    assert len(effects) == 0


def test_skips_recent_notes() -> None:
    """A note within the threshold window should not produce any effects."""
    _create_unsigned_note(hours_ago=12)
    handler = _make_handler(secrets={"THRESHOLD_HOURS": "48"})

    effects = handler.execute()

    assert len(effects) == 0


def test_respects_custom_threshold() -> None:
    """A custom THRESHOLD_HOURS secret should change the cutoff."""
    _create_unsigned_note(hours_ago=30)
    handler = _make_handler(secrets={"THRESHOLD_HOURS": "24"})

    effects = handler.execute()

    assert len(effects) == 1


def test_filters_by_note_type() -> None:
    """When NOTE_TYPES is set, only matching note types should produce tasks."""
    _create_unsigned_note(hours_ago=72, note_type_name="Office visit")
    _create_unsigned_note(hours_ago=72, note_type_name="Progress note")

    handler = _make_handler(secrets={"NOTE_TYPES": "Office visit"})
    effects = handler.execute()

    assert len(effects) == 1
    payload = _parse_effect_payload(effects[0])
    assert "Sign note for" in payload["data"]["title"]


def test_skips_notes_without_provider() -> None:
    """A note with no provider should not produce any effects."""
    patient = PatientFactory.create()
    note_type = NoteTypeFactory.create(name="Office visit")
    provider = StaffFactory.create()
    note = NoteFactory.create(
        note_type_version=note_type,
        patient=patient,
        provider=provider,
        datetime_of_service=arrow.utcnow().shift(hours=-72).datetime,
    )
    Note.objects.filter(dbid=note.dbid).update(provider=None)

    handler = _make_handler()

    effects = handler.execute()

    assert len(effects) == 0


def test_skips_duplicate_reminders() -> None:
    """If an open reminder task already exists for the same note, skip it."""
    note = _create_unsigned_note(hours_ago=72)

    note_date = note.datetime_of_service.strftime("%Y-%m-%d")
    patient_name = f"{note.patient.first_name} {note.patient.last_name}"
    Task.objects.create(
        patient=note.patient,
        assignee=note.provider,
        status=TaskStatus.OPEN,
        title=f"Sign note for {patient_name} from {note_date}",
    )

    handler = _make_handler()
    effects = handler.execute()

    assert len(effects) == 0


def test_creates_task_when_prior_reminder_is_closed() -> None:
    """A closed prior reminder should not prevent a new task from being created."""
    note = _create_unsigned_note(hours_ago=72)

    note_date = note.datetime_of_service.strftime("%Y-%m-%d")
    patient_name = f"{note.patient.first_name} {note.patient.last_name}"
    Task.objects.create(
        patient=note.patient,
        assignee=note.provider,
        status=TaskStatus.CLOSED,
        title=f"Sign note for {patient_name} from {note_date}",
    )

    handler = _make_handler()
    effects = handler.execute()

    assert len(effects) == 1


def test_multiple_unsigned_notes_create_multiple_tasks() -> None:
    """Multiple overdue unsigned notes should each produce a reminder task."""
    _create_unsigned_note(hours_ago=72, note_type_name="Office visit")
    _create_unsigned_note(hours_ago=96, note_type_name="Progress note")

    handler = _make_handler()
    effects = handler.execute()

    assert len(effects) == 2


def test_task_has_unsigned_note_reminder_label() -> None:
    """Created tasks should have the 'unsigned-note-reminder' label for identification."""
    _create_unsigned_note(hours_ago=72)
    handler = _make_handler()

    effects = handler.execute()

    assert len(effects) == 1
    payload = _parse_effect_payload(effects[0])
    assert "unsigned-note-reminder" in payload["data"]["labels"]


def test_batch_size_limits_effects() -> None:
    """MAX_BATCH_SIZE should cap how many notes are processed per run."""
    for i in range(5):
        _create_unsigned_note(hours_ago=72 + i, note_type_name="Office visit")

    handler = _make_handler(secrets={"MAX_BATCH_SIZE": "3"})
    effects = handler.execute()

    assert len(effects) == 3


def test_oldest_notes_processed_first() -> None:
    """Notes should be processed oldest-first so the most overdue get reminders."""
    recent = _create_unsigned_note(hours_ago=72, note_type_name="Office visit")
    oldest = _create_unsigned_note(hours_ago=200, note_type_name="Office visit")

    handler = _make_handler(secrets={"MAX_BATCH_SIZE": "1"})
    effects = handler.execute()

    assert len(effects) == 1
    payload = _parse_effect_payload(effects[0])
    oldest_date = oldest.datetime_of_service.strftime("%Y-%m-%d")
    assert oldest_date in payload["data"]["title"]


def test_empty_instance_produces_no_effects() -> None:
    """When there are no unsigned overdue notes, nothing should happen."""
    handler = _make_handler()
    effects = handler.execute()

    assert len(effects) == 0
