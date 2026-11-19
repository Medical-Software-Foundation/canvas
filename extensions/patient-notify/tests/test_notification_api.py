"""Tests for notification API endpoints."""
import json
from http import HTTPStatus
from unittest.mock import MagicMock, PropertyMock

from pytest_mock import MockerFixture

from patient_notify.handlers.notification_api import NotificationAPI


def _make_api(secrets: dict | None = None) -> NotificationAPI:
    """Instantiate NotificationAPI without calling __init__."""
    handler = NotificationAPI.__new__(NotificationAPI)
    handler.event = MagicMock()
    handler.secrets = secrets or {}
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def test_api_get_admin_page() -> None:
    """Test getting admin page HTML."""
    api = _make_api()
    responses = api.get_admin_page()

    assert len(responses) == 1
    response = responses[0]
    assert b"Patient Notifications Admin" in response.content
    # Five tab labels
    assert b"switchTab('campaigns')" in response.content
    assert b"switchTab('visit-settings')" in response.content
    assert b"switchTab('variables')" in response.content
    assert b"switchTab('history')" in response.content
    assert b"switchTab('info')" in response.content
    # Old tabs removed
    assert b"switchTab('templates')" not in response.content
    assert b"switchTab('settings')" not in response.content
    # Campaigns is default active tab
    assert b'id="campaigns" class="tab-panel active"' in response.content
    # Campaigns tab contains global campaign config with accordion rows
    assert b"Event Alerts" in response.content
    assert b"Scheduled Notifications" in response.content
    assert b"global_alerts_container" in response.content
    assert b"global_scheduled_container" in response.content
    assert b"accordion-icon" in response.content
    assert b"active-toggle" in response.content
    # Variables tab contains custom variables
    assert b"custom_variables_container" in response.content
    assert b"Custom Variables" in response.content
    # Overrides tab contains visit types
    assert b"visit_types_container" in response.content
    # Info tab contains integration status
    assert b"integration_status" in response.content
    assert b"twilio_status_icon" in response.content
    assert b"sendgrid_status_icon" in response.content
    # Timing fields rendered by JS in the campaigns tab
    assert b"day_out_send_time" in response.content
    assert b"day_out_timezone" in response.content
    # Channel column in history table
    assert b"Channel" in response.content
    # No old layout artifacts
    assert b"sender_staff" not in response.content
    assert b"fallback_team" not in response.content
    assert b'id="clinic_name"' not in response.content
    assert b'id="clinic_phone"' not in response.content
    # Template variables in JS
    assert b"patient_preferred_name" in response.content
    assert b"location_full_name" in response.content
    assert b"organization_name" in response.content
    assert b"organization_full_name" in response.content
    assert b"organization_short_name" in response.content
    assert b"organization_address" in response.content
    assert b"organization_phone" in response.content
    assert b"telehealth_link" in response.content
    assert b"minutes_until" in response.content
    # Validation support
    assert b"validateSingleCampaign" in response.content
    # Toggle and channel support
    assert b"active-toggle" in response.content
    assert b"channel-toggle" in response.content


def test_api_admin_page_gather_single_campaign_no_saved_seed() -> None:
    """gatherSingleCampaign must not seed entry from savedNoteTypeCampaigns. Only
    the allPatches accumulator should carry saved fields so successive campaigns
    do not overwrite each other's UI changes."""
    api = _make_api()
    response = api.get_admin_page()[0]
    assert b"var entry = Object.assign({}, saved)" not in response.content, (
        "gatherSingleCampaign seeds entry from saved, causing later campaigns to "
        "overwrite earlier campaigns' UI changes. Remove the seed."
    )


def test_api_get_config(mocker: MockerFixture) -> None:
    """Test getting campaign configuration."""
    mock_config = MagicMock()
    mock_config.to_dict.return_value = {
        "confirmation_enabled": True,
        "telehealth_enabled": False,
    }
    mocker.patch("patient_notify.handlers.notification_api.load_config", return_value=mock_config)

    api = _make_api()
    responses = api.get_config()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK


def test_api_save_config(mocker: MockerFixture) -> None:
    """Test saving campaign configuration."""
    mock_request = MagicMock()
    mock_request.json.return_value = {
        "confirmation_enabled": False,
        "telehealth_enabled": True,
        "custom_variables": {"org": "Acme"},
    }

    mocker.patch("patient_notify.handlers.notification_api.save_config")
    mocker.patch("patient_notify.handlers.notification_api.CampaignConfig")

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.save_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK


def test_api_save_config_invalid_keys(mocker: MockerFixture) -> None:
    """Test saving config with unexpected keys still succeeds due to filtering."""
    mock_request = MagicMock()
    mock_request.json.return_value = {
        "confirmation_enabled": True,
        "bogus_field": "should be filtered",
    }

    mock_save = mocker.patch("patient_notify.handlers.notification_api.save_config")

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.save_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK
    mock_save.assert_called_once()


