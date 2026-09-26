"""Tests for handlers/reminder_scheduler.py — the cron task that fires
appointment reminders and telehealth-join messages."""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from appointment_reminders.handlers.reminder_scheduler import (
    ReminderScheduler,
    _in_send_window,
    _is_day_out_window,
    _parse_send_time,
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



def test_execute_never_writes_the_config() -> None:
    """The cron is read-only with respect to config.

    It used to call save_config() on every tick to "refresh the config TTL" —
    real when config lived in the cache, meaningless once it moved to a
    CampaignConfigRecord row with no expiry. That rewrote the whole config blob
    288 times a day to change nothing, and let a tick clobber an admin's
    concurrent save with its own stale copy.
    """
    import appointment_reminders.handlers.reminder_scheduler as mod

    assert not hasattr(mod, "save_config"), "the cron must not import save_config"

    scheduler = _scheduler()
    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=CampaignConfig(reminders_enabled=False, telehealth_enabled=False),
    ), patch(
        "appointment_reminders.services.config.save_config"
    ) as mock_save, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ):
        scheduler.execute()
    mock_save.assert_not_called()


# ---- the near-midnight miss ----

_TZ = zoneinfo.ZoneInfo("America/New_York")


def _utc(y, m, d, hh, mm, tz=_TZ) -> datetime:
    """A local wall-clock moment, as UTC."""
    return datetime(y, m, d, hh, mm, tzinfo=tz).astimezone(timezone.utc)


def test_day_out_send_time_late_in_the_day_still_fires_after_midnight() -> None:
    """Regression: a send time in the last GRACE_MINUTES of the day never fired.

    The scheduled instant used to be anchored to *now*'s local date and then
    gated on `now.date() == target_date`. With send_time 23:58 the only ticks
    inside the grace window land on the following date, so they failed that
    check and the reminder was lost entirely — not late, never sent.
    """
    appt = _utc(2026, 9, 10, 14, 0)          # appointment, local 2pm
    # target date is 2026-09-09, so the scheduled instant is 09-09 23:58 local.
    before = _utc(2026, 9, 9, 23, 55)        # tick before it: not yet due
    after = _utc(2026, 9, 10, 0, 0)          # tick 2 min later, next local date
    assert _is_day_out_window(before, appt, 1440, "23:58", "America/New_York") is False
    assert _is_day_out_window(after, appt, 1440, "23:58", "America/New_York") is True


def test_day_out_still_bounded_by_grace_after_midnight_spill() -> None:
    """The spill must not become an unbounded catch-up window."""
    appt = _utc(2026, 9, 10, 14, 0)
    too_late = _utc(2026, 9, 10, 0, 10)      # 12 min after 23:58, grace is 7
    assert _is_day_out_window(too_late, appt, 1440, "23:58", "America/New_York") is False


def test_day_out_ordinary_send_time_unchanged() -> None:
    """The common case must behave exactly as before the anchor change."""
    appt = _utc(2026, 9, 10, 14, 0)
    assert _is_day_out_window(
        _utc(2026, 9, 9, 9, 2), appt, 1440, "09:00", "America/New_York") is True
    assert _is_day_out_window(
        _utc(2026, 9, 9, 8, 55), appt, 1440, "09:00", "America/New_York") is False
    assert _is_day_out_window(
        _utc(2026, 9, 9, 9, 30), appt, 1440, "09:00", "America/New_York") is False
    # wrong date entirely
    assert _is_day_out_window(
        _utc(2026, 9, 8, 9, 2), appt, 1440, "09:00", "America/New_York") is False


def test_day_out_honours_multi_day_intervals() -> None:
    appt = _utc(2026, 9, 10, 14, 0)
    # 3 days out => target date 2026-09-07
    assert _is_day_out_window(
        _utc(2026, 9, 7, 9, 2), appt, 4320, "09:00", "America/New_York") is True
    assert _is_day_out_window(
        _utc(2026, 9, 9, 9, 2), appt, 4320, "09:00", "America/New_York") is False


def test_malformed_send_time_falls_back_instead_of_raising() -> None:
    """A bad config string must not take the whole scan down with it."""
    assert _parse_send_time("09:30") == (9, 30)
    assert _parse_send_time("") == (9, 0)
    assert _parse_send_time("9") == (9, 0)          # no colon: IndexError before
    assert _parse_send_time("abc") == (9, 0)
    assert _parse_send_time("25:00") == (9, 0)      # out of range
    assert _parse_send_time("09:99") == (9, 0)


