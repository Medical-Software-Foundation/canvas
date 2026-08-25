"""Cron task for scheduled appointment reminders."""
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

from appointment_reminders.services.business_line import (
    get_business_line_from_number,
    get_business_line_name,
)
from appointment_reminders.services.config import (
    NoteTypeCampaignConfig,
    get_effective_campaign_config,
    load_config,
)
from appointment_reminders.services.delivery import deliver_to_patient
from appointment_reminders.services.history import log_delivery
from appointment_reminders.services.templates import get_template_variables, render_template

class _TelehealthFailure:
    """Minimal result object for logging a telehealth link-missing failure."""

    channel = "telehealth"
    success = False
    error = "No meeting link on appointment or provider"
    recipient = ""


# Intervals >= 1 day are "day-out" and sent at a configured time of day
DAY_OUT_THRESHOLD = 1440  # minutes

# How late a send may be: one scan interval plus slack. A message fires on the
# first scan at or after its target moment, never before. A narrower symmetric
# band would silently drop the send whenever a tick ran late, and CRON ticks are
# not evenly spaced in practice. Bounding the lateness is also what stops a
# backfill burst when a campaign is first enabled: targets older than this are
# skipped, not replayed.
GRACE_MINUTES = 7

_DEFAULT_TZ = "America/New_York"
_DEFAULT_SEND_HOUR = 9
_DEFAULT_SEND_MINUTE = 0


