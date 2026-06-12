"""SimpleAPI endpoint that saves a combined PDF as a DocumentReference.

The browser assembles all captured/uploaded pages into a single PDF (pdf-lib) and
posts it as the `document` file part. This handler validates, base64-encodes, and
creates the DocumentReference via the Canvas FHIR client — no server-side PDF
libraries are required (they are not available in the plugin sandbox).
"""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.encounter import Encounter
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.patient import Patient

from logger import log

from capture.services.document_fhir import create_document_reference
from capture.services.media_fhir import create_media
from capture.services.patient_photo import update_patient_photo
from capture.utils.constants import (
    CLINICAL_DATE_FORMAT,
    DOCUMENT_TYPES,
    IDEMPOTENCY_CACHE_PREFIX,
    IDEMPOTENCY_TTL_SECONDS,
    IMAGE_CONTENT_TYPES,
    MAX_PDF_BYTES,
    MAX_TITLE_LENGTH,
    PDF_CONTENT_TYPE,
    PLUGIN_NAME,
    SECRET_FHIR_CLIENT_ID,
    SECRET_FHIR_CLIENT_SECRET,
)

# Note states a clinical image can be attached to: editable notes only (excludes
# LOCKED / SIGNED). Matches CurrentNoteStateEvent.editable() and the simulator picker.
EDITABLE_NOTE_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]

# Image magic bytes — JPEG (FF D8 FF) / PNG (89 50 4E 47).
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")


def _is_supported_image(data: bytes) -> bool:
    return any(data.startswith(sig) for sig in _IMAGE_MAGIC)

# Cache bust for the served modal HTML; regenerated on each deploy/restart.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


def _error(message: str, status: HTTPStatus) -> list:
    return [JSONResponse({"ok": False, "error": message}, status_code=status)]


def _str_field(form: Any, name: str) -> str:
    """Read a string form field safely (ignores file parts; never raises).

    Typed as ``Any`` deliberately: it duck-types over any form-part variant
    (``StringFormPart`` exposes ``.value``; file parts don't) and over the
    lightweight doubles used in tests.
    """
    if name not in form:
        return ""
    part = form[name]
    if part.is_file():
        return ""
    value: str = part.value or ""
    return value


