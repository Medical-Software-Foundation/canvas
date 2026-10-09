"""CronTask to refresh cache TTLs, re-sync daily, and maintain lead-time blocks."""

from __future__ import annotations

from datetime import date, timedelta


from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from provider_availability.engine.admin_calendar import missing_clinic_calendar_effects
from provider_availability.engine.roles import (
    get_schedulable_provider_ids,
    get_schedulable_staff,
)
from provider_availability.engine.event_sync import (
    build_provider_hold_refresh_effects,
    build_provider_lead_time_effects,
    lead_time_rules,
    sync_provider_availability,
)
from provider_availability.engine.storage import (
    get_all_recurring_blocks,
    get_all_rules,
    get_last_sync_date,
    get_seen_schedulable_ids,
    refresh_all_ttls,
    set_last_sync_date,
    set_seen_schedulable_ids,
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

        # Detect day rollover BEFORE _daily_resync (which updates the sync date).
        day_changed = get_last_sync_date() != date.today().isoformat()

        try:
            schedulable = get_schedulable_staff()
        except Exception:
            # A failed lookup must not stop the lead-time, daily and hold
            # refreshes below, which do not depend on it.
            log.exception("CacheRefreshTask: schedulable staff lookup failed")
            schedulable = None
        effects = _ensure_provider_calendars(schedulable) if schedulable is not None else []

        # Who is bookable changes outside the plugin too: a role edited on a
        # staff record, someone activated or deactivated, or the Provider role
        # type fallback switching on or off. Rebuild availability when it does.
        if schedulable is not None:
            effects.extend(_reconcile_if_schedulable_changed({str(s.id) for s in schedulable}))

        # Daily re-sync: when the date changes, re-sync all rules
        # so recurrence_ends_at advances for effective_end enforcement
        effects.extend(_daily_resync())

        # Refresh lead-time blocks every cron tick (the lead window slides continuously)
        effects.extend(_refresh_lead_time_blocks())

        # Refresh hold-type blocks once per day. The hold window advances by whole
        # days, so rebuilding every tick only re-emits identical events (and runs
        # delete/create DB work) 287 extra times a day.
        if day_changed:
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
            has_schedule = rule.time_windows if rule.recurrence_frequency == "daily" else rule.weekly_schedule
            if not (rule.is_active and has_schedule):
                continue
            # Rule just became active today
            if rule.effective_start and rule.effective_start == today:
                providers_to_sync.add(rule.provider_id)
            # Rule expired yesterday — remove its events
            if rule.effective_end and rule.effective_end == yesterday:
                providers_to_sync.add(rule.provider_id)
        if providers_to_sync:
            schedulable_ids = get_schedulable_provider_ids()
            for pid in providers_to_sync:
                effects.extend(sync_provider_availability(pid, schedulable_ids=schedulable_ids))
        set_last_sync_date(today_str)
        log.info("daily_resync: checked %d rules, re-synced %d providers", len(rules), len(providers_to_sync))
    except Exception:
        log.exception("daily_resync: error re-syncing rules")

    return effects


def _refresh_lead_time_blocks() -> list[Effect]:
    """Refresh lead-time blocks for all rules with min_lead_hours > 0."""
    effects: list[Effect] = []
    try:
        # One pass per provider: lead-time events are per provider, so building
        # them rule by rule made each rule delete the others' events every tick.
        by_provider: dict[str, list] = {}
        for rule in lead_time_rules(get_all_rules()):
            by_provider.setdefault(rule.provider_id, []).append(rule)
        for provider_id, rules in by_provider.items():
            effects.extend(build_provider_lead_time_effects(provider_id, rules))
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
        # One pass per provider: hold events are found by title per provider, so
        # refreshing block by block deleted the same events once per hold block.
        by_provider: dict[str, list] = {}
        for block in get_all_recurring_blocks():
            if block.is_active and block.hold_type != "none":
                by_provider.setdefault(block.provider_id, []).append(block)
        for provider_id, blocks in by_provider.items():
            effects.extend(build_provider_hold_refresh_effects(provider_id, blocks))
    except Exception:
        log.exception("_refresh_hold_blocks: error refreshing hold blocks")
    return effects


def _reconcile_if_schedulable_changed(schedulable_ids: set[str]) -> list[Effect]:
    """Re-sync every provider's availability when the schedulable set changed.

    The first tick after install only records the set: install already ran a
    full sync against it.
    """
    try:
        seen = get_seen_schedulable_ids()
        if seen is None:
            set_seen_schedulable_ids(sorted(schedulable_ids))
            return []
        if set(seen) == schedulable_ids:
            return []
        log.info(
            "schedulable set changed: %d added, %d removed, reconciling availability",
            len(schedulable_ids - set(seen)), len(set(seen) - schedulable_ids),
        )
        from provider_availability.api.availability_api import _reconcile_availability_to_roles

        # Only the people who gained or lost bookability; everyone else is unchanged.
        return _reconcile_availability_to_roles(only=schedulable_ids ^ set(seen))
    except Exception:
        log.exception("_reconcile_if_schedulable_changed: error reconciling")
        return []


def _ensure_provider_calendars(active_providers: list | None = None) -> list[Effect]:
    """Create Clinic calendars for any active providers missing one."""
    effects: list[Effect] = []
    try:
        if active_providers is None:
            active_providers = get_schedulable_staff()
        effects.extend(missing_clinic_calendar_effects(active_providers))
        created = len(effects)
        if created:
            log.info("ensure_calendars: created %d new Clinic calendars", created)
    except Exception:
        log.exception("ensure_calendars: error checking/creating calendars")

    return effects
