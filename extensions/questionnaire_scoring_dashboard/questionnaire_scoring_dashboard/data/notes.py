"""Thin database access for open/editable notes for a patient."""

from __future__ import annotations

from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates

_OPEN_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]


def fetch_open_note_rows(patient_id: str) -> list[dict]:
    """Return open/editable notes for a patient as plain dicts.

    Each dict: {"id": external note id, "dos": iso str, "title": str}.
    Notes are scoped to the patient, so the returned ids are the only valid
    insertion targets for that patient.
    """
    open_dbids = list(
        CurrentNoteStateEvent.objects.filter(state__in=_OPEN_STATES).values_list(
            "note_id", flat=True
        )
    )
    rows = []
    for note in Note.objects.filter(patient__id=patient_id, dbid__in=open_dbids):
        dos = note.datetime_of_service.isoformat() if note.datetime_of_service else ""
        rows.append({"id": str(note.id), "dos": dos, "title": getattr(note, "title", "") or ""})
    return rows
