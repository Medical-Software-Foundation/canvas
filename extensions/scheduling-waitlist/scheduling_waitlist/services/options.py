"""Builds the choices offered on the waitlist form and the roster filters.

Appointment types, providers, and locations are read from the instance rather
than listed in configuration, so the plugin carries no practice-specific names
and works on a fresh install with nothing configured. The appointment-type
secret narrows that list; it does not define it.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import NoteType, PracticeLocation, Staff
from canvas_sdk.v1.data.note import NoteTypeCategories
from logger import log

from scheduling_waitlist.constants import (
    PREFERENCE_ANY,
    STATUS_EXPIRED,
    STATUS_OFFERED,
    STATUS_REMOVED,
    STATUS_SCHEDULED,
    STATUS_WAITING,
)
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.display import location_name, staff_name

# Fixed vocabulary. Stored on the entry, displayed on the task, and matched on
# only when the practice turns window enforcement on.
TIME_WINDOWS: tuple[dict[str, Any], ...] = (
    {"value": "any", "label": "Any time", "days": [], "start": "", "end": ""},
    {
        "value": "weekday_am",
        "label": "Weekday mornings",
        "days": [0, 1, 2, 3, 4],
        "start": "08:00",
        "end": "12:00",
    },
    {
        "value": "weekday_pm",
        "label": "Weekday afternoons",
        "days": [0, 1, 2, 3, 4],
        "start": "12:00",
        "end": "17:00",
    },
    {
        "value": "weekend",
        "label": "Weekends",
        "days": [5, 6],
        "start": "08:00",
        "end": "17:00",
    },
)

STATUS_LABELS: tuple[tuple[str, str], ...] = (
    (STATUS_WAITING, "Waiting"),
    (STATUS_OFFERED, "Offered"),
    (STATUS_SCHEDULED, "Scheduled"),
    (STATUS_REMOVED, "Removed"),
    (STATUS_EXPIRED, "Expired"),
)


def time_window_by_value(value: str) -> dict[str, Any] | None:
    """Look up a window in the fixed vocabulary."""
    for window in TIME_WINDOWS:
        if window["value"] == value:
            return window
    return None


def windows_for_value(value: str) -> list[dict[str, Any]]:
    """The structured form stored on an entry for a chosen window.

    "Any time" stores nothing, which keeps the common case cheap to match and
    means an entry with no stored window is never accidentally filtered out.
    """
    window = time_window_by_value(value)
    if window is None or not window["days"]:
        return []
    return [{"days": list(window["days"]), "start": window["start"], "end": window["end"]}]


# Categories a patient can never be booked into, so they have no business in a
# waitlist form. ``schedule_event`` is the one that prompted this: Canvas uses it
# for calendar blocks such as "Generic event", which are marked scheduleable
# because staff schedule *time* with them -- there is no patient involved, and an
# entry waiting for one can never be filled.
#
# Stated as an exclusion rather than an allow-list of visit categories so an
# instance that classifies a real visit type unusually still offers it. Read from
# the SDK enum rather than typed as strings, so a renamed member breaks the import
# instead of silently matching nothing.
NON_VISIT_CATEGORIES = frozenset(
    {
        str(NoteTypeCategories.SCHEDULE_EVENT),
        str(NoteTypeCategories.MESSAGE),
        str(NoteTypeCategories.LETTER),
        str(NoteTypeCategories.TASK),
        str(NoteTypeCategories.DATA),
        str(NoteTypeCategories.CCDA),
        str(NoteTypeCategories.REVIEW),
    }
)


def _category(note_type: Any) -> str:
    """An appointment type's category, as the stored string."""
    return str(getattr(note_type, "category", "") or "")


def is_patient_visit(note_type: Any) -> bool:
    """Whether a patient could actually be booked into this type.

    Public because the roster's next-appointment column asks the same question of
    an appointment already on the books, and answering it twice is how the form
    and the validator came to disagree about "Generic event".

    An unset category is treated as a visit: it is more likely an instance the SDK
    enum does not cover than a calendar block, and hiding a real appointment type
    is the worse mistake -- an entry nobody can create is invisible, while an odd
    one in the list is obvious and harmless.
    """
    return _category(note_type) not in NON_VISIT_CATEGORIES