class ReminderScheduler(CronTask):
    """Check for appointments needing reminders every 5 minutes."""

    SCHEDULE = "*/5 * * * *"

    def execute(self) -> list[Effect]:
        """Check appointments and send reminders."""
        # Read-only. This used to call save_config() right here to "refresh the
        # config TTL", which was real when the config lived in the cache. It now
        # lives in a CampaignConfigRecord row with no expiry, so that write
        # rewrote the entire config blob — every campaign's templates, every
        # per-visit-type and per-business-line override — 288 times a day to
        # change nothing, and opened a window where a tick could clobber an
        # admin's concurrent save with its own stale copy.
        config = load_config()

        cache = get_cache()
        now = datetime.now(timezone.utc)

        # Compute dynamic end_window from every interval that might fire.
        # Global acts as the master switch; per-type records can extend the
        # window with their own intervals unless they're explicit opt-outs.
        #
        # Reminder and telehealth intervals are kept apart because they are
        # scheduled differently: a reminder interval >= a day is date-relative
        # (fires at a configured send time), while *every* telehealth interval is
        # time-relative regardless of size — the telehealth branch below ignores
        # send_time entirely. Lumping them together would make the gate treat a
        # large telehealth interval as date-relative and skip scans it needs.
        reminder_intervals: list[int] = []
        telehealth_intervals: list[int] = []
        send_windows: set[tuple[str, str]] = set()

        if config.reminders_enabled:
            reminder_intervals.extend(config.reminder_intervals)
            send_windows.add((config.reminder_send_time, config.reminder_timezone))
        if config.telehealth_enabled:
            telehealth_intervals.extend(config.telehealth_intervals)

        for nt_data in config.note_type_reminders.values():
            nt_cfg = NoteTypeCampaignConfig.from_dict(nt_data)
            if config.reminders_enabled and nt_cfg.reminders_enabled is not False:
                reminder_intervals.extend(nt_cfg.reminder_intervals)
                # A blank per-type value inherits the global one, already added.
                if nt_cfg.reminder_send_time:
                    send_windows.add(
                        (nt_cfg.reminder_send_time,
                         nt_cfg.reminder_timezone or config.reminder_timezone)
                    )
            if config.telehealth_enabled and nt_cfg.telehealth_enabled is not False:
                telehealth_intervals.extend(nt_cfg.telehealth_intervals)

        all_intervals = reminder_intervals + telehealth_intervals
        if not all_intervals:
            log.info("Reminders and telehealth globally disabled, skipping")
            return []

        # Gate: skip the appointment query entirely when nothing can fire on this
        # tick. Every telehealth interval and every sub-day reminder interval is
        # time-relative, so those can fire at any tick and force the scan. But a
        # day-out reminder can only fire in the grace window after its send time,
        # which is a property of `now` alone — so with only day-out intervals
        # configured (a single daily reminder, the common case) this turns 288
        # scans a day into one. Business-line overrides cannot set a send time or
        # interval, so these two sources are the complete set.
        time_relative = [i for i in reminder_intervals if i < DAY_OUT_THRESHOLD]
        time_relative.extend(telehealth_intervals)
        if not time_relative and not any(
            _in_send_window(now, send_time, send_tz)
            for send_time, send_tz in send_windows
        ):
            log.info("No interval can fire on this tick; skipping the scan")
            return []

        # Kept as-is for the dedup cache TTLs further down, which want the raw
        # interval rather than the scan horizon.
        max_interval_minutes = max(all_intervals)

        # A day-out interval does not fire on a duration. It fires at `send_time`
        # on (appointment's local date - interval_days), and the appointment can
        # sit anywhere within that date — so its real lead time runs from just
        # over interval_days days to a full day more. Sizing the scan window by
        # the raw interval therefore dropped every eligible appointment past
        # interval_minutes + grace, silently: no log line, no error.
        #
        # Measured on a test instance with reminder_intervals [1440] and a 09:00 ET
        # send. Three appointments on the next local date, all date-eligible:
        # 16.5h out fired, 29h and 35h out were dropped. The old 24.1h horizon
        # admitted only the first.
        #
        # So pad day-out reminder intervals to cover their whole target date.
        # Telehealth intervals are never padded, whatever their size, because the
        # telehealth branch below is genuinely time-relative — the same
        # distinction the gate above draws. The extra hour absorbs a DST
        # fall-back day, which is 25 hours long locally and would otherwise put
        # the last hour of the target date out of reach once a year.
        #
        # Over-inclusion is free here: _is_day_out_window still makes the exact
        # per-appointment decision, so a wider scan changes only how many rows
        # are considered, never which ones fire. Under-inclusion was the bug.
        scan_horizon_minutes = max(
            [
                ((i // 1440) + 1) * 1440 + 60 if i >= DAY_OUT_THRESHOLD else i
                for i in reminder_intervals
            ]
            + telehealth_intervals
        )
        end_window = now + timedelta(minutes=scan_horizon_minutes + GRACE_MINUTES)

        # Only query booked appointments (excludes canceled, no-showed, etc.).
        # Single pass, so .iterator() bounds peak memory over a window that held
        # ~3.4k appointments on the busiest instance measured. chunk_size is
        # large on purpose: every chunk re-runs all four prefetches, and a small
        # chunk measured ~200ms/scan slower for memory that was never scarce.
        appointments = (
            Appointment.objects.filter(
                start_time__gte=now,
                start_time__lte=end_window,
                status__in=["unconfirmed", "attempted", "confirmed"],
            )
            .select_related(
                "patient", "patient__business_line", "provider", "location", "note_type"
            )
            .prefetch_related(
                "patient__telecom",
                "provider__roles",
                "location__addresses",
                "location__telecom",
            )
            .iterator(chunk_size=1000)
        )

        all_effects: list[Effect] = []
        reminders_sent = 0

        for appointment in appointments:
            note_type_id = str(appointment.note_type.id) if appointment.note_type else None
            business_line = get_business_line_name(appointment.patient)
            bl_from_number = get_business_line_from_number(config, business_line)
            enabled, channels, sms_template, email_template, intervals, send_time, send_tz = (
                get_effective_campaign_config(
                    config, note_type_id, "reminder", business_line=business_line
                )
            )

            time_until = appointment.start_time - now
            minutes_until = int(time_until.total_seconds() / 60)

            # Reminder campaign — telehealth is configured independently below
            # and must run regardless of whether reminders are enabled for this
            # appointment's note type.
            if enabled:
                for interval_minutes in intervals:
                    if interval_minutes >= DAY_OUT_THRESHOLD:
                        # Day-out: date-relative with configured send time
                        if not _is_day_out_window(
                            now, appointment.start_time, interval_minutes, send_time, send_tz
                        ):
                            continue
                    else:
                        # Short interval: time-relative. Fire on the first scan
                        # at or after the target moment, never before it.
                        overdue = interval_minutes - minutes_until
                        if overdue < 0 or overdue > GRACE_MINUTES:
                            continue

                    cache_key = f"cr:reminder_sent:{appointment.id}:{interval_minutes}"
                    if cache.get(cache_key):
                        continue

                    # Render both templates with per-type content
                    variables = get_template_variables(
                        appointment.patient, appointment, config.reminder_timezone,
                        config=config,
                    )

                    sms_content = render_template(sms_template, variables)
                    email_content = render_template(email_template, variables)

                    log.info(
                        f"Sending {interval_minutes}-minute reminder for appointment {appointment.id}"
                    )

                    effects, results = deliver_to_patient(
                        appointment.patient,
                        sms_content,
                        email_content,
                        channels,
                        "reminder",
                        self.secrets,
                        str(appointment.id),
                        from_number=bl_from_number,
                        config=config,
                    )
                    all_effects.extend(effects)

                    log_delivery(
                        str(appointment.id),
                        str(appointment.patient.id),
                        "reminder",
                        results,
                        sms_content=sms_content,
                        email_content=email_content,
                    )

                    # Mark as sent
                    ttl_seconds = (max_interval_minutes + 1440) * 60
                    cache.set(cache_key, "1", timeout_seconds=ttl_seconds)

                    reminders_sent += 1

            # --- Telehealth join campaign (alongside reminders) ---
            if not (appointment.note_type and appointment.note_type.is_telehealth):
                continue

            th_enabled, th_channels, th_sms_tpl, th_email_tpl, th_intervals, _th_st, _th_tz = (
                get_effective_campaign_config(
                    config, note_type_id, "telehealth", business_line=business_line
                )
            )
            if not th_enabled or not th_intervals:
                continue

            for interval_minutes in th_intervals:
                # Same first-scan-at-or-after rule as reminders above.
                overdue = interval_minutes - minutes_until
                if overdue < 0 or overdue > GRACE_MINUTES:
                    continue

                th_cache_key = f"cr:telehealth_sent:{appointment.id}:{interval_minutes}"
                if cache.get(th_cache_key):
                    continue

                th_variables = get_template_variables(
                    appointment.patient, appointment, config.reminder_timezone,
                    config=config,
                )

                # Skip if no telehealth link — log failure
                if not th_variables.get("telehealth_link"):
                    log.warning(
                        f"[notify] Telehealth link missing for appointment "
                        f"{appointment.id} — skipping send"
                    )
                    log_delivery(
                        str(appointment.id),
                        str(appointment.patient.id),
                        "telehealth",
                        [_TelehealthFailure()],
                    )
                    ttl_seconds = (max_interval_minutes + 1440) * 60
                    cache.set(th_cache_key, "1", timeout_seconds=ttl_seconds)
                    continue

                th_sms = render_template(th_sms_tpl, th_variables)
                th_email = render_template(th_email_tpl, th_variables)

                log.info(
                    f"Sending telehealth join for appointment {appointment.id} "
                    f"({interval_minutes}-min interval)"
                )

                th_effects, th_results = deliver_to_patient(
                    appointment.patient,
                    th_sms,
                    th_email,
                    th_channels,
                    "telehealth",
                    self.secrets,
                    str(appointment.id),
                    from_number=bl_from_number,
                    config=config,
                )
                all_effects.extend(th_effects)

                log_delivery(
                    str(appointment.id),
                    str(appointment.patient.id),
                    "telehealth",
                    th_results,
                    sms_content=th_sms,
                    email_content=th_email,
                )

                ttl_seconds = (max_interval_minutes + 1440) * 60
                cache.set(th_cache_key, "1", timeout_seconds=ttl_seconds)
                reminders_sent += 1

        log.info(f"Sent {reminders_sent} reminders")
        return all_effects


def _parse_send_time(send_time: str) -> tuple[int, int]:
    """Parse ``HH:MM`` into (hour, minute), falling back to 09:00.

    Defensive because a malformed value would otherwise raise inside the
    per-appointment loop and take down the whole scan — every patient's
    reminders lost to one bad config string.
    """
    if not send_time:
        return _DEFAULT_SEND_HOUR, _DEFAULT_SEND_MINUTE
    parts = send_time.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        log.warning(
            f"Malformed reminder send time {send_time!r}; "
            f"falling back to {_DEFAULT_SEND_HOUR:02d}:{_DEFAULT_SEND_MINUTE:02d}"
        )
        return _DEFAULT_SEND_HOUR, _DEFAULT_SEND_MINUTE
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        log.warning(f"Out-of-range reminder send time {send_time!r}; falling back")
        return _DEFAULT_SEND_HOUR, _DEFAULT_SEND_MINUTE
    return hour, minute


def _scheduled_moment(day: date, send_time: str, send_tz: str) -> datetime:
    """The absolute instant ``send_time`` falls on ``day`` in ``send_tz``."""
    hour, minute = _parse_send_time(send_time)
    tz = zoneinfo.ZoneInfo(send_tz or _DEFAULT_TZ)
    return datetime.combine(day, dt_time(hour, minute), tzinfo=tz)


def _is_day_out_window(
    now: datetime,
    appt_start: datetime,
    interval_minutes: int,
    send_time: str,
    send_tz: str,
) -> bool:
    """Whether a day-out interval is due: at or just after the send time on the
    target date. ``GRACE_MINUTES`` bounds how late the send may be.

    The scheduled instant is anchored to the **target date**, not to ``now``'s
    local date. That distinction is the fix for a real miss: anchoring to ``now``
    meant a send time within ``GRACE_MINUTES`` of the end of the local day could
    never fire at all, because the only ticks inside its grace window landed on
    the following date and were then rejected by a date-equality check. Anchoring
    to the target date lets the window span midnight, and makes that date check
    redundant — being within grace of one specific instant already implies it.
    """
    appt_local = appt_start.astimezone(zoneinfo.ZoneInfo(send_tz or _DEFAULT_TZ))
    interval_days = interval_minutes // 1440
    target_date = (appt_local - timedelta(days=interval_days)).date()
    elapsed = (now - _scheduled_moment(target_date, send_time, send_tz)).total_seconds()
    return 0 <= elapsed <= GRACE_MINUTES * 60


def _in_send_window(now: datetime, send_time: str, send_tz: str) -> bool:
    """Could a day-out reminder on this (send_time, tz) fire right now?

    Appointment-independent, which is what makes it usable as a gate before the
    query runs: the firing instants for a given send time are "that time on some
    local date", so being inside one is a property of ``now`` alone.

    Checks yesterday's instant as well as today's, because a send time near the
    end of the local day has a grace window that spills past midnight — the same
    case ``_is_day_out_window`` handles.
    """
    now_local = now.astimezone(zoneinfo.ZoneInfo(send_tz or _DEFAULT_TZ))
    for days_back in (0, 1):
        day = (now_local - timedelta(days=days_back)).date()
        elapsed = (now - _scheduled_moment(day, send_time, send_tz)).total_seconds()
        if 0 <= elapsed <= GRACE_MINUTES * 60:
            return True
    return False
