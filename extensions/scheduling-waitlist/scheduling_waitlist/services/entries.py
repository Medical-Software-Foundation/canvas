"""Reading and writing waitlist entries.

Filtering, searching, and sorting all happen in the database rather than in the
browser. A practice-wide waitlist runs to thousands of rows, and the search box
matches patient names, so filtering client-side would mean shipping every
waitlisted patient's name to the browser whatever the filter said.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError
from django.db.models import Q

from scheduling_waitlist.constants import (
    DEFAULT_PAGE_SIZE,
    MATCHABLE_STATUSES,
    MAX_PAGE_SIZE,
    PREFERENCE_ANY,
)
from scheduling_waitlist.models import WaitlistEntry
from scheduling_waitlist.services.preferences import (
    accepts_location,
    accepts_note_type,
    accepts_provider,
)

# Related rows every serialized entry reads. Selecting them up front turns a
# page of 100 entries from 500 queries into one.
ENTRY_RELATIONS = (
    "patient",
    "note_type",
    "desired_provider",
    "desired_location",
    "created_by",
)

SORT_PRIORITY = "priority"
SORT_WAIT = "wait"
SORT_PATIENT = "patient"

# How many words of a search term are honoured. Each one is another predicate on
# the patient join, and the term comes from a query string.
SEARCH_TERM_WORD_LIMIT = 5

_SORT_FIELDS: dict[str, tuple[str, ...]] = {
    # Priority band first, then longest waiting inside the band. dbid last so
    # equal rows keep a stable order between requests.
    SORT_PRIORITY: ("priority_rank", "created_at", "dbid"),
    SORT_WAIT: ("created_at", "dbid"),
    SORT_PATIENT: ("patient__last_name", "patient__first_name", "dbid"),
}


def normalize_sort(raw: str | None) -> tuple[str, bool]:
    """Split a sort parameter into a known key and a direction.

    An unrecognized key falls back to priority rather than failing the request:
    a stale bookmark should still show the roster.
    """
    value = (raw or "").strip()
    descending = value.startswith("-")
    if descending:
        value = value[1:]
    if value not in _SORT_FIELDS:
        return SORT_PRIORITY, False
    return value, descending


def normalize_limit(raw: Any) -> int | None:
    """Page size, capped. ``None`` means the value was not a number."""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_PAGE_SIZE
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    if value <= 0:
        return DEFAULT_PAGE_SIZE
    return min(value, MAX_PAGE_SIZE)


def normalize_offset(raw: Any) -> int | None:
    """Row offset. ``None`` means the value was not a number."""
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    return max(value, 0)


def _order_by(sort_key: str, descending: bool) -> list[str]:
    fields = _SORT_FIELDS[sort_key]
    if not descending:
        return list(fields)
    # Only the leading column flips; the tiebreakers stay ascending so the order
    # remains deterministic.
    head, *tail = fields
    return [f"-{head}", *tail]


def build_queryset(
    *,
    status: str = "",
    search: str = "",
    note_type_dbid: Any = None,
    provider_dbid: Any = None,
    location_dbid: Any = None,
    priority_label: str = "",
    sort: str = SORT_PRIORITY,
    descending: bool = False,
) -> Any:
    """The filtered, ordered queryset behind the roster."""
    queryset = WaitlistEntry.objects.all()

    if status:
        queryset = queryset.filter(status=status)
    else:
        # The roster is a list of people still waiting, so closed entries stay
        # out until someone asks for them by status.
        queryset = queryset.filter(status__in=list(MATCHABLE_STATUSES))

    # Every word has to match a name part, rather than the whole string having to
    # match one part.
    #
    # The box says "Patient name", and a full name typed into it used to find
    # nothing: no single column holds both words, so "Nikola Tesla" was tested
    # against first_name and last_name entire and matched neither. One word still
    # behaves exactly as before -- "lee" matches either part -- so this only adds
    # the case that was broken. It also lets the chart hand the roster a display
    # name to filter by, which is where the defect surfaced.
    #
    # Capped, because each word is another join predicate and the term arrives
    # from a query string. Five is well past any real name.
    for word in (search or "").split()[:SEARCH_TERM_WORD_LIMIT]:
        queryset = queryset.filter(
            Q(patient__first_name__icontains=word) | Q(patient__last_name__icontains=word)
        )

    # Each of these three asks the question the user is really asking: "who could
    # take a slot like this?" -- so an entry that said "any" is included, not
    # filtered out. Selecting a provider used to hide exactly the patients who
    # would see anybody, which is backwards: they are the most likely candidates,
    # and the freed-slot matcher would name them while the roster denied they
    # existed. The predicates are shared with matching so the two cannot drift.
    if note_type_dbid:
        queryset = queryset.filter(accepts_note_type(note_type_dbid))

    # Passing PREFERENCE_ANY narrows to entries whose patient will see anyone,
    # rather than widening. The roster's filter bar does not offer it -- there,
    # "Any provider" means "do not filter" -- but this is a REST endpoint and the
    # behaviour is kept and tested for callers that want it.
    if provider_dbid == PREFERENCE_ANY:
        queryset = queryset.filter(provider_preference=PREFERENCE_ANY)
    elif provider_dbid:
        queryset = queryset.filter(accepts_provider(provider_dbid))

    if location_dbid == PREFERENCE_ANY:
        queryset = queryset.filter(location_preference=PREFERENCE_ANY)
    elif location_dbid:
        queryset = queryset.filter(accepts_location(location_dbid))

    if priority_label:
        queryset = queryset.filter(priority_label=priority_label)

    return queryset.select_related(*ENTRY_RELATIONS).order_by(*_order_by(sort, descending))


def list_entries(*, limit: int, offset: int, **filters: Any) -> tuple[list[Any], int]:
    """A page of entries plus the total matching the same filters."""
    queryset = build_queryset(**filters)
    total = queryset.count()
    return list(queryset[offset : offset + limit]), total


def get_entry(entry_dbid: Any) -> Any | None:
    """One entry with its related rows, or ``None``."""
    return (
        WaitlistEntry.objects.filter(dbid=entry_dbid)
        .select_related(*ENTRY_RELATIONS)
        .first()
    )


class DuplicateEntryError(Exception):
    """This patient already has a live entry for this appointment type."""


def live_entries_for_patient(patient_dbid: Any) -> list[Any]:
    """Every entry this patient is currently waiting on.

    Drives the chart banner, which says whether a patient is already on the
    waitlist without the reader having to open the roster.
    """
    if patient_dbid is None:
        return []
    return list(
        WaitlistEntry.objects.filter(
            patient_id=patient_dbid, status__in=list(MATCHABLE_STATUSES)
        ).select_related(*ENTRY_RELATIONS)
    )


def has_live_entry(patient_dbid: Any) -> bool:
    """Whether this patient has any entry still on the list.

    Separate from :func:`live_entries_for_patient` because the chart-header
    button only needs the yes/no. That runs on every chart open, and the other
    function answers it by joining five relations and building model instances
    that are then discarded -- this is one ``EXISTS`` with no joins.
    """
    if patient_dbid is None:
        return False
    return WaitlistEntry.objects.filter(
        patient_id=patient_dbid, status__in=list(MATCHABLE_STATUSES)
    ).exists()


def has_live_entry_for_service(patient_dbid: Any, note_type_dbid: Any) -> bool:
    """Whether this patient is already waiting for this one appointment type.

    The question the button on a freed appointment asks, which is narrower than
    :func:`has_live_entry`: a patient waiting for a physical is *not* waiting for
    the follow-up slot that just opened, and telling a scheduler otherwise would
    stop them adding the thing they should.

    A yes/no like :func:`has_live_entry` rather than :func:`find_live_entry`,
    which selects five relations to build a model that would be thrown away. This
    runs on every note header render.
    """
    if patient_dbid is None or note_type_dbid is None:
        return False
    return WaitlistEntry.objects.filter(
        patient_id=patient_dbid,
        note_type_id=note_type_dbid,
        status__in=list(MATCHABLE_STATUSES),
    ).exists()


def find_live_entry(patient_dbid: Any, note_type_dbid: Any) -> Any | None:
    """An existing live entry for the same patient and appointment type."""
    return (
        WaitlistEntry.objects.filter(
            patient_id=patient_dbid,
            note_type_id=note_type_dbid,
            status__in=list(MATCHABLE_STATUSES),
        )
        .select_related(*ENTRY_RELATIONS)
        .first()
    )


def create_entry(*, created_by_dbid: Any, **fields: Any) -> Any:
    """Add a patient to the waitlist.

    Raises :class:`DuplicateEntryError` when the same patient is already
    waiting for the same appointment type. Both the chart form and the roster
    post here, so the same person can be submitted twice from two surfaces; the
    partial unique index is the real guard and this is the readable message.
    """
    patient_dbid = fields.get("patient_id")
    note_type_dbid = fields.get("note_type_id")

    if find_live_entry(patient_dbid, note_type_dbid) is not None:
        raise DuplicateEntryError

    try:
        return WaitlistEntry.objects.create(created_by_id=created_by_dbid, **fields)
    except IntegrityError as exc:
        # Lost a race against a concurrent submission; the index caught it.
        raise DuplicateEntryError from exc


# Fields an edit is allowed to change. The patient is deliberately absent: an
# entry belongs to the person it was created for, and reassigning it through a
# request body would quietly move someone else's place in the queue.
EDITABLE_FIELDS = (
    "note_type_id",
    "provider_preference",
    "desired_provider_id",
    "location_preference",
    "desired_location_id",
    "priority_label",
    "priority_rank",
    "preferred_windows",
    "preferred_windows_timezone",
    "preferred_window_note",
    "note",
)


def update_entry(entry: Any, **fields: Any) -> Any:
    """Apply an edit to an existing entry.

    Written out field by field rather than looping with ``setattr``: the
    RestrictedPython sandbox blocks ``setattr``, so the concise version passes
    the test suite and then fails on the instance. Keeping ``EDITABLE_FIELDS``
    above as the single list of what may be edited, with
    ``test_every_editable_field_is_assignable`` pinning the two together.
    """
    changed = False

    if "note_type_id" in fields:
        entry.note_type_id = fields["note_type_id"]
        changed = True
    if "provider_preference" in fields:
        entry.provider_preference = fields["provider_preference"]
        changed = True
    if "desired_provider_id" in fields:
        entry.desired_provider_id = fields["desired_provider_id"]
        changed = True
    if "location_preference" in fields:
        entry.location_preference = fields["location_preference"]
        changed = True
    if "desired_location_id" in fields:
        entry.desired_location_id = fields["desired_location_id"]
        changed = True
    if "priority_label" in fields:
        entry.priority_label = fields["priority_label"]
        changed = True
    if "priority_rank" in fields:
        entry.priority_rank = fields["priority_rank"]
        changed = True
    if "preferred_windows" in fields:
        entry.preferred_windows = fields["preferred_windows"]
        changed = True
    if "preferred_windows_timezone" in fields:
        entry.preferred_windows_timezone = fields["preferred_windows_timezone"]
        changed = True
    if "preferred_window_note" in fields:
        entry.preferred_window_note = fields["preferred_window_note"]
        changed = True
    if "note" in fields:
        entry.note = fields["note"]
        changed = True

    if changed:
        entry.save()
    return entry
