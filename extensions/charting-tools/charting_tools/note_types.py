"""Note types a template can be inserted into automatically."""

from typing import Any

from canvas_sdk.v1.data.note import Note, NoteType, NoteTypeCategories

# Categories whose notes hold commands.
CHARTING_CATEGORIES = (
    NoteTypeCategories.ENCOUNTER,
    NoteTypeCategories.INPATIENT,
    NoteTypeCategories.REVIEW,
)


def note_type_options() -> list[dict[str, str]]:
    """Current versions of active charting note types, by name."""
    rows = (
        NoteType.objects.filter(
            is_active=True,
            deprecated_at__isnull=True,
            category__in=CHARTING_CATEGORIES,
        )
        .order_by("name")
        .values("unique_identifier", "name")
    )
    return [{"unique_identifier": str(row["unique_identifier"]), "name": row["name"]} for row in rows]


def note_type_identifier(note: Note) -> str | None:
    """The version-independent identifier of a note's type."""
    note_type = note.note_type_version
    return str(note_type.unique_identifier) if note_type else None


def template_for_note_type(templates: Any, identifier: str) -> Any | None:
    """Return the first template assigned to ``identifier``, in the order given."""
    for template in templates:
        if any(
            nt.get("unique_identifier") == identifier for nt in (template.note_types or [])
        ):
            return template
    return None
