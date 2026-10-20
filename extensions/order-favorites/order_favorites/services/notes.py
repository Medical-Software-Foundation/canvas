"""Which notes favorites can be added to, and how a note is named in the panel.

Favorites go into open visit (encounter) and chart review notes only. Letters and messages never
lock, so a state check alone would let orders land where nobody sees them in the chart; they are
left out by category. The same check runs when the note-header button is drawn and again when
orders are added, since the note can be locked or deleted while the panel is open.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import Note
from canvas_sdk.v1.data.note import NoteStates, NoteTypeCategories
from canvas_sdk.v1.data.reason_for_visit import ReasonForVisit

from order_favorites.services.access import staff_name
from order_favorites.services.catalog import parse_uuid

OPEN_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]
TARGET_CATEGORIES = [NoteTypeCategories.ENCOUNTER, NoteTypeCategories.REVIEW]
# A note's body columns can be large and nothing here reads them.
NOTE_BLOBS = ("_body", "_body_content", "_body_order", "related_data")


def _eligible() -> Any:
    return Note.objects.defer(*NOTE_BLOBS).filter(
        current_state__state__in=OPEN_STATES,
        note_type_version__category__in=TARGET_CATEGORIES,
    )


def eligible_note_by_dbid(dbid: Any) -> Note | None:
    if dbid in (None, ""):
        return None
    try:
        return _eligible().filter(dbid=int(dbid)).first()
    except (TypeError, ValueError):
        return None


def eligible_note(note_id: str | None) -> Note | None:
    """The open visit or chart review note with this id, or None."""
    if not note_id or parse_uuid(note_id) is None:
        return None
    note: Note | None = _eligible().select_related("note_type_version", "provider", "patient").filter(id=note_id).first()
    return note


MAX_OTHER_NOTES = 20


def patient_open_notes(note_id: str | None) -> tuple[list[Note], int]:
    """The open visit and chart review notes of the patient whose note this is, most recently changed
    first, at most MAX_OTHER_NOTES of them, plus how many are open in all. The note itself is looked
    up in any state, so this still works after it was locked."""
    if not note_id or parse_uuid(note_id) is None:
        return [], 0
    patient_id = Note.objects.filter(id=note_id).values_list("patient_id", flat=True).first()
    if patient_id is None:
        return [], 0
    open_notes = _eligible().filter(patient_id=patient_id)
    shown = list(open_notes.select_related("note_type_version", "provider", "patient").order_by("-modified")[:MAX_OTHER_NOTES])
    total = len(shown) if len(shown) < MAX_OTHER_NOTES else open_notes.count()
    return shown, total


def reason_for_visit_titles(notes: list[Note]) -> dict[int, str]:
    """For each note, the text of its first reason for visit that is still on the note (deleted and
    entered-in-error reasons are skipped), which Canvas uses as the note's heading. One query for all the notes. Carried over from dot-phrases (library._reason_for_visit_title).

    For a coded reason Canvas uses the code's name, and only falls back to the comment when there's
    no code. A practice setting can make Canvas use the last reason instead, and plugins can't read
    it, so a note with two reasons can differ.
    """
    titles: dict[int, str] = {}
    dbids = [n.dbid for n in notes]
    if not dbids:
        return titles
    reasons = ReasonForVisit.objects.committed().filter(note_id__in=dbids).prefetch_related("codings").order_by("dbid")
    for rfv in reasons:
        if rfv.note_id in titles:
            continue
        codings = list(rfv.codings.all())
        text = str(codings[-1].display or "").strip() if codings else ""
        if not text:
            text = str(ReasonForVisit.string_from_narrative_json(rfv.narrative_json) or "").strip()
        if text:
            titles[rfv.note_id] = text
    return titles


def note_url(note: Note) -> str:
    """The note in the patient's chart. Canvas reads noteId as the note's dbid, not its id, scrolls to
    it, and loads older notes first if needed. Blank when the note has no patient."""
    if note.patient is None:
        return ""
    return f"/patient/{note.patient.id}?noteId={note.dbid}"


def note_label(note: Note, reason_title: str | None = None) -> dict[str, Any]:
    """Title, visit time, provider, and chart link, as the panel's "Adding to" line shows them.

    The title follows the note heading in Canvas: the reason for visit, then the note's title, then its
    type. Pass reason_title when it was looked up in bulk; otherwise it is looked up here.
    """
    if reason_title is None:
        reason_title = reason_for_visit_titles([note]).get(note.dbid, "")
    title = reason_title or note.title or (note.note_type_version.name if note.note_type_version else "") or "Note"
    when = note.datetime_of_service
    return {
        "id": str(note.id),
        "title": title,
        # Sent as a timestamp so the browser shows the date in the user's time zone, as the note header does.
        "when": when.isoformat() if when else "",
        "provider": staff_name(note.provider),
        "url": note_url(note),
    }
