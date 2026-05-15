"""Filter native scheduler slots to provider availability windows.

Subscribes to ``APPOINTMENT__SLOTS__POST_SEARCH`` and returns
``APPOINTMENT__SLOTS__POST_SEARCH_RESULTS`` with the slot list trimmed so
that:

* Slots outside the provider's Available windows are dropped.
* Slots that overlap a provider's Busy block are dropped.
* If a provider has no Available windows configured for the date, ALL of
  their slots are dropped (fail-closed).

The undocumented context shape is logged on every invocation so the filter
can be refined once real-world payloads are observed in UAT.
"""

from __future__ import annotations

import datetime
import json
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import PracticeLocation
from logger import log

from provider_availability_manager.utils.calendar_availability import (
    get_availability_windows,
    get_blocking_calendar_events,
    get_location_timezone,
)
from provider_availability_manager.utils.scheduling_logic import (
    _slot_in_windows,
    _subtract_blocks,
)


def _resolve_location_name(selected_values: dict) -> str:
    """Pull a location name from the selected_values payload.

    The exact shape is undocumented; try the keys we've seen on related
    appointment-form events first, then fall back to a PracticeLocation
    lookup by id.
    """
    if not isinstance(selected_values, dict):
        return ""

    location = selected_values.get("location")
    if isinstance(location, dict):
        for key in ("name", "full_name", "label", "text"):
            value = location.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        loc_id = location.get("id") or location.get("value")
        if isinstance(loc_id, str) and loc_id:
            loc = PracticeLocation.objects.filter(id=loc_id).first()
            if loc:
                return loc.full_name
    elif isinstance(location, str) and location.strip():
        loc = PracticeLocation.objects.filter(id=location).first()
        return loc.full_name if loc else location.strip()

    return ""


def _parse_slot_dt(value) -> datetime.datetime | None:
    """Parse a slot start/end value into a datetime."""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str) and value:
        s = value.replace("Z", "+00:00")
        try:
            return datetime.datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _to_naive_local(dt: datetime.datetime, tz: ZoneInfo) -> datetime.datetime:
    """Convert dt into ``tz`` and drop the tzinfo so it can be compared to
    the naive-local availability windows returned by ``calendar_availability``.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(tz).replace(tzinfo=None)
    return dt


def _provider_id_from_entry(entry) -> str:
    """Extract a provider id from a slots_by_provider list entry."""
    if not isinstance(entry, dict):
        return ""
    provider = entry.get("provider")
    if isinstance(provider, dict):
        pid = provider.get("id") or provider.get("value")
        if isinstance(pid, str):
            return pid
    pid = entry.get("provider_id") or entry.get("id")
    return pid if isinstance(pid, str) else ""


def _filter_one_provider_slots(
    provider_id: str,
    location_name: str,
    slots: list,
    staff_cache: dict,
    calendar_cache: dict,
) -> list:
    """Return only the slots that fit within (Available − Busy) windows.

    Fails closed: if no Available windows exist for the requested date,
    returns an empty list regardless of what slots Canvas suggested.
    """
    if not slots:
        return []

    tz_name = get_location_timezone(
        provider_id, location_name,
        staff_cache=staff_cache, calendar_cache=calendar_cache,
    )
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")

    windows_by_date: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {}

    def _net_windows_for_date(date_str: str):
        if date_str in windows_by_date:
            return windows_by_date[date_str]
        windows = get_availability_windows(
            provider_id, location_name, date_str,
            staff_cache=staff_cache, calendar_cache=calendar_cache,
        )
        if not windows:
            windows_by_date[date_str] = []
            return []
        busy = get_blocking_calendar_events(
            provider_id, date_str, tz_name,
            staff_cache=staff_cache, calendar_cache=calendar_cache,
        )
        net = _subtract_blocks(windows, busy)
        windows_by_date[date_str] = net
        return net

    kept = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        slot_start = _parse_slot_dt(slot.get("start"))
        slot_end = _parse_slot_dt(slot.get("end"))
        if slot_start is None or slot_end is None:
            continue

        local_start = _to_naive_local(slot_start, tz)
        local_end = _to_naive_local(slot_end, tz)
        date_str = local_start.date().isoformat()

        net = _net_windows_for_date(date_str)
        if not net:
            continue
        if _slot_in_windows(local_start, local_end, net):
            kept.append(slot)

    return kept


class AvailabilitySlotFilter(BaseHandler):
    """Trim native scheduler slots to configured provider availability."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT__SLOTS__POST_SEARCH)

    def compute(self) -> list[Effect]:
        context = self.event.context or {}
        slots_by_provider = context.get("slots_by_provider")
        selected_values = context.get("selected_values") or {}

        log.info(
            "AvailabilitySlotFilter: context_keys=%s selected_values=%s "
            "slots_by_provider_type=%s",
            list(context.keys()),
            selected_values,
            type(slots_by_provider).__name__,
        )

        location_name = _resolve_location_name(selected_values)
        if not location_name:
            log.warning(
                "AvailabilitySlotFilter: cannot resolve location from "
                "selected_values=%s; passing slots through unchanged",
                selected_values,
            )
            return []

        staff_cache: dict = {}
        calendar_cache: dict = {}
        filtered: list | dict

        if isinstance(slots_by_provider, list):
            filtered = []
            for entry in slots_by_provider:
                if not isinstance(entry, dict):
                    continue
                provider_id = _provider_id_from_entry(entry)
                if not provider_id:
                    filtered.append(entry)
                    continue
                new_entry = dict(entry)
                new_entry["slots"] = _filter_one_provider_slots(
                    provider_id,
                    location_name,
                    entry.get("slots") or [],
                    staff_cache,
                    calendar_cache,
                )
                filtered.append(new_entry)
        elif isinstance(slots_by_provider, dict):
            filtered = {}
            for provider_id, slots in slots_by_provider.items():
                if not isinstance(provider_id, str):
                    continue
                filtered[provider_id] = _filter_one_provider_slots(
                    provider_id,
                    location_name,
                    slots if isinstance(slots, list) else [],
                    staff_cache,
                    calendar_cache,
                )
        else:
            log.warning(
                "AvailabilitySlotFilter: unexpected slots_by_provider type %s; "
                "passing through unchanged",
                type(slots_by_provider).__name__,
            )
            return []

        return [
            Effect(
                type=EffectType.APPOINTMENT__SLOTS__POST_SEARCH_RESULTS,
                payload=json.dumps({"slots_by_provider": filtered}),
            )
        ]
