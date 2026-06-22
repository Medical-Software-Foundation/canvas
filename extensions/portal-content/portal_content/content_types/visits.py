"""Visit notes portal content.

Lists finalized visit notes, renders an After Visit Summary (AVS) for each, and
resolves the original clinical-note document for "View Note". All data comes
from SDK models (Note, Command, DocumentReference) - no FHIR.

Visibility is gated two ways, both fail-closed:
- NOTE_TYPES: only notes whose note_type_version.code is configured are shown.
- FINALIZED_STATES: only signed/locked/etc. notes are shown (never drafts).

These helpers return plain data (or None); the API handler maps that to HTTP
responses, which keeps the data logic easy to test.
"""

from __future__ import annotations

from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.document_reference import DocumentReference
from canvas_sdk.v1.data.note import Note
from logger import log

from portal_content.services.avs_renderer import AVSRenderer

# Note states a patient is allowed to see: signed, locked, relocked, discarded-lock.
FINALIZED_STATES = ["SGN", "LKD", "RLK", "DSC"]

# DocumentReference category for the original clinical note document.
CLINICAL_NOTE_CATEGORY = "clinical-note"


def get_note_types_filter(secrets: dict) -> list[str]:
    """Return configured allowed note-type codes from NOTE_TYPES (may be empty)."""
    note_types_config = secrets.get("NOTE_TYPES", "")
    return [nt.strip() for nt in note_types_config.split(",") if nt.strip()]


def list_notes(patient_id: str, note_types: list[str], limit: int = 20, offset: int = 0) -> dict:
    """Return a page of the patient's finalized, allowed visit notes, newest first."""
    query = (
        Note.objects.filter(patient__id=patient_id)
        .select_related("note_type_version", "provider", "current_state")
        .filter(
            current_state__state__in=FINALIZED_STATES,
            note_type_version__code__in=note_types,
        )
        .order_by("-created")
    )

    total = query.count()
    notes = list(query[offset : offset + limit])
    log.info(f"Found {total} finalized visit notes for patient {patient_id}")

    return {
        "summaries": [_note_list_info(note) for note in notes],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total,
    }


def render_avs(patient_id: str, note_id: str, note_types: list[str]) -> str | None:
    """Return AVS HTML for a finalized, patient-owned, allowed note, else None."""
    note = _get_accessible_note(patient_id, note_id, note_types)
    if note is None:
        return None
    return AVSRenderer(note_id).render()


def get_note_document(patient_id: str, note_id: str, note_types: list[str]) -> dict | None:
    """Resolve the original clinical-note document for "View Note".

    Returns {"content_url", "content_type"} for a same-origin iframe, or None
    when the note is inaccessible or has no associated document.
    """
    note = _get_accessible_note(patient_id, note_id, note_types)
    if note is None or not note.encounter:
        return None

    document = (
        DocumentReference.objects.for_patient(patient_id)
        .filter(
            category__code=CLINICAL_NOTE_CATEGORY,
            status="current",
            encounter__id=note.encounter.id,
        )
        .order_by("-date")
        .first()
    )

    if document is None:
        return None

    return {
        # Streamed through the plugin's own /document proxy (FHIR-backed).
        "content_url": f"/plugin-io/api/portal_content/app/document?ref_id={document.id}",
        "content_type": document.document_content_type or "",
    }


def _get_accessible_note(patient_id: str, note_id: str, note_types: list[str]) -> Note | None:
    """Fetch a note only if it belongs to the patient, is an allowed type, and is finalized."""
    try:
        note = Note.objects.select_related(
            "note_type_version", "provider", "current_state", "patient"
        ).get(id=note_id)
    except Note.DoesNotExist:
        return None

    if not note.patient or str(note.patient.id) != str(patient_id):
        log.warning(f"Patient {patient_id} denied access to note {note_id} (ownership)")
        return None

    note_type_version = note.note_type_version
    if not note_type_version or note_type_version.code not in note_types:
        log.warning(f"Note {note_id} denied: note type not in configured NOTE_TYPES")
        return None

    current_state = note.current_state
    if not current_state or current_state.state not in FINALIZED_STATES:
        log.warning(f"Note {note_id} denied: not finalized")
        return None

    return note


def _note_list_info(note: Note) -> dict:
    """Minimal card data for the visit list."""
    note_type_version = note.note_type_version
    visit_type = note_type_version.name if note_type_version else None
    return {
        "note_id": str(note.id),
        "visit_date": note.created.isoformat() if note.created else None,
        "visit_type": visit_type,
        "provider_name": _provider_name(note),
        "chief_concern": _chief_concern(note),
    }


def _provider_name(note: Note) -> str:
    """The visit provider's display name, or a neutral fallback."""
    return note.provider.full_name if note.provider else "Provider"


def _chief_concern(note: Note) -> str | None:
    """The reason-for-visit comment from the note's reasonForVisit command, if any."""
    data = (
        Command.objects.filter(
            note=note,
            schema_key="reasonForVisit",
            entered_in_error__isnull=True,
            state="committed",
        )
        .order_by("-dbid")
        .values_list("data", flat=True)
        .first()
    )
    if isinstance(data, dict):
        comment = data.get("comment")
        if comment:
            return str(comment)
    return None