def test_api_patch_config(mocker: MockerFixture) -> None:
    """Test partial config update via PATCH endpoint."""
    mock_request = MagicMock()
    mock_request.json.return_value = {"clinic_name": "Patched Clinic"}

    mock_patch = mocker.patch("patient_notify.handlers.notification_api.patch_config")

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.patch_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK
    mock_patch.assert_called_once_with({"clinic_name": "Patched Clinic"})


def test_api_patch_config_invalid(mocker: MockerFixture) -> None:
    """Test PATCH endpoint returns 400 on TypeError."""
    mock_request = MagicMock()
    mock_request.json.return_value = {"clinic_name": "Test"}

    mocker.patch(
        "patient_notify.handlers.notification_api.patch_config",
        side_effect=TypeError("bad field"),
    )

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.patch_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_api_get_global_history(mocker: MockerFixture) -> None:
    """Test getting global notification history."""
    mock_cache = MagicMock()
    history_data = [
        {
            "timestamp": "2026-02-12T12:00:00Z",
            "patient_id": "patient1",
            "campaign_type": "confirmation",
            "channel": "sms",
            "status": "delivered",
        },
        {
            "timestamp": "2026-02-12T11:00:00Z",
            "patient_id": "patient2",
            "campaign_type": "reminder",
            "channel": "email",
            "status": "delivered",
        },
    ]
    mock_cache.get.return_value = json.dumps(history_data)
    mocker.patch("patient_notify.handlers.notification_api.get_cache", return_value=mock_cache)

    api = _make_api()
    responses = api.get_global_history()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK


def test_api_get_patient_history(mocker: MockerFixture) -> None:
    """Test getting patient-specific notification history."""
    mock_cache = MagicMock()
    history_data = [
        {
            "timestamp": "2026-02-12T12:00:00Z",
            "patient_id": "patient123",
            "campaign_type": "confirmation",
            "channel": "portal",
            "status": "delivered",
        }
    ]
    mock_cache.get.return_value = json.dumps(history_data)
    mocker.patch("patient_notify.handlers.notification_api.get_cache", return_value=mock_cache)

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.get_patient_history()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK
    mock_cache.get.assert_called_once_with("cr:log:patient123", default="[]")


def test_api_get_patient_view_page() -> None:
    """Test getting patient view HTML page."""
    api = _make_api()
    responses = api.get_patient_view_page()

    assert len(responses) == 1
    response = responses[0]
    assert b"Send Notification" in response.content
    assert b"Notification History" in response.content
    assert b"loadHistory" in response.content
    assert b"toggleSection" in response.content
    assert b"delivery_alert" in response.content
    assert b"banner-warning" in response.content
    assert b"blockedCodes" in response.content


