"""Tests for the reschedule-cancelled-appointment handler.

Each test is wrapped in a transaction that is rolled back afterwards, so the
factory/ORM-created rows below don't leak between tests.
"""

import json
import uuid
from datetime import datetime
from unittest.mock import Mock

import arrow

from canvas_sdk.effects.effect import EffectType
from canvas_sdk.test_utils.factories import PatientFactory, StaffFactory, TeamFactory
from canvas_sdk.v1.data.appointment import (
    Appointment,
    AppointmentLabel,
    AppointmentProgressStatus,
)
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note, NoteType
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import TaskLabel

from reschedule_cancelled_appointment.handlers.event_handlers import (
    RESCHEDULE_LABEL,
    RescheduleCancelledAppointmentHandler,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_handler(
    target_id: object, secrets: dict[str, str] | None = None
) -> RescheduleCancelledAppointmentHandler:
    """Build a handler whose event targets the given appointment id."""
    event = Mock()
    event.target.id = str(target_id)
    return RescheduleCancelledAppointmentHandler(event=event, secrets=secrets or {})


def _create_appointment(
    patient: Patient,
    provider: Staff | None,
    *,
    start_time: datetime,
    status: str = AppointmentProgressStatus.CANCELLED.value,
    entered_in_error: object = None,
    location: PracticeLocation | None = None,
    note_type: NoteType | None = None,
    note: Note | None = None,
    comment: str = "",
) -> Appointment:
    """Create a persisted Appointment (no factory exists for it in the SDK)."""
    return Appointment.objects.create(
        patient=patient,
        provider=provider,
        start_time=start_time,
        duration_minutes=30,
        status=status,
        telehealth_instructions_sent=False,
        entered_in_error=entered_in_error,
        location=location,
        note_type=note_type,
        note=note,
        comment=comment,
    )


def _create_label(name: str, *, active: bool = True) -> TaskLabel:
    return TaskLabel.objects.create(name=name, position=0, active=active)


def _add_label(appointment: Appointment, label: TaskLabel) -> None:
    AppointmentLabel.objects.create(appointment=appointment, task_label=label)


def _task_data(effect: object) -> dict:
    """Extract the task payload dict from a CREATE_TASK effect."""
    return json.loads(effect.payload)["data"]  # type: ignore[attr-defined]


def _comment_data(effect: object) -> dict:
    """Extract the comment payload dict from a CREATE_TASK_COMMENT effect."""
    return json.loads(effect.payload)["data"]  # type: ignore[attr-defined]


def _future() -> datetime:
    return arrow.utcnow().shift(days=3).datetime


# --------------------------------------------------------------------------- #
# Effect shape
# --------------------------------------------------------------------------- #
def test_returns_task_and_linked_comment() -> None:
    """A cancellation yields a CREATE_TASK plus a CREATE_TASK_COMMENT linked to it."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    effects = _make_handler(appointment.id, {}).compute()

    assert len(effects) == 2
    task, comment = effects
    assert task.type == EffectType.CREATE_TASK
    assert comment.type == EffectType.CREATE_TASK_COMMENT
    # The comment points at the task that was just created.
    assert _comment_data(comment)["task"]["id"] == _task_data(task)["id"]


# --------------------------------------------------------------------------- #
# Assignment routing
# --------------------------------------------------------------------------- #
def test_assigns_to_scheduling_team_when_configured_and_found() -> None:
    """A configured, existing scheduling team receives the reschedule task."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    team = TeamFactory.create(name="Scheduling")
    appointment = _create_appointment(patient, provider, start_time=_future())

    effects = _make_handler(
        appointment.id, {"SCHEDULING_TEAM_NAME": "Scheduling"}
    ).compute()

    data = _task_data(effects[0])
    assert data["team"]["id"] == str(team.id)
    assert data["assignee"]["id"] is None
    assert data["patient"]["id"] == str(patient.id)
    assert data["status"] == "OPEN"
    assert "Reschedule cancelled appointment" in data["title"]


def test_team_name_matched_case_insensitively() -> None:
    """The team name secret matches the Team regardless of casing."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    team = TeamFactory.create(name="Scheduling")
    appointment = _create_appointment(patient, provider, start_time=_future())

    effects = _make_handler(
        appointment.id, {"SCHEDULING_TEAM_NAME": "scheduling"}
    ).compute()

    assert _task_data(effects[0])["team"]["id"] == str(team.id)


def test_assigns_to_provider_when_no_team_secret() -> None:
    """With no scheduling team configured, the task goes to the provider."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    data = _task_data(_make_handler(appointment.id, {}).compute()[0])
    assert data["assignee"]["id"] == str(provider.id)
    assert data["team"]["id"] is None


def test_assigns_to_provider_when_team_name_not_found() -> None:
    """A configured team name with no matching Team falls back to the provider."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    data = _task_data(
        _make_handler(
            appointment.id, {"SCHEDULING_TEAM_NAME": "Does Not Exist"}
        ).compute()[0]
    )
    assert data["assignee"]["id"] == str(provider.id)
    assert data["team"]["id"] is None


def test_blank_team_name_falls_back_to_provider() -> None:
    """A blank/whitespace team-name secret is treated as unset."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    data = _task_data(
        _make_handler(appointment.id, {"SCHEDULING_TEAM_NAME": "   "}).compute()[0]
    )
    assert data["assignee"]["id"] == str(provider.id)
    assert data["team"]["id"] is None