# ---- the day-out gate ----

def test_in_send_window_true_only_within_grace() -> None:
    assert _in_send_window(_utc(2026, 9, 9, 9, 0), "09:00", "America/New_York") is True
    assert _in_send_window(_utc(2026, 9, 9, 9, 7), "09:00", "America/New_York") is True
    assert _in_send_window(_utc(2026, 9, 9, 9, 8), "09:00", "America/New_York") is False
    assert _in_send_window(_utc(2026, 9, 9, 8, 59), "09:00", "America/New_York") is False


def test_in_send_window_covers_the_midnight_spill() -> None:
    """Yesterday's instant counts, or the gate would block the very tick that
    _is_day_out_window needs for a late send time."""
    assert _in_send_window(_utc(2026, 9, 10, 0, 0), "23:58", "America/New_York") is True


def _run_gate(config: CampaignConfig, now: datetime):
    """Run execute() at a fixed `now`, returning the appointment queryset mock."""
    scheduler = _scheduler()
    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.datetime"
    ) as mock_dt, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt:
        mock_dt.now.return_value = now
        mock_dt.combine = datetime.combine
        (mock_appt.objects.filter.return_value
            .select_related.return_value
            .prefetch_related.return_value
            .iterator.return_value) = []
        scheduler.execute()
    return mock_appt


def test_gate_skips_the_scan_when_only_day_out_and_outside_the_window() -> None:
    """The whole point: 287 of 288 daily ticks should not touch the table.

    With a single day-out interval, a reminder can only fire in the grace
    window after its send time. Every other tick was querying every booked
    appointment in a multi-day window to discover it had nothing to do.
    """
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440],
        telehealth_enabled=False, reminder_send_time="00:50",
        reminder_timezone="America/New_York",
    )
    mock_appt = _run_gate(config, _utc(2026, 9, 9, 14, 0))  # nowhere near 00:50
    mock_appt.objects.filter.assert_not_called()


def test_gate_allows_the_scan_inside_the_send_window() -> None:
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440],
        telehealth_enabled=False, reminder_send_time="00:50",
        reminder_timezone="America/New_York",
    )
    mock_appt = _run_gate(config, _utc(2026, 9, 9, 0, 52))
    mock_appt.objects.filter.assert_called_once()


def test_gate_always_allows_the_scan_when_a_short_interval_exists() -> None:
    """Sub-day reminder intervals are time-relative and can fire on any tick."""
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440, 45],
        telehealth_enabled=False, reminder_send_time="00:50",
        reminder_timezone="America/New_York",
    )
    mock_appt = _run_gate(config, _utc(2026, 9, 9, 14, 0))
    mock_appt.objects.filter.assert_called_once()


def test_gate_always_allows_the_scan_when_telehealth_is_on() -> None:
    """Telehealth intervals are time-relative *whatever their size* — the
    telehealth branch ignores send_time. A day-sized one must not be mistaken
    for date-relative and gated away."""
    for th_intervals in ([15], [1440]):
        config = CampaignConfig(
            reminders_enabled=True, reminder_intervals=[1440],
            telehealth_enabled=True, telehealth_intervals=th_intervals,
            reminder_send_time="00:50", reminder_timezone="America/New_York",
        )
        mock_appt = _run_gate(config, _utc(2026, 9, 9, 14, 0))
        mock_appt.objects.filter.assert_called_once(), th_intervals


def test_gate_respects_a_per_visit_type_send_time() -> None:
    """A visit type with its own send time must open the gate at that time.

    Missing a send-time source here would silently stop that type's reminders,
    which is the failure mode this gate has to avoid.
    """
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440],
        telehealth_enabled=False, reminder_send_time="09:00",
        reminder_timezone="America/New_York",
        note_type_reminders={
            "nt-1": {"note_type_id": "nt-1", "reminder_send_time": "17:00"},
        },
    )
    # 17:02 matches only the per-type send time, not the 09:00 global.
    mock_appt = _run_gate(config, _utc(2026, 9, 9, 17, 2))
    mock_appt.objects.filter.assert_called_once()


