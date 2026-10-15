"""Turning a Scheduling feature on or off, and what that does to calendars.

Each switch is read where its events are drawn (engine.settings.is_feature_on),
so turning one off stops new events at once. This module handles what is
already on calendars: the admin picks keep or remove, and it lists the items a
change would affect so they can see them first.

Choices per feature (``choice`` in ``apply_feature_change``):

- buffers: "keep" (each buffer stays until its appointment passes) or "remove"
- lead_time: "keep" (blocks run out on their own, within a day) or "remove"
- holds: "keep" (until their dates pass) or "remove"
- overrides: "keep" (existing overrides keep applying; no new ones) or "stop"
  (those dates go back to regular hours)
- provider_timezones: no choice; every provider moves to the practice timezone

Turning a feature back on needs no choice: the next sync or background run
draws its events again, and overrides and timezones are re-synced at once.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event as EventEffect
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.calendar import Event as EventModel
from django.db.models import Q
from logger import log

from provider_availability.engine.admin_calendar import get_admin_calendars
from provider_availability.engine.event_sync import (
    HOLD_TITLE_PREFIXES,
    LEAD_TIME_TITLE,
    _hold_event_ids,
    build_provider_hold_refresh_effects,
    build_block_event_effects,
    build_delete_block_effects,
    build_provider_lead_time_effects,
    build_recurring_blocks_resync_effects,
    delete_all_lead_time_events,
    sync_provider_availability,
)
from provider_availability.engine.provider_resolver import get_provider_displays
from provider_availability.engine.roles import get_schedulable_provider_ids
from provider_availability.engine.settings import FEATURES, set_feature
from provider_availability.engine.storage import (
    get_all_blocks,
    get_all_provider_timezones,
    get_all_recurring_blocks,
    get_all_rules,
    get_practice_timezone,
    get_rules_for_provider,
)
from provider_availability.engine.tz_utils import to_provider_naive

BUFFER_TITLE = "Buffer"  # protocols/appointment_buffer.py draws these
CHOICES = {
    "buffers": ("keep", "remove"),
    "lead_time": ("keep", "remove"),
    "holds": ("keep", "remove"),
    "overrides": ("keep", "stop"),
    "provider_timezones": ("move",),
}
# Rows listed per feature in the affected-items table. The count is exact; the
# list stops here so one request stays small on a large practice.
MAX_ROWS = 500


# ── Who has events ────────────────────────────────────────────────────

def _providers_with_schedules() -> list[str]:
    """Every provider with a saved rule or block, which is everyone the plugin draws for."""
    ids = {r.provider_id for r in get_all_rules()}
    ids |= {b.provider_id for b in get_all_blocks()}
    ids |= {b.provider_id for b in get_all_recurring_blocks()}
    return sorted(ids)


def _future_events(provider_id: str, title_q: Q, now: dt.datetime) -> list[EventModel]:
    cal_ids = [c.id for c in get_admin_calendars(provider_id)]
    if not cal_ids:
        return []
    return list(
        EventModel.objects.filter(title_q, calendar__id__in=cal_ids, is_cancelled=False, ends_at__gt=now)
        .order_by("starts_at")
    )


def _title_q(feature: str) -> Q:
    if feature == "buffers":
        return Q(title__startswith=BUFFER_TITLE)
    if feature == "lead_time":
        return Q(title=LEAD_TIME_TITLE)
    q = Q()
    for prefix in HOLD_TITLE_PREFIXES:
        q |= Q(title__startswith=prefix)
    return q


# ── Formatting ────────────────────────────────────────────────────────

def _clock(t: dt.datetime | dt.time) -> str:
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _span(a: dt.datetime, b: dt.datetime) -> str:
    return f"{_clock(a)} – {_clock(b)}"


def _day(d: dt.date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def _minutes(a: dt.datetime, b: dt.datetime) -> int:
    return int((b - a).total_seconds() // 60)


# ── Affected items ────────────────────────────────────────────────────

def _event_rows(feature: str, provider_id: str, now: dt.datetime) -> list[list[str]]:
    events = _future_events(provider_id, _title_q(feature), now)
    if not events:
        return []
    appt_starts: set[dt.datetime] = set()
    if feature == "buffers":
        # A pre-buffer ends when its appointment starts; anything else is a post-buffer.
        appt_starts = set(
            Appointment.objects.filter(
                provider__id=provider_id, start_time__gte=now - dt.timedelta(days=1), entered_in_error__isnull=True
            ).values_list("start_time", flat=True)
        )
    rows: list[list[str]] = []
    for evt in events:
        start = to_provider_naive(evt.starts_at, provider_id)
        end = to_provider_naive(evt.ends_at, provider_id)
        if feature == "buffers":
            before = evt.ends_at in appt_starts
            appt_time = end if before else start
            rows.append([_day(start.date()), _clock(appt_time), f"{_minutes(start, end)} min {'before' if before else 'after'}"])
        elif feature == "lead_time":
            rows.append([_day(start.date()), _span(start, end)])
        else:
            kind = "Next-day" if "Next" in (evt.title or "") else "Same-day"
            rows.append([_day(start.date()), _span(start, end), kind])
    return rows


def _override_rows(provider_id: str, today: dt.date) -> list[list[str]]:
    rows: list[tuple[dt.date, list[str]]] = []
    for rule in get_rules_for_provider(provider_id):
        for ovr in rule.date_overrides:
            if ovr.date < today:
                continue
            change = "Closed" if ovr.is_closed else ", ".join(f"{_clock(w.start)} – {_clock(w.end)}" for w in ovr.time_windows)
            rows.append((ovr.date, [_day(ovr.date), change, ovr.reason or ""]))
    return [r for _, r in sorted(rows, key=lambda pair: pair[0])]


def affected_items(feature: str, now: dt.datetime | None = None) -> dict[str, Any]:
    """What turning ``feature`` off would affect, grouped by provider.

    Returns ``{"feature", "total", "columns", "providers": [{"provider_id",
    "name", "count", "rows"}]}``. For provider timezones each provider has one
    row: their timezone and the practice timezone they would move to.
    Raises ValueError for an unknown feature.
    """
    if feature not in FEATURES:
        raise ValueError(f"Unknown feature: {feature}")
    now = now or dt.datetime.now(dt.UTC)
    columns = {
        "buffers": ["Date", "Appointment", "Buffer"],
        "lead_time": ["Date", "Blocked"],
        "holds": ["Date", "Time", "Type"],
        "overrides": ["Date", "Change", "Reason"],
        "provider_timezones": ["Current timezone", "New timezone"],
    }[feature]

    by_provider: dict[str, list[list[str]]] = {}
    if feature == "provider_timezones":
        practice = get_practice_timezone()
        for pid, tz_name in get_all_provider_timezones().items():
            if tz_name and tz_name != practice:
                by_provider[pid] = [[tz_name, practice]]
    else:
        for pid in _providers_with_schedules():
            if feature == "overrides":
                rows = _override_rows(pid, to_provider_naive(now, pid).date())
            else:
                rows = _event_rows(feature, pid, now)
            if rows:
                by_provider[pid] = rows

    names = get_provider_displays(list(by_provider)) if by_provider else {}
    providers: list[dict[str, Any]] = []
    total = 0
    shown = 0
    for pid, rows in by_provider.items():
        total += len(rows)
        keep = rows[: max(0, MAX_ROWS - shown)]
        shown += len(keep)
        providers.append({
            "provider_id": pid,
            "name": names.get(pid, {}).get("name", ""),
            "count": len(rows),
            "rows": keep,
        })
    providers.sort(key=lambda p: (p["name"].split(" ")[-1].lower(), p["name"].lower()))
    return {"feature": feature, "total": total, "columns": columns, "providers": providers}


# ── Applying a change ─────────────────────────────────────────────────

def _delete_future(feature: str, now: dt.datetime) -> list[Effect]:
    if feature == "lead_time":
        return delete_all_lead_time_events()
    effects: list[Effect] = []
    for pid in _providers_with_schedules():
        cal_ids = [c.id for c in get_admin_calendars(pid)]
        if not cal_ids:
            continue
        if feature == "holds":
            effects.extend(EventEffect(event_id=eid).delete() for eid in _hold_event_ids(cal_ids))
        else:
            effects.extend(
                EventEffect(event_id=str(evt.id)).delete()
                for evt in _future_events(pid, _title_q(feature), now)
            )
    return effects


def _resync_availability(provider_ids: list[str]) -> list[Effect]:
    """Redraw availability and lead time for these providers, after overrides or timezones change."""
    schedulable = get_schedulable_provider_ids()
    effects: list[Effect] = []
    for pid in provider_ids:
        effects.extend(sync_provider_availability(pid, schedulable_ids=schedulable))
        effects.extend(build_provider_lead_time_effects(pid, get_rules_for_provider(pid)))
    return effects


def _redraw_for_timezone_change(provider_ids: list[str], flip: Any) -> list[Effect]:
    """Rebuild these providers' events around a timezone change made by ``flip()``.

    One-off blocks are deleted before the change, while their events still
    carry the old timezone's times, and redrawn after it, the same way a single
    provider's timezone change is handled.
    """
    blocks = [b for b in get_all_blocks() if b.provider_id in provider_ids]
    effects: list[Effect] = []
    for blk in blocks:
        effects.extend(build_delete_block_effects(blk.provider_id, blk, keep_others=False))
    flip()
    effects.extend(_resync_availability(provider_ids))
    effects.extend(build_recurring_blocks_resync_effects(
        [rb for rb in get_all_recurring_blocks() if rb.provider_id in provider_ids]
    ))
    for blk in blocks:
        effects.extend(build_block_event_effects(blk))
    return effects


def apply_feature_change(feature: str, on: bool, choice: str = "") -> list[Effect]:
    """Turn ``feature`` on or off and return the calendar effects that go with it.

    Raises ValueError for an unknown feature or a choice that feature doesn't offer.
    """
    if feature not in FEATURES:
        raise ValueError(f"Unknown feature: {feature}")
    if not on and choice not in CHOICES[feature]:
        raise ValueError(f"Choose one of: {', '.join(CHOICES[feature])}")
    now = dt.datetime.now(dt.UTC)
    effects: list[Effect] = []

    if feature == "provider_timezones":
        moved = [pid for pid, tz in get_all_provider_timezones().items() if tz]
        effects = _redraw_for_timezone_change(moved, lambda: set_feature(feature, on))
    elif feature == "overrides":
        set_feature(feature, on, keep_existing_overrides=(choice != "stop"))
        if on or choice == "stop":
            # Hours on override dates change either way: back to regular, or back to the override.
            with_overrides = sorted({r.provider_id for r in get_all_rules() if r.date_overrides})
            effects = _resync_availability(with_overrides)
    else:
        set_feature(feature, on)
        if not on and choice == "remove":
            effects = _delete_future(feature, now)
        elif on and feature == "lead_time":
            for pid in _providers_with_schedules():
                effects.extend(build_provider_lead_time_effects(pid, get_rules_for_provider(pid)))
        elif on and feature == "holds":
            # Draw each provider's holds now rather than waiting for the background job.
            holds_by_provider: dict[str, list] = {}
            for rb in get_all_recurring_blocks():
                if rb.is_active and rb.hold_type != "none":
                    holds_by_provider.setdefault(rb.provider_id, []).append(rb)
            for pid, blocks in holds_by_provider.items():
                effects.extend(build_provider_hold_refresh_effects(pid, blocks))

    log.info("features: %s turned %s (choice=%s), %d effects", feature, "on" if on else "off", choice or "-", len(effects))
    return effects
