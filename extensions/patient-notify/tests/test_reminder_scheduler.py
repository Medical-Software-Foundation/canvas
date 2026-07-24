"""Tests for reminder scheduler cron task."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from pytest_mock import MockerFixture

from patient_notify.handlers.reminder_scheduler import ReminderScheduler
from patient_notify.services.config import CampaignConfig, NoteTypeCampaignConfig
from patient_notify.services.delivery import DeliveryResult


def _make_scheduler() -> ReminderScheduler:
    """Instantiate scheduler without calling __init__."""
    scheduler = ReminderScheduler.__new__(ReminderScheduler)
    scheduler.event = MagicMock()
    scheduler.secrets = {"twilio-account-sid": "AC123"}
    scheduler.environment = {}
    return scheduler


def _make_appointment(
    appt_id: str = "appt1",
    minutes_from_now: int = 120,
    patient_id: str = "patient1",
    note_type_id: str | None = None,
    is_telehealth: bool = False,
) -> MagicMock:
    """Create a mock appointment."""
    now = datetime.now(timezone.utc)
    appt = MagicMock()
    appt.id = appt_id
    appt.start_time = now + timedelta(minutes=minutes_from_now + 5)
    appt.patient = MagicMock()
    appt.patient.id = patient_id
    appt.note_type_id = note_type_id
    if note_type_id:
        mock_note_type = MagicMock()
        mock_note_type.id = note_type_id
        mock_note_type.is_telehealth = is_telehealth
        appt.note_type = mock_note_type
    else:
        appt.note_type = None
    return appt


def _make_config(**kwargs: object) -> CampaignConfig:
    """Create a CampaignConfig with test defaults."""
    defaults: dict = {
        "note_type_campaigns": {},
    }
    defaults.update(kwargs)
    return CampaignConfig(**defaults)


def _patch_appointment_query(mocker: MockerFixture, appointments: list) -> MagicMock:
    """Set up the chained appointment query mock."""
    mock_prefetch = MagicMock()
    mock_prefetch.__iter__ = MagicMock(return_value=iter(appointments))
    mock_select = MagicMock()
    mock_select.prefetch_related.return_value = mock_prefetch
    mock_filter = MagicMock()
    mock_filter.select_related.return_value = mock_select
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.Appointment.objects.filter",
        return_value=mock_filter,
    )
    return mock_filter


def test_scheduler_schedule() -> None:
    """Test scheduler runs every 15 minutes."""
    assert ReminderScheduler.SCHEDULE == "*/15 * * * *"


def test_scheduler_sends_reminders(mocker: MockerFixture) -> None:
    """Test scheduler sends reminders for upcoming appointments with per-type config."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="Reminder SMS for {{patient_first_name}}",
        reminder_email_template="<p>Reminder email for {{patient_first_name}}</p>",
        reminder_channels=["sms", "email"],
    ).to_dict()
    config = _make_config(note_type_campaigns={"nt-office": nt_data})
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(minutes_from_now=1440, note_type_id="nt-office")
    _patch_appointment_query(mocker, [appt])

    mocker.patch.object(
        ReminderScheduler, "_is_reminder_send_window", return_value=True
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="Rendered"
    )

    mock_effects = [MagicMock()]
    mock_results = [DeliveryResult(success=True, channel="sms")]
    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=(mock_effects, mock_results),
    )
    mock_log = mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    assert len(effects) == 1
    mock_deliver.assert_called_once()
    mock_log.assert_called_once()
    mock_cache.set.assert_called()


def test_scheduler_filters_active_appointment_statuses(mocker: MockerFixture) -> None:
    """Test scheduler queries only active appointment statuses."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(note_type_campaigns={"nt-office": nt_data})
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    mock_prefetch = MagicMock()
    mock_prefetch.__iter__ = MagicMock(return_value=iter([]))
    mock_select = MagicMock()
    mock_select.prefetch_related.return_value = mock_prefetch
    mock_filter_result = MagicMock()
    mock_filter_result.select_related.return_value = mock_select
    mock_objects_filter = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.Appointment.objects.filter",
        return_value=mock_filter_result,
    )

    scheduler = _make_scheduler()
    scheduler.execute()

    call_kwargs = mock_objects_filter.call_args[1]
    assert call_kwargs["status__in"] == ["unconfirmed", "attempted", "confirmed"]


def test_scheduler_skips_already_sent(mocker: MockerFixture) -> None:
    """Test scheduler skips reminders already sent."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(note_type_campaigns={"nt-office": nt_data})
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = "1"  # Already sent
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(minutes_from_now=1440, note_type_id="nt-office")
    _patch_appointment_query(mocker, [appt])

    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient"
    )

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    assert effects == []
    mock_deliver.assert_not_called()


