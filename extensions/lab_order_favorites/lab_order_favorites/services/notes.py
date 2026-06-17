"""Lookups for the fallback chart review note.

When a patient has no open encounter note to stage lab orders into, the
patient-scoped app creates a chart review note instead. These helpers find the
note type to use and the location to stamp on the new note - the same defaults
the New Note button applies.
"""

from canvas_sdk.v1.data.note import NoteType, NoteTypeCategories
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff


def chart_review_note_type_id() -> str | None:
    """Return the id of the active chart review note type, or None.

    Canvas ships a system-managed chart review note type (category 'review').
    Pick the lowest-ranked active, visible one so it matches what a user would
    reach from the New Note menu.
    """
    note_type = (
        NoteType.objects.filter(
            category=NoteTypeCategories.REVIEW, is_active=True, is_visible=True
        )
        .order_by("rank", "dbid")
        .first()
    )
    return str(note_type.id) if note_type else None


def default_practice_location_id(provider_id: str) -> str | None:
    """Return the location id for a new note created by ``provider_id``.

    Mirrors the New Note button: use the acting provider's primary practice
    location, falling back to the first active location on the instance.
    """
    staff = Staff.objects.filter(id=provider_id).select_related("primary_practice_location").first()
    if staff:
        primary = staff.primary_practice_location
        if primary:
            return str(primary.id)
    location = PracticeLocation.objects.filter(active=True).order_by("dbid").first()
    return str(location.id) if location else None
