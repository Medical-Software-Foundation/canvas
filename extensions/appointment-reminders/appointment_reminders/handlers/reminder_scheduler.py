"""Cron task for scheduled appointment reminders."""
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

from appointment_reminders.services.claims import (
    REMINDER,
    TELEHEALTH,
    claim_store,
)
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
from appointment_reminders.services.templates import (
    get_template_variables,
    render_template,
    resolve_timezone_name,
)

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


def scan_queryset(now: datetime, end_window: datetime):
    """The appointments a scan considers, bounded to the window.

    Module level so tests assert against the real query rather than a copy of
    it. A test that rebuilds this by hand drifts the moment someone edits one
    and not the other, and then guards nothing — which is exactly the failure it
    would be there to prevent.

    Only booked statuses: canceled and no-showed appointments are excluded here
    rather than skipped in the loop.

    Every prefetch below is read per appointment inside the loop and filtered in
    Python, so a dropped lookup does not fail, it silently becomes one query per
    row across the whole window.
    """
    return (
        Appointment.objects.filter(
            start_time__gte=now,
            start_time__lte=end_window,
            status__in=["unconfirmed", "attempted", "confirmed"],
        )
        .select_related(
            "patient", "patient__business_line", "provider", "location", "note_type"
        )
        .prefetch_related(
            # Delivery picks the phone and email off this.
            "patient__telecom",
            # The timezone resolver reads the chart's chosen scheduling timezone
            # first and falls back to the address, so both are needed.
            "patient__settings",
            "patient__addresses",
            "provider__roles",
            "location__addresses",
            "location__telecom",
        )
    )


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

        now = datetime.now(timezone.utc)
        claims = claim_store()

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

        # Housekeeping runs before either early return below. Claims have no
        # automatic expiry now that they are rows rather than cache entries, so
        # a prune that only ran on ticks which reach the send loop would stop
        # entirely whenever the gate skipped the scan or campaigns were turned
        # off — leaving the table to grow with nothing left to clear it. Bounded
        # per run, and a no-op query on the ticks with nothing to delete.
        claims.prune(max(all_intervals, default=DAY_OUT_THRESHOLD))

        if not all_intervals:
            log.info("Reminders and telehealth globally disabled, skipping")
            return []

        # Gate: skip the appointment query entirely when nothing can fire on this
        # tick. Every telehealth interval and every sub-day reminder interval is
        # time-relative, so those can fire at any tick and force the scan. But a
        # day-out reminder can only fire in the grace window after its send time,
        # which is a property of `now` and a timezone alone. Business-line
        # overrides cannot set a send time or interval, so the global setting
        # plus per-visit-type overrides are the complete set of send times.
        #
        # The timezone half of that is per patient: a day-out reminder fires at
        # its send time in the *patient's* zone, so the gate has to ask whether
        # that instant is passing anywhere a patient can resolve to.
        #
        # This asked it of RESOLVABLE_ZONES, the eleven zones `timezones.py` can
        # derive from a US address. That is narrower than what the resolver can
        # return, and not by a little: the chart's preferredSchedulingTimezone
        # holds any IANA name, and one production instance has patients on
        # America/Detroit, America/Indiana/Indianapolis, America/Kentucky/
        # Louisville and America/Menominee, none of which an address resolves
        # to. A patient on a zone outside the eleven had their day-out reminder
        # dropped on the tick it was due, and the only trace was a log line that
        # reads like a normal quiet tick.
        #
        # Asking about UTC offsets instead makes the gate complete: what decides
        # whether a local clock reads the send time is the offset, not the zone
        # name, and there are 38 distinct offsets against 598 zones. Day-out-only
        # instances still skip ~82% of ticks rather than ~96%, and the gate is
        # only an optimization — _is_day_out_window still makes the exact
        # per-appointment decision, so a wider gate changes how many ticks run
        # the query, never which reminders fire. Under-inclusion was the bug.
        time_relative = [i for i in reminder_intervals if i < DAY_OUT_THRESHOLD]
        time_relative.extend(telehealth_intervals)
        if not time_relative and not _any_send_time_passing(now, send_windows):
            log.info("No interval can fire on this tick; skipping the scan")
            return []

        # A day-out interval does not fire on a duration. It fires at `send_time`
        # on (appointment's local date - interval_days), and the appointment can
        # sit anywhere within that date — so its real lead time runs from just
        # over interval_days days to a full day more. Sizing the scan window by
        # the raw interval therefore dropped every eligible appointment past
        # interval_minutes + grace, silently: no log line, no error.
        #
        # Measured on a live instance with reminder_intervals [1440] and a 09:00 ET
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

        # Single pass, so .iterator() bounds peak memory over a window that held
        # ~3.4k appointments on the busiest instance measured. chunk_size is
        # large on purpose: every chunk re-runs all the prefetches, and a small
        # chunk measured ~200ms/scan slower for memory that was never scarce.
        appointments = scan_queryset(now, end_window).iterator(chunk_size=1000)

        all_effects: list[Effect] = []
        reminders_sent = 0

        for appointment in appointments:
            # Appointment.patient is a nullable FK: admin blocks, provider
            # availability blocks and imported calendar holds are real rows with
            # patient_id NULL. They carry a real note_type, so they resolve to the
            # global config and come back enabled, and the first thing the send path
            # does is read patient.first_name. The sibling patient_communications
            # plugins all carry this guard; it was dropped when this plugin was
            # split out of that one.
            if not appointment.patient:
                continue

            # Per-appointment isolation. CLAUDE.md says not to wrap handler logic in
            # a bare except, and that is right for a request handler — but this is a
            # batch loop, and without it one bad row takes out every appointment
            # after it in iteration order. The day-out path makes that expensive: it
            # gets one grace window per day, so a single failure costs a whole day of
            # reminders. log.exception keeps the traceback, so nothing is hidden.
            try:
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

                # The zone the message will be rendered in is also the zone its
                # send time is measured in, so "9:00 AM" means 9:00 AM where the
                # patient is. Resolved once per appointment and reused by both
                # the firing check and the template variables below. The
                # configured zone stays as the fallback for a patient whose own
                # is unknown.
                patient_tz = resolve_timezone_name(appointment.patient, send_tz)

                # Reminder campaign — telehealth is configured independently below
                # and must run regardless of whether reminders are enabled for this
                # appointment's note type.
                if enabled:
                    for interval_minutes in intervals:
                        if interval_minutes >= DAY_OUT_THRESHOLD:
                            # Day-out: date-relative with configured send time
                            if not _is_day_out_window(
                                now,
                                appointment.start_time,
                                interval_minutes,
                                send_time,
                                patient_tz,
                            ):
                                continue
                        else:
                            # Short interval: time-relative. Fire on the first scan
                            # at or after the target moment, never before it.
                            overdue = interval_minutes - minutes_until
                            if overdue < 0 or overdue > GRACE_MINUTES:
                                continue

                        claim_key = f"{appointment.id}:{interval_minutes}"
                        # Cheap pre-check to skip the render work for an interval
                        # already handled. The authoritative, race-safe claim is
                        # `claim` below, immediately before the send.
                        if claims.already_claimed(REMINDER, claim_key):
                            continue

                        # Render both templates with per-type content
                        # Rendered in the same zone the send fired in. Passing
                        # the already-resolved zone rather than the configured
                        # default is what keeps the two from disagreeing when a
                        # visit type overrides the timezone.
                        variables = get_template_variables(
                            appointment.patient, appointment, patient_tz,
                            config=config,
                        )

                        sms_content = render_template(sms_template, variables)
                        email_content = render_template(email_template, variables)

                        # Claimed after rendering, so a template failure does not
                        # burn the claim on a send that never happened.
                        if not claims.claim(REMINDER, claim_key):
                            continue

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
                            # Already loaded by the scan's select_related; without
                            # this the audit write re-reads the same patient row
                            # once per delivery.
                            patient=appointment.patient,
                        )

                        if _send_should_be_retried(results):
                            claims.release(REMINDER, claim_key)
                            log.warning(
                                f"[notify] Nothing delivered for appointment "
                                f"{appointment.id} at {interval_minutes} minutes; "
                                "releasing the claim so a later tick retries"
                            )
                        else:
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

                    th_claim_key = f"{appointment.id}:{interval_minutes}"
                    # Cheap pre-check; the race-safe claim is `claim` below.
                    if claims.already_claimed(TELEHEALTH, th_claim_key):
                        continue

                    th_variables = get_template_variables(
                        appointment.patient, appointment, config.reminder_timezone,
                        config=config,
                    )

                    # Skip if no telehealth link — log failure
                    if not th_variables.get("telehealth_link"):
                        # Claimed too, and deliberately never released: a missing
                        # link does not resolve itself within the window, so
                        # without the claim this would re-log the same failure
                        # row every tick. The claim also keeps an overlapping
                        # invocation from logging it a second time.
                        if not claims.claim(TELEHEALTH, th_claim_key):
                            continue
                        log.warning(
                            f"[notify] Telehealth link missing for appointment "
                            f"{appointment.id} — skipping send"
                        )
                        log_delivery(
                            str(appointment.id),
                            str(appointment.patient.id),
                            "telehealth",
                            [_TelehealthFailure()],
                            patient=appointment.patient,
                        )
                        continue

                    th_sms = render_template(th_sms_tpl, th_variables)
                    th_email = render_template(th_email_tpl, th_variables)

                    if not claims.claim(TELEHEALTH, th_claim_key):
                        continue

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
                        patient=appointment.patient,
                    )

                    if _send_should_be_retried(th_results):
                        claims.release(TELEHEALTH, th_claim_key)
                        log.warning(
                            f"[notify] Nothing delivered for telehealth join on "
                            f"appointment {appointment.id} at {interval_minutes} "
                            "minutes; releasing the claim so a later tick retries"
                        )
                    else:
                        reminders_sent += 1

            except Exception:
                log.exception(
                    f"Failed to process appointment {appointment.id}; "
                    "skipping it and continuing the scan"
                )
                continue
        log.info(f"Sent {reminders_sent} reminders")
        return all_effects


