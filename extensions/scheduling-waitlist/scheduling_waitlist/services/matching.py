"""Deciding which waiting patients fit a slot.

The same predicate drives both directions: which entries a freed slot should
name, and which entry a new booking satisfies. Keeping them as one function is
deliberate -- if they disagreed, the plugin could tell staff to book a patient
into a slot it would then refuse to recognise.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Q

from scheduling_waitlist.constants import MATCHABLE_STATUSES, PREFERENCE_ANY
from scheduling_waitlist.models import WaitlistEntry
from scheduling_waitlist.services.display import (
    location_name,
    note_type_name,
    staff_name,
)
from scheduling_waitlist.services.entries import ENTRY_RELATIONS
from scheduling_waitlist.services.slot import FreedSlot

# How many entries the no-match diagnostic quotes verbatim. Enough to see the
# mismatch on a test instance, few enough that a practice-sized backlog does not
# produce an unreadable log line.
MAX_EXPLAINED_ENTRIES = 3


def _describe_slot(slot: FreedSlot) -> str:
    """The slot's three matched attributes, with the identifiers behind them.

    The identifiers are printed because the labels alone can lie. A practice can
    carry two ``NoteType`` rows with the same name -- Canvas versions them -- so
    an entry and a slot can both read "Office visit" and still be different rows,
    which is invisible in a log that prints only names.
    """
    return (
        f"slot was {slot.note_type_label} (type #{slot.note_type_dbid})"
        f" / {slot.provider_label} (staff #{slot.provider_dbid})"
        f" / {slot.location_label} (location #{slot.location_dbid})"
    )


def _describe_entry(entry: Any) -> str:
    """What one entry asked for, in the same shape as the slot description."""
    note_type = getattr(entry, "note_type", None)
    if note_type is None:
        service = "any service"
    else:
        service = f"{note_type_name(note_type)} (type #{getattr(entry, 'note_type_id', None)})"

    if getattr(entry, "provider_preference", "") == PREFERENCE_ANY:
        provider = "any provider"
    else:
        provider = (
            f"{staff_name(getattr(entry, 'desired_provider', None))} "
            f"(staff #{getattr(entry, 'desired_provider_id', None)})"
        )

    if getattr(entry, "location_preference", "") == PREFERENCE_ANY:
        location = "any location"
    else:
        location = (
            f"{location_name(getattr(entry, 'desired_location', None))} "
            f"(location #{getattr(entry, 'desired_location_id', None)})"
        )

    return f"{service} / {provider} / {location}"


def explain_no_match(slot: FreedSlot) -> str:
    """Why this slot named nobody, in terms a person can act on.

    "Matched nobody" on its own is unactionable: an empty list, an incompatible
    list, and a list whose only candidate is the patient who cancelled all look
    identical from the outside. Working that out has repeatedly meant reading code
    rather than logs, so the reasons are counted here instead.

    When nothing was compatible it also quotes what the entries did ask for,
    beside what the slot offered. Naming only one side of a comparison that failed
    leaves the reader to guess the other, which is how diagnosing this turned into
    several rounds of deploying and cancelling.

    Only reached when there were no matches, so the extra counts are paid on the
    diagnostic path rather than on every cancellation that produces a task.
    """
    live = WaitlistEntry.objects.filter(status__in=list(MATCHABLE_STATUSES))
    total = live.count()

    shape = _describe_slot(slot)
    if not total:
        return f"{shape}; nobody is on the waitlist"

    reasons = [shape, f"{total} live entr{'y' if total == 1 else 'ies'} on the list"]

    compatible = live.filter(
        compatibility_q(slot.note_type_dbid, slot.provider_dbid, slot.location_dbid)
    )
    if not compatible.exists():
        quoted = [
            _describe_entry(entry)
            for entry in live.select_related(*ENTRY_RELATIONS)[:MAX_EXPLAINED_ENTRIES]
        ]
        reasons.append(
            "none of them asked for this service, provider and location "
            "(an entry matches only if it named exactly that, or said any); "
            f"the list asked for: {' | '.join(quoted)}"
        )
        if total > MAX_EXPLAINED_ENTRIES:
            reasons.append(f"{total - MAX_EXPLAINED_ENTRIES} further entries not quoted")
        return "; ".join(reasons)

    if slot.vacating_patient_dbid is not None and compatible.filter(
        patient_id=slot.vacating_patient_dbid
    ).exists():
        reasons.append(
            "the only compatible entries belong to the patient who gave the slot up, "
            "who is deliberately never offered their own slot back"
        )
        return "; ".join(reasons)

    reasons.append(
        "compatible entries exist but were filtered out -- check whether they are "
        "already marked scheduled against this appointment, or fall outside their "
        "preferred window while WAITLIST_ENFORCE_TIME_WINDOWS is on"
    )
    return "; ".join(reasons)


def compatibility_q(
    note_type_dbid: Any, provider_dbid: Any, location_dbid: Any
) -> Q:
    """Whether an entry accepts an appointment with these attributes.

    An entry matches when, for each of type, provider, and location, either it
    asked for exactly that or it said anything would do.
    """
    # A null appointment type on an entry means "any type".
    type_q = Q(note_type__isnull=True)
    if note_type_dbid is not None:
        type_q = type_q | Q(note_type_id=note_type_dbid)

    provider_q = Q(provider_preference=PREFERENCE_ANY)
    if provider_dbid is not None:
        provider_q = provider_q | Q(desired_provider_id=provider_dbid)

    location_q = Q(location_preference=PREFERENCE_ANY)
    if location_dbid is not None:
        location_q = location_q | Q(desired_location_id=location_dbid)

    return type_q & provider_q & location_q


def _window_covers(window: dict, local_start: datetime) -> bool:
    """Whether one stored window contains a local start time."""
    days = window.get("days") or []
    if days and local_start.weekday() not in days:
        return False

    start = window.get("start") or ""
    end = window.get("end") or ""
    if not start or not end:
        return True

    clock = local_start.strftime("%H:%M")
    return start <= clock < end


def entry_accepts_time(entry: Any, slot: FreedSlot, *, fallback_timezone: str) -> bool:
    """Whether a patient's preferred day and time cover this slot.

    Only consulted when the practice has turned window enforcement on. An entry
    with no stored preference accepts anything, which is what "any time" means.
    """
    windows = getattr(entry, "preferred_windows", None) or []
    if not windows:
        return True
    if not isinstance(slot.start_time, datetime):
        return True

    zone_name = (
        getattr(entry, "preferred_windows_timezone", "") or fallback_timezone or "UTC"
    )
    try:
        zone = ZoneInfo(zone_name)
    except (KeyError, ValueError):
        # An unusable timezone must not silently drop the patient from the
        # match; showing one extra name is the safer failure.
        return True

    local_start = slot.start_time.astimezone(zone)
    return any(_window_covers(window, local_start) for window in windows)


def find_matching_entries(
    slot: FreedSlot,
    *,
    limit: int,
    enforce_time_windows: bool = False,
    fallback_timezone: str = "UTC",
) -> list[Any]:
    """Waiting patients who fit this slot, most urgent and longest waiting first."""
    queryset = (
        WaitlistEntry.objects.filter(status__in=list(MATCHABLE_STATUSES))
        .filter(
            compatibility_q(slot.note_type_dbid, slot.provider_dbid, slot.location_dbid)
        )
        .exclude(scheduled_appointment_id=slot.appointment_dbid)
    )

    # Without this the patient who just cancelled is offered their own slot
    # back: cancelling re-arms their entry, and the entry then matches the slot
    # the cancellation created.
    if slot.vacating_patient_dbid is not None:
        queryset = queryset.exclude(patient_id=slot.vacating_patient_dbid)

    queryset = queryset.select_related(*ENTRY_RELATIONS).order_by(
        "priority_rank", "created_at", "dbid"
    )

    if not enforce_time_windows:
        return list(queryset[:limit])

    # Filtered in Python rather than SQL because the comparison needs the
    # patient's own timezone. Reads one extra page to allow for exclusions.
    matched = []
    for entry in queryset[: limit * 2]:
        if entry_accepts_time(entry, slot, fallback_timezone=fallback_timezone):
            matched.append(entry)
        if len(matched) >= limit:
            break
    return matched


def find_entries_to_flip(appointment: Any) -> list[Any]:
    """Entries a new booking satisfies, for the patient who booked it."""
    patient_dbid = getattr(appointment, "patient_id", None)
    if patient_dbid is None:
        return []

    return list(
        WaitlistEntry.objects.filter(
            patient_id=patient_dbid, status__in=list(MATCHABLE_STATUSES)
        )
        .filter(
            compatibility_q(
                getattr(appointment, "note_type_id", None),
                getattr(appointment, "provider_id", None),
                getattr(appointment, "location_id", None),
            )
        )
        .select_related(*ENTRY_RELATIONS)
        .order_by("priority_rank", "created_at", "dbid")
    )


def find_entries_for_appointment(appointment_dbid: Any) -> list[Any]:
    """Entries recorded as satisfied by a given appointment."""
    from scheduling_waitlist.constants import STATUS_SCHEDULED

    return list(
        WaitlistEntry.objects.filter(
            scheduled_appointment_id=appointment_dbid, status=STATUS_SCHEDULED
        ).select_related(*ENTRY_RELATIONS)
    )