def test_scheduler_multiple_intervals(mocker: MockerFixture) -> None:
    """Test scheduler handles multiple reminder intervals."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[10080, 1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(note_type_campaigns={"nt-office": nt_data})
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt1 = _make_appointment(appt_id="a1", minutes_from_now=10080, note_type_id="nt-office")
    appt2 = _make_appointment(appt_id="a2", minutes_from_now=1440, note_type_id="nt-office")
    _patch_appointment_query(mocker, [appt1, appt2])

    mocker.patch.object(
        ReminderScheduler, "_is_reminder_send_window", return_value=True
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="test"
    )

    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [DeliveryResult(success=True, channel="sms")]),
    )
    mock_log = mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    # 2 appointments x 2 intervals = 4 deliveries
    assert mock_log.call_count == 4
    assert len(effects) == 4


def test_scheduler_skips_null_note_type(mocker: MockerFixture) -> None:
    """Test scheduler skips appointments with no note type."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(note_type_campaigns={"nt-office": nt_data})
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(minutes_from_now=1440, note_type_id=None)
    _patch_appointment_query(mocker, [appt])

    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient"
    )

    scheduler = _make_scheduler()
    scheduler.execute()

    mock_deliver.assert_not_called()


def test_scheduler_no_intervals_configured(mocker: MockerFixture) -> None:
    """Test scheduler returns early when no per-type and no global intervals are configured."""
    config = _make_config(
        note_type_campaigns={},
        reminders_enabled=False,
        telehealth_enabled=False,
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache")

    mock_filter = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.Appointment.objects.filter"
    )

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    assert effects == []
    mock_filter.assert_not_called()


def test_scheduler_global_reminder_intervals_drive_window(mocker: MockerFixture) -> None:
    """Global reminder intervals must drive the scheduler window even when no per-type override exists."""
    config = _make_config(
        note_type_campaigns={},
        reminders_enabled=True,
        reminder_intervals=[1440],
        telehealth_enabled=False,
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache")

    mock_filter = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.Appointment.objects.filter",
        return_value=MagicMock(
            select_related=MagicMock(
                return_value=MagicMock(
                    prefetch_related=MagicMock(
                        return_value=MagicMock(__iter__=MagicMock(return_value=iter([])))
                    )
                )
            )
        ),
    )

    scheduler = _make_scheduler()
    scheduler.execute()

    mock_filter.assert_called_once()
    call_kwargs = mock_filter.call_args[1]
    now = datetime.now(timezone.utc)
    end_window = call_kwargs["start_time__lte"]
    assert end_window > now + timedelta(minutes=1440)
    assert end_window < now + timedelta(minutes=1440 + 30)


