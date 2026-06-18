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
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.staff import Staff

from reschedule_cancelled_appointment.handlers.event_handlers import (
    RESCHEDULE_LABEL,
    RescheduleCancelledAppointmentHandler,
)


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
    )


def _task_data(effect: object) -> dict:
    """Extract the task payload dict from a CREATE_TASK effect."""
    return json.loads(effect.payload)["data"]  # type: ignore[attr-defined]


def _future() -> datetime:
    return arrow.utcnow().shift(days=3).datetime


def test_assigns_to_scheduling_team_when_configured_and_found() -> None:
    """A configured, existing scheduling team receives the reschedule task."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    team = TeamFactory.create(name="Scheduling")
    appointment = _create_appointment(patient, provider, start_time=_future())

    handler = _make_handler(appointment.id, {"SCHEDULING_TEAM_NAME": "Scheduling"})
    effects = handler.compute()

    assert len(effects) == 1
    effect = effects[0]
    assert effect.type == EffectType.CREATE_TASK

    data = _task_data(effect)
    assert data["team"]["id"] == str(team.id)
    assert data["assignee"]["id"] is None
    assert data["patient"]["id"] == str(patient.id)
    assert data["labels"] == [RESCHEDULE_LABEL]
    assert data["status"] == "OPEN"
    assert "Reschedule cancelled appointment" in data["title"]


def test_team_name_matched_case_insensitively() -> None:
    """The team name secret matches the Team regardless of casing."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    team = TeamFactory.create(name="Scheduling")
    appointment = _create_appointment(patient, provider, start_time=_future())

    handler = _make_handler(appointment.id, {"SCHEDULING_TEAM_NAME": "scheduling"})
    effects = handler.compute()

    data = _task_data(effects[0])
    assert data["team"]["id"] == str(team.id)


def test_assigns_to_provider_when_no_team_secret() -> None:
    """With no scheduling team configured, the task goes to the provider."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    handler = _make_handler(appointment.id, {})
    effects = handler.compute()

    data = _task_data(effects[0])
    assert data["assignee"]["id"] == str(provider.id)
    assert data["team"]["id"] is None


def test_assigns_to_provider_when_team_name_not_found() -> None:
    """A configured team name with no matching Team falls back to the provider."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    handler = _make_handler(appointment.id, {"SCHEDULING_TEAM_NAME": "Does Not Exist"})
    effects = handler.compute()

    data = _task_data(effects[0])
    assert data["assignee"]["id"] == str(provider.id)
    assert data["team"]["id"] is None


def test_blank_team_name_falls_back_to_provider() -> None:
    """A blank/whitespace team-name secret is treated as unset."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    handler = _make_handler(appointment.id, {"SCHEDULING_TEAM_NAME": "   "})
    effects = handler.compute()

    data = _task_data(effects[0])
    assert data["assignee"]["id"] == str(provider.id)
    assert data["team"]["id"] is None


def test_due_date_is_next_day() -> None:
    """The reschedule task is due roughly one day after cancellation."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(patient, provider, start_time=_future())

    handler = _make_handler(appointment.id, {})
    effects = handler.compute()

    due = arrow.get(_task_data(effects[0])["due"])
    assert arrow.utcnow().shift(hours=23) < due < arrow.utcnow().shift(hours=25)


def test_skips_past_appointment() -> None:
    """Cancelling an already-passed appointment creates no task."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(
        patient, provider, start_time=arrow.utcnow().shift(days=-1).datetime
    )

    handler = _make_handler(appointment.id, {})
    assert handler.compute() == []


def test_skips_entered_in_error_appointment() -> None:
    """An entered-in-error appointment creates no task."""
    patient = PatientFactory.create()
    provider = StaffFactory.create()
    appointment = _create_appointment(
        patient,
        provider,
        start_time=_future(),
        entered_in_error=provider.user,
    )

    handler = _make_handler(appointment.id, {})
    assert handler.compute() == []


def test_creates_unassigned_task_when_no_team_and_no_provider() -> None:
    """Last-resort guard: with neither a team nor a provider, the task is still
    created (unassigned) rather than silently dropped."""
    patient = PatientFactory.create()
    appointment = _create_appointment(patient, None, start_time=_future())

    handler = _make_handler(appointment.id, {})
    effects = handler.compute()

    assert len(effects) == 1
    data = _task_data(effects[0])
    assert data["team"]["id"] is None
    assert data["assignee"]["id"] is None
    assert data["patient"]["id"] == str(patient.id)


def test_returns_empty_when_appointment_not_found() -> None:
    """A target id with no matching appointment yields no effects (no crash)."""
    handler = _make_handler(uuid.uuid4(), {})
    assert handler.compute() == []


def test_responds_to_appointment_canceled() -> None:
    """The handler subscribes to the APPOINTMENT_CANCELED event."""
    from canvas_sdk.events import EventType

    assert RescheduleCancelledAppointmentHandler.RESPONDS_TO == [
        EventType.Name(EventType.APPOINTMENT_CANCELED)
    ]