def test_gate_still_skips_when_no_configured_send_time_matches() -> None:
    """`now` must miss both send times in *every* resolvable zone.

    14:00 Eastern is 18:00 UTC, which is 09:00 and 17:00 in none of them. The
    earlier version of this test used 13:00 Eastern, which is 09:00 in Alaska —
    a tick the gate is now right to open, since an Alaskan patient's day-out
    reminder fires at 09:00 Alaska time.
    """
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440],
        telehealth_enabled=False, reminder_send_time="09:00",
        reminder_timezone="America/New_York",
        note_type_reminders={
            "nt-1": {"note_type_id": "nt-1", "reminder_send_time": "17:00"},
        },
    )
    mock_appt = _run_gate(config, _utc(2026, 9, 9, 14, 0))
    mock_appt.objects.filter.assert_not_called()


# ---- scan horizon for day-out intervals ----

def _end_window(config: CampaignConfig, now: datetime):
    """Run execute() and return the start_time__lte the scan was given."""
    scheduler = _scheduler()
    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.datetime"
    ) as mock_dt, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt:
        mock_dt.now.return_value = now
        mock_dt.combine = datetime.combine
        (mock_appt.objects.filter.return_value
            .select_related.return_value
            .prefetch_related.return_value
            .iterator.return_value) = []
        scheduler.execute()
    if not mock_appt.objects.filter.called:
        return None
    return mock_appt.objects.filter.call_args.kwargs["start_time__lte"]


def test_day_out_scan_reaches_the_end_of_the_target_date() -> None:
    """Regression: appointments late on the target date were silently dropped.

    A day-out interval fires at send_time on (appt_date - interval_days), so an
    appointment anywhere in that date is eligible — a lead time of up to a full
    extra day. Sizing the window by the raw interval gave a 24.1h horizon for a
    1-day interval, so only appointments in the first few hours of the target
    date were ever seen.

    Measured on a live instance at the 09:00 ET window on 2026-08-25 with
    reminder_intervals [1440]: three appointments on 2026-08-26, all
    date-eligible. 01:30 ET (16.5h out) fired; 14:00 ET (29h) and 20:00 ET (35h)
    produced no rows at all.
    """
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440], telehealth_enabled=False,
        reminder_send_time="09:00", reminder_timezone="America/New_York",
    )
    now = _utc(2026, 8, 25, 9, 0)
    end_window = _end_window(config, now)
    assert end_window is not None, "the send window should open the gate"

    horizon_hours = (end_window - now).total_seconds() / 3600
    assert horizon_hours >= 48, f"horizon only reaches {horizon_hours:.1f}h"

    # The three real appointments, by lead time from that window.
    for lead_hours in (16.5, 29.0, 35.0):
        assert now + timedelta(hours=lead_hours) <= end_window, lead_hours


def test_day_out_horizon_covers_a_dst_lengthened_day() -> None:
    """A fall-back local day is 25 hours, putting the target date's last hour
    just past a flat 48h. Cheap to cover, since over-inclusion is free."""
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440], telehealth_enabled=False,
        reminder_send_time="00:00", reminder_timezone="America/New_York",
    )
    now = _utc(2026, 11, 1, 0, 1)
    end_window = _end_window(config, now)
    assert (end_window - now).total_seconds() / 3600 >= 49


def test_multi_day_interval_horizon_is_padded_too() -> None:
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[4320], telehealth_enabled=False,
        reminder_send_time="09:00", reminder_timezone="America/New_York",
    )
    now = _utc(2026, 8, 25, 9, 0)
    horizon_hours = (_end_window(config, now) - now).total_seconds() / 3600
    # 3-day interval spans target dates up to 4 days out.
    assert 96 <= horizon_hours < 120, horizon_hours


def test_sub_day_reminder_interval_is_not_padded() -> None:
    """Short intervals really are durations; padding them would widen the scan
    for no reason on every tick, since they keep the gate permanently open."""
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[45], telehealth_enabled=False,
        reminder_send_time="09:00", reminder_timezone="America/New_York",
    )
    now = _utc(2026, 8, 25, 14, 0)
    horizon_minutes = (_end_window(config, now) - now).total_seconds() / 60
    assert horizon_minutes == 45 + 7


