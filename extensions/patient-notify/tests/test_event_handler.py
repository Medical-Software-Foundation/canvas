"""Tests for appointment event handler."""
from unittest.mock import MagicMock

from pytest_mock import MockerFixture
from canvas_sdk.events import EventType

from patient_notify.handlers.event_handler import AppointmentEventHandler
from patient_notify.services.delivery import DeliveryResult


def _make_handler(event: MagicMock) -> AppointmentEventHandler:
    """Instantiate handler without calling __init__."""
    handler = AppointmentEventHandler.__new__(AppointmentEventHandler)
    handler.event = event
    handler.secrets = {"twilio-account-sid": "AC123"}
    handler.environment = {}
    return handler


def _patch_campaign_config(mocker: MockerFixture, enabled: bool, campaign_type: str = "confirmation") -> MagicMock:
    """Patch get_effective_campaign_config to return controlled values."""
    result: tuple[bool, list[int], list[str], str, str, str]
    if enabled:
        result = (True, [], ["sms", "email"], f"Hello {{{{patient_first_name}}}}", "<p>Hello</p>", "09:00")
    else:
        result = (False, [], [], "", "", "")
    mock_fn = mocker.patch(
        "patient_notify.handlers.event_handler.get_effective_campaign_config",
        return_value=result,
    )
    return mock_fn


def _patch_common(mocker: MockerFixture, config_attrs: dict | None = None) -> dict:
    """Patch common dependencies and return mock references."""
    attrs: dict[str, object] = {
        "custom_variables": {},
    }
    if config_attrs:
        attrs.update(config_attrs)
    mock_config = MagicMock(**attrs)
    mocker.patch("patient_notify.handlers.event_handler.load_config", return_value=mock_config)

    mock_patient = MagicMock()
    mock_prefetch = MagicMock()
    mock_prefetch.get.return_value = mock_patient
    mocker.patch(
        "patient_notify.handlers.event_handler.Patient.objects.prefetch_related",
        return_value=mock_prefetch,
    )

    mock_note_type = MagicMock()
    mock_note_type.id = "nt-office"
    mock_appointment = MagicMock()
    mock_appointment.note_type = mock_note_type
    mock_select = MagicMock()
    mock_select.get.return_value = mock_appointment
    mocker.patch(
        "patient_notify.handlers.event_handler.Appointment.objects.select_related",
        return_value=mock_select,
    )

    mocker.patch(
        "patient_notify.handlers.event_handler.get_template_variables",
        return_value={"patient_first_name": "John"},
    )
    mocker.patch(
        "patient_notify.handlers.event_handler.render_template",
        return_value="Hello John",
    )

    return {
        "config": mock_config,
        "patient": mock_patient,
        "appointment": mock_appointment,
    }


def test_responds_to_correct_events() -> None:
    """Test handler responds to correct event types."""
    assert EventType.Name(EventType.APPOINTMENT_CREATED) in AppointmentEventHandler.RESPONDS_TO
    assert EventType.Name(EventType.APPOINTMENT_CANCELED) in AppointmentEventHandler.RESPONDS_TO
    assert EventType.Name(EventType.APPOINTMENT_NO_SHOWED) in AppointmentEventHandler.RESPONDS_TO


def test_appointment_created(mocker: MockerFixture) -> None:
    """Test handler for appointment created event."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    _patch_common(mocker)
    _patch_campaign_config(mocker, enabled=True)

    mock_effects = [MagicMock()]
    mock_results = [DeliveryResult(success=True, channel="sms")]
    mock_deliver = mocker.patch(
        "patient_notify.handlers.event_handler.deliver_to_patient",
        return_value=(mock_effects, mock_results),
    )
    mock_log = mocker.patch("patient_notify.handlers.event_handler.log_delivery_to_cache")

    handler = _make_handler(event)
    effects = handler.compute()

    assert effects == mock_effects
    mock_deliver.assert_called_once()
    call_args = mock_deliver.call_args
    assert call_args[0][4] == "confirmation"
    mock_log.assert_called_once_with("appt-1", "patient-1", "confirmation", mock_results)


def test_appointment_canceled(mocker: MockerFixture) -> None:
    """Test handler for appointment canceled event."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CANCELED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    _patch_common(mocker)
    mock_effective = mocker.patch(
        "patient_notify.handlers.event_handler.get_effective_campaign_config",
        return_value=(True, [], ["sms"], "Cancelled", "<p>Cancelled</p>", "09:00"),
    )

    mock_results = [DeliveryResult(success=True, channel="sms")]
    mocker.patch(
        "patient_notify.handlers.event_handler.deliver_to_patient",
        return_value=([MagicMock()], mock_results),
    )
    mock_log = mocker.patch("patient_notify.handlers.event_handler.log_delivery_to_cache")

    handler = _make_handler(event)
    effects = handler.compute()

    assert len(effects) == 1
    mock_effective.assert_called_once()
    assert mock_effective.call_args[0][1] == "cancellation"
    mock_log.assert_called_once_with("appt-1", "patient-1", "cancellation", mock_results)


