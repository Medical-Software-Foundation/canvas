"""Tests for handlers/event_handler.py — appointment-event-driven
notifications and auto-form-assignment.

`compute()` orchestrates several services (config, forms, delivery,
templates, history). We mock all of them and verify the right things
are called in the right circumstances.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


from appointment_reminders.handlers.event_handler import AppointmentEventHandler
from appointment_reminders.services.config import CampaignConfig


def _handler(
    event_name: str = "APPOINTMENT_CREATED",
    appointment_id: str = "appt-1",
    patient_id: str | None = "patient-1",
) -> AppointmentEventHandler:
    handler = AppointmentEventHandler.__new__(AppointmentEventHandler)
    event = MagicMock()
    event.name = event_name
    event.target.id = appointment_id
    event.context = {}
    if patient_id is not None:
        event.context = {"patient": {"id": patient_id}}
    handler.event = event
    handler.secrets = {
        "twilio-account-sid": "AC",
        "twilio-auth-token": "tok",
        "twilio-phone-number": "+1800",
        "sendgrid-api-key": "SG",
        "sendgrid-from-email": "from@example.com",
    }
    return handler


def _appointment(
    appt_id="appt-1",
    note_type_id="nt-1",
    note_type_name="Initial",
    days_out: int = 7,
) -> MagicMock:
    appt = MagicMock()
    appt.id = appt_id
    note_type = MagicMock()
    note_type.id = note_type_id
    note_type.name = note_type_name
    appt.note_type = note_type
    appt.start_time = datetime.now(timezone.utc) + timedelta(days=days_out)
    return appt


# ---- compute() — early returns ----

def test_compute_returns_empty_when_no_patient_id() -> None:
    handler = _handler(patient_id=None)
    with patch(
        "appointment_reminders.handlers.event_handler.load_config"
    ) as mock_load:
        result = handler.compute()
    assert result == []
    mock_load.assert_not_called()


def test_compute_returns_empty_when_appointment_not_found() -> None:
    handler = _handler(event_name="APPOINTMENT_CREATED")

    class DNE(Exception):
        pass

    with patch(
        "appointment_reminders.handlers.event_handler.load_config"
    ) as mock_load, patch(
        "appointment_reminders.handlers.event_handler.Appointment"
    ) as mock_appt_cls:
        mock_load.return_value = CampaignConfig()
        mock_appt_cls.DoesNotExist = DNE
        chain = mock_appt_cls.objects.select_related.return_value.prefetch_related.return_value
        chain.get.side_effect = DNE
        result = handler.compute()
    assert result == []


def test_compute_skips_when_event_is_unknown_and_not_create_or_update() -> None:
    """An unmapped event (e.g. APPOINTMENT_CHECKED_IN) → no-op."""
    handler = _handler(event_name="APPOINTMENT_CHECKED_IN")
    with patch(
        "appointment_reminders.handlers.event_handler.load_config"
    ) as mock_load, patch(
        "appointment_reminders.handlers.event_handler.Appointment"
    ) as mock_appt_cls:
        mock_load.return_value = CampaignConfig()
        result = handler.compute()
    assert result == []
    mock_appt_cls.objects.select_related.assert_not_called()


# ---- compute() — campaign disabled ----

def test_compute_records_skipped_metadata_when_campaign_disabled() -> None:
    handler = _handler(event_name="APPOINTMENT_CANCELED")
    appt = _appointment()
    # Globally enabled so we get past the master-switch check, but per-note-type
    # explicitly opts out — that's the "disabled" path that records the metadata.
    config = CampaignConfig(
        cancellation_enabled=True,
        note_type_reminders={
            "nt-1": {"note_type_id": "nt-1", "cancellation_enabled": False},
        },
    )
    patient = MagicMock()
    patient.telecom.all.return_value = []

    class DNE(Exception):
        pass

    with patch(
        "appointment_reminders.handlers.event_handler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.event_handler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.event_handler.Patient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.handlers.event_handler.AppointmentsMetadata"
    ) as mock_meta:
        mock_appt_cls.DoesNotExist = DNE
        mock_patient_cls.DoesNotExist = DNE
        chain = mock_appt_cls.objects.select_related.return_value.prefetch_related.return_value
        chain.get.return_value = appt
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        mock_meta.return_value.upsert.return_value = MagicMock()
        result = handler.compute()
    assert len(result) == 1
    upsert_arg = mock_meta.return_value.upsert.call_args.kwargs.get("value")
    assert upsert_arg.startswith("skipped|campaign_disabled")


# ---- compute() — full delivery happy path ----

def test_compute_full_cancellation_dispatches_delivery() -> None:
    handler = _handler(event_name="APPOINTMENT_CANCELED")
    appt = _appointment()
    config = CampaignConfig(
        cancellation_enabled=True,
        cancellation_channels=["sms"],
        cancellation_sms_template="Your appt is cancelled",
        cancellation_email_template="Your appt is cancelled",
    )
    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.telecom.all.return_value = []

    class DNE(Exception):
        pass

    with patch(
        "appointment_reminders.handlers.event_handler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.event_handler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.event_handler.Patient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.handlers.event_handler.get_template_variables",
        return_value={"patient_first_name": "Jane"},
    ), patch(
        "appointment_reminders.handlers.event_handler.deliver_to_patient",
        return_value=([MagicMock()], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.handlers.event_handler.log_delivery"
    ) as mock_log:
        mock_appt_cls.DoesNotExist = DNE
        mock_patient_cls.DoesNotExist = DNE
        chain = mock_appt_cls.objects.select_related.return_value.prefetch_related.return_value
        chain.get.return_value = appt
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        result = handler.compute()
    assert len(result) == 1
    mock_deliver.assert_called_once()
    mock_log.assert_called_once()


def test_compute_returns_empty_when_patient_not_found() -> None:
    handler = _handler(event_name="APPOINTMENT_CANCELED")
    appt = _appointment()
    config = CampaignConfig(
        cancellation_enabled=True,
        cancellation_channels=["sms"],
        cancellation_sms_template="x",
    )

    class DNE(Exception):
        pass

    with patch(
        "appointment_reminders.handlers.event_handler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.event_handler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.event_handler.Patient"
    ) as mock_patient_cls:
        mock_appt_cls.DoesNotExist = DNE
        mock_patient_cls.DoesNotExist = DNE
        chain = mock_appt_cls.objects.select_related.return_value.prefetch_related.return_value
        chain.get.return_value = appt
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.side_effect = DNE
        result = handler.compute()
    assert result == []

