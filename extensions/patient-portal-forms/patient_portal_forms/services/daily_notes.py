"""Find-or-create logic for the bundled portal-form note.

Submissions on the same calendar day land in the same Note when bundling
is supported. Bundling requires the instance to have a proper "Patient
Portal Form" note type — when the plugin falls back to a Data Import note
type, each submission gets its own note (verified empirically against the
home-app: DATA notes are effectively one-shot writes).
"""

from __future__ import annotations

import uuid
from datetime import date

from canvas_sdk.v1.data.note import Note, NoteStates

from patient_portal_forms.models import CustomPatient, PatientDailyNote


# Notes in these states cannot accept new commands, so we can't bundle into
# them — the submit endpoint mints a fresh note and updates the pointer.
_UNREUSABLE_NOTE_STATES = {
    NoteStates.LOCKED,
    NoteStates.RELOCKED,
    NoteStates.DELETED,
    NoteStates.CANCELLED,
}


def _note_is_reusable(note: Note | None) -> bool:
    if note is None:
        return False
    # `current_state` is backed by a view (CurrentNoteStateEvent) that only
    # has a row once a NoteStateChangeEvent has been written for the note.
    # Plugin-created notes may not have a state row yet — that's still
    # editable, so treat missing state as reusable.
    state = note.current_state.state if note.current_state else None
    return state not in _UNREUSABLE_NOTE_STATES


class DailyNoteService:
    """Resolve the bundle note UUID for a (patient, day) pair."""

    @classmethod
    def resolve(
        cls,
        patient_id: str,
        day: date,
        *,
        bundle: bool,
    ) -> tuple[uuid.UUID, bool]:
        """Return ``(note_uuid, reuse)``.

        ``bundle=False`` (used when falling back to a Data Import note type)
        always returns a fresh UUID and ``reuse=False``. DATA notes are
        one-shot writes — bundling into them silently drops the second
        submission.

        ``bundle=True`` looks up the existing pointer for (patient, day):

        - If the pointed-at note still accepts writes, returns its UUID
          and ``reuse=True``. The caller then skips ``NoteEffect.create``
          and just appends QuestionnaireCommand effects to the existing note.

        - Otherwise allocates a new UUID, replaces the pointer in place via
          ``update_or_create`` (no constraint violation — the unique key is
          (patient, date) and we're rewriting the same row), and returns
          ``reuse=False``.
        """
        if not bundle:
            return uuid.uuid4(), False

        patient = CustomPatient.objects.get(id=patient_id)
        pointer = PatientDailyNote.objects.filter(patient=patient, date=day).first()
        if pointer:
            existing_note = (
                Note.objects.select_related("current_state")
                .filter(id=pointer.note_uuid)
                .first()
            )
            if _note_is_reusable(existing_note):
                return uuid.UUID(pointer.note_uuid), True

        new_uuid = uuid.uuid4()
        PatientDailyNote.objects.update_or_create(
            patient=patient,
            date=day,
            defaults={"note_uuid": str(new_uuid)},
        )
        return new_uuid, False