def test_scheduler_telehealth_global_reminder_drives_day_out_leg(mocker: MockerFixture) -> None:
    """Telehealth visit types must fetch appointments within both telehealth and global reminder windows."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-tele",
        telehealth_enabled=True,
        telehealth_override=True,
        telehealth_intervals=[15],
        telehealth_sms_template="join sms",
        telehealth_email_template="<p>join</p>",
        telehealth_channels=["sms"],
    ).to_dict()
    config = _make_config(
        note_type_campaigns={"nt-tele": nt_data},
        reminders_enabled=True,
        reminder_intervals=[1440],
        telehealth_enabled=False,
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache")

    mock_filter = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.Appointment.objects.filter",
        return_value=MagicMock(
            select_related=MagicMock(
                return_value=MagicMock(
                    prefetch_related=MagicMock(
                        return_value=MagicMock(__iter__=MagicMock(return_value=iter([])))
                    )
                )
            )
        ),
    )

    scheduler = _make_scheduler()
    scheduler.execute()

    mock_filter.assert_called_once()
    call_kwargs = mock_filter.call_args[1]
    now = datetime.now(timezone.utc)
    end_window = call_kwargs["start_time__lte"]
    # Window must reach the longest interval, the global day-out reminder, not just the 15 minute join leg.
    assert end_window > now + timedelta(minutes=1440)


def test_scheduler_per_type_disabled_skips(mocker: MockerFixture) -> None:
    """Test scheduler skips appointments when per-type reminders_enabled is False."""
    enabled_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    disabled_data = NoteTypeCampaignConfig(
        note_type_id="nt-annual",
        reminders_enabled=False,
        reminder_intervals=[20160],
    ).to_dict()
    config = _make_config(
        note_type_campaigns={"nt-office": enabled_data, "nt-annual": disabled_data},
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(minutes_from_now=1440, note_type_id="nt-annual")
    _patch_appointment_query(mocker, [appt])

    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient"
    )

    scheduler = _make_scheduler()
    scheduler.execute()

    mock_deliver.assert_not_called()


def test_scheduler_returns_accumulated_effects(mocker: MockerFixture) -> None:
    """Test scheduler returns effects from all deliveries."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(note_type_campaigns={"nt-office": nt_data})
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(minutes_from_now=1440, note_type_id="nt-office")
    _patch_appointment_query(mocker, [appt])

    mocker.patch.object(
        ReminderScheduler, "_is_reminder_send_window", return_value=True
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="test"
    )

    effect1 = MagicMock()
    effect2 = MagicMock()
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([effect1, effect2], [DeliveryResult(success=True, channel="sms")]),
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    assert effect1 in effects
    assert effect2 in effects


def test_scheduler_passes_secrets_to_delivery(mocker: MockerFixture) -> None:
    """Test scheduler passes self.secrets to deliver_to_patient."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(note_type_campaigns={"nt-office": nt_data})
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(minutes_from_now=1440, note_type_id="nt-office")
    _patch_appointment_query(mocker, [appt])

    mocker.patch.object(
        ReminderScheduler, "_is_reminder_send_window", return_value=True
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="test"
    )

    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([], []),
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    scheduler.secrets = {"twilio-account-sid": "AC999"}
    scheduler.execute()

    # secrets is the 6th positional arg (index 5)
    assert mock_deliver.call_args[0][5] == {"twilio-account-sid": "AC999"}


def test_scheduler_telehealth_join_notification(mocker: MockerFixture) -> None:
    """Test scheduler sends telehealth join notifications for telehealth appointments."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-tele",

        telehealth_enabled=True,
        telehealth_override=True,
        telehealth_intervals=[60],
        telehealth_sms_template="Join your telehealth visit",
        telehealth_email_template="<p>Join your telehealth visit</p>",
        telehealth_channels=["sms"],
    ).to_dict()
    config = _make_config(
        note_type_campaigns={"nt-tele": nt_data},
        telehealth_enabled=True,
        telehealth_intervals=[60],
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(
        minutes_from_now=60, note_type_id="nt-tele", is_telehealth=True
    )
    _patch_appointment_query(mocker, [appt])

    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="Join"
    )

    mock_effects = [MagicMock()]
    mock_results = [DeliveryResult(success=True, channel="sms")]
    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=(mock_effects, mock_results),
    )
    mock_log = mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    assert len(effects) == 1
    assert mock_deliver.call_args[0][4] == "telehealth"
    mock_log.assert_called_once()