def test_telehealth_interval_is_never_padded_whatever_its_size() -> None:
    """The telehealth branch ignores send_time entirely — a day-sized telehealth
    interval is still a duration, so padding it would be wrong in kind."""
    config = CampaignConfig(
        reminders_enabled=False, telehealth_enabled=True,
        telehealth_intervals=[1440],
        reminder_send_time="09:00", reminder_timezone="America/New_York",
    )
    now = _utc(2026, 8, 25, 14, 0)
    horizon_minutes = (_end_window(config, now) - now).total_seconds() / 60
    assert horizon_minutes == 1440 + 7


def test_horizon_takes_the_widest_across_mixed_intervals() -> None:
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440, 45],
        telehealth_enabled=True, telehealth_intervals=[15],
        reminder_send_time="09:00", reminder_timezone="America/New_York",
    )
    now = _utc(2026, 8, 25, 14, 0)
    horizon_hours = (_end_window(config, now) - now).total_seconds() / 3600
    assert horizon_hours >= 48


# ---- patient-less appointments and per-row isolation ----

def _appt(dbid, start, patient=True, note_type_id="nt-1"):
    """An appointment in the scan window, with or without a patient."""
    a = MagicMock()
    a.id = f"appt-{dbid}"
    a.start_time = start
    a.note_type = MagicMock()
    a.note_type.id = note_type_id
    if patient:
        a.patient = MagicMock()
        a.patient.id = f"pat-{dbid}"
        a.patient.business_line = None
    else:
        a.patient = None          # admin block / availability hold / imported hold
    return a


def _run_scan(appointments, now, config):
    """Drive execute() over a fixed appointment list, capturing deliveries."""
    scheduler = _scheduler()
    sent = []

    def _deliver(patient, *a, **kw):
        sent.append(getattr(patient, "id", None))
        return ([], [])

    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.datetime"
    ) as mock_dt, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_template_variables",
        return_value={"patient_first_name": "X"},
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.render_template",
        return_value="body",
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient",
        side_effect=_deliver,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.log_delivery"
    ):
        mock_dt.now.return_value = now
        mock_dt.combine = datetime.combine
        mock_cache.return_value.get.return_value = None
        (mock_appt.objects.filter.return_value
            .select_related.return_value
            .prefetch_related.return_value
            .iterator.return_value) = appointments
        result = scheduler.execute()
    return sent, result


_SHORT_CFG = CampaignConfig(
    reminders_enabled=True, reminder_intervals=[45], telehealth_enabled=False,
    reminder_send_time="09:00", reminder_timezone="America/New_York",
)


def test_patientless_appointment_does_not_raise_and_does_not_send() -> None:
    """Appointment.patient is nullable: admin blocks and availability holds are
    real rows with patient_id NULL, and they resolve to the global config."""
    now = _utc(2026, 9, 1, 14, 0)
    due = now + timedelta(minutes=45)
    sent, _ = _run_scan([_appt(1, due, patient=False)], now, _SHORT_CFG)
    assert sent == []


def test_a_patientless_row_does_not_suppress_a_later_valid_one() -> None:
    """The regression that matters.

    Without the guard the loop raised AttributeError on patient.first_name and
    the whole tick died, losing every appointment after it in iteration order.
    A test that only asserted "does not raise" would pass once a guard existed
    but would not have caught the original failure.
    """
    now = _utc(2026, 9, 1, 14, 0)
    due = now + timedelta(minutes=45)
    appointments = [_appt(1, due, patient=False), _appt(2, due, patient=True)]
    sent, _ = _run_scan(appointments, now, _SHORT_CFG)
    assert sent == ["pat-2"], "the valid appointment after the bad row must still send"


def test_a_row_that_raises_for_any_other_reason_is_isolated() -> None:
    """Per-row isolation, not just a patient guard.

    The guard closes the one hole we found; this closes the class. A day-out
    interval gets one grace window per day, so losing the rest of a tick costs
    a whole day of reminders.
    """
    now = _utc(2026, 9, 1, 14, 0)
    due = now + timedelta(minutes=45)
    exploding = _appt(1, due, patient=True)
    type(exploding).note_type = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("bad row"))
    )
    appointments = [exploding, _appt(2, due, patient=True)]
    sent, _ = _run_scan(appointments, now, _SHORT_CFG)
    assert sent == ["pat-2"]


