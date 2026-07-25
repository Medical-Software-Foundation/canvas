"""Tests for handlers/reminder_scheduler.py — the cron task that fires
appointment reminders and telehealth-join messages."""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from appointment_reminders.handlers.reminder_scheduler import (
    ReminderScheduler,
    _is_day_out_window,
)
from appointment_reminders.services.config import CampaignConfig


def _scheduler() -> ReminderScheduler:
    handler = ReminderScheduler.__new__(ReminderScheduler)
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
    minutes_until: int = 60,
    note_type_id="nt-1",
    is_telehealth: bool = False,
) -> MagicMock:
    appt = MagicMock()
    appt.id = appt_id
    nt = MagicMock()
    nt.id = note_type_id
    nt.is_telehealth = is_telehealth
    appt.note_type = nt
    appt.start_time = datetime.now(timezone.utc) + timedelta(minutes=minutes_until)
    patient = MagicMock()
    patient.id = "patient-1"
    appt.patient = patient
    return appt


# ---- execute() — early returns ----

def test_execute_returns_empty_when_all_intervals_disabled() -> None:
    scheduler = _scheduler()
    config = CampaignConfig(reminders_enabled=False, telehealth_enabled=False)
    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ):
        result = scheduler.execute()
    assert result == []


# ---- execute() — full path ----

def test_execute_sends_reminder_for_matching_interval() -> None:
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[60],  # 1-hour reminder
        reminder_channels=["sms"],
        reminder_sms_template="Reminder: {{appointment_date}}",
        reminder_email_template="Reminder",
    )
    appt = _appointment(minutes_until=60)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_template_variables",
        return_value={"appointment_date": "June 1"},
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.handlers.reminder_scheduler.log_delivery"
    ):
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        result = scheduler.execute()

    assert len(result) == 1
    mock_deliver.assert_called_once()


def test_execute_skips_already_sent_reminders() -> None:
    """Cache hit on cr:reminder_sent:* short-circuits the send."""
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[60],
        reminder_channels=["sms"],
        reminder_sms_template="x",
    )
    appt = _appointment(minutes_until=60)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient"
    ) as mock_deliver:
        mock_cache.return_value.get.return_value = "1"  # already sent
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        result = scheduler.execute()

    assert result == []
    mock_deliver.assert_not_called()


def test_execute_skips_appointments_outside_interval_window() -> None:
    """Appointment is 90 min out, interval is 60 — the 60-min target has not
    arrived yet (overdue is negative), so skip. Reminders never send early."""
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[60],
        reminder_channels=["sms"],
        reminder_sms_template="x",
    )
    appt = _appointment(minutes_until=90)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient"
    ) as mock_deliver:
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        result = scheduler.execute()

    assert result == []
    mock_deliver.assert_not_called()


def test_execute_sends_telehealth_when_appointment_is_telehealth() -> None:
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[60],
        reminder_channels=["sms"],
        reminder_sms_template="r",
        telehealth_enabled=True,
        telehealth_intervals=[15],
        telehealth_channels=["sms"],
        telehealth_sms_template="join now",
    )
    appt = _appointment(minutes_until=15, is_telehealth=True)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_template_variables",
        return_value={"telehealth_link": "https://meet.example.com/x"},
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.handlers.reminder_scheduler.log_delivery"
    ):
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        scheduler.execute()

    # First call is the regular reminder (interval=60, but appt is 15 min out — skipped)
    # Telehealth fires for interval=15
    deliver_calls = [c for c in mock_deliver.call_args_list]
    campaign_types = [c.args[4] for c in deliver_calls]
    assert "telehealth" in campaign_types


def test_execute_sends_telehealth_when_reminders_globally_disabled() -> None:
    """Telehealth and reminder are independently configured campaigns. A
    clinic that uses Canvas's built-in reminders but wants telehealth-join
    SMS from this plugin sets reminders_enabled=False, telehealth_enabled=True
    — telehealth must still fire.
    """
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=False,
        telehealth_enabled=True,
        telehealth_intervals=[15],
        telehealth_channels=["sms"],
        telehealth_sms_template="join now",
    )
    appt = _appointment(minutes_until=15, is_telehealth=True)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_template_variables",
        return_value={"telehealth_link": "https://meet.example.com/x"},
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.handlers.reminder_scheduler.log_delivery"
    ):
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        scheduler.execute()

    campaign_types = [c.args[4] for c in mock_deliver.call_args_list]
    assert "telehealth" in campaign_types
    assert "reminder" not in campaign_types


def test_execute_logs_telehealth_failure_when_no_link() -> None:
    """Missing telehealth_link → log delivery failure but no send."""
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[60],
        reminder_channels=["sms"],
        reminder_sms_template="r",
        telehealth_enabled=True,
        telehealth_intervals=[15],
        telehealth_channels=["sms"],
        telehealth_sms_template="join",
    )
    appt = _appointment(minutes_until=15, is_telehealth=True)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_template_variables",
        return_value={"telehealth_link": ""},
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient"
    ) as mock_deliver, patch(
        "appointment_reminders.handlers.reminder_scheduler.log_delivery"
    ) as mock_log:
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        scheduler.execute()

    mock_deliver.assert_not_called()
    mock_log.assert_called_once()
    log_results = mock_log.call_args.args[3]
    assert log_results[0].channel == "telehealth"
    assert log_results[0].success is False