def test_scheduler_telehealth_skips_non_telehealth(mocker: MockerFixture) -> None:
    """Test scheduler does not send telehealth notifications for non-telehealth appointments."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(
        note_type_campaigns={"nt-office": nt_data},
        telehealth_enabled=True,
        telehealth_intervals=[60],
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(
        minutes_from_now=60, note_type_id="nt-office", is_telehealth=False
    )
    _patch_appointment_query(mocker, [appt])

    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="test"
    )

    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
    )

    scheduler = _make_scheduler()
    scheduler.execute()

    mock_deliver.assert_not_called()


def test_scheduler_telehealth_uses_separate_cache_prefix(mocker: MockerFixture) -> None:
    """Test telehealth notifications use cr:telehealth_sent cache prefix."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-tele",

        telehealth_enabled=True,
        telehealth_override=True,
        telehealth_intervals=[60],
        telehealth_sms_template="Join",
        telehealth_email_template="<p>Join</p>",
        telehealth_channels=["sms"],
    ).to_dict()
    config = _make_config(
        note_type_campaigns={"nt-tele": nt_data},
        telehealth_enabled=True,
        telehealth_intervals=[60],
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(
        appt_id="appt-tele", minutes_from_now=60, note_type_id="nt-tele", is_telehealth=True
    )
    _patch_appointment_query(mocker, [appt])

    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="Join"
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [DeliveryResult(success=True, channel="sms")]),
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    scheduler.execute()

    set_calls = [c for c in mock_cache.set.call_args_list if "telehealth_sent" in str(c)]
    assert len(set_calls) == 1
    assert "cr:telehealth_sent:appt-tele:60" in str(set_calls[0])


# Campaign-type branching tests


def test_scheduler_reminder_uses_send_window(mocker: MockerFixture) -> None:
    """Test _process_intervals uses send window logic for campaign_type=reminder."""
    from zoneinfo import ZoneInfo

    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-office",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()

    et = ZoneInfo("America/New_York")
    target_send = datetime(2026, 3, 13, 9, 5, tzinfo=et)
    now_utc = target_send.astimezone(timezone.utc)

    config = CampaignConfig(
        day_out_send_time="09:00",
        day_out_timezone="America/New_York",
        note_type_campaigns={"nt-office": nt_data},
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = MagicMock()
    appt.id = "appt-r"
    appt.start_time = datetime(2026, 3, 14, 14, 0, tzinfo=timezone.utc)
    appt.patient = MagicMock()
    appt.patient.id = "p1"
    mock_note_type = MagicMock()
    mock_note_type.id = "nt-office"
    mock_note_type.is_telehealth = False
    appt.note_type = mock_note_type

    _patch_appointment_query(mocker, [appt])
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="test"
    )
    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [DeliveryResult(success=True, channel="sms")]),
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    # Patch datetime.now to return our controlled time
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.datetime",
        wraps=datetime,
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.datetime.now",
        return_value=now_utc,
    )
    effects = scheduler.execute()

    assert len(effects) == 1
    mock_deliver.assert_called_once()


