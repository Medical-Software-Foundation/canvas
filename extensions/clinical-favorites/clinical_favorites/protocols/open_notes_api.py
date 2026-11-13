"""List notes a clinician can see in the Insert modal, flagged with state."""

from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.note import Note, NoteStates


OPEN_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]

LOCKED_STATES = [
    NoteStates.LOCKED,
    NoteStates.SIGNED,
    NoteStates.RELOCKED,
]

PICKABLE_STATES = OPEN_STATES + LOCKED_STATES

LOCKED_STATE_VALUES = {s.value for s in LOCKED_STATES}


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class OpenNotesAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """List the patient's notes that are candidates for command insertion."""

    PATH = "/routes/open-notes"

    def get(self) -> list[Response | Effect]:
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"success": False, "error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"success": False, "error": "Patient not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        notes_qs = (
            Note.objects.filter(
                patient=patient,
                current_state__state__in=PICKABLE_STATES,
            )
            .select_related("current_state", "note_type_version")
        )

        notes = []
        for note in notes_qs:
            current_state = getattr(note, "current_state", None)
            state = getattr(current_state, "state", "") if current_state else ""
            if not state:
                continue

            note_type = ""
            try:
                note_type = note.note_type_version.name or ""
            except Exception:
                note_type = ""

            dos = getattr(note, "datetime_of_service", None) or getattr(note, "created", None)

            notes.append({
                "id": str(note.id),
                "note_type": note_type,
                "datetime_of_service": _iso(dos),
                "modified": _iso(note.modified),
                "state": state,
                "locked": state in LOCKED_STATE_VALUES,
            })

        notes.sort(
            key=lambda n: (n.get("datetime_of_service") or "", n.get("modified") or ""),
            reverse=True,
        )

        first = (getattr(patient, "first_name", "") or "").strip()
        last = (getattr(patient, "last_name", "") or "").strip()
        patient_name = f"{first} {last}".strip() or getattr(patient, "mrn", "") or str(patient_id)

        return [
            JSONResponse({
                "success": True,
                "notes": notes,
                "count": len(notes),
                "patient_name": patient_name,
            })
        ]
