"""CronTask to refresh cache TTLs, re-sync daily, and maintain lead-time blocks."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4


from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff
from logger import log

from provider_availability.engine.event_sync import (
    build_hold_block_refresh_effects,
    build_lead_time_block_effects,
    sync_provider_availability,
)
from provider_availability.engine.storage import (
    get_all_recurring_blocks,
    get_all_rules,
    get_last_sync_date,
    refresh_all_ttls,
    set_last_sync_date,
    should_refresh_ttls,
)

LAST_SYNC_KEY = "pa:last_sync_date"


class CacheRefreshTask(CronTask):
    """Refresh TTLs on all cached availability rules and admin blocks.

    Also ensures Clinic calendars exist for all active providers,
    performs a daily re-sync of availability events, and refreshes
    lead-time blocks.
    """

    SCHEDULE = "*/5 * * * *"

    def execute(self) -> list[Effect]:
        if should_refresh_ttls():
            refreshed = refresh_all_ttls()
            log.info(f"Cache TTL refresh complete: {refreshed} keys refreshed")
        else:
            refreshed = 0

        effects = _ensure_provider_calendars()

        # Daily re-sync: when the date changes, re-sync all rules
        # so recurrence_ends_at advances for effective_end enforcement
        effects.extend(_daily_resync())

        # Refresh lead-time blocks every cron tick
        effects.extend(_refresh_lead_time_blocks())

        # Refresh hold-type blocks daily (same schedule as daily resync)
        effects.extend(_refresh_hold_blocks())

        return effects


def _daily_resync() -> list[Effect]:
    """Re-sync rules whose effective dates cross today's boundary.

    Only resyncs rules that:
    - Just became active (effective_start == today)
    - Just expired (effective_end == yesterday)
    Rules with a 25-year horizon or no date bounds don't need daily churn.
    """
    effects: list[Effect] = []
    today_str = date.today().isoformat()
    last_sync = get_last_sync_date()

    if last_sync == today_str:
        return effects

    today = date.today()
    yesterday = today - timedelta(days=1)

    try:
        rules = get_all_rules()
        providers_to_sync: set[str] = set()
        for rule in rules:
            if not (rule.is_active and rule.weekly_schedule):
                continue
            # Rule just became active today
            if rule.effective_start and rule.effective_start == today:
                providers_to_sync.add(rule.provider_id)
            # Rule expired yesterday — remove its events
            if rule.effective_end and rule.effective_end == yesterday:
                providers_to_sync.add(rule.provider_id)
        for pid in providers_to_sync:
            effects.extend(sync_provider_availability(pid))
        set_last_sync_date(today_str)
        log.info("daily_resync: checked %d rules, re-synced %d providers", len(rules), len(providers_to_sync))
    except Exception:
        log.exception("daily_resync: error re-syncing rules")

    return effects


def _refresh_lead_time_blocks() -> list[Effect]:
    """Refresh lead-time blocks for all rules with min_lead_hours > 0."""
    effects: list[Effect] = []
    try:
        rules = get_all_rules()
        for rule in rules:
            if rule.is_active and rule.booking_interval.min_lead_hours > 0:
                effects.extend(build_lead_time_block_effects(rule))
    except Exception:
        log.exception("_refresh_lead_time_blocks: error refreshing lead-time blocks")
    return effects


def _refresh_hold_blocks() -> list[Effect]:
    """Refresh hold-type recurring block events.

    For each hold-type recurring block, delete existing hold events and
    recreate for the current rolling window. This naturally handles
    the daily release — each day, the earliest blocked date gets freed.
    """
    effects: list[Effect] = []
    try:
        blocks = get_all_recurring_blocks()
        for block in blocks:
            if block.is_active and block.hold_type != "none":
                effects.extend(build_hold_block_refresh_effects(block))
    except Exception:
        log.exception("_refresh_hold_blocks: error refreshing hold blocks")
    return effects


def _ensure_provider_calendars() -> list[Effect]:
    """Create Clinic calendars for any active providers missing one."""
    effects: list[Effect] = []
    try:
        active_providers = Staff.objects.filter(
            active=True, roles__role_type="PROVIDER"
        ).distinct()

        created = 0
        for staff in active_providers:
            staff_key = str(staff.id)
            existing = CalendarModel.objects.filter(description=staff_key).first()
            if existing:
                continue

            calendar_id = str(uuid4())
            cal_effect = CalendarEffect(
                id=calendar_id,
                provider=staff_key,
                type=CalendarType.Clinic,
                description=staff_key,
            ).create()
            effects.append(cal_effect)
            created += 1
            log.info(
                "ensure_calendars: created Clinic calendar for %s %s (%s)",
                staff.first_name,
                staff.last_name,
                staff_key,
            )

        if created:
            log.info("ensure_calendars: created %d new Clinic calendars", created)
    except Exception:
        log.exception("ensure_calendars: error checking/creating calendars")

    return effects
