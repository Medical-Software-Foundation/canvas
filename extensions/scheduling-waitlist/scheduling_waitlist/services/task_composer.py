"""Wording for the task raised when a slot frees up.

Pure string building, so the exact text a scheduler reads can be checked
without a database or an effect.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from scheduling_waitlist.services.display import patient_name
from scheduling_waitlist.services.slot import FreedSlot

TITLE_MAX = 140

# Only ever added when it says something the reader could not already see. There
# is deliberately no standing footer: a line that appears on every task -- such
# as a reminder that the plugin does not book anybody -- is read once and skipped
# forever after, while still costing every reader the space.
HINT_DISCLAIMER = (
    "Preferred times are a hint - matching did not filter on them."
)

# What freed the slot, in words. The raw event used to be printed, which put an
# internal enum number ("Slot freed (4)") in front of schedulers.
_CAUSES = {
    "APPOINTMENT_CANCELED": "Cancelled.",
    "APPOINTMENT_NO_SHOWED": "Marked no-show.",
    "APPOINTMENT_RESCHEDULED": "Rescheduled away.",
    "PATIENT_PORTAL__APPOINTMENT_CANCELED": "Cancelled by the patient.",
    "PATIENT_PORTAL__APPOINTMENT_RESCHEDULED": "Rescheduled by the patient.",
}

ANY_TIME = "Any time"

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def describe_cause(source_event: str) -> str:
    """How the slot came free, phrased for a person.

    An unrecognised event yields nothing rather than a guess: the surrounding
    lines already say a slot is open, so silence costs the reader less than a
    wrong or cryptic label.
    """
    return _CAUSES.get((source_event or "").strip().upper(), "")


def describe_wait(waited: int | None) -> str:
    """How long they have been waiting, in words.

    "waiting 0 days" is technically true and reads like a bug, so a same-day
    entry says so instead.
    """
    if waited is None:
        return ""
    if waited <= 0:
        return "added today"
    return f"waiting {waited} day" if waited == 1 else f"waiting {waited} days"


def format_slot_time(
    slot: FreedSlot, *, timezone_name: str, brief: bool = False
) -> str:
    """The slot's start, in the practice's display timezone.

    Practice locations carry no timezone of their own -- the SDK model has no such
    field -- so this is one configured setting for the whole instance. The zone
    abbreviation is always printed in the full form, so a wrong setting is visible
    rather than silently shifting every time staff read.

    ``brief`` drops the year, zone and duration for the task title, where the
    column is narrow and the reader only needs to know which slot this is; the
    comment carries the unambiguous version.
    """
    if not isinstance(slot.start_time, datetime):
        return "Time unknown"

    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (KeyError, ValueError):
        zone = ZoneInfo("UTC")

    local = slot.start_time.astimezone(zone)
    # The hour is formatted by hand rather than with "%-I", which is a
    # platform extension rather than standard, so this reads the same wherever
    # the plugin runs.
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    clock = f"{hour}:{local.strftime('%M')} {meridiem}"

    if brief:
        return f"{local.strftime('%a %d %b')}, {clock}"

    label = f"{local.strftime('%a %d %b %Y')}, {clock} {local.strftime('%Z')}".strip()
    if slot.duration_minutes:
        label = f"{label} ({slot.duration_minutes} min)"
    return label


def compose_title(slot: FreedSlot, match_count: int, *, timezone_name: str) -> str:
    """One short line: when, what, and how many people to ring.

    Deliberately shorter than the slot's full description. This is read in the
    task queue, where the column is narrow -- the previous title ran past a
    hundred characters and wrapped to eight lines there, burying the count at the
    end. The provider, location and duration move to the comment, where there is
    room for them.

    "to call" rather than "match": the reader's next action is a phone call, not
    the evaluation of a query.
    """
    parts = [
        f"Slot opened {format_slot_time(slot, timezone_name=timezone_name, brief=True)}",
        slot.note_type_label,
        f"{match_count} to call",
    ]
    title = " · ".join(part for part in parts if part)
    return title if len(title) <= TITLE_MAX else f"{title[: TITLE_MAX - 1]}…"


def _describe_days(days: Any) -> str:
    """Weekdays with consecutive runs collapsed.

    "Mon-Fri" rather than "Mon, Tue, Wed, Thu, Fri", which is the shape the
    commonest stored window takes and read as a wall of abbreviations.
    """
    ordered = sorted(
        {day for day in days if isinstance(day, int) and 0 <= day < len(_WEEKDAYS)}
    )
    if not ordered:
        return ""

    runs: list[list[int]] = []
    for day in ordered:
        if runs and day == runs[-1][-1] + 1:
            runs[-1].append(day)
        else:
            runs.append([day])

    return ", ".join(
        _WEEKDAYS[run[0]] if len(run) == 1 else f"{_WEEKDAYS[run[0]]}-{_WEEKDAYS[run[-1]]}"
        for run in runs
    )


def _describe_window(entry: Any) -> str:
    note = getattr(entry, "preferred_window_note", "") or ""
    if note:
        return note

    windows = getattr(entry, "preferred_windows", None) or []
    if not windows:
        return ANY_TIME

    described = []
    for window in windows:
        days = _describe_days(window.get("days") or [])
        start = window.get("start") or ""
        end = window.get("end") or ""
        span = f"{start}-{end}" if start and end else ""
        text = " ".join(part for part in (days, span) if part)
        if text:
            described.append(text)
    return "; ".join(described) or ANY_TIME


def compose_body(
    slot: FreedSlot,
    entries: list[Any],
    *,
    timezone_name: str,
    today: Any = None,
    enforce_time_windows: bool = False,
) -> str:
    """The task comment: what freed up, then who to ring, in order.

    The slot is described once here rather than repeated from the title, and each
    patient gets one line plus their note. The previous version restated the
    slot's service, provider and location under every patient as "Wants", which is
    necessarily compatible -- that is what made them a match -- so it told the
    reader nothing and buried what does differ.
    """
    from scheduling_waitlist.services.serializers import days_waiting

    slot_line = " · ".join(
        part
        for part in (
            format_slot_time(slot, timezone_name=timezone_name),
            slot.note_type_label,
            slot.provider_label,
            slot.location_label,
        )
        if part
    )

    lines = [line for line in (describe_cause(slot.source_event), slot_line) if line]
    lines.extend(["", "Call in priority order:"])

    showed_a_window = False
    for index, entry in enumerate(entries, start=1):
        patient = getattr(entry, "patient", None)
        priority = getattr(entry, "priority_label", "") or "Unset"

        detail = [f"{priority} priority"]
        if today is not None:
            detail.append(describe_wait(days_waiting(getattr(entry, "created_at", None), today)))

        window = _describe_window(entry)
        # "Any time" says nothing a reader can act on, so it is left out.
        if window and window != ANY_TIME:
            detail.append(f"prefers {window}")
            showed_a_window = True

        summary = ", ".join(part for part in detail if part)
        lines.append(f"{index}. {patient_name(patient)} - {summary}" if summary
                     else f"{index}. {patient_name(patient)}")

        note = getattr(entry, "note", "") or ""
        if note:
            # Its own line: a staff note is free text and can be long.
            lines.append(f"   Note: {note}")

    # Only when a preference was actually shown, and only when it did not in fact
    # constrain the match -- otherwise the caveat would be noise or a lie. The
    # blank separator belongs to the caveat: without one the comment would end on
    # a trailing empty line under the last patient.
    if showed_a_window and not enforce_time_windows:
        lines.append("")
        lines.append(HINT_DISCLAIMER)
    return "\n".join(lines)