class DocumentAPI(StaffSessionAuthMixin, SimpleAPI):
    """Receives a combined PDF + metadata and creates a DocumentReference."""

    PREFIX = "/documents"

    @api.get("/ui")
    def companion_ui(self) -> list[Response | Effect]:
        """Serve the capture/upload modal HTML for URL-iframe surfaces.

        The in-chart app drawer renders the modal via inline ``content=`` (see
        ``document_app.PatientDocumentCaptureApp``). The Provider Companion modal
        instead renders a URL iframe, so its Application points here; this returns
        the same ``upload_modal.html`` with the patient pre-associated from the
        ``patient_id`` query param.
        """
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        html = render_to_string(
            "templates/upload_modal.html",
            {
                "patient_id": patient_id,
                "api_base": f"/plugin-io/api/{PLUGIN_NAME}",
                "cache_bust": _CACHE_BUST,
                # The Provider Companion supplies its own close/back chrome, so
                # hide our in-modal X on this surface.
                "show_close": False,
            },
        )
        return [
            HTMLResponse(
                html,
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "no-store"},
            )
        ]

    @api.get("/notes")
    def list_notes(self) -> list[Response | Effect]:
        """Eligible notes for the Exam-photo picker: the current author's editable
        notes for this patient that have an encounter (a Media needs one)."""
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return _error("patient_id is required.", HTTPStatus.BAD_REQUEST)
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return _error("Could not determine the current user.", HTTPStatus.BAD_REQUEST)

        open_ids = CurrentNoteStateEvent.objects.filter(
            state__in=EDITABLE_NOTE_STATES
        ).values_list("note_id", flat=True)
        notes = (
            Note.objects.filter(
                dbid__in=open_ids, patient__id=patient_id, provider__id=staff_id
            )
            .exclude(encounter__isnull=True)
            .select_related("note_type_version")
            .order_by("-datetime_of_service")[:25]
        )
        result = [
            {
                "id": str(note.id),
                "note_type": note.note_type_version.name if note.note_type_version else "Note",
                "title": note.title or "",
                "datetime_of_service": (
                    note.datetime_of_service.isoformat() if note.datetime_of_service else ""
                ),
            }
            for note in notes
        ]
        return [JSONResponse({"ok": True, "notes": result}, status_code=HTTPStatus.OK)]

    @api.post("/insert-image")
    def insert_image(self) -> list[Response | Effect]:
        """Attach a single image to a note as a FHIR Media (Exam photo branch)."""
        form = self.request.form_data()
        note_id = _str_field(form, "note_id")
        idempotency_key = _str_field(form, "idempotency_key").strip()
        caption = " ".join(_str_field(form, "caption").split())[:MAX_TITLE_LENGTH] or "Clinical photo"

        if not note_id:
            return _error("note_id is required.", HTTPStatus.BAD_REQUEST)
        if "image" not in form or not form["image"].is_file():
            return _error("An image is required.", HTTPStatus.BAD_REQUEST)

        part = form["image"]
        content_type = (part.content_type or "").lower().split(";")[0].strip()
        if content_type not in IMAGE_CONTENT_TYPES:
            return _error("The image must be a JPG or PNG.", HTTPStatus.BAD_REQUEST)
        image_bytes = part.content
        if not image_bytes:
            return _error("The image is empty.", HTTPStatus.BAD_REQUEST)
        if not _is_supported_image(image_bytes):
            return _error("The image must be a JPG or PNG.", HTTPStatus.BAD_REQUEST)
        if len(image_bytes) > MAX_PDF_BYTES:
            return _error("The image is too large.", HTTPStatus.BAD_REQUEST)

        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return _error("Could not determine the current user.", HTTPStatus.BAD_REQUEST)

        # Re-enforce the picker's rules server-side (the client-side list isn't enough):
        # the note must be the current user's own, in an editable state (NOT locked/signed),
        # and have an encounter. Mirrors the GET /notes query for this single note.
        open_ids = CurrentNoteStateEvent.objects.filter(
            state__in=EDITABLE_NOTE_STATES
        ).values_list("note_id", flat=True)
        note = (
            Note.objects.filter(id=note_id, dbid__in=open_ids, provider__id=staff_id)
            .exclude(encounter__isnull=True)
            .select_related("patient")
            .first()
        )
        if note is None or note.patient is None:
            return _error(
                "That note can't accept an image — it must be one of your own open notes.",
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        encounter = Encounter.objects.filter(note__id=note_id).first()
        if encounter is None:
            return _error(
                "This note has no encounter; an image can't be attached.",
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        client_id = self.secrets.get(SECRET_FHIR_CLIENT_ID)
        client_secret = self.secrets.get(SECRET_FHIR_CLIENT_SECRET)
        if not client_id or not client_secret:
            log.error("FHIR client credentials are not configured")
            return _error("Image service is not configured.", HTTPStatus.INTERNAL_SERVER_ERROR)

        cache = None
        cache_key = ""
        if idempotency_key:
            cache = get_cache()
            cache_key = f"{IDEMPOTENCY_CACHE_PREFIX}{idempotency_key}"
            existing = cache.get(cache_key)
            if existing:
                log.info(f"Idempotent replay: returning existing Media {existing}")
                return [JSONResponse({"ok": True, "media_id": existing}, status_code=HTTPStatus.OK)]

        try:
            media_id = create_media(
                client_id=client_id,
                client_secret=client_secret,
                patient_id=str(note.patient.id),
                encounter_id=str(encounter.id),
                image_bytes=image_bytes,
                content_type=content_type,
                title=caption,
            )
        except Exception as exc:  # noqa: BLE001 - surface clean error, log truncated detail
            log.error(f"Media create failed: {str(exc)[:500]}")
            return _error("Could not add the image to the note.", HTTPStatus.BAD_GATEWAY)

        if cache and cache_key:
            cache.set(cache_key, media_id, timeout_seconds=IDEMPOTENCY_TTL_SECONDS)

        log.info(f"Saved Media id={media_id} note={note_id} patient={note.patient.id}")
        return [
            JSONResponse({"ok": True, "media_id": media_id}, status_code=HTTPStatus.CREATED)
        ]

    @api.post("/set-photo")
    def set_photo(self) -> list[Response | Effect]:
        """Set the patient's profile picture (Patient.photo) from a single image."""
        form = self.request.form_data()
        patient_id = _str_field(form, "patient_id")
        if not patient_id:
            return _error("patient_id is required.", HTTPStatus.BAD_REQUEST)
        if "image" not in form or not form["image"].is_file():
            return _error("An image is required.", HTTPStatus.BAD_REQUEST)

        part = form["image"]
        content_type = (part.content_type or "").lower().split(";")[0].strip()
        if content_type not in IMAGE_CONTENT_TYPES:
            return _error("The image must be a JPG or PNG.", HTTPStatus.BAD_REQUEST)
        image_bytes = part.content
        if not image_bytes:
            return _error("The image is empty.", HTTPStatus.BAD_REQUEST)
        if not _is_supported_image(image_bytes):
            return _error("The image must be a JPG or PNG.", HTTPStatus.BAD_REQUEST)
        if len(image_bytes) > MAX_PDF_BYTES:
            return _error("The image is too large.", HTTPStatus.BAD_REQUEST)

        if not Patient.objects.filter(id=patient_id).exists():
            return _error("Patient not found.", HTTPStatus.BAD_REQUEST)

        client_id = self.secrets.get(SECRET_FHIR_CLIENT_ID)
        client_secret = self.secrets.get(SECRET_FHIR_CLIENT_SECRET)
        if not client_id or not client_secret:
            log.error("FHIR client credentials are not configured")
            return _error("Photo service is not configured.", HTTPStatus.INTERNAL_SERVER_ERROR)

        try:
            update_patient_photo(
                client_id=client_id,
                client_secret=client_secret,
                patient_id=patient_id,
                image_bytes=image_bytes,
                content_type=content_type,
            )
        except Exception as exc:  # noqa: BLE001 - surface clean error, log truncated detail
            log.error(f"Patient photo update failed: {str(exc)[:500]}")
            return _error("Could not update the profile picture.", HTTPStatus.BAD_GATEWAY)

        log.info(f"Updated profile picture for patient={patient_id}")
        return [JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]

    @api.post("/submit")
    def submit_document(self) -> list[Response | Effect]:
        """Save the posted PDF to the patient's chart.

        Expects multipart/form-data with:
        - document: a single application/pdf file part (assembled in the browser)
        - patient_id: string
        - document_type: "clinical" | "administrative"
        - title: non-empty string
        """
        form = self.request.form_data()

        # --- metadata (read safely; ignores file parts, never raises) ---
        patient_id = _str_field(form, "patient_id")
        document_type = _str_field(form, "document_type")
        clinical_date_raw = _str_field(form, "clinical_date").strip()
        idempotency_key = _str_field(form, "idempotency_key").strip()

        # Sanitize the title to a clean single line and cap its length so it can
        # never break the (single-line) document title field on the Canvas record.
        title = " ".join(_str_field(form, "title").split())[:MAX_TITLE_LENGTH]

        if not patient_id:
            return _error("patient_id is required.", HTTPStatus.BAD_REQUEST)
        if document_type not in DOCUMENT_TYPES:
            return _error("A valid document_type is required.", HTTPStatus.BAD_REQUEST)
        if not title:
            return _error("A title is required.", HTTPStatus.BAD_REQUEST)

        # fumage requires a strictly zero-padded YYYY-MM-DD date. Parse to validate it
        # is a real date, then re-emit the canonical form so non-padded input
        # (e.g. 2026-6-9) can't be rejected downstream.
        try:
            parsed_date = datetime.strptime(clinical_date_raw, CLINICAL_DATE_FORMAT)
            clinical_date = parsed_date.strftime(CLINICAL_DATE_FORMAT)
        except ValueError:
            return _error(
                "A valid document date (YYYY-MM-DD) is required.",
                HTTPStatus.BAD_REQUEST,
            )

        # A clinical document date in the future is almost always a typo; reject it.
        if parsed_date.date() > datetime.now().date():
            return _error(
                "The document date can’t be in the future.",
                HTTPStatus.BAD_REQUEST,
            )

        if not Patient.objects.filter(id=patient_id).exists():
            return _error("Patient not found.", HTTPStatus.BAD_REQUEST)

        # The logged-in staff member is recorded as the document reviewer.
        reviewer_id = self.request.headers.get("canvas-logged-in-user-id")
        if not reviewer_id:
            return _error(
                "Could not determine the current user.", HTTPStatus.BAD_REQUEST
            )

        # --- document (single combined PDF) ---
        if "document" not in form or not form["document"].is_file():
            return _error("A document file is required.", HTTPStatus.BAD_REQUEST)

        part = form["document"]
        content_type = (part.content_type or "").lower().split(";")[0].strip()
        if content_type != PDF_CONTENT_TYPE:
            return _error("The document must be a PDF.", HTTPStatus.BAD_REQUEST)

        pdf_bytes = part.content
        if not pdf_bytes:
            return _error("The document is empty.", HTTPStatus.BAD_REQUEST)
        # Defense-in-depth: confirm the bytes are actually a PDF, not just a part
        # labeled application/pdf. (The browser assembles every document with pdf-lib,
        # so valid uploads always start with the %PDF- header.)
        if not pdf_bytes.startswith(b"%PDF-"):
            return _error("The document must be a PDF.", HTTPStatus.BAD_REQUEST)
        if len(pdf_bytes) > MAX_PDF_BYTES:
            return _error("The document is too large.", HTTPStatus.BAD_REQUEST)

        # --- secrets ---
        client_id = self.secrets.get(SECRET_FHIR_CLIENT_ID)
        client_secret = self.secrets.get(SECRET_FHIR_CLIENT_SECRET)
        if not client_id or not client_secret:
            log.error("FHIR client credentials are not configured")
            return _error(
                "Document service is not configured.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        # --- idempotency: if this attempt already succeeded, return the same id ---
        cache = None
        cache_key = ""
        if idempotency_key:
            cache = get_cache()
            cache_key = f"{IDEMPOTENCY_CACHE_PREFIX}{idempotency_key}"
            existing = cache.get(cache_key)
            if existing:
                log.info(f"Idempotent replay: returning existing DocumentReference {existing}")
                return [
                    JSONResponse(
                        {"ok": True, "document_reference_id": existing},
                        status_code=HTTPStatus.OK,
                    )
                ]

        # --- create DocumentReference ---
        try:
            document_reference_id = create_document_reference(
                client_id=client_id,
                client_secret=client_secret,
                patient_id=patient_id,
                document_type_key=document_type,
                title=title,
                pdf_bytes=pdf_bytes,
                reviewer_id=reviewer_id,
                clinical_date=clinical_date,
            )
        except Exception as exc:  # noqa: BLE001 - surface clean error, log truncated detail
            log.error(f"DocumentReference create failed: {str(exc)[:500]}")
            return _error(
                "Could not save the document to the chart.",
                HTTPStatus.BAD_GATEWAY,
            )

        if cache and cache_key:
            cache.set(cache_key, document_reference_id, timeout_seconds=IDEMPOTENCY_TTL_SECONDS)

        log.info(
            "Saved DocumentReference "
            f"id={document_reference_id} patient={patient_id} type={document_type}"
        )
        return [
            JSONResponse(
                {"ok": True, "document_reference_id": document_reference_id},
                status_code=HTTPStatus.CREATED,
            )
        ]