def test_appointment_no_showed(mocker: MockerFixture) -> None:
    """Test handler for appointment no-showed event."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_NO_SHOWED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    _patch_common(mocker)
    mock_effective = mocker.patch(
        "patient_notify.handlers.event_handler.get_effective_campaign_config",
        return_value=(True, [], ["sms", "email"], "We missed you", "<p>We missed you</p>", "09:00"),
    )

    mock_results = [DeliveryResult(success=True, channel="email")]
    mocker.patch(
        "patient_notify.handlers.event_handler.deliver_to_patient",
        return_value=([MagicMock()], mock_results),
    )
    mock_log = mocker.patch("patient_notify.handlers.event_handler.log_delivery_to_cache")

    handler = _make_handler(event)
    effects = handler.compute()

    assert len(effects) == 1
    assert mock_effective.call_args[0][1] == "noshow"
    mock_log.assert_called_once_with("appt-1", "patient-1", "noshow", mock_results)


def test_campaign_disabled(mocker: MockerFixture) -> None:
    """Test handler skips when campaign is disabled via get_effective_campaign_config."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    _patch_common(mocker)
    _patch_campaign_config(mocker, enabled=False)

    mock_deliver = mocker.patch("patient_notify.handlers.event_handler.deliver_to_patient")

    handler = _make_handler(event)
    effects = handler.compute()

    assert effects == []
    mock_deliver.assert_not_called()


def test_no_patient_id() -> None:
    """Test handler handles missing patient ID gracefully."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {}

    handler = _make_handler(event)
    effects = handler.compute()

    assert effects == []


def test_patient_does_not_exist(mocker: MockerFixture) -> None:
    """Test handler handles Patient.DoesNotExist gracefully."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-gone"}}

    mock_config = MagicMock(custom_variables={})
    mocker.patch("patient_notify.handlers.event_handler.load_config", return_value=mock_config)

    mock_patient_cls = mocker.patch("patient_notify.handlers.event_handler.Patient")
    mock_patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_patient_cls.objects.prefetch_related.return_value.get.side_effect = (
        mock_patient_cls.DoesNotExist()
    )

    mock_deliver = mocker.patch("patient_notify.handlers.event_handler.deliver_to_patient")

    handler = _make_handler(event)
    effects = handler.compute()

    assert effects == []
    mock_deliver.assert_not_called()


def test_appointment_does_not_exist(mocker: MockerFixture) -> None:
    """Test handler handles Appointment.DoesNotExist gracefully."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-gone"
    event.context = {"patient": {"id": "patient-1"}}

    mock_config = MagicMock(custom_variables={})
    mocker.patch("patient_notify.handlers.event_handler.load_config", return_value=mock_config)

    mock_patient = MagicMock()
    mock_prefetch = MagicMock()
    mock_prefetch.get.return_value = mock_patient
    mocker.patch(
        "patient_notify.handlers.event_handler.Patient.objects.prefetch_related",
        return_value=mock_prefetch,
    )

    mock_appt_cls = mocker.patch("patient_notify.handlers.event_handler.Appointment")
    mock_appt_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
    mock_appt_cls.objects.select_related.return_value.get.side_effect = (
        mock_appt_cls.DoesNotExist()
    )

    mock_deliver = mocker.patch("patient_notify.handlers.event_handler.deliver_to_patient")

    handler = _make_handler(event)
    effects = handler.compute()

    assert effects == []
    mock_deliver.assert_not_called()


def test_returns_effects_from_delivery(mocker: MockerFixture) -> None:
    """Test handler returns the effects from deliver_to_patient."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    _patch_common(mocker)
    _patch_campaign_config(mocker, enabled=True)

    expected_effects = [MagicMock(), MagicMock()]
    mocker.patch(
        "patient_notify.handlers.event_handler.deliver_to_patient",
        return_value=(expected_effects, [DeliveryResult(success=True, channel="sms")]),
    )
    mocker.patch("patient_notify.handlers.event_handler.log_delivery_to_cache")

    handler = _make_handler(event)
    effects = handler.compute()

    assert effects == expected_effects


