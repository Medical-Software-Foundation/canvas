"""Tests for services/history.py — delivery audit log writes/reads."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from appointment_reminders.services.history import (
    _iso,
    get_patient_history,
    get_unresolved_senders,
    log_delivery,
    log_inbound_response,
    log_unresolved_sender,
)

_HIST = "appointment_reminders.services.history"


def _result(channel="sms", success=True, error=None, recipient="+1") -> MagicMock:
    r = MagicMock()
    r.channel = channel
    r.success = success
    r.error = error
    r.recipient = recipient
    return r


def test_log_delivery_returns_early_when_no_results() -> None:
    """No DB calls when results is empty."""
    with patch("appointment_reminders.services.history.CustomPatient") as mock_patient:
        log_delivery("appt-1", "patient-1", "reminder", [])
    mock_patient.objects.get.assert_not_called()


def test_log_delivery_warns_and_returns_when_patient_not_found() -> None:
    class DNE(Exception):
        pass

    with patch(
        "appointment_reminders.services.history.CustomPatient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.services.history.Patient"
    ) as mock_patient_proxy, patch(
        "appointment_reminders.services.history.NotificationDelivery"
    ) as mock_delivery:
        mock_patient_proxy.DoesNotExist = DNE
        mock_patient_cls.objects.get.side_effect = DNE
        log_delivery("appt-1", "patient-1", "reminder", [_result()])
    mock_delivery.objects.create.assert_not_called()


def test_log_delivery_creates_one_row_per_result() -> None:
    patient = MagicMock()
    with patch(
        "appointment_reminders.services.history.CustomPatient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.services.history.NotificationDelivery"
    ) as mock_delivery:
        mock_patient_cls.objects.get.return_value = patient
        results = [
            _result(channel="sms", success=True),
            _result(channel="email", success=False, error="boom"),
        ]
        log_delivery(
            "appt-1", "patient-1", "reminder", results,
            sms_content="sms body", email_content="<p>email body</p>",
        )

    assert mock_delivery.objects.create.call_count == 2
    sms_call = mock_delivery.objects.create.call_args_list[0]
    email_call = mock_delivery.objects.create.call_args_list[1]
    assert sms_call.kwargs["content"] == "sms body"
    assert sms_call.kwargs["status"] == "delivered"
    assert email_call.kwargs["content"] == "<p>email body</p>"
    assert email_call.kwargs["status"] == "failed"
    assert email_call.kwargs["error"] == "boom"


def test_log_delivery_uses_empty_string_when_appointment_id_falsy() -> None:
    patient = MagicMock()
    with patch(
        "appointment_reminders.services.history.CustomPatient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.services.history.NotificationDelivery"
    ) as mock_delivery:
        mock_patient_cls.objects.get.return_value = patient
        log_delivery("", "patient-1", "message_notification", [_result()])
    assert mock_delivery.objects.create.call_args.kwargs["appointment_id"] == ""


def test_get_patient_history_serializes_rows() -> None:
    row1 = MagicMock()
    row1.created_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    row1.appointment_id = "appt-1"
    row1.campaign_type = "reminder"
    row1.channel = "sms"
    row1.status = "delivered"
    row1.error = ""
    row1.content = "body"
    row1.recipient = "+1555"

    row2 = MagicMock()
    row2.created_at = None
    row2.appointment_id = ""
    row2.campaign_type = "message_notification"
    row2.channel = "email"
    row2.status = "failed"
    row2.error = "boom"
    row2.content = ""
    row2.recipient = ""

    qs = MagicMock()
    qs.order_by.return_value = [row1, row2]
    with patch(
        "appointment_reminders.services.history.NotificationDelivery"
    ) as mock_delivery:
        mock_delivery.objects.filter.return_value = qs
        result = get_patient_history("patient-1")
    assert len(result) == 2
    assert result[0]["timestamp"].startswith("2026-05-01")
    assert result[0]["recipient"] == "+1555"
    assert result[1]["timestamp"] == ""


def test_iso_naive_datetime_is_treated_as_utc() -> None:
    dt = datetime(2026, 5, 1, 12, 0)  # naive
    assert _iso(dt) == "2026-05-01T12:00:00+00:00"


def test_iso_none_returns_empty_string() -> None:
    assert _iso(None) == ""


# ---- unresolved senders ----

def test_log_unresolved_sender_writes_a_patientless_row() -> None:
    """The one row that carries no patient — there is no patient to carry."""
    with patch(f"{_HIST}.NotificationDelivery") as mock_delivery:
        log_unresolved_sender(body="Y", from_number="+14155551234")

    kwargs = mock_delivery.objects.create.call_args.kwargs
    assert kwargs["patient"] is None
    assert kwargs["campaign_type"] == "inbound_response"
    assert kwargs["status"] == "unresolved_sender"
    assert kwargs["channel"] == "sms"
    assert kwargs["content"] == "Y"        # ops needs to know it was a confirm
    assert kwargs["recipient"] == "+14155551234"  # and who to chase
    assert kwargs["appointment_id"] == ""


def test_log_unresolved_sender_does_not_look_up_a_patient() -> None:
    """Unlike the other writers, it must not require a patient row to exist."""
    with patch(f"{_HIST}.CustomPatient") as mock_patient, \
         patch(f"{_HIST}.NotificationDelivery"):
        log_unresolved_sender(body="STOP", from_number="+19998887777")
    mock_patient.objects.get.assert_not_called()


def test_log_unresolved_sender_tolerates_empty_body() -> None:
    with patch(f"{_HIST}.NotificationDelivery") as mock_delivery:
        log_unresolved_sender(body="", from_number="")
    kwargs = mock_delivery.objects.create.call_args.kwargs
    assert kwargs["content"] == ""
    assert kwargs["recipient"] == ""


def test_get_unresolved_senders_filters_and_orders() -> None:
    row = MagicMock()
    row.created_at = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    row.appointment_id = ""
    row.campaign_type = "inbound_response"
    row.channel = "sms"
    row.status = "unresolved_sender"
    row.error = ""
    row.content = "Y"
    row.recipient = "+14155551234"

    with patch(f"{_HIST}.NotificationDelivery") as mock_delivery:
        mock_delivery.objects.filter.return_value.order_by.return_value = [row]
        result = get_unresolved_senders(limit=100)

    mock_delivery.objects.filter.assert_called_once_with(
        campaign_type="inbound_response", status="unresolved_sender"
    )
    mock_delivery.objects.filter.return_value.order_by.assert_called_once_with(
        "-created_at"
    )
    assert len(result) == 1
    assert result[0]["status"] == "unresolved_sender"
    assert result[0]["recipient"] == "+14155551234"
    assert result[0]["patient_id"] == ""  # no patient to report


def test_unresolved_rows_are_excluded_from_patient_history() -> None:
    """Patient history is keyed on a patient, so these can never appear there.

    Guards the pairing: the write path is the only producer and the /admin
    endpoint the only reader, so a patient-less row is never orphaned.
    """
    with patch(f"{_HIST}.NotificationDelivery") as mock_delivery:
        mock_delivery.objects.filter.return_value.order_by.return_value = []
        get_patient_history("pat-1")
    mock_delivery.objects.filter.assert_called_once_with(patient__id="pat-1")


# ---- log_inbound_response (the patient-keyed sibling) ----

def test_log_inbound_response_writes_a_patient_keyed_row() -> None:
    patient = MagicMock()
    with patch(f"{_HIST}.CustomPatient") as mock_patient_cls, \
         patch(f"{_HIST}.NotificationDelivery") as mock_delivery:
        mock_patient_cls.objects.get.return_value = patient
        log_inbound_response(
            patient_id="pat-1",
            appointment_id="appt-1",
            status="opted_out+declined",
            body="CANCEL",
            from_number="+14155551234",
        )

    kwargs = mock_delivery.objects.create.call_args.kwargs
    assert kwargs["patient"] is patient
    assert kwargs["campaign_type"] == "inbound_response"
    assert kwargs["status"] == "opted_out+declined"
    assert kwargs["appointment_id"] == "appt-1"
    assert kwargs["content"] == "CANCEL"


def test_log_inbound_response_skips_when_patient_missing() -> None:
    """A vanished patient must not raise out of the webhook."""
    class DNE(Exception):
        pass

    with patch(f"{_HIST}.CustomPatient") as mock_patient_cls, \
         patch(f"{_HIST}.Patient") as mock_proxy, \
         patch(f"{_HIST}.NotificationDelivery") as mock_delivery:
        mock_proxy.DoesNotExist = DNE
        mock_patient_cls.objects.get.side_effect = DNE
        log_inbound_response(
            patient_id="gone", appointment_id="", status="confirmed",
            body="Y", from_number="+1",
        )

    mock_delivery.objects.create.assert_not_called()