def test_scheduler_telehealth_uses_raw_offset(mocker: MockerFixture) -> None:
    """Test _process_intervals uses raw offset for campaign_type=telehealth."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-tele",

        telehealth_enabled=True,
        telehealth_override=True,
        telehealth_intervals=[60],
        telehealth_sms_template="Join",
        telehealth_email_template="<p>Join</p>",
        telehealth_channels=["sms"],
    ).to_dict()
    config = CampaignConfig(
        note_type_campaigns={"nt-tele": nt_data},
        telehealth_enabled=True,
        telehealth_intervals=[60],
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = _make_appointment(
        appt_id="appt-t", minutes_from_now=60, note_type_id="nt-tele", is_telehealth=True
    )
    _patch_appointment_query(mocker, [appt])

    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="Join"
    )
    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [DeliveryResult(success=True, channel="sms")]),
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    assert len(effects) == 1
    mock_deliver.assert_called_once()


# Reminder send window tests


def test_reminder_send_window_fires_at_configured_time() -> None:
    """Test day-out interval fires when now is within 15 min of configured send time."""
    from zoneinfo import ZoneInfo

    config = CampaignConfig(day_out_send_time="09:00", day_out_timezone="America/New_York")

    # Create an appointment 2 days from now
    et = ZoneInfo("America/New_York")
    target_date = datetime(2026, 3, 12, 9, 5, tzinfo=et)
    now_utc = target_date.astimezone(timezone.utc)

    appt = MagicMock()
    appt.start_time = datetime(2026, 3, 14, 14, 0, tzinfo=timezone.utc)

    result = ReminderScheduler._is_reminder_send_window(appt, now_utc, 2880, config)
    assert result is True


def test_reminder_send_window_invalid_timezone_falls_back() -> None:
    """Test _is_reminder_send_window falls back to America/New_York for invalid timezone."""
    from zoneinfo import ZoneInfo

    config = CampaignConfig(day_out_send_time="09:00", day_out_timezone="Invalid/Timezone")

    et = ZoneInfo("America/New_York")
    target_date = datetime(2026, 3, 12, 9, 5, tzinfo=et)
    now_utc = target_date.astimezone(timezone.utc)

    appt = MagicMock()
    appt.start_time = datetime(2026, 3, 14, 14, 0, tzinfo=timezone.utc)

    result = ReminderScheduler._is_reminder_send_window(appt, now_utc, 2880, config)
    assert result is True


def test_scheduler_is_telehealth_exception(mocker: MockerFixture) -> None:
    """Test scheduler handles exception when accessing note_type.is_telehealth."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-broken",

        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[1440],
        reminder_sms_template="test",
        reminder_email_template="<p>test</p>",
    ).to_dict()
    config = _make_config(
        note_type_campaigns={"nt-broken": nt_data},
        telehealth_enabled=True,
        telehealth_intervals=[60],
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    appt = MagicMock()
    appt.id = "appt-broken"
    appt.start_time = datetime.now(timezone.utc) + timedelta(minutes=1445)
    appt.patient = MagicMock()
    appt.patient.id = "p1"
    mock_note_type = MagicMock()
    mock_note_type.id = "nt-broken"
    type(mock_note_type).is_telehealth = property(lambda self: (_ for _ in ()).throw(Exception("DB error")))
    appt.note_type = mock_note_type

    _patch_appointment_query(mocker, [appt])

    mocker.patch.object(
        ReminderScheduler, "_is_reminder_send_window", return_value=True
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="test"
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [DeliveryResult(success=True, channel="sms")]),
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    # Reminders should still fire (1 effect), telehealth skipped due to exception
    assert len(effects) == 1


def test_scheduler_telehealth_skips_outside_interval_window(mocker: MockerFixture) -> None:
    """Test _process_intervals skips telehealth when time difference exceeds 15 minutes."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-tele",

        telehealth_enabled=True,
        telehealth_override=True,
        telehealth_intervals=[60],
        telehealth_sms_template="Join",
        telehealth_email_template="<p>Join</p>",
        telehealth_channels=["sms"],
    ).to_dict()
    config = _make_config(
        note_type_campaigns={"nt-tele": nt_data},
        telehealth_enabled=True,
        telehealth_intervals=[60],
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.load_config", return_value=config)
    mocker.patch("patient_notify.handlers.reminder_scheduler.save_config")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.handlers.reminder_scheduler.get_cache", return_value=mock_cache)

    # Appointment 120 minutes from now, but interval is 60, so difference is 60 > 15
    appt = _make_appointment(
        appt_id="appt-t", minutes_from_now=120, note_type_id="nt-tele", is_telehealth=True
    )
    _patch_appointment_query(mocker, [appt])

    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.get_template_variables", return_value={}
    )
    mocker.patch(
        "patient_notify.handlers.reminder_scheduler.render_template", return_value="Join"
    )
    mock_deliver = mocker.patch(
        "patient_notify.handlers.reminder_scheduler.deliver_to_patient",
    )
    mocker.patch("patient_notify.handlers.reminder_scheduler.log_delivery_to_cache")

    scheduler = _make_scheduler()
    effects = scheduler.execute()

    assert effects == []
    mock_deliver.assert_not_called()


def test_reminder_send_window_skips_outside_window() -> None:
    """Test day-out interval skips when now is outside the 15-minute window."""
    from zoneinfo import ZoneInfo

    config = CampaignConfig(day_out_send_time="09:00", day_out_timezone="America/New_York")

    et = ZoneInfo("America/New_York")
    # 3 AM ET, well outside the 9 AM window
    now_local = datetime(2026, 3, 12, 3, 0, tzinfo=et)
    now_utc = now_local.astimezone(timezone.utc)

    appt = MagicMock()
    appt.start_time = datetime(2026, 3, 14, 14, 0, tzinfo=timezone.utc)

    result = ReminderScheduler._is_reminder_send_window(appt, now_utc, 2880, config)
    assert result is False