def _send_should_be_retried(results: list) -> bool:
    """Whether a claim should be released so a later tick can try again.

    Claiming up front trades duplicate sends for missed ones: a claim that is
    never released means nothing retries. Releasing when the send genuinely
    failed keeps that trade from costing a patient their reminder, and the
    remaining ticks inside the grace window are the retries.

    Released only when *nothing* went out. If one channel succeeded, retrying
    would re-send it, which is the duplicate this whole mechanism exists to
    prevent. A ``skipped:`` result is not a failure to retry either — no phone
    on file, no configured keys, and testing mode all resolve to the same answer
    on the next tick, so releasing would just re-log the same row every 5
    minutes for the life of the window.
    """
    if not results:
        return False
    if any(r.success for r in results):
        return False
    return any(not str(r.error or "").startswith("skipped:") for r in results)


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


def _utc_offsets_in_effect(at: datetime) -> set[timedelta]:
    """Every UTC offset in force somewhere in the world at ``at``.

    Enumerated from the tz database rather than hardcoded, because the set is
    seasonal: a zone's offset changes at its DST transitions, so a static list
    would be wrong for part of the year. About 38 distinct offsets fall out of
    598 zones, and the walk costs ~30ms — paid only on ticks where the gate is
    actually consulted, and cheap against the appointment query it decides
    whether to skip.

    A zone that fails to load is skipped rather than raised on. The gate must
    not be the thing that takes down a scan.
    """
    offsets: set[timedelta] = set()
    for name in zoneinfo.available_timezones():
        try:
            offset = zoneinfo.ZoneInfo(name).utcoffset(at)
        except Exception:
            continue
        if offset is not None:
            offsets.add(offset)
    return offsets