def test_api_empty_history(mocker: MockerFixture) -> None:
    """Test getting history when cache is empty."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.handlers.notification_api.get_cache", return_value=mock_cache)

    api = _make_api()
    responses = api.get_global_history()

    assert len(responses) == 1


def test_api_get_note_types(mocker: MockerFixture) -> None:
    """Test getting schedulable note types."""
    mock_nt1 = MagicMock()
    mock_nt1.id = "nt-1"
    mock_nt1.name = "Office Visit"
    mock_nt1.is_telehealth = False

    mock_nt2 = MagicMock()
    mock_nt2.id = "nt-2"
    mock_nt2.name = "Telehealth Visit"
    mock_nt2.is_telehealth = True

    mock_qs = MagicMock()
    mock_qs.order_by.return_value = [mock_nt1, mock_nt2]

    mock_note_type = mocker.patch("patient_notify.handlers.notification_api.NoteType", create=True)
    mock_note_type.objects.filter.return_value = mock_qs

    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.note": MagicMock(NoteType=mock_note_type)},
    )

    api = _make_api()
    responses = api.get_note_types()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert len(data) == 2
    assert data[0]["id"] == "nt-1"
    assert data[0]["name"] == "Office Visit"
    assert data[1]["is_telehealth"] is True


def test_api_save_config_with_note_type_campaigns(mocker: MockerFixture) -> None:
    """Test saving config that includes note_type_campaigns."""
    mock_request = MagicMock()
    mock_request.json.return_value = {
        "note_type_campaigns": {
            "nt-1": {
                "note_type_id": "nt-1",
                "note_type_name": "Office Visit",
                "reminder_override": True,
                "reminder_intervals": [4320],
                "reminder_sms_template": "Your appt is coming up",
                "reminder_email_template": "<p>Your appt is coming up</p>",
                "reminder_channels": ["sms", "email"],
            }
        },
        "custom_variables": {"office_hours": "9am-5pm"},
    }

    mock_save = mocker.patch("patient_notify.handlers.notification_api.save_config")

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.save_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK
    mock_save.assert_called_once()
    saved_config = mock_save.call_args[0][0]
    assert "nt-1" in saved_config.note_type_campaigns


def test_api_get_global_history_with_patient_names(mocker: MockerFixture) -> None:
    """Test global history enriches entries with patient names."""
    mock_cache = MagicMock()
    history_data = [
        {
            "timestamp": "2026-02-12T12:00:00Z",
            "patient_id": "patient1",
            "campaign_type": "reminder",
            "channel": "sms",
            "status": "delivered",
        },
    ]
    mock_cache.get.return_value = json.dumps(history_data)
    mocker.patch("patient_notify.handlers.notification_api.get_cache", return_value=mock_cache)

    mock_patient = MagicMock()
    mock_patient.id = "patient1"
    mock_patient.first_name = "Jane"
    mock_patient.last_name = "Doe"

    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.filter.return_value.only.return_value = [mock_patient]
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    api = _make_api()
    responses = api.get_global_history()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert data[0]["patient_first_name"] == "Jane"
    assert data[0]["patient_last_name"] == "Doe"


def test_api_integration_status_all_configured() -> None:
    """Test integration status when all keys are configured."""
    secrets = {
        "twilio-account-sid": "AC123",
        "twilio-auth-token": "token",
        "twilio-phone-number": "+1555",
        "sendgrid-api-key": "SG.test",
        "sendgrid-from-email": "noreply@clinic.com",
    }
    api = _make_api(secrets=secrets)
    responses = api.get_integration_status()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert data["twilio_configured"] is True
    assert data["sendgrid_configured"] is True


def test_api_integration_status_none_configured() -> None:
    """Test integration status when no keys are configured."""
    api = _make_api(secrets={})
    responses = api.get_integration_status()

    data = json.loads(responses[0].content)
    assert data["twilio_configured"] is False
    assert data["sendgrid_configured"] is False


def test_api_integration_status_partial() -> None:
    """Test integration status when only Twilio is configured."""
    secrets = {
        "twilio-account-sid": "AC123",
        "twilio-auth-token": "token",
        "twilio-phone-number": "+1555",
    }
    api = _make_api(secrets=secrets)
    responses = api.get_integration_status()

    data = json.loads(responses[0].content)
    assert data["twilio_configured"] is True
    assert data["sendgrid_configured"] is False


def test_api_save_config_rejects_xss_custom_variable_key(mocker: MockerFixture) -> None:
    """Test that custom variable keys with special characters are rejected."""
    mock_request = MagicMock()
    mock_request.json.return_value = {
        "custom_variables": {"x'+alert(1)+'": "malicious"},
    }

    mock_save = mocker.patch("patient_notify.handlers.notification_api.save_config")

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.save_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert "Invalid custom variable key" in responses[0].content.decode()
    mock_save.assert_not_called()


def test_api_save_config_accepts_valid_custom_variable_keys(mocker: MockerFixture) -> None:
    """Test that alphanumeric and underscore keys are accepted."""
    mock_request = MagicMock()
    mock_request.json.return_value = {
        "custom_variables": {"clinic_name": "Acme", "phone2": "555-1234"},
    }

    mocker.patch("patient_notify.handlers.notification_api.save_config")

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.save_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK


def test_api_patch_config_rejects_negative_reminder_intervals(mocker: MockerFixture) -> None:
    """Test PATCH endpoint rejects negative reminder_intervals."""
    mock_request = MagicMock()
    mock_request.json.return_value = {"reminder_intervals": [-60]}

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.patch_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert b"non-negative" in responses[0].content


def test_api_patch_config_accepts_valid_reminder_intervals(mocker: MockerFixture) -> None:
    """Test PATCH endpoint accepts valid reminder_intervals including 0."""
    mock_request = MagicMock()
    mock_request.json.return_value = {"reminder_intervals": [0, 1440, 10080]}

    mocker.patch("patient_notify.handlers.notification_api.patch_config")

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.patch_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK


def test_api_patch_config_rejects_negative_note_type_reminder_intervals(mocker: MockerFixture) -> None:
    """Test PATCH endpoint rejects negative reminder intervals inside note_type_campaigns."""
    mock_request = MagicMock()
    mock_request.json.return_value = {
        "note_type_campaigns": {
            "nt-1": {"reminder_intervals": [-10]},
        }
    }

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.patch_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_api_admin_page_has_retry_ui() -> None:
    """Test admin page HTML contains retry modal, filter checkbox, and retry button CSS."""
    api = _make_api()
    responses = api.get_admin_page()

    response = responses[0]
    assert b"retry_modal" in response.content
    assert b"history_filter_failed" in response.content
    assert b"btn btn-default btn-sm" in response.content


def test_api_patient_view_has_send_section() -> None:
    """Test patient view HTML contains manual send UI elements."""
    api = _make_api()
    responses = api.get_patient_view_page()

    response = responses[0]
    assert b"Send Notification" in response.content
    assert b"send_appointment" in response.content
    assert b"send_campaign" in response.content
    assert b"send_channel" in response.content
    assert b"preview_content" in response.content
    assert b"loadAppointments" in response.content
    assert b"sendNotification" in response.content
    assert b"fetchPreview" in response.content


def test_api_get_patient_appointments(mocker: MockerFixture) -> None:
    """Test getting patient appointments for manual send picker."""
    from datetime import datetime, timezone

    mock_appt = MagicMock()
    mock_appt.id = "appt-1"
    mock_appt.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    mock_appt.status = "booked"
    mock_appt.provider = MagicMock()
    mock_appt.provider.first_name = "Dr."
    mock_appt.provider.last_name = "Smith"
    mock_appt.note_type = MagicMock()
    mock_appt.note_type.name = "Office Visit"
    mock_appt.note_type.is_telehealth = False

    mock_qs = MagicMock()
    mock_qs.select_related.return_value = mock_qs
    mock_qs.order_by.return_value = [mock_appt]

    mock_appointment_cls = MagicMock()
    mock_appointment_cls.objects.filter.return_value = mock_qs
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appointment_cls)},
    )
    mocker.patch("django.utils.timezone.now")

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.get_patient_appointments()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert len(data) == 1
    assert data[0]["id"] == "appt-1"
    assert data[0]["note_type_name"] == "Office Visit"
    assert data[0]["provider_name"] == "Dr. Smith"
    assert data[0]["is_telehealth"] is False


def test_api_preview_notification(mocker: MockerFixture) -> None:
    """Test previewing a notification returns rendered templates."""
    mock_patient = MagicMock()
    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.get.return_value = mock_patient
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appointment = MagicMock()
    mock_appointment.note_type = MagicMock()
    mock_appointment.note_type.id = "nt-1"
    mock_appointment_cls = MagicMock()
    mock_appointment_cls.objects.select_related.return_value.get.return_value = mock_appointment
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appointment_cls)},
    )

    mock_config = MagicMock()
    mocker.patch("patient_notify.services.config.load_config", return_value=mock_config)
    mocker.patch(
        "patient_notify.services.config.resolve_templates",
        return_value=("SMS: Hello {{patient_first_name}}", "Email: Hello"),
    )
    mocker.patch(
        "patient_notify.services.templates.get_template_variables",
        return_value={"patient_first_name": "Jane"},
    )
    mocker.patch(
        "patient_notify.services.templates.render_template",
        side_effect=lambda tpl, _vars: tpl.replace("{{patient_first_name}}", "Jane"),
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {"appointment_id": "appt-1", "campaign_type": "confirmation"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.preview_notification()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert "SMS: Hello Jane" in data["sms_content"]


def test_api_preview_notification_missing_params() -> None:
    """Test preview endpoint returns 400 when params are missing."""
    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.preview_notification()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_api_send_notification(mocker: MockerFixture) -> None:
    """Test manual send endpoint delivers and logs."""
    from patient_notify.services.delivery import DeliveryResult

    mock_patient = MagicMock()
    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.prefetch_related.return_value.get.return_value = mock_patient
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appointment = MagicMock()
    mock_appointment_cls = MagicMock()
    mock_appointment_cls.objects.select_related.return_value.get.return_value = mock_appointment
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appointment_cls)},
    )

    mock_config = MagicMock()
    mocker.patch("patient_notify.services.config.load_config", return_value=mock_config)
    mock_log = mocker.patch("patient_notify.services.history.log_delivery_to_cache")

    mock_result = DeliveryResult(success=True, channel="sms", error=None)
    mocker.patch.object(
        NotificationAPI, "_send_single_notification", return_value=mock_result,
    )

    secrets = {
        "twilio-account-sid": "AC123",
        "twilio-auth-token": "token",
        "twilio-phone-number": "+1555",
    }
    api = _make_api(secrets=secrets)
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {
        "appointment_id": "appt-1",
        "campaign_type": "confirmation",
        "channel": "sms",
    }
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.send_notification()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert data["result"]["success"] is True
    mock_log.assert_called_once()


def test_api_send_notification_invalid_channel() -> None:
    """Test send endpoint rejects invalid channel."""
    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {
        "appointment_id": "appt-1",
        "campaign_type": "confirmation",
        "channel": "fax",
    }
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.send_notification()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_api_send_notification_missing_params() -> None:
    """Test send endpoint returns 400 when params are missing."""
    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {"appointment_id": "appt-1"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.send_notification()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_api_save_config_type_error(mocker: MockerFixture) -> None:
    """Test save_config returns 400 when CampaignConfig.from_dict raises TypeError."""
    mock_request = MagicMock()
    mock_request.json.return_value = {"bad": "data"}

    mocker.patch(
        "patient_notify.handlers.notification_api.CampaignConfig.from_dict",
        side_effect=TypeError("unexpected keyword argument"),
    )

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.save_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert b"Invalid configuration" in responses[0].content


def test_api_patch_config_rejects_invalid_custom_variable_keys(mocker: MockerFixture) -> None:
    """Test PATCH endpoint rejects custom variable keys with special characters."""
    mock_request = MagicMock()
    mock_request.json.return_value = {"custom_variables": {"bad-key!": "value"}}

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.patch_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert b"Invalid custom variable key" in responses[0].content


def test_api_patch_config_rejects_invalid_send_time(mocker: MockerFixture) -> None:
    """Test PATCH endpoint rejects malformed day_out_send_time."""
    mock_request = MagicMock()
    mock_request.json.return_value = {"day_out_send_time": "25:99"}

    api = _make_api()
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.patch_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert b"HH:MM" in responses[0].content


def test_api_get_patient_detail(mocker: MockerFixture) -> None:
    """Test patient detail endpoint returns patient info and next appointment."""
    from datetime import date, datetime, timezone

    mock_telecom_phone = MagicMock()
    mock_telecom_phone.system = "phone"
    mock_telecom_phone.value = "555-1234"
    mock_telecom_phone.has_consent = True
    mock_telecom_phone.opted_out = False

    mock_telecom_email = MagicMock()
    mock_telecom_email.system = "email"
    mock_telecom_email.value = "jane@test.com"
    mock_telecom_email.has_consent = True
    mock_telecom_email.opted_out = False

    mock_addr = MagicMock()
    mock_addr.state = "active"
    mock_addr.city = "Springfield"
    mock_addr.state_code = "IL"
    mock_addr.use = "home"

    mock_patient = MagicMock()
    mock_patient.id = "p1"
    mock_patient.first_name = "Jane"
    mock_patient.last_name = "Doe"
    mock_patient.nickname = ""
    mock_patient.mrn = "MRN001"
    mock_patient.birth_date = date(1990, 5, 15)
    mock_patient.active = True
    mock_patient.deceased = False
    mock_patient.telecom.all.return_value = [mock_telecom_phone, mock_telecom_email]
    mock_patient.addresses.all.return_value = [mock_addr]

    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.prefetch_related.return_value.get.return_value = mock_patient
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appt = MagicMock()
    mock_appt.start_time = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    mock_appt.status = "booked"
    mock_appt_cls = MagicMock()
    mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = mock_appt
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appt_cls)},
    )
    mocker.patch("django.utils.timezone.now")

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "p1"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.get_patient_detail()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert data["first_name"] == "Jane"
    assert data["phone"] == "555-1234"
    assert data["email"] == "jane@test.com"
    assert data["address"] == "Springfield, IL"
    assert data["next_appointment"] is not None


def test_api_get_patient_detail_not_found(mocker: MockerFixture) -> None:
    """Test patient detail returns 404 when patient does not exist."""
    mock_patient_cls = MagicMock()
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_patient_cls.objects.prefetch_related.return_value.get.side_effect = (
        mock_patient_cls.DoesNotExist()
    )
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "gone"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.get_patient_detail()

    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_api_send_single_notification_sms(mocker: MockerFixture) -> None:
    """Test _send_single_notification sends SMS when credentials are present."""
    from patient_notify.services.delivery import DeliveryResult

    mock_contact = MagicMock()
    mock_contact.value = "+15551234567"

    mock_patient = MagicMock()
    mock_patient.telecom.filter.return_value = [mock_contact]

    mock_appointment = MagicMock()
    mock_appointment.note_type = MagicMock()
    mock_appointment.note_type.id = "nt-1"

    mock_config = MagicMock()

    mocker.patch(
        "patient_notify.services.config.resolve_templates",
        return_value=("SMS text", "Email text"),
    )
    mocker.patch(
        "patient_notify.services.templates.get_template_variables",
        return_value={"patient_first_name": "Jane"},
    )
    mocker.patch(
        "patient_notify.services.templates.render_template",
        return_value="Rendered SMS",
    )
    expected_result = DeliveryResult(success=True, channel="sms")
    mocker.patch(
        "patient_notify.services.delivery._send_sms",
        return_value=expected_result,
    )
    mocker.patch("patient_notify.services.delivery._has_direct_sms_keys", return_value=True)
    mocker.patch("patient_notify.services.delivery._normalize_phone_e164", return_value="+15551234567")

    secrets = {
        "twilio-account-sid": "AC123",
        "twilio-auth-token": "token",
        "twilio-phone-number": "+15550000000",
    }
    api = _make_api(secrets=secrets)
    result = api._send_single_notification(mock_patient, mock_appointment, "confirmation", "sms", mock_config)

    assert result.success is True
    assert result.channel == "sms"


def test_api_send_single_notification_email(mocker: MockerFixture) -> None:
    """Test _send_single_notification sends email when credentials are present."""
    from patient_notify.services.delivery import DeliveryResult

    mock_contact = MagicMock()
    mock_contact.value = "jane@test.com"

    mock_patient = MagicMock()
    mock_patient.telecom.filter.return_value = [mock_contact]

    mock_appointment = MagicMock()
    mock_appointment.note_type = MagicMock()
    mock_appointment.note_type.id = "nt-1"

    mock_config = MagicMock()

    mocker.patch(
        "patient_notify.services.config.resolve_templates",
        return_value=("SMS text", "Email text"),
    )
    mocker.patch(
        "patient_notify.services.templates.get_template_variables",
        return_value={"patient_first_name": "Jane"},
    )
    mocker.patch(
        "patient_notify.services.templates.render_template",
        return_value="Rendered email",
    )
    expected_result = DeliveryResult(success=True, channel="email")
    mocker.patch(
        "patient_notify.services.delivery._send_email",
        return_value=expected_result,
    )
    mocker.patch("patient_notify.services.delivery._has_direct_email_keys", return_value=True)
    mocker.patch("patient_notify.services.delivery._plaintext_to_html", return_value="<p>Rendered</p>")

    secrets = {
        "sendgrid-api-key": "SG.test",
        "sendgrid-from-email": "noreply@clinic.com",
    }
    api = _make_api(secrets=secrets)
    result = api._send_single_notification(mock_patient, mock_appointment, "confirmation", "email", mock_config)

    assert result.success is True
    assert result.channel == "email"


def test_api_send_single_notification_no_credentials(mocker: MockerFixture) -> None:
    """Test _send_single_notification returns failure when credentials are missing."""
    mock_patient = MagicMock()
    mock_appointment = MagicMock()
    mock_appointment.note_type = MagicMock()
    mock_appointment.note_type.id = "nt-1"
    mock_config = MagicMock()

    mocker.patch(
        "patient_notify.services.config.resolve_templates",
        return_value=("SMS", "Email"),
    )
    mocker.patch(
        "patient_notify.services.templates.get_template_variables",
        return_value={},
    )
    mocker.patch(
        "patient_notify.services.templates.render_template",
        return_value="Rendered",
    )
    mocker.patch("patient_notify.services.delivery._has_direct_sms_keys", return_value=False)
    mocker.patch("patient_notify.services.delivery._has_direct_email_keys", return_value=False)

    api = _make_api(secrets={})
    result = api._send_single_notification(mock_patient, mock_appointment, "confirmation", "sms", mock_config)

    assert result.success is False
    assert "credentials not configured" in result.error


def test_api_send_single_notification_sms_no_phone(mocker: MockerFixture) -> None:
    """Test _send_single_notification returns failure when patient has no valid phone."""
    from patient_notify.services.delivery import DeliveryResult

    mock_patient = MagicMock()
    mock_patient.telecom.filter.return_value = []

    mock_appointment = MagicMock()
    mock_appointment.note_type = MagicMock()
    mock_appointment.note_type.id = "nt-1"
    mock_config = MagicMock()

    mocker.patch(
        "patient_notify.services.config.resolve_templates",
        return_value=("SMS", "Email"),
    )
    mocker.patch("patient_notify.services.templates.get_template_variables", return_value={})
    mocker.patch("patient_notify.services.templates.render_template", return_value="Rendered")
    mocker.patch("patient_notify.services.delivery._has_direct_sms_keys", return_value=True)

    secrets = {
        "twilio-account-sid": "AC123",
        "twilio-auth-token": "token",
        "twilio-phone-number": "+15550000000",
    }
    api = _make_api(secrets=secrets)
    result = api._send_single_notification(mock_patient, mock_appointment, "confirmation", "sms", mock_config)

    assert result.success is False
    assert "no valid phone" in result.error


def test_api_send_single_notification_email_no_address(mocker: MockerFixture) -> None:
    """Test _send_single_notification returns failure when patient has no email."""
    mock_patient = MagicMock()
    mock_patient.telecom.filter.return_value = []

    mock_appointment = MagicMock()
    mock_appointment.note_type = MagicMock()
    mock_appointment.note_type.id = "nt-1"
    mock_config = MagicMock()

    mocker.patch(
        "patient_notify.services.config.resolve_templates",
        return_value=("SMS", "Email"),
    )
    mocker.patch("patient_notify.services.templates.get_template_variables", return_value={})
    mocker.patch("patient_notify.services.templates.render_template", return_value="Rendered")
    mocker.patch("patient_notify.services.delivery._has_direct_email_keys", return_value=True)

    secrets = {
        "sendgrid-api-key": "SG.test",
        "sendgrid-from-email": "noreply@clinic.com",
    }
    api = _make_api(secrets=secrets)
    result = api._send_single_notification(mock_patient, mock_appointment, "confirmation", "email", mock_config)

    assert result.success is False
    assert "no email address" in result.error


def test_api_retry_notification(mocker: MockerFixture) -> None:
    """Test retry endpoint resends a failed notification."""
    from patient_notify.services.delivery import DeliveryResult

    mock_patient = MagicMock()
    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.prefetch_related.return_value.get.return_value = mock_patient
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appointment = MagicMock()
    mock_appointment_cls = MagicMock()
    mock_appointment_cls.objects.select_related.return_value.get.return_value = mock_appointment
    mock_appointment_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appointment_cls)},
    )

    mock_config = MagicMock()
    mocker.patch("patient_notify.services.config.load_config", return_value=mock_config)

    history_entries = [
        {
            "channel": "sms",
            "campaign_type": "confirmation",
            "appointment_id": "appt-1",
            "status": "failed",
        }
    ]
    mocker.patch(
        "patient_notify.services.history.get_patient_log",
        return_value=list(reversed(history_entries)),
    )
    mock_log = mocker.patch("patient_notify.services.history.log_delivery_to_cache")

    mock_result = DeliveryResult(success=True, channel="sms", error=None)
    mocker.patch.object(
        NotificationAPI, "_send_single_notification", return_value=mock_result,
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {"log_index": 0}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.retry_notification()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert data["result"]["success"] is True
    mock_log.assert_called_once()


def test_api_retry_notification_missing_log_index() -> None:
    """Test retry endpoint returns 400 when log_index is missing."""
    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.retry_notification()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert b"log_index" in responses[0].content


def test_api_retry_notification_invalid_log_index(mocker: MockerFixture) -> None:
    """Test retry endpoint returns 400 when log_index is out of range."""
    mocker.patch(
        "patient_notify.services.history.get_patient_log",
        return_value=[{"channel": "sms", "campaign_type": "confirmation"}],
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {"log_index": 5}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.retry_notification()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert b"Invalid log_index" in responses[0].content


def test_api_retry_notification_patient_not_found(mocker: MockerFixture) -> None:
    """Test retry endpoint returns 404 when patient does not exist."""
    mocker.patch(
        "patient_notify.services.history.get_patient_log",
        return_value=[{"channel": "sms", "campaign_type": "confirmation", "appointment_id": "a1"}],
    )

    mock_patient_cls = MagicMock()
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_patient_cls.objects.prefetch_related.return_value.get.side_effect = (
        mock_patient_cls.DoesNotExist()
    )
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "gone"}
    mock_request.json.return_value = {"log_index": 0}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.retry_notification()

    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_api_retry_notification_appointment_not_found(mocker: MockerFixture) -> None:
    """Test retry endpoint returns 404 when appointment does not exist."""
    mocker.patch(
        "patient_notify.services.history.get_patient_log",
        return_value=[{"channel": "sms", "campaign_type": "confirmation", "appointment_id": "a1"}],
    )

    mock_patient_cls = MagicMock()
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_patient_cls.objects.prefetch_related.return_value.get.return_value = MagicMock()
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appt_cls = MagicMock()
    mock_appt_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_appt_cls.objects.select_related.return_value.get.side_effect = (
        mock_appt_cls.DoesNotExist()
    )
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appt_cls)},
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {"log_index": 0}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.retry_notification()

    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_api_preview_notification_patient_not_found(mocker: MockerFixture) -> None:
    """Test preview endpoint returns 404 when patient does not exist."""
    mock_patient_cls = MagicMock()
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_patient_cls.objects.get.side_effect = mock_patient_cls.DoesNotExist()
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "gone"}
    mock_request.json.return_value = {"appointment_id": "a1", "campaign_type": "confirmation"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.preview_notification()

    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_api_preview_notification_appointment_not_found(mocker: MockerFixture) -> None:
    """Test preview endpoint returns 404 when appointment does not exist."""
    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.get.return_value = MagicMock()
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appt_cls = MagicMock()
    mock_appt_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_appt_cls.objects.select_related.return_value.get.side_effect = (
        mock_appt_cls.DoesNotExist()
    )
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appt_cls)},
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {"appointment_id": "gone", "campaign_type": "confirmation"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.preview_notification()

    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_api_preview_notification_fallback_templates(mocker: MockerFixture) -> None:
    """Test preview uses resolve_templates to get global defaults regardless of enabled state."""
    mock_patient = MagicMock()
    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.get.return_value = mock_patient
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appointment = MagicMock()
    mock_appointment.note_type = MagicMock()
    mock_appointment.note_type.id = "nt-1"
    mock_appointment_cls = MagicMock()
    mock_appointment_cls.objects.select_related.return_value.get.return_value = mock_appointment
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appointment_cls)},
    )

    mock_config = MagicMock()
    mocker.patch("patient_notify.services.config.load_config", return_value=mock_config)
    mocker.patch(
        "patient_notify.services.config.resolve_templates",
        return_value=("Global SMS", "Global Email"),
    )
    mocker.patch(
        "patient_notify.services.templates.get_template_variables",
        return_value={"patient_first_name": "Jane"},
    )
    mocker.patch(
        "patient_notify.services.templates.render_template",
        side_effect=lambda tpl, _vars: tpl,
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {"appointment_id": "appt-1", "campaign_type": "confirmation"}
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.preview_notification()

    assert len(responses) == 1
    data = json.loads(responses[0].content)
    assert data["sms_content"] == "Global SMS"
    assert data["email_content"] == "Global Email"


def test_api_send_notification_patient_not_found(mocker: MockerFixture) -> None:
    """Test send endpoint returns 404 when patient does not exist."""
    mock_patient_cls = MagicMock()
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_patient_cls.objects.prefetch_related.return_value.get.side_effect = (
        mock_patient_cls.DoesNotExist()
    )
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "gone"}
    mock_request.json.return_value = {
        "appointment_id": "appt-1",
        "campaign_type": "confirmation",
        "channel": "sms",
    }
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.send_notification()

    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_api_send_notification_appointment_not_found(mocker: MockerFixture) -> None:
    """Test send endpoint returns 404 when appointment does not exist."""
    mock_patient_cls = MagicMock()
    mock_patient_cls.objects.prefetch_related.return_value.get.return_value = MagicMock()
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls)},
    )

    mock_appt_cls = MagicMock()
    mock_appt_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_appt_cls.objects.select_related.return_value.get.side_effect = (
        mock_appt_cls.DoesNotExist()
    )
    mocker.patch.dict(
        "sys.modules",
        {"canvas_sdk.v1.data.appointment": MagicMock(Appointment=mock_appt_cls)},
    )

    api = _make_api()
    mock_request = MagicMock()
    mock_request.path_params = {"patient_id": "patient123"}
    mock_request.json.return_value = {
        "appointment_id": "gone",
        "campaign_type": "confirmation",
        "channel": "sms",
    }
    type(api).request = PropertyMock(return_value=mock_request)
    responses = api.send_notification()

    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_api_reset_config(mocker: MockerFixture) -> None:
    """Test reset config endpoint deletes cached config."""
    mock_cache = MagicMock()
    mocker.patch("patient_notify.handlers.notification_api.get_cache", return_value=mock_cache)

    api = _make_api()
    responses = api.reset_config_endpoint()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.OK
    mock_cache.delete.assert_called_once_with("cr:config")


def test_api_admin_page_timezone_in_campaigns_tab() -> None:
    """Test timezone dropdown is rendered by JS in the campaigns tab, not in a separate settings tab."""
    api = _make_api()
    responses = api.get_admin_page()

    content = responses[0].content.decode()
    # Timezone is rendered inside the reminders accordion by renderCampaignAccordions
    assert "day_out_timezone" in content
    assert "renderCampaignAccordions" in content
    # Old settings tab and save function are gone
    assert 'id="settings"' not in content
    assert "saveSettings" not in content


def test_api_admin_page_cv_key_validation_rejects_invalid_chars() -> None:
    """validateCvKey must show an error for invalid chars, not silently sanitize."""
    api = _make_api()
    response = api.get_admin_page()[0]
    # The silent-sanitize path must be gone
    assert b"keyInput.value = sanitized" not in response.content, (
        "validateCvKey silently replaces invalid input. "
        "It must show an error message instead."
    )
    # There must be an error message string for invalid characters
    assert b"Only letters, numbers, and underscores" in response.content


def test_api_admin_page_cv_value_has_format_hint() -> None:
    """The custom variable value input must have a descriptive placeholder and hint text."""
    api = _make_api()
    response = api.get_admin_page()[0]
    assert b"replacement text" in response.content


def test_api_admin_page_view_profile_is_btn_default() -> None:
    """View Profile must use btn-default class so it renders as a button, not a text link."""
    api = _make_api()
    response = api.get_admin_page()[0]
    # bare btn class for an href pointing to /patient/ must not appear
    assert b'"btn" href="/patient/' not in response.content, (
        "View Profile anchor uses bare btn class (renders as text link). "
        "It must use btn btn-default."
    )