def test_creates_unassigned_task_when_no_team_and_no_provider() -> None:
    """Last-resort guard: with neither a team nor a provider, the task is still
    created (unassigned) rather than silently dropped."""
    patient = PatientFactory.create()
    appointment = _create_appointment(patient, None, start_time=_future())

    effects = _make_handler(appointment.id, {}).compute()

    assert len(effects) == 2
    data = _task_data(effects[0])
    assert data["team"]["id"] is None
    assert data["assignee"]["id"] is None
    assert data["patient"]["id"] == str(patient.id)


def test_due_date_is_next_day() -> None:
    """The reschedule task is due roughly one day after cancellation."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    due = arrow.get(_task_data(_make_handler(appointment.id, {}).compute()[0])["due"])
    assert arrow.utcnow().shift(hours=23) < due < arrow.utcnow().shift(hours=25)


# --------------------------------------------------------------------------- #
# Skip conditions
# --------------------------------------------------------------------------- #
def test_skips_past_appointment() -> None:
    """Cancelling an already-passed appointment creates no task."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(
        patient, provider, start_time=arrow.utcnow().shift(days=-1).datetime
    )
    assert _make_handler(appointment.id, {}).compute() == []


def test_skips_entered_in_error_appointment() -> None:
    """An entered-in-error appointment creates no task."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(
        patient, provider, start_time=_future(), entered_in_error=provider.user
    )
    assert _make_handler(appointment.id, {}).compute() == []


def test_returns_empty_when_appointment_not_found() -> None:
    """A target id with no matching appointment yields no effects (no crash)."""
    assert _make_handler(uuid.uuid4(), {}).compute() == []


# --------------------------------------------------------------------------- #
# Labels: inherit appointment labels + Reschedule-only-if-it-exists
# --------------------------------------------------------------------------- #
def test_no_label_when_reschedule_label_absent_and_no_appointment_labels() -> None:
    """No labels are added (and none created) when nothing applies."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    assert _task_data(_make_handler(appointment.id, {}).compute()[0])["labels"] == []


def test_adds_reschedule_label_only_when_it_exists() -> None:
    """The Reschedule label is added when a TaskLabel of that name exists."""
    _create_label(RESCHEDULE_LABEL)
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    assert _task_data(_make_handler(appointment.id, {}).compute()[0])["labels"] == [
        RESCHEDULE_LABEL
    ]


def test_inactive_reschedule_label_is_not_added() -> None:
    """An inactive Reschedule label is treated as not existing."""
    _create_label(RESCHEDULE_LABEL, active=False)
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    assert _task_data(_make_handler(appointment.id, {}).compute()[0])["labels"] == []


