"""Cron task for scheduled appointment reminders and telehealth join notifications."""
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

if TYPE_CHECKING:
    from canvas_sdk.caching.base import Cache

from patient_notify.services.config import (
    CampaignConfig,
    NoteTypeCampaignConfig,
    get_effective_campaign_config,
    load_config,
    resolve_templates,
    save_config,
)
from patient_notify.services.delivery import deliver_to_patient
from patient_notify.services.history import log_delivery_to_cache
from patient_notify.services.templates import get_template_variables, render_template


class ReminderScheduler(CronTask):
    """Check for appointments needing reminders every 15 minutes."""

    SCHEDULE = "*/15 * * * *"

    def execute(self) -> list[Effect]:
        """Check appointments and send reminders and telehealth join notifications."""
        config = load_config()

        # Refresh config TTL every time we run
        save_config(config)

        cache = get_cache()
        now = datetime.now(timezone.utc)

        # Compute dynamic end_window from all interval-based campaigns
        all_intervals: list[int] = []
        for nt_data in config.note_type_campaigns.values():
            nt_cfg = NoteTypeCampaignConfig.from_dict(nt_data)
            if nt_cfg.reminders_enabled:
                all_intervals.extend(nt_cfg.reminder_intervals)
            if nt_cfg.telehealth_enabled:
                all_intervals.extend(nt_cfg.telehealth_intervals)

        # Also include global telehealth intervals
        if config.telehealth_enabled:
            all_intervals.extend(config.telehealth_intervals)

        # Also include global reminder intervals so visit types without an
        # explicit reminder override still drive the scheduler window.
        if config.reminders_enabled:
            all_intervals.extend(config.reminder_intervals)

        if not all_intervals:
            log.info("No per-type reminders or telehealth notifications configured, skipping")
            return []

        max_interval_minutes = max(all_intervals)
        end_window = now + timedelta(minutes=max_interval_minutes + 15)

        # Only query booked appointments (excludes canceled, no-showed, etc.)
        appointments = (
            Appointment.objects.filter(
                start_time__gte=now,
                start_time__lte=end_window,
                status__in=["unconfirmed", "attempted", "confirmed"],
            )
            .select_related("patient", "provider", "location", "note_type")
            .prefetch_related("patient__telecom")
        )

        all_effects: list[Effect] = []
        reminders_sent = 0

        for appointment in appointments:
            note_type = appointment.note_type
            note_type_id = str(note_type.id) if note_type else None

            # Process reminders
            r_enabled, r_intervals, r_channels, _r_sms, _r_email, r_send_time = (
                get_effective_campaign_config(config, "reminders", note_type_id)
            )
            if r_enabled:
                r_sms, r_email = resolve_templates(config, "reminders", note_type_id)
                sent = self._process_intervals(
                    appointment, now, r_intervals, r_channels, r_sms, r_email,
                    "reminder", "cr:reminder_sent", config, cache,
                    max_interval_minutes, r_send_time,
                )
                all_effects.extend(sent)
                reminders_sent += len(sent)

            # Process telehealth join notifications
            is_telehealth = False
            if note_type:
                try:
                    is_telehealth = note_type.is_telehealth
                except Exception:
                    pass

            if is_telehealth:
                t_enabled, t_intervals, t_channels, _t_sms, _t_email, _t_send_time = (
                    get_effective_campaign_config(config, "telehealth", note_type_id)
                )
                if t_enabled:
                    t_sms, t_email = resolve_templates(config, "telehealth", note_type_id)
                    sent = self._process_intervals(
                        appointment, now, t_intervals, t_channels, t_sms, t_email,
                        "telehealth", "cr:telehealth_sent", config, cache,
                        max_interval_minutes, "",
                    )
                    all_effects.extend(sent)
                    reminders_sent += len(sent)

        log.info(f"Sent {reminders_sent} notifications")
        return all_effects

    def _process_intervals(
        self,
        appointment: Appointment,
        now: datetime,
        intervals: list[int],
        channels: list[str],
        sms_template: str,
        email_template: str,
        campaign_type: str,
        cache_prefix: str,
        config: CampaignConfig,
        cache: "Cache",
        max_interval_minutes: int,
        send_time: str = "",
    ) -> list[Effect]:
        """Process interval-based notifications for a single appointment."""
        effects: list[Effect] = []
        time_until = appointment.start_time - now
        minutes_until = int(time_until.total_seconds() / 60)

        for interval_minutes in intervals:
            # Reminders use configured send time, telehealth uses raw offset
            if campaign_type == "reminder":
                if not self._is_reminder_send_window(
                    appointment, now, interval_minutes, config, send_time,
                ):
                    continue
            elif abs(minutes_until - interval_minutes) > 15:
                continue

            cache_key = f"{cache_prefix}:{appointment.id}:{interval_minutes}"
            if cache.get(cache_key):
                continue

            variables = get_template_variables(
                appointment.patient, appointment,
                config=config, note_type=appointment.note_type,
            )
            variables["minutes_until"] = str(interval_minutes)
            sms_content = render_template(sms_template, variables)
            email_content = render_template(email_template, variables)

            log.info(
                f"Sending {interval_minutes}-minute {campaign_type} "
                f"notification for appointment {appointment.id}"
            )

            new_effects, results = deliver_to_patient(
                appointment.patient,
                sms_content,
                email_content,
                channels,
                campaign_type,
                self.secrets,
            )
            effects.extend(new_effects)

            log_delivery_to_cache(
                str(appointment.id),
                str(appointment.patient.id),
                campaign_type,
                results,
            )

            # Mark as sent
            ttl_seconds = (max_interval_minutes + 1440) * 60
            cache.set(cache_key, "1", timeout_seconds=ttl_seconds)

        return effects

    @staticmethod
    def _is_reminder_send_window(
        appointment: Appointment,
        now: datetime,
        interval_minutes: int,
        config: CampaignConfig,
        send_time: str = "",
    ) -> bool:
        """Check whether now falls within the 15-minute send window for a reminder interval.

        The target delivery time is the appointment date minus N days, at the
        given send time in the configured timezone. If send_time is empty,
        falls back to the global config value.
        """
        days_out = interval_minutes // 1440
        appt_date = appointment.start_time.date()
        target_date = appt_date - timedelta(days=days_out)

        send_time = send_time or config.day_out_send_time or "09:00"
        tz_name = config.day_out_timezone or "America/New_York"

        try:
            tz = ZoneInfo(tz_name)
        except (KeyError, Exception):
            tz = ZoneInfo("America/New_York")

        parts = send_time.split(":")
        hour = int(parts[0]) if len(parts) >= 1 else 9
        minute = int(parts[1]) if len(parts) >= 2 else 0

        target_dt = datetime(
            target_date.year, target_date.month, target_date.day,
            hour, minute, tzinfo=tz,
        )
        target_utc = target_dt.astimezone(timezone.utc)
        return abs((now - target_utc).total_seconds() / 60) <= 15