def _type_option(note_type: Any) -> dict[str, Any]:
    """One appointment type as the form and the roster filters consume it."""
    code = (getattr(note_type, "code", "") or "").strip()
    name = (getattr(note_type, "name", "") or "").strip() or code
    return {"dbid": getattr(note_type, "dbid", None), "code": code, "name": name}


def list_appointment_types(config: WaitlistConfig) -> list[dict[str, Any]]:
    """Appointment types a patient can be booked into, narrowed by configuration.

    Only types that can actually be scheduled are offered: a waitlist entry for
    something nobody can book is a dead row. Being scheduleable is not sufficient,
    though -- a calendar block such as "Generic event" is scheduleable because
    staff schedule time with it, and has no patient. See ``NON_VISIT_CATEGORIES``.

    Configuration **narrows** this list, it does not define it. With nothing
    configured every bookable type is offered, so the plugin works on a fresh
    install. A configured list that matches nothing bookable is a mistake rather
    than an instruction to offer nothing, so it falls back to the full list and
    says so in the log -- an empty form teaches a scheduler nothing.

    This is the single authority on what may be waitlisted:
    ``services/validation.py`` checks submissions against this list rather than
    re-deriving the rule, because the two disagreeing is exactly how the form
    came to offer services it then refused.
    """
    scheduleable = list(
        NoteType.objects.filter(
            is_scheduleable=True,
            is_active=True,
            is_visible=True,
            deprecated_at__isnull=True,
        ).order_by("name")
    )

    # Narrowed in Python rather than SQL: this is a small reference table read to
    # fill a dropdown, and doing it here means the fallback below costs no second
    # query.
    bookable = [_type_option(nt) for nt in scheduleable if is_patient_visit(nt)]
    if not bookable and scheduleable:
        # Nothing left. Rather than hand a scheduler an empty form, offer what the
        # instance says is scheduleable and say so -- an instance that categorises
        # its visit types unusually is a configuration to look at, not a reason to
        # stop working.
        log.error(
            "scheduling_waitlist: no scheduleable appointment type has a "
            "patient-visit category, so every scheduleable type is being offered "
            f"instead; categories seen were {sorted({_category(nt) for nt in scheduleable})}"
        )
        bookable = [_type_option(nt) for nt in scheduleable]

    allowed = {code.casefold() for code in config.appointment_type_codes}
    if not allowed:
        return bookable

    narrowed = [option for option in bookable if str(option["code"]).casefold() in allowed]
    if narrowed:
        return narrowed

    if bookable:
        log.error(
            "scheduling_waitlist: WAITLIST_APPOINTMENT_TYPES matches no bookable "
            "appointment type, so every bookable type is being offered instead; "
            f"configured codes were {sorted(config.appointment_type_codes)}"
        )
    return bookable


def list_providers() -> list[dict[str, Any]]:
    """Active staff who can be requested by name."""
    return [
        {"dbid": getattr(staff, "dbid", None), "name": staff_name(staff)}
        for staff in Staff.objects.filter(active=True).order_by("last_name", "first_name")
    ]


def list_locations() -> list[dict[str, Any]]:
    """Active practice locations."""
    return [
        {"dbid": getattr(location, "dbid", None), "name": location_name(location)}
        for location in PracticeLocation.objects.filter(active=True).order_by("full_name")
    ]


def list_priorities(config: WaitlistConfig) -> list[dict[str, Any]]:
    """Configured priority labels, most urgent first."""
    return [
        {"label": label, "rank": rank}
        for rank, label in enumerate(config.priority_labels)
    ]


def build_options(config: WaitlistConfig) -> dict[str, Any]:
    """Everything the form and the filter bar need, in one payload."""
    appointment_types = list_appointment_types(config)
    return {
        "appointment_types": appointment_types,
        "providers": list_providers(),
        "locations": list_locations(),
        "priorities": list_priorities(config),
        "time_windows": [
            {"value": window["value"], "label": window["label"]} for window in TIME_WINDOWS
        ],
        "statuses": [{"value": value, "label": label} for value, label in STATUS_LABELS],
        "any_preference": PREFERENCE_ANY,
        # Whether anything can be waitlisted at all, which is a property of the
        # instance rather than of this plugin's configuration: with no variable
        # set every bookable type is offered. False only when the instance has
        # no bookable appointment types, which no plugin setting can fix.
        "can_add": bool(appointment_types),
    }
