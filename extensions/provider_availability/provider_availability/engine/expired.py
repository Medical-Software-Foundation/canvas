"""Items that ended a while ago, and the choice to clear them from the admin lists.

Nothing here touches calendars: removing an item drops it from the plugin's
storage only, so the past calendar events it created stay in Canvas.
"""

from __future__ import annotations

from datetime import date, timedelta

from logger import log

from provider_availability.engine.storage import (
    delete_block,
    delete_event_ids,
    delete_recurring_block,
    delete_rule_by_id,
    get_all_blocks,
    get_all_recurring_blocks,
    get_all_rules,
    get_expired_snoozes,
    save_rule,
    set_expired_snoozes,
)

# Items that ended more than this many days ago are offered for removal.
EXPIRED_KEEP_DAYS = 30
# "Ask again later" hides the question for this many days, per provider.
SNOOZE_DAYS = 30


def _cutoff(today: date) -> date:
    return today - timedelta(days=EXPIRED_KEEP_DAYS)


def count_expired(provider_ids: list[str], today: date | None = None) -> dict[str, int]:
    """Count items per provider that ended before the cutoff. Providers with none are left out."""
    wanted = set(provider_ids)
    cutoff = _cutoff(today or date.today())
    counts: dict[str, int] = {}

    def add(pid: str, n: int = 1) -> None:
        if n and pid in wanted:
            counts[pid] = counts.get(pid, 0) + n

    for rule in get_all_rules():
        if rule.effective_end and rule.effective_end < cutoff:
            add(rule.provider_id)
        else:
            add(rule.provider_id, sum(1 for o in rule.date_overrides if o.date < cutoff))
    for block in get_all_blocks():
        if block.end.date() < cutoff:
            add(block.provider_id)
    for rb in get_all_recurring_blocks():
        if rb.effective_end and rb.effective_end < cutoff:
            add(rb.provider_id)
    return counts


def expired_summary(provider_ids: list[str], today: date | None = None) -> dict:
    """What the banner offers: expired items for these providers, minus any still snoozed."""
    today = today or date.today()
    snoozes = get_expired_snoozes()
    counts = {
        pid: n
        for pid, n in count_expired(provider_ids, today).items()
        if not (snoozes.get(pid) and date.fromisoformat(snoozes[pid]) > today)
    }
    return {"count": sum(counts.values()), "provider_ids": sorted(counts)}


def remove_expired(provider_ids: list[str], today: date | None = None) -> int:
    """Drop these providers' items that ended before the cutoff. Storage only; returns how many."""
    wanted = set(provider_ids)
    cutoff = _cutoff(today or date.today())
    removed = 0
    for rule in get_all_rules():
        if rule.provider_id not in wanted:
            continue
        if rule.effective_end and rule.effective_end < cutoff:
            delete_rule_by_id(rule.provider_id, rule.id)
            delete_event_ids(rule.id)
            removed += 1
            continue
        kept = [o for o in rule.date_overrides if o.date >= cutoff]
        if len(kept) < len(rule.date_overrides):
            removed += len(rule.date_overrides) - len(kept)
            rule.date_overrides = kept
            save_rule(rule)
    for block in get_all_blocks():
        if block.provider_id in wanted and block.end.date() < cutoff:
            delete_block(block.provider_id, block.id)
            delete_event_ids(block.id)
            removed += 1
    for rb in get_all_recurring_blocks():
        if rb.provider_id in wanted and rb.effective_end and rb.effective_end < cutoff:
            delete_recurring_block(rb.provider_id, rb.id)
            delete_event_ids(rb.id)
            removed += 1
    log.info("remove_expired: dropped %d items for %d providers", removed, len(wanted))
    return removed


def snooze_expired(provider_ids: list[str], today: date | None = None) -> date:
    """Hide the question for these providers until SNOOZE_DAYS from today. Returns that date."""
    until = (today or date.today()) + timedelta(days=SNOOZE_DAYS)
    snoozes = get_expired_snoozes()
    for pid in provider_ids:
        snoozes[pid] = until.isoformat()
    # Drop snoozes that have run out so the stored map does not grow forever.
    today_iso = (today or date.today()).isoformat()
    set_expired_snoozes({pid: d for pid, d in snoozes.items() if d > today_iso})
    return until
