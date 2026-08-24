"""Tests for handlers/notification_api.py — staff-facing admin and
patient-detail SimpleAPI endpoints.

The class is a `SimpleAPI` subclass with a `StaffSessionAuthMixin`. We
instantiate via `__new__` (skipping framework init), patch path params
and request bodies on the mock request, and patch every Canvas SDK
import the endpoint uses.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch


from appointment_reminders.handlers.notification_api import NotificationAPI
from appointment_reminders.services.config import CampaignConfig


def _api(
    path_params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    query_params: dict | None = None,
    secrets: dict | None = None,
) -> NotificationAPI:
    api = NotificationAPI.__new__(NotificationAPI)
    api.request = MagicMock()
    api.request.path_params = path_params or {}
    api.request.json.return_value = json_body or {}
    api.request.headers = MagicMock()
    api.request.headers.get = MagicMock(side_effect=lambda k, d="": (headers or {}).get(k, d))
    api.request.query_params = MagicMock()
    api.request.query_params.get = MagicMock(side_effect=lambda k, d=None: (query_params or {}).get(k, d))
    api.secrets = secrets if secrets is not None else {}
    api.request.path = "/admin"
    return api


# ---- authenticate: admin role gate ----
#
# This is the enforceable boundary for the admin console. The provider-menu
# item cannot be hidden per user, so any logged-in staff member can navigate
# straight to these URLs; refusing them here is what protects the config.

_AUTHZ = "appointment_reminders.handlers.notification_api.is_admin_staff"


def _creds(user_id: str = "s1", user_type: str = "Staff") -> MagicMock:
    credentials = MagicMock()
    credentials.logged_in_user = {"id": user_id, "type": user_type}
    return credentials


def _api_at(path: str, secrets: dict | None = None) -> NotificationAPI:
    api = _api(secrets=secrets)
    api.request.path = path
    return api


def test_authenticate_allows_admin_on_admin_route() -> None:
    api = _api_at("/admin", secrets={"ADMIN_ROLE_NAMES": "Practice Manager"})
    with patch(_AUTHZ, return_value=True) as gate:
        assert api.authenticate(_creds()) is True
    gate.assert_called_once_with("s1", {"ADMIN_ROLE_NAMES": "Practice Manager"})


def test_authenticate_rejects_non_admin_on_admin_route() -> None:
    api = _api_at("/admin")
    with patch(_AUTHZ, return_value=False):
        assert api.authenticate(_creds()) is False


def test_authenticate_rejects_non_admin_on_config_write() -> None:
    """POST /admin/config rewrites campaigns instance-wide — the route that matters most."""
    api = _api_at("/admin/config")
    with patch(_AUTHZ, return_value=False):
        assert api.authenticate(_creds()) is False


def test_authenticate_gates_every_admin_subroute() -> None:
    for path in (
        "/admin",
        "/admin/config",
        "/admin/note-types",
        "/admin/business-lines",
        "/admin/integration-status",
        "/admin/unresolved-senders",
        "/admin/patient/abc123",
    ):
        api = _api_at(path)
        with patch(_AUTHZ, return_value=False):
            assert api.authenticate(_creds()) is False, path


def test_authenticate_leaves_patient_panel_routes_open_to_any_staff() -> None:
    """The chart panel is ordinary staff workflow; only /admin is restricted."""
    for path in (
        "/patient/abc123/history",
        "/patient/abc123/appointments",
        "/patient/abc123/preview",
        "/patient/abc123/send",
        "/patient-view",
        "/access-denied",
    ):
        api = _api_at(path)
        with patch(_AUTHZ, return_value=False) as gate:
            assert api.authenticate(_creds()) is True, path
        gate.assert_not_called()


def test_authenticate_rejects_a_patient_session_outright() -> None:
    """StaffSessionAuthMixin raises for a non-staff session, before the role check."""
    from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError

    api = _api_at("/patient-view")
    with patch(_AUTHZ) as gate:
        try:
            api.authenticate(_creds(user_type="Patient"))
        except InvalidCredentialsError:
            pass
        else:
            raise AssertionError("expected InvalidCredentialsError")
    gate.assert_not_called()


# ---- unresolved senders ----

def test_unresolved_senders_endpoint_returns_rows() -> None:
    rows = [{"status": "unresolved_sender", "recipient": "+14155551234", "content": "Y"}]
    with patch(
        "appointment_reminders.handlers.notification_api.fetch_unresolved_senders",
        return_value=rows,
    ) as mock_fetch:
        result = _api().get_unresolved_senders_endpoint()

    assert result[0].status_code == HTTPStatus.OK
    assert json.loads(result[0].content) == rows
    mock_fetch.assert_called_once_with(limit=100)


def test_unresolved_senders_endpoint_returns_empty_list_when_none() -> None:
    with patch(
        "appointment_reminders.handlers.notification_api.fetch_unresolved_senders",
        return_value=[],
    ):
        result = _api().get_unresolved_senders_endpoint()
    assert json.loads(result[0].content) == []


# ---- access-denied page ----

def test_access_denied_page_renders_without_admin_role() -> None:
    result = _api().get_access_denied_page()
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.OK


# ---- get_admin_page ----

def test_get_admin_page_returns_html() -> None:
    api = _api()
    result = api.get_admin_page()
    assert len(result) == 1
    # HTMLResponse — body should be a non-empty HTML string
    assert result[0].status_code == HTTPStatus.OK


# ---- get_note_types ----

def test_get_note_types_returns_active_scheduleable_types() -> None:
    api = _api()
    nt = MagicMock()
    nt.id = "nt-1"
    nt.name = "Initial"
    nt.is_telehealth = False
    with patch(
        "canvas_sdk.v1.data.note.NoteType"
    ) as mock_note_type:
        mock_note_type.objects.filter.return_value.order_by.return_value = [nt]
        result = api.get_note_types()
    assert result[0].status_code == HTTPStatus.OK


# ---- get_business_lines ----

def test_get_business_lines_returns_active_lines() -> None:
    api = _api()
    bl = MagicMock()
    bl.id = "bl-1"
    bl.name = "Northwind Health"
    with patch("canvas_sdk.v1.data.BusinessLine") as mock_bl:
        mock_bl.objects.filter.return_value.order_by.return_value = [bl]
        result = api.get_business_lines()
    mock_bl.objects.filter.assert_called_once_with(active=True)
    assert result[0].status_code == HTTPStatus.OK


# ---- get_integration_status ----

def test_integration_status_all_configured() -> None:
    api = _api()
    api.secrets = {
        "twilio-account-sid": "AC",
        "twilio-auth-token": "tok",
        "twilio-phone-number": "+1",
        "sendgrid-api-key": "SG",
        "sendgrid-from-email": "from@example.com",
    }
    result = api.get_integration_status()
    assert result[0].status_code == HTTPStatus.OK


def test_integration_status_neither_configured() -> None:
    api = _api()
    api.secrets = {}
    result = api.get_integration_status()
    assert result[0].status_code == HTTPStatus.OK


# ---- get_config / save_config_endpoint ----

def test_get_config_returns_dict() -> None:
    api = _api()
    with patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=CampaignConfig(reminders_enabled=True),
    ):
        result = api.get_config()
    assert result[0].status_code == HTTPStatus.OK


def test_save_config_endpoint_persists_and_returns_ok() -> None:
    api = _api(json_body={"reminders_enabled": True})
    with patch(
        "appointment_reminders.handlers.notification_api.save_config"
    ) as mock_save:
        result = api.save_config_endpoint()
    assert result[0].status_code == HTTPStatus.OK
    mock_save.assert_called_once()


def test_save_config_endpoint_rejects_invalid_payload() -> None:
    """A TypeError from `from_dict` returns 400."""
    api = _api(json_body={"reminders_enabled": True})
    with patch(
        "appointment_reminders.handlers.notification_api.CampaignConfig.from_dict",
        side_effect=TypeError("bad"),
    ):
        result = api.save_config_endpoint()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


# ---- save_config_endpoint under LOCK_MESSAGE_TEMPLATES ----

_LOCKED = {"LOCK_MESSAGE_TEMPLATES": "true"}


def test_save_config_endpoint_allows_template_edit_while_locked() -> None:
    """The lock does not apply to admins — they own the approved copy.

    It constrains manual senders instead; see the manual_send tests below.
    """
    api = _api(
        json_body={"reminder_sms_template": "reworded copy"},
        secrets=_LOCKED,
    )
    with patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=CampaignConfig(),
    ), patch(
        "appointment_reminders.handlers.notification_api.save_config"
    ) as mock_save:
        result = api.save_config_endpoint()

    assert result[0].status_code == HTTPStatus.OK
    assert mock_save.call_args[0][0].reminder_sms_template == "reworded copy"


def test_save_config_endpoint_allows_scheduling_change_when_locked() -> None:
    """Locking freezes copy only — cadence and channels stay editable."""
    stored = CampaignConfig()
    payload = stored.to_dict()
    payload["reminders_enabled"] = True
    payload["reminder_intervals"] = [1440]
    payload["reminder_channels"] = ["sms"]
    api = _api(json_body=payload, secrets=_LOCKED)

    with patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=stored,
    ), patch(
        "appointment_reminders.handlers.notification_api.save_config"
    ) as mock_save:
        result = api.save_config_endpoint()

    assert result[0].status_code == HTTPStatus.OK
    saved = mock_save.call_args[0][0]
    assert saved.reminders_enabled is True
    assert saved.reminder_intervals == [1440]


def test_save_config_endpoint_allows_template_edit_when_unlocked() -> None:
    """Without the secret the same payload saves normally."""
    api = _api(json_body={"reminder_sms_template": "reworded copy"}, secrets={})
    with patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=CampaignConfig(),
    ), patch(
        "appointment_reminders.handlers.notification_api.save_config"
    ) as mock_save:
        result = api.save_config_endpoint()

    assert result[0].status_code == HTTPStatus.OK
    assert mock_save.call_args[0][0].reminder_sms_template == "reworded copy"


def test_integration_status_reports_lock_state() -> None:
    """The admin page reads the lock from here to render read-only templates."""
    unlocked = _api(secrets={})
    locked = _api(secrets=_LOCKED)
    assert json.loads(unlocked.get_integration_status()[0].content)["templates_locked"] is False
    assert json.loads(locked.get_integration_status()[0].content)["templates_locked"] is True


def test_integration_status_reports_testing_mode() -> None:
    """Drives the live-sending warning banner in the admin app."""
    off = _api(secrets={})
    on = _api(secrets={"TESTING_MODE": "true"})
    assert json.loads(off.get_integration_status()[0].content)["testing_mode"] is False
    assert json.loads(on.get_integration_status()[0].content)["testing_mode"] is True


# ---- get_patient_detail ----

def test_get_patient_detail_returns_404_when_patient_missing() -> None:
    api = _api(path_params={"patient_id": "patient-1"})

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls:
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.prefetch_related.return_value.get.side_effect = DNE
        result = api.get_patient_detail()
    assert result[0].status_code == HTTPStatus.NOT_FOUND


def test_get_patient_detail_returns_full_payload() -> None:
    api = _api(path_params={"patient_id": "patient-1"})

    patient = MagicMock()
    patient.id = "patient-1"
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.nickname = "Janie"
    patient.mrn = "1234"
    patient.birth_date = datetime(2000, 1, 1).date()
    patient.active = True
    patient.deceased = False

    phone_telecom = MagicMock(
        system="phone", value="555", has_consent=True, opted_out=False
    )
    email_telecom = MagicMock(
        system="email", value="x@y.com", has_consent=False, opted_out=True
    )
    patient.telecom.all.return_value = [phone_telecom, email_telecom]

    home_addr = MagicMock(state="active", use="home")
    home_addr.city = "Austin"
    home_addr.state_code = "TX"
    patient.addresses.all.return_value = [home_addr]

    class DNE(Exception):
        pass

    # `get_patient_detail` does local imports — must patch the SDK module path
    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "canvas_sdk.v1.data.appointment.Appointment"
    ) as mock_appt_cls:
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.prefetch_related.return_value.get.return_value = patient
        mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = None
        result = api.get_patient_detail()
    assert result[0].status_code == HTTPStatus.OK


def test_get_patient_detail_swallows_appointment_lookup_exception() -> None:
    """A DB error fetching the next appointment must not 500 the patient detail."""
    api = _api(path_params={"patient_id": "patient-1"})
    patient = MagicMock()
    patient.id = "patient-1"
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.nickname = ""
    patient.mrn = ""
    patient.birth_date = None
    patient.active = True
    patient.deceased = False
    patient.telecom.all.return_value = []
    patient.addresses.all.return_value = []

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "canvas_sdk.v1.data.appointment.Appointment"
    ) as mock_appt_cls:
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.prefetch_related.return_value.get.return_value = patient
        mock_appt_cls.objects.filter.side_effect = RuntimeError("DB down")
        result = api.get_patient_detail()
    assert result[0].status_code == HTTPStatus.OK


# ---- get_patient_history ----

def test_get_patient_history_returns_list() -> None:
    api = _api(path_params={"patient_id": "patient-1"})
    with patch(
        "appointment_reminders.handlers.notification_api.fetch_patient_history",
        return_value=[{"campaign_type": "reminder"}],
    ):
        result = api.get_patient_history()
    assert result[0].status_code == HTTPStatus.OK


# ---- get_patient_appointments ----

def test_get_patient_appointments_combines_appointments_and_standalone_notes() -> None:
    api = _api(path_params={"patient_id": "patient-1"})

    appt = MagicMock()
    appt.id = "appt-1"
    appt.note_id = "note-A"
    appt.start_time = datetime(2026, 5, 1, tzinfo=timezone.utc)
    appt.description = "Visit"
    appt.note_type.id = "nt-1"
    appt.note_type.name = "Initial"
    appt.provider.first_name = "Sam"
    appt.provider.last_name = "Park"
    appt.status = "confirmed"

    standalone_note = MagicMock()
    standalone_note.id = "note-B"
    standalone_note.datetime_of_service = datetime(2026, 4, 1, tzinfo=timezone.utc)
    standalone_note.title = "Phone call"
    standalone_note.note_type_version.id = "ntv-1"
    standalone_note.note_type_version.name = "Phone"
    standalone_note.provider.first_name = "Dr."
    standalone_note.provider.last_name = "Lopez"

    with patch(
        "canvas_sdk.v1.data.appointment.Appointment"
    ) as mock_appt_cls, patch(
        "canvas_sdk.v1.data.note.Note"
    ) as mock_note_cls:
        # appointments
        mock_appt_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = MagicMock()
        mock_appt_cls.objects.filter.return_value.select_related.return_value.order_by.return_value.__iter__ = lambda self: iter([appt])
        # The slicing [:20] returns the same iterable
        appt_qs = mock_appt_cls.objects.filter.return_value.select_related.return_value.order_by.return_value
        appt_qs.__getitem__ = lambda self, k: [appt]

        # standalone notes — chain: filter().select_related().order_by().exclude()[:20]
        notes_qs = MagicMock()
        notes_qs.exclude.return_value = notes_qs
        notes_qs.__getitem__ = lambda self, k: [standalone_note]
        mock_note_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = notes_qs

        result = api.get_patient_appointments()
    assert result[0].status_code == HTTPStatus.OK


# ---- preview_template ----

def test_preview_template_rejects_when_required_fields_missing() -> None:
    api = _api(path_params={"patient_id": "patient-1"}, json_body={})
    result = api.preview_template()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_preview_template_returns_404_when_patient_missing() -> None:
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={"appointment_id": "appt-1", "campaign_type": "reminder"},
    )

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls:
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.get.side_effect = DNE
        result = api.preview_template()
    assert result[0].status_code == HTTPStatus.NOT_FOUND


def test_preview_template_returns_404_when_appointment_missing() -> None:
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={"appointment_id": "appt-1", "campaign_type": "reminder"},
    )
    patient = MagicMock()

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "canvas_sdk.v1.data.appointment.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=CampaignConfig(),
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_appt_cls.DoesNotExist = DNE
        mock_patient_cls.objects.get.return_value = patient
        mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.get.side_effect = DNE
        result = api.preview_template()
    assert result[0].status_code == HTTPStatus.NOT_FOUND


def test_preview_template_appointment_path_renders_globals_when_per_type_empty() -> None:
    """When global config is enabled but per-type returns empty, the endpoint
    falls back to global templates."""
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={"appointment_id": "appt-1", "campaign_type": "reminder"},
    )
    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"

    appt = MagicMock()
    appt.note_type = None
    appt.start_time = datetime(2026, 5, 1, tzinfo=timezone.utc)

    config = CampaignConfig(
        reminders_enabled=False,  # disabled → empty templates
        reminder_sms_template="GLOBAL SMS",
        reminder_email_template="GLOBAL EMAIL",
        reminder_channels=["sms"],
    )

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "canvas_sdk.v1.data.appointment.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.services.templates.get_template_variables",
        return_value={"patient_first_name": "Jane"},
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_appt_cls.DoesNotExist = DNE
        mock_patient_cls.objects.get.return_value = patient
        mock_appt_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = appt
        result = api.preview_template()
    assert result[0].status_code == HTTPStatus.OK


def test_preview_template_note_path() -> None:
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={"note_id": "note-1", "campaign_type": "telehealth"},
    )
    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"

    note = MagicMock()
    note.note_type_version = None
    note.provider = None
    note.location = None
    note.datetime_of_service = datetime(2026, 5, 1, tzinfo=timezone.utc)
    note.title = "Phone call"

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "canvas_sdk.v1.data.note.Note"
    ) as mock_note_cls, patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=CampaignConfig(),
    ), patch(
        "appointment_reminders.services.templates._get_org_variables",
        return_value={},
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_note_cls.DoesNotExist = DNE
        mock_patient_cls.objects.get.return_value = patient
        mock_note_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.get.return_value = note
        result = api.preview_template()
    assert result[0].status_code == HTTPStatus.OK


# ---- manual_send ----

def test_manual_send_rejects_when_no_channels() -> None:
    api = _api(path_params={"patient_id": "patient-1"}, json_body={"channels": []})
    result = api.manual_send()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_manual_send_returns_404_when_patient_missing() -> None:
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={"channels": ["sms"], "sms_content": "hi"},
    )

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls:
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.side_effect = DNE
        result = api.manual_send()
    assert result[0].status_code == HTTPStatus.NOT_FOUND


def test_manual_send_dispatches_delivery_for_appointment() -> None:
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={
            "channels": ["sms"],
            "sms_content": "hello",
            "email_content": "world",
            "appointment_id": "appt-1",
            "campaign_type": "manual",
        },
    )
    api.secrets = {}
    patient = MagicMock()

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.services.delivery.deliver_to_patient",
        return_value=([MagicMock()], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.services.history.log_delivery"
    ), patch(
        "appointment_reminders.handlers.notification_api.load_config", return_value=MagicMock()
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_name", return_value="Test-Line"
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_from_number",
        return_value="+15551112222",
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        result = api.manual_send()
    # Last response should be the JSON {results: [...]}
    assert result[-1].status_code == HTTPStatus.OK
    mock_deliver.assert_called_once()
    # Manual sends now go out from the patient's business-line number, not the global one.
    assert mock_deliver.call_args.kwargs["from_number"] == "+15551112222"


def test_manual_send_skips_metadata_for_note_only_send() -> None:
    """note_id provided but no appointment_id → effects list is dropped."""
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={
            "channels": ["sms"],
            "sms_content": "hi",
            "note_id": "note-1",
            "campaign_type": "manual",
        },
    )
    patient = MagicMock()

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.services.delivery.deliver_to_patient",
        return_value=(
            [MagicMock()],  # would-be metadata effects
            [MagicMock(channel="sms", success=True, error=None)],
        ),
    ), patch(
        "appointment_reminders.services.history.log_delivery"
    ), patch(
        "appointment_reminders.handlers.notification_api.load_config", return_value=MagicMock()
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_name", return_value="Test-Line"
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_from_number", return_value=""
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        result = api.manual_send()
    # First (and only) item should be the JSONResponse since metadata was dropped
    assert len(result) == 1
    assert result[-1].status_code == HTTPStatus.OK


# ---- get_patient_view_page ----

def test_get_patient_view_page_returns_html() -> None:
    api = _api()
    result = api.get_patient_view_page()
    assert result[0].status_code == HTTPStatus.OK


# ---- manual_send under LOCK_MESSAGE_TEMPLATES ----

def test_manual_send_refuses_unknown_campaign_while_locked() -> None:
    """A campaign with no stored template is refused rather than sent empty.

    Covers the retired "custom" type and any other unrecognized value posted
    straight to the endpoint.
    """
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={
            "channels": ["sms"],
            "sms_content": "anything at all",
            "appointment_id": "appt-1",
            "campaign_type": "custom",
        },
        secrets=_LOCKED,
    )
    with patch(
        "appointment_reminders.services.delivery.deliver_to_patient"
    ) as mock_deliver:
        result = api.manual_send()

    assert result[0].status_code == HTTPStatus.FORBIDDEN
    assert "LOCK_MESSAGE_TEMPLATES" in json.loads(result[0].content)["error"]
    mock_deliver.assert_not_called()


def test_manual_send_ignores_client_copy_while_locked() -> None:
    """The posted body is discarded and the stored template is re-rendered.

    This is the real boundary: the read-only textareas are only a convenience,
    and anything holding a staff session could POST here directly.
    """
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={
            "channels": ["sms", "email"],
            "sms_content": "SMUGGLED COPY",
            "email_content": "SMUGGLED COPY",
            "appointment_id": "appt-1",
            "campaign_type": "reminder",
        },
        secrets=_LOCKED,
    )
    patient = MagicMock()

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch.object(
        NotificationAPI,
        "_render_campaign_message",
        return_value=(None, {
            "sms_content": "approved sms",
            "email_content": "approved email",
            "channels": ["sms", "email"],
        }),
    ) as mock_render, patch(
        "appointment_reminders.services.delivery.deliver_to_patient",
        return_value=([], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.services.history.log_delivery"
    ), patch(
        "appointment_reminders.handlers.notification_api.load_config", return_value=MagicMock()
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_name", return_value=""
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_from_number",
        return_value="",
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        result = api.manual_send()

    assert result[-1].status_code == HTTPStatus.OK
    mock_render.assert_called_once()
    sent_sms, sent_email = mock_deliver.call_args[0][1], mock_deliver.call_args[0][2]
    assert sent_sms == "approved sms"
    assert sent_email == "approved email"
    assert "SMUGGLED" not in sent_sms and "SMUGGLED" not in sent_email


def test_manual_send_passes_client_copy_through_when_unlocked() -> None:
    """Without the secret, manual senders keep full control of the wording."""
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={
            "channels": ["sms"],
            "sms_content": "hand written",
            "email_content": "",
            "appointment_id": "appt-1",
            "campaign_type": "reminder",
        },
        secrets={},
    )
    patient = MagicMock()

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch.object(
        NotificationAPI, "_render_campaign_message"
    ) as mock_render, patch(
        "appointment_reminders.services.delivery.deliver_to_patient",
        return_value=([], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.services.history.log_delivery"
    ), patch(
        "appointment_reminders.handlers.notification_api.load_config", return_value=MagicMock()
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_name", return_value=""
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_from_number",
        return_value="",
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        result = api.manual_send()

    assert result[-1].status_code == HTTPStatus.OK
    mock_render.assert_not_called()
    assert mock_deliver.call_args[0][1] == "hand written"


# ---- patient panel rendering under LOCK_MESSAGE_TEMPLATES ----

def test_patient_view_never_offers_custom() -> None:
    """Custom was removed from the product; every send is template-backed."""
    for secrets in ({}, _LOCKED):
        html = _api(secrets=secrets).get_patient_view_page()[0].content
        if isinstance(html, bytes):
            html = html.decode()
        assert 'value="custom"' not in html


def test_patient_view_locks_boxes_when_locked() -> None:
    """The lock is baked into the markup, so there is no window after load in
    which the copy is editable."""
    html = _api(secrets=_LOCKED).get_patient_view_page()[0].content
    if isinstance(html, bytes):
        html = html.decode()

    assert '<textarea id="sms-textarea" rows="3" readonly' in html
    assert '<textarea id="email-textarea" rows="4" readonly' in html


def test_patient_view_leaves_composer_editable_when_unlocked() -> None:
    html = _api(secrets={}).get_patient_view_page()[0].content
    if isinstance(html, bytes):
        html = html.decode()

    assert "readonly" not in html


# ---- cross-patient scoping on preview / manual send ----

def test_preview_scopes_appointment_lookup_to_the_patient_in_the_path() -> None:
    """An appointment id belonging to another patient must not be renderable.

    The rendered message carries the appointment's time, provider, location and
    telehealth join link, so pairing patient A with patient B's appointment
    would deliver B's details to A. The lookup is filtered by the patient in the
    URL, which turns a mismatched pair into a 404.
    """
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={"appointment_id": "appt-belonging-to-someone-else", "campaign_type": "reminder"},
    )

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "canvas_sdk.v1.data.appointment.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=CampaignConfig(),
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_appt_cls.DoesNotExist = DNE
        # A filter scoped to this patient finds nothing for another patient's id.
        mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.get.side_effect = DNE
        result = api.preview_template()

    assert result[0].status_code == HTTPStatus.NOT_FOUND
    # The scoping must come from the query, not from a post-hoc comparison.
    assert mock_appt_cls.objects.filter.call_args.kwargs == {"patient__id": "patient-1"}


def test_preview_scopes_note_lookup_to_the_patient_in_the_path() -> None:
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={"note_id": "note-belonging-to-someone-else", "campaign_type": "reminder"},
    )

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "canvas_sdk.v1.data.note.Note"
    ) as mock_note_cls, patch(
        "appointment_reminders.handlers.notification_api.load_config",
        return_value=CampaignConfig(),
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_note_cls.DoesNotExist = DNE
        mock_note_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.get.side_effect = DNE
        result = api.preview_template()

    assert result[0].status_code == HTTPStatus.NOT_FOUND
    assert mock_note_cls.objects.filter.call_args.kwargs == {"patient__id": "patient-1"}


def test_manual_send_refuses_body_with_unresolved_placeholders() -> None:
    """A rendered body that still carries {{...}} must not reach the patient.
    This is the backstop for the standalone-note telehealth path, which used to
    deliver a literal "{{telehealth_link}}".
    """
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={
            "channels": ["sms"],
            "sms_content": "Join: {{telehealth_link}} now",
            "appointment_id": "appt-1",
            "campaign_type": "telehealth",
        },
    )
    patient = MagicMock()

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.services.delivery.deliver_to_patient"
    ) as mock_deliver, patch(
        "appointment_reminders.services.history.log_delivery"
    ), patch(
        "appointment_reminders.handlers.notification_api.load_config", return_value=MagicMock()
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        result = api.manual_send()

    assert result[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "telehealth_link" in json.loads(result[0].content)["error"]
    mock_deliver.assert_not_called()


def test_manual_send_ignores_placeholders_in_unselected_channel() -> None:
    """Only the channels actually being sent are checked, so a typo in an unused
    email template cannot block an SMS-only send.
    """
    api = _api(
        path_params={"patient_id": "patient-1"},
        json_body={
            "channels": ["sms"],
            "sms_content": "Your visit is August 5, 2026.",
            "email_content": "<p>{{broken_field}}</p>",
            "appointment_id": "appt-1",
            "campaign_type": "reminder",
        },
    )
    patient = MagicMock()

    class DNE(Exception):
        pass

    with patch(
        "canvas_sdk.v1.data.patient.Patient"
    ) as mock_patient_cls, patch(
        "appointment_reminders.services.delivery.deliver_to_patient",
        return_value=([MagicMock()], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.services.history.log_delivery"
    ), patch(
        "appointment_reminders.handlers.notification_api.load_config", return_value=MagicMock()
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_name",
        return_value="Test-Line",
    ), patch(
        "appointment_reminders.handlers.notification_api.get_business_line_from_number",
        return_value="+15551112222",
    ):
        mock_patient_cls.DoesNotExist = DNE
        mock_patient_cls.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
        result = api.manual_send()

    assert result[-1].status_code == HTTPStatus.OK
    mock_deliver.assert_called_once()
