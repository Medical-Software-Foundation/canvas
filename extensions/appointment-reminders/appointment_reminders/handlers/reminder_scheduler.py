"""Cron task for scheduled appointment reminders."""
import zoneinfo
from datetime import datetime, timedelta, timezone

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
    save_config,
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


class ReminderScheduler(CronTask):
    """Check for appointments needing reminders every 5 minutes."""

    SCHEDULE = "*/5 * * * *"

    def execute(self) -> list[Effect]:
        """Check appointments and send reminders."""
        config = load_config()

        # Refresh config TTL every time we run
        save_config(config)

        cache = get_cache()
        now = datetime.now(timezone.utc)

        # Compute dynamic end_window from every interval that might fire.
        # Global acts as the master switch; per-type records can extend the
        # window with their own intervals unless they're explicit opt-outs.
        all_intervals: list[int] = []

        if config.reminders_enabled:
            all_intervals.extend(config.reminder_intervals)
        if config.telehealth_enabled:
            all_intervals.extend(config.telehealth_intervals)

        for nt_data in config.note_type_reminders.values():
            nt_cfg = NoteTypeCampaignConfig.from_dict(nt_data)
            if config.reminders_enabled and nt_cfg.reminders_enabled is not False:
                all_intervals.extend(nt_cfg.reminder_intervals)
            if config.telehealth_enabled and nt_cfg.telehealth_enabled is not False:
                all_intervals.extend(nt_cfg.telehealth_intervals)

        if not all_intervals:
            log.info("Reminders and telehealth globally disabled, skipping")
            return []

        max_interval_minutes = max(all_intervals)
        end_window = now + timedelta(minutes=max_interval_minutes + GRACE_MINUTES)

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


def _is_day_out_window(
    now: datetime,
    appt_start: datetime,
    interval_minutes: int,
    send_time: str,
    send_tz: str,
) -> bool:
    """Whether a day-out interval is due: right date, at or just after send time.

    ``GRACE_MINUTES`` bounds how late the send may be.

    Caveat: the date check is local to ``send_tz``, so a send time within
    ``GRACE_MINUTES`` of local midnight can be missed: the next scan falls on
    the following date and no longer matches ``target_date``.
    """
    tz = zoneinfo.ZoneInfo(send_tz or "America/New_York")
    now_local = now.astimezone(tz)
    appt_local = appt_start.astimezone(tz)

    interval_days = interval_minutes // 1440
    target_date = (appt_local - timedelta(days=interval_days)).date()
    if now_local.date() != target_date:
        return False

    # Due once the configured send time has arrived, within one scan's grace
    hour, minute = 9, 0
    if send_time:
        parts = send_time.split(":")
        hour, minute = int(parts[0]), int(parts[1])
    scheduled = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    elapsed_seconds = (now_local - scheduled).total_seconds()
    return 0 <= elapsed_seconds <= GRACE_MINUTES * 60
