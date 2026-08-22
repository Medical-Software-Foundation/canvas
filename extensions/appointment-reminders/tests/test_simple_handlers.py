"""Tests for the small SDK handler classes — timeline filter, message
broadcast, websocket auth, and the three Application launch handlers.

These are mostly thin wrappers around SDK Effect builders. We mock the SDK
ORM (NoteType, Message) and assert the produced effects/short-circuits.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from appointment_reminders.handlers.admin_app import NotifyAdminApp
from appointment_reminders.handlers.patient_app import NotifyPatientApp
from appointment_reminders.handlers.timeline_filter import TimelineMessageFilter


# ---- TimelineMessageFilter ----

def test_timeline_filter_returns_no_effect_when_message_note_type_missing() -> None:
    handler = TimelineMessageFilter.__new__(TimelineMessageFilter)
    with patch(
        "appointment_reminders.handlers.timeline_filter.NoteType"
    ) as mock_note_type:
        mock_note_type.objects.filter.return_value.first.return_value = None
        assert handler.compute() == []


def test_timeline_filter_returns_no_effect_when_unique_identifier_missing() -> None:
    handler = TimelineMessageFilter.__new__(TimelineMessageFilter)
    with patch(
        "appointment_reminders.handlers.timeline_filter.NoteType"
    ) as mock_note_type:
        mock_note_type.objects.filter.return_value.first.return_value = MagicMock(
            unique_identifier=""
        )
        assert handler.compute() == []


def test_timeline_filter_excludes_message_note_type() -> None:
    handler = TimelineMessageFilter.__new__(TimelineMessageFilter)
    msg_nt = MagicMock(unique_identifier="msg-uid")
    with patch(
        "appointment_reminders.handlers.timeline_filter.NoteType"
    ) as mock_note_type, patch(
        "appointment_reminders.handlers.timeline_filter.PatientTimelineEffect"
    ) as mock_effect_cls:
        mock_note_type.objects.filter.return_value.first.return_value = msg_nt
        mock_effect = MagicMock()
        mock_effect_cls.return_value.apply.return_value = mock_effect
        result = handler.compute()
    assert result == [mock_effect]
    mock_effect_cls.assert_called_once_with(excluded_note_types=["msg-uid"])



def _admin_app(user: dict | None = None) -> NotifyAdminApp:
    app = NotifyAdminApp.__new__(NotifyAdminApp)
    app.event = MagicMock()
    app.event.context = {"user": user if user is not None else {"id": "s1", "type": "Staff"}}
    app.secrets = {"ADMIN_ROLE_NAMES": "Practice Manager"}
    return app


def test_notify_admin_app_on_open_returns_modal_effect() -> None:
    app = _admin_app()
    with patch(
        "appointment_reminders.handlers.admin_app.LaunchModalEffect"
    ) as mock_modal, patch(
        "appointment_reminders.handlers.admin_app.is_admin_staff", return_value=True
    ):
        mock_effect = MagicMock()
        mock_modal.return_value.apply.return_value = mock_effect
        result = app.on_open()

    assert result == mock_effect
    kwargs = mock_modal.call_args.kwargs
    assert "/admin?v=" in kwargs["url"]  # cache-bust query string appended
    assert "Appointment Reminders" == kwargs["title"]


def test_notify_admin_app_on_open_refuses_staff_without_admin_role() -> None:
    app = _admin_app()
    with patch(
        "appointment_reminders.handlers.admin_app.LaunchModalEffect"
    ) as mock_modal, patch(
        "appointment_reminders.handlers.admin_app.is_admin_staff", return_value=False
    ) as mock_gate:
        app.on_open()

    mock_gate.assert_called_once_with("s1", {"ADMIN_ROLE_NAMES": "Practice Manager"})
    url = mock_modal.call_args.kwargs["url"]
    assert "/access-denied" in url
    assert "/admin?" not in url


def test_notify_admin_app_on_open_refuses_non_staff_without_role_lookup() -> None:
    """A patient-typed user is refused before any role query runs."""
    app = _admin_app(user={"id": "p1", "type": "Patient"})
    with patch(
        "appointment_reminders.handlers.admin_app.LaunchModalEffect"
    ) as mock_modal, patch(
        "appointment_reminders.handlers.admin_app.is_admin_staff"
    ) as mock_gate:
        app.on_open()

    mock_gate.assert_not_called()
    assert "/access-denied" in mock_modal.call_args.kwargs["url"]


def test_notify_patient_app_on_open_uses_patient_id_from_context() -> None:
    app = NotifyPatientApp.__new__(NotifyPatientApp)
    app.event = MagicMock()
    app.event.context = {"patient": {"id": "patient-9"}}
    with patch(
        "appointment_reminders.handlers.patient_app.LaunchModalEffect"
    ) as mock_modal:
        mock_effect = MagicMock()
        mock_modal.return_value.apply.return_value = mock_effect
        result = app.on_open()
    assert result == mock_effect
    assert "patient_id=patient-9" in mock_modal.call_args.kwargs["url"]