def test_scan_completes_and_still_returns_effects_after_a_bad_row() -> None:
    now = _utc(2026, 9, 1, 14, 0)
    due = now + timedelta(minutes=45)
    sent, result = _run_scan(
        [_appt(1, due, patient=False), _appt(2, due, patient=True)], now, _SHORT_CFG
    )
    assert isinstance(result, list)
    assert sent == ["pat-2"]


# ---- day-out reminders fire at the patient's local send time ----
#
# Before this, a 09:00 America/New_York send reached a Pacific patient at 06:00
# their time. The send time is now measured in the same zone the message is
# rendered in.

def _pacific_patient_appointment(appt_start_utc: datetime) -> MagicMock:
    appt = _appointment()
    appt.start_time = appt_start_utc
    address = MagicMock()
    address.state_code = "CA"
    address.postal_code = "94105"
    address.country = "US"
    address.use = "home"
    address.state = "active"
    appt.patient.last_known_timezone = None
    appt.patient.addresses.all.return_value = [address]
    return appt


def _run_day_out(now_utc: datetime, appt: MagicMock) -> MagicMock:
    """Run one scan at `now_utc` with a single 1-day reminder at 09:00 Eastern."""
    scheduler = _scheduler()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[1440],
        reminder_channels=["sms"],
        reminder_sms_template="Reminder: {{appointment_date}}",
        reminder_email_template="Reminder",
        reminder_send_time="09:00",
        reminder_timezone="America/New_York",
        telehealth_enabled=False,
    )
    with patch(
        "appointment_reminders.handlers.reminder_scheduler.load_config",
        return_value=config,
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.handlers.reminder_scheduler.datetime"
    ) as mock_dt, patch(
        "appointment_reminders.handlers.reminder_scheduler.Appointment"
    ) as mock_appt_cls, patch(
        "appointment_reminders.handlers.reminder_scheduler.get_template_variables",
        return_value={"appointment_date": "June 8"},
    ), patch(
        "appointment_reminders.handlers.reminder_scheduler.deliver_to_patient",
        return_value=([MagicMock()], [MagicMock(channel="sms", success=True, error=None)]),
    ) as mock_deliver, patch(
        "appointment_reminders.handlers.reminder_scheduler.log_delivery"
    ):
        mock_dt.now.return_value = now_utc
        mock_dt.combine = datetime.combine
        mock_cache.return_value.get.return_value = None
        chain = mock_appt_cls.objects.filter.return_value.select_related.return_value.prefetch_related
        chain.return_value.iterator.return_value = [appt]
        scheduler.execute()
    return mock_deliver


_PT = zoneinfo.ZoneInfo("America/Los_Angeles")


def test_day_out_reminder_fires_at_nine_in_the_patients_zone() -> None:
    appt = _pacific_patient_appointment(
        datetime(2026, 6, 8, 14, 0, tzinfo=_PT).astimezone(timezone.utc)
    )
    now = datetime(2026, 6, 7, 9, 0, tzinfo=_PT).astimezone(timezone.utc)
    assert _run_day_out(now, appt).call_count == 1


def test_day_out_reminder_does_not_fire_at_nine_in_the_clinic_zone() -> None:
    """09:00 Eastern is 06:00 for this patient. Sending then is the behavior
    that prompted the change, and TCPA quiet hours start at 08:00 local."""
    appt = _pacific_patient_appointment(
        datetime(2026, 6, 8, 14, 0, tzinfo=_PT).astimezone(timezone.utc)
    )
    now = datetime(
        2026, 6, 7, 9, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
    ).astimezone(timezone.utc)
    _run_day_out(now, appt).assert_not_called()


def test_gate_opens_for_a_tick_that_is_the_send_time_only_in_another_zone() -> None:
    """The scan gate has to admit 09:00 Pacific even though the configured zone
    is Eastern, or a Pacific patient's day-out reminder never fires at all."""
    config = CampaignConfig(
        reminders_enabled=True, reminder_intervals=[1440],
        telehealth_enabled=False, reminder_send_time="09:00",
        reminder_timezone="America/New_York",
    )
    now = datetime(2026, 6, 7, 9, 0, tzinfo=_PT).astimezone(timezone.utc)
    mock_appt = _run_gate(config, now)
    mock_appt.objects.filter.assert_called_once()