def _send_time_passing_at_offset(
    now: datetime, send_time: str, offset: timedelta
) -> bool:
    """Whether a clock at ``offset`` currently reads within grace of ``send_time``."""
    hour, minute = _parse_send_time(send_time)
    local = now + offset
    local_seconds = local.hour * 3600 + local.minute * 60 + local.second
    target_seconds = hour * 3600 + minute * 60
    # Modulo rather than a same-date subtraction, so a send time near the end of
    # the day whose grace window spills past midnight is still matched — the same
    # case ``_is_day_out_window`` handles by anchoring to the target date.
    return 0 <= (local_seconds - target_seconds) % 86400 <= GRACE_MINUTES * 60


def _any_send_time_passing(
    now: datetime, send_windows: set[tuple[str, str]]
) -> bool:
    """Could a day-out reminder fire right now, for a patient in any timezone?

    Appointment-independent, which is what makes it usable before the query
    runs: the firing instants for a send time are "that time on some local
    clock", so being inside one is a property of ``now`` and an offset alone.

    The configured zone in each window is ignored on purpose. It is one zone
    among the ones patients resolve to, and its offset is already in the set.
    """
    if not send_windows:
        return False
    offsets = _utc_offsets_in_effect(now)
    return any(
        _send_time_passing_at_offset(now, send_time, offset)
        for send_time, _send_tz in send_windows
        for offset in offsets
    )
