"""Items that ended a while ago, and the choice to clear them from the admin lists.

Nothing here touches calendars: removing an item drops it from the plugin's
storage only, so the past calendar events it created stay in Canvas.

Each item has a key ("rule:<id>", "override:<rule id>:<date>", "block:<id>",
"recurring:<id>") so the review panel can remove or snooze exactly the ones
picked. Snoozes are per item: something else that ends later still brings
the banner back.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

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
# "Ask again later" hides an item for this many days.
SNOOZE_DAYS = 30

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ABBR = {"monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu", "friday": "Fri", "saturday": "Sat", "sunday": "Sun"}


def _cutoff(today: date) -> date:
    return today - timedelta(days=EXPIRED_KEEP_DAYS)


def _clock(t: Any) -> str:
    """9:00 AM style, from a time or datetime."""
    hour = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {suffix}"


def _windows(windows: list) -> str:
    return ", ".join(f"{_clock(w.start)} – {_clock(w.end)}" for w in windows)


def _weekly(schedule: dict, daily_windows: list | None = None) -> str:
    """'Mon, Wed 9:00 AM – 3:00 PM' from a weekly schedule; 'Daily …' for daily rules."""
    if daily_windows:
        return f"Daily {_windows(daily_windows)}"
    days = [d for d in _DAYS if schedule.get(d)]
    if not days:
        return ""
    first = _windows(schedule[days[0]])
    same = all(_windows(schedule[d]) == first for d in days)
    label = ", ".join(_ABBR[d] for d in days)
    return f"{label} {first}" if same else f"{label} (varies by day)"


def _short_date(d: date) -> str:
    return f"{_ABBR[_DAYS[d.weekday()]]} {d.month}/{d.day}"


def list_expired(provider_ids: list[str], today: date | None = None) -> list[dict]:
    """Every item for these providers that ended before the cutoff, oldest first per provider."""
    wanted = set(provider_ids)
    cutoff = _cutoff(today or date.today())
    items: list[dict] = []

    for rule in get_all_rules():
        if rule.provider_id not in wanted:
            continue
        if rule.effective_end and rule.effective_end < cutoff:
            daily = rule.time_windows if rule.recurrence_frequency == "daily" else None
            items.append({
                "key": f"rule:{rule.id}", "provider_id": rule.provider_id, "kind": "available",
                "when": _weekly(rule.weekly_schedule, daily), "reason": rule.reason, "ended": rule.effective_end.isoformat(),
            })
            continue
        for o in rule.date_overrides:
            if o.date < cutoff:
                items.append({
                    "key": f"override:{rule.id}:{o.date.isoformat()}", "provider_id": rule.provider_id, "kind": "override",
                    "when": f"{_short_date(o.date)} " + ("closed" if o.is_closed else _windows(o.time_windows)),
                    "reason": o.reason, "ended": o.date.isoformat(),
                })

    for block in get_all_blocks():
        if block.provider_id in wanted and block.end.date() < cutoff:
            span = "all day" if block.all_day else f"{_clock(block.start)} – {_clock(block.end)}"
            items.append({
                "key": f"block:{block.id}", "provider_id": block.provider_id, "kind": "blocked",
                "when": f"{_short_date(block.start.date())} {span}", "reason": block.reason, "ended": block.end.date().isoformat(),
            })

    for rb in get_all_recurring_blocks():
        if rb.provider_id in wanted and rb.effective_end and rb.effective_end < cutoff:
            daily = rb.time_windows if rb.recurrence_frequency == "daily" else None
            items.append({
                "key": f"recurring:{rb.id}", "provider_id": rb.provider_id,
                "kind": "hold" if rb.hold_type != "none" else "blocked",
                "when": _weekly(rb.weekly_schedule, daily), "reason": rb.reason, "ended": rb.effective_end.isoformat(),
            })

    items.sort(key=lambda i: (i["provider_id"], i["ended"]))
    return items


def expired_summary(provider_ids: list[str], today: date | None = None) -> dict:
    """What the banner and panel offer: expired items for these providers, minus any still snoozed."""
    today = today or date.today()
    snoozes = get_expired_snoozes()
    items = [
        i for i in list_expired(provider_ids, today)
        if not (snoozes.get(i["key"]) and date.fromisoformat(snoozes[i["key"]]) > today)
    ]
    return {"count": len(items), "items": items}


def remove_expired(keys: list[str], provider_ids: list[str], today: date | None = None) -> int:
    """Drop the picked items, if they belong to these providers and are past the cutoff.

    Storage only; returns how many were dropped.
    """
    picked = set(keys)
    wanted = set(provider_ids)
    cutoff = _cutoff(today or date.today())
    removed = 0
    for rule in get_all_rules():
        if rule.provider_id not in wanted:
            continue
        if f"rule:{rule.id}" in picked and rule.effective_end and rule.effective_end < cutoff:
            delete_rule_by_id(rule.provider_id, rule.id)
            delete_event_ids(rule.id)
            removed += 1
            continue
        kept = [o for o in rule.date_overrides if not (o.date < cutoff and f"override:{rule.id}:{o.date.isoformat()}" in picked)]
        if len(kept) < len(rule.date_overrides):
            removed += len(rule.date_overrides) - len(kept)
            rule.date_overrides = kept
            save_rule(rule)
    for block in get_all_blocks():
        if block.provider_id in wanted and f"block:{block.id}" in picked and block.end.date() < cutoff:
            delete_block(block.provider_id, block.id)
            delete_event_ids(block.id)
            removed += 1
    for rb in get_all_recurring_blocks():
        if rb.provider_id in wanted and f"recurring:{rb.id}" in picked and rb.effective_end and rb.effective_end < cutoff:
            delete_recurring_block(rb.provider_id, rb.id)
            delete_event_ids(rb.id)
            removed += 1
    log.info("remove_expired: dropped %d of %d picked items", removed, len(picked))
    return removed


def snooze_expired(keys: list[str], today: date | None = None) -> date:
    """Hide these items until SNOOZE_DAYS from today. Returns that date."""
    today = today or date.today()
    until = today + timedelta(days=SNOOZE_DAYS)
    snoozes = get_expired_snoozes()
    for key in keys:
        snoozes[key] = until.isoformat()
    # Drop snoozes that have run out so the stored map does not grow forever.
    set_expired_snoozes({k: d for k, d in snoozes.items() if d > today.isoformat()})
    return until