def test_passes_secrets_to_delivery(mocker: MockerFixture) -> None:
    """Test handler passes self.secrets to deliver_to_patient."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    _patch_common(mocker)
    _patch_campaign_config(mocker, enabled=True)

    mock_deliver = mocker.patch(
        "patient_notify.handlers.event_handler.deliver_to_patient",
        return_value=([], []),
    )
    mocker.patch("patient_notify.handlers.event_handler.log_delivery_to_cache")

    handler = _make_handler(event)
    handler.secrets = {"twilio-account-sid": "AC999"}
    handler.compute()

    # secrets is the 6th positional arg (index 5)
    assert mock_deliver.call_args[0][5] == {"twilio-account-sid": "AC999"}


def test_passes_note_type_to_effective_config(mocker: MockerFixture) -> None:
    """Test handler resolves note_type_id from appointment and passes to config resolution."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    _patch_common(mocker)
    mock_effective = _patch_campaign_config(mocker, enabled=True)

    mocker.patch(
        "patient_notify.handlers.event_handler.deliver_to_patient",
        return_value=([], []),
    )
    mocker.patch("patient_notify.handlers.event_handler.log_delivery_to_cache")

    handler = _make_handler(event)
    handler.compute()

    assert mock_effective.call_args[0][1] == "confirmation"
    assert mock_effective.call_args[0][2] == "nt-office"


def test_unmapped_event_type(mocker: MockerFixture) -> None:
    """Test handler returns empty list for event types not in _EVENT_TO_CAMPAIGN."""
    event = MagicMock()
    event.name = "SOME_UNKNOWN_EVENT"
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    mock_config = MagicMock(custom_variables={})
    mocker.patch("patient_notify.handlers.event_handler.load_config", return_value=mock_config)

    mock_deliver = mocker.patch("patient_notify.handlers.event_handler.deliver_to_patient")

    handler = _make_handler(event)
    effects = handler.compute()

    assert effects == []
    mock_deliver.assert_not_called()


def test_select_related_includes_note_type(mocker: MockerFixture) -> None:
    """Test appointment query includes note_type in select_related."""
    event = MagicMock()
    event.name = EventType.Name(EventType.APPOINTMENT_CREATED)
    event.target.id = "appt-1"
    event.context = {"patient": {"id": "patient-1"}}

    mock_config = MagicMock(custom_variables={})
    mocker.patch("patient_notify.handlers.event_handler.load_config", return_value=mock_config)

    mock_patient = MagicMock()
    mock_prefetch = MagicMock()
    mock_prefetch.get.return_value = mock_patient
    mocker.patch(
        "patient_notify.handlers.event_handler.Patient.objects.prefetch_related",
        return_value=mock_prefetch,
    )

    mock_note_type = MagicMock()
    mock_note_type.id = "nt-1"
    mock_appointment = MagicMock()
    mock_appointment.note_type = mock_note_type

    mock_select = MagicMock()
    mock_select.get.return_value = mock_appointment
    mock_select_related = mocker.patch(
        "patient_notify.handlers.event_handler.Appointment.objects.select_related",
        return_value=mock_select,
    )

    mocker.patch(
        "patient_notify.handlers.event_handler.get_effective_campaign_config",
        return_value=(False, [], [], "", "", ""),
    )

    handler = _make_handler(event)
    handler.compute()

    call_args = mock_select_related.call_args[0]
    assert "note_type" in call_args