# ---- _is_day_out_window ----

def test_is_day_out_window_matches_target_date_and_time() -> None:
    tz = zoneinfo.ZoneInfo("America/New_York")
    appt_local = datetime(2026, 6, 8, 14, 0, tzinfo=tz)
    now_local = datetime(2026, 6, 7, 9, 0, tzinfo=tz)  # 1 day before, 9 AM
    appt_utc = appt_local.astimezone(timezone.utc)
    now_utc = now_local.astimezone(timezone.utc)
    assert _is_day_out_window(now_utc, appt_utc, 1440, "09:00", "America/New_York") is True


def test_is_day_out_window_rejects_when_not_target_date() -> None:
    tz = zoneinfo.ZoneInfo("America/New_York")
    appt_local = datetime(2026, 6, 8, 14, 0, tzinfo=tz)
    now_local = datetime(2026, 6, 5, 9, 0, tzinfo=tz)  # 3 days before
    assert (
        _is_day_out_window(
            now_local.astimezone(timezone.utc),
            appt_local.astimezone(timezone.utc),
            1440,
            "09:00",
            "America/New_York",
        )
        is False
    )


def test_is_day_out_window_rejects_when_outside_send_time_window() -> None:
    tz = zoneinfo.ZoneInfo("America/New_York")
    appt_local = datetime(2026, 6, 8, 14, 0, tzinfo=tz)
    now_local = datetime(2026, 6, 7, 11, 0, tzinfo=tz)  # 11 AM, 2h past 9 AM
    assert (
        _is_day_out_window(
            now_local.astimezone(timezone.utc),
            appt_local.astimezone(timezone.utc),
            1440,
            "09:00",
            "America/New_York",
        )
        is False
    )


def test_is_day_out_window_uses_default_send_time_when_blank() -> None:
    """Empty send_time defaults to 9:00 AM."""
    tz = zoneinfo.ZoneInfo("America/New_York")
    appt_local = datetime(2026, 6, 8, 14, 0, tzinfo=tz)
    now_local = datetime(2026, 6, 7, 9, 0, tzinfo=tz)
    assert (
        _is_day_out_window(
            now_local.astimezone(timezone.utc),
            appt_local.astimezone(timezone.utc),
            1440,
            "",
            "",
        )
        is True
    )


def test_execute_sends_reminder_that_came_due_within_the_grace_window() -> None:
    """A 45-min reminder whose target passed 5 min ago still fires.

    The old symmetric +/-2 min band dropped this send whenever a tick ran late.
    """
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[45],
        reminder_channels=["sms"],
        reminder_sms_template="Reminder",
    )
    # 40 min until the appointment, so the 45-min target passed ~5 min ago.
    appt = _appointment(minutes_until=40)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_template_variables",
        return_value={},
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.handlers.reminder_scheduler.log_delivery"
    ):
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        result = scheduler.execute()

    assert len(result) == 1
    mock_deliver.assert_called_once()


def test_execute_skips_reminder_staler_than_the_grace_window() -> None:
    """A target 40 min in the past is not replayed.

    This is what stops a backfill burst when a campaign is first enabled.
    """
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[45],
        reminder_channels=["sms"],
        reminder_sms_template="Reminder",
    )
    appt = _appointment(minutes_until=5)

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.save_config"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient"
    ) as mock_deliver:
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        result = scheduler.execute()

    assert result == []
    mock_deliver.assert_not_called()


def test_is_day_out_window_allows_late_send_within_grace() -> None:
    """9 AM send time: a scan at 9:05 still counts as due."""
    tz = zoneinfo.ZoneInfo("America/New_York")
    appt_local = datetime(2026, 6, 8, 14, 0, tzinfo=tz)
    now_local = datetime(2026, 6, 7, 9, 5, tzinfo=tz)
    assert (
        _is_day_out_window(
            now_local.astimezone(timezone.utc),
            appt_local.astimezone(timezone.utc),
            1440,
            "09:00",
            "America/New_York",
        )
        is True
    )


def test_is_day_out_window_never_sends_before_the_send_time() -> None:
    """8 AM is before the 9 AM send time, so not due regardless of grace."""
    tz = zoneinfo.ZoneInfo("America/New_York")
    appt_local = datetime(2026, 6, 8, 14, 0, tzinfo=tz)
    now_local = datetime(2026, 6, 7, 8, 0, tzinfo=tz)
    assert (
        _is_day_out_window(
            now_local.astimezone(timezone.utc),
            appt_local.astimezone(timezone.utc),
            1440,
            "09:00",
            "America/New_York",
        )
        is False
    )