def test_inherits_appointment_labels() -> None:
    """Existing appointment labels are carried onto the task."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())
    _add_label(appointment, _create_label("Telehealth"))

    assert _task_data(_make_handler(appointment.id, {}).compute()[0])["labels"] == [
        "Telehealth"
    ]


def test_inherits_labels_and_adds_reschedule_when_present() -> None:
    """Inherited labels and the Reschedule label combine (Reschedule last)."""
    _create_label(RESCHEDULE_LABEL)
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())
    _add_label(appointment, _create_label("Telehealth"))

    assert _task_data(_make_handler(appointment.id, {}).compute()[0])["labels"] == [
        "Telehealth",
        RESCHEDULE_LABEL,
    ]


def test_reschedule_label_not_duplicated_when_already_on_appointment() -> None:
    """If the appointment already carries a Reschedule label, it isn't doubled."""
    reschedule = _create_label(RESCHEDULE_LABEL)
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())
    _add_label(appointment, reschedule)

    assert _task_data(_make_handler(appointment.id, {}).compute()[0])["labels"] == [
        RESCHEDULE_LABEL
    ]


# --------------------------------------------------------------------------- #
# Comment with appointment information
# --------------------------------------------------------------------------- #
def test_comment_includes_appointment_details() -> None:
    """The comment summarises provider, date/time, location and note type."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    location = PracticeLocation.objects.create(
        full_name="Downtown Clinic",
        short_name="Downtown",
        place_of_service_code="11",
        bill_through_organization=False,
    )
    note_type = NoteType.objects.create(name="Office Visit")
    appointment = _create_appointment(
        patient,
        provider,
        start_time=_future(),
        location=location,
        note_type=note_type,
        comment="Knee pain",
    )

    body = _comment_data(_make_handler(appointment.id, {}).compute()[1])["body"]

    assert provider.full_name in body
    assert "Downtown Clinic" in body
    assert "Office Visit" in body
    assert "Reason for visit: Knee pain" in body
    assert arrow.get(appointment.start_time).format("MMM D, YYYY") in body


def test_comment_prefers_reason_for_visit_command() -> None:
    """A committed Reason For Visit command is preferred over the appointment comment."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    note_type = NoteType.objects.create(name="Office Visit")
    note = Note.objects.create(note_type_version=note_type, provider=provider)
    Command.objects.create(
        note=note,
        schema_key="reasonForVisit",
        state="committed",
        data={"comment": "Annual physical"},
        anchor_object_dbid=0,
    )
    appointment = _create_appointment(
        patient, provider, start_time=_future(), note=note, comment="ignored fallback"
    )

    body = _comment_data(_make_handler(appointment.id, {}).compute()[1])["body"]
    assert "Reason for visit: Annual physical" in body


def test_comment_reason_for_visit_uses_structured_coding_text() -> None:
    """A structured RFV command's coding text is used when present."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    note_type = NoteType.objects.create(name="Office Visit")
    note = Note.objects.create(note_type_version=note_type, provider=provider)
    Command.objects.create(
        note=note,
        schema_key="reasonForVisit",
        state="committed",
        data={"coding": {"text": "Hypertension follow-up"}},
        anchor_object_dbid=0,
    )
    appointment = _create_appointment(
        patient, provider, start_time=_future(), note=note
    )

    body = _comment_data(_make_handler(appointment.id, {}).compute()[1])["body"]
    assert "Reason for visit: Hypertension follow-up" in body


def test_comment_reason_for_visit_falls_back_to_comment_when_command_empty() -> None:
    """An RFV command with no usable text falls back to the appointment comment."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    note_type = NoteType.objects.create(name="Office Visit")
    note = Note.objects.create(note_type_version=note_type, provider=provider)
    Command.objects.create(
        note=note,
        schema_key="reasonForVisit",
        state="committed",
        data={"comment": ""},
        anchor_object_dbid=0,
    )
    appointment = _create_appointment(
        patient, provider, start_time=_future(), note=note, comment="Sore throat"
    )

    body = _comment_data(_make_handler(appointment.id, {}).compute()[1])["body"]
    assert "Reason for visit: Sore throat" in body


def test_comment_reason_for_visit_defaults_when_unknown() -> None:
    """With no RFV command and no comment, the reason falls back to a placeholder."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    body = _comment_data(_make_handler(appointment.id, {}).compute()[1])["body"]
    assert "Reason for visit: Not documented" in body
    assert "Location: Not specified" in body
    assert "Note type: Not specified" in body


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def test_responds_to_appointment_canceled() -> None:
    """The handler subscribes to the APPOINTMENT_CANCELED event."""
    from canvas_sdk.events import EventType

    assert RescheduleCancelledAppointmentHandler.RESPONDS_TO == [
        EventType.Name(EventType.APPOINTMENT_CANCELED)
    ]
