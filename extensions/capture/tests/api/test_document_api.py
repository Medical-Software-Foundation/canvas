"""Tests for the DocumentAPI SimpleAPI endpoint."""

import json
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory

from capture.api import document_api as da
from capture.api.document_api import DocumentAPI

PDF = b"%PDF-1.4 combined document"
SECRETS = {
    "CANVAS_FHIR_CLIENT_ID": "cid",
    "CANVAS_FHIR_CLIENT_SECRET": "secret",
}


class StrPart:
    def __init__(self, value):
        self.value = value

    def is_file(self):
        return False


class FilePart:
    def __init__(self, content, content_type):
        self.content = content
        self.content_type = content_type

    def is_file(self):
        return True


def make_form(
    patient_id="p", document_type="clinical", title="Note",
    clinical_date="2026-06-09", document="pdf",
):
    form = {}
    if patient_id is not None:
        form["patient_id"] = StrPart(patient_id)
    if document_type is not None:
        form["document_type"] = StrPart(document_type)
    if title is not None:
        form["title"] = StrPart(title)
    if clinical_date is not None:
        form["clinical_date"] = StrPart(clinical_date)
    if document == "pdf":
        form["document"] = FilePart(PDF, "application/pdf")
    elif document is not None:
        form["document"] = document
    return form


@pytest.fixture
def doc_api():
    api = DocumentAPI.__new__(DocumentAPI)
    api.secrets = dict(SECRETS)
    api.request = Mock()
    api.request.headers = {"canvas-logged-in-user-id": "staff-1"}
    return api


def _run(doc_api, form):
    doc_api.request.form_data.return_value = form
    return doc_api.submit_document()


def _body(response):
    return json.loads(response[0].content)


# ---- companion UI endpoint (GET /documents/ui) ----

def test_companion_ui_serves_modal_html_with_patient(doc_api) -> None:
    doc_api.request.query_params = {"patient_id": "patient-789"}
    with patch(
        "capture.api.document_api.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html>modal</html>"
        resp = doc_api.companion_ui()
        assert resp[0].status_code == HTTPStatus.OK
        template, context = mock_render.call_args[0]
        assert template == "templates/upload_modal.html"
        assert context["patient_id"] == "patient-789"
        assert context["api_base"] == "/plugin-io/api/capture"
        assert "cache_bust" in context
        assert context["show_close"] is False  # companion hides our X (has own chrome)


def test_companion_ui_without_patient_id(doc_api) -> None:
    doc_api.request.query_params = {}
    with patch(
        "capture.api.document_api.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html></html>"
        resp = doc_api.companion_ui()
        assert resp[0].status_code == HTTPStatus.OK
        _, context = mock_render.call_args[0]
        assert context["patient_id"] == ""


# ---- validation (no DB needed) ----

def test_missing_patient_id(doc_api) -> None:
    resp = _run(doc_api, make_form(patient_id=None))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST
    assert _body(resp)["ok"] is False


def test_invalid_document_type(doc_api) -> None:
    resp = _run(doc_api, make_form(document_type="bogus"))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_empty_title(doc_api) -> None:
    resp = _run(doc_api, make_form(title="   "))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_invalid_date(doc_api) -> None:
    resp = _run(doc_api, make_form(clinical_date="06/09/2026"))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_impossible_date(doc_api) -> None:
    resp = _run(doc_api, make_form(clinical_date="2026-13-40"))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_future_date_rejected(doc_api) -> None:
    resp = _run(doc_api, make_form(clinical_date="2099-12-31"))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST
    assert "future" in _body(resp).get("error", "").lower()


# ---- DB-backed paths ----

@pytest.mark.django_db
def test_patient_not_found(doc_api) -> None:
    resp = _run(doc_api, make_form(patient_id="00000000000000000000000000000000"))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST
    assert "Patient not found" in _body(resp)["error"]


@pytest.mark.django_db
def test_missing_document_part(doc_api) -> None:
    patient = PatientFactory.create()
    resp = _run(doc_api, make_form(patient_id=str(patient.id), document=None))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_non_pdf_document_rejected(doc_api) -> None:
    patient = PatientFactory.create()
    form = make_form(patient_id=str(patient.id), document=FilePart(b"x", "image/jpeg"))
    resp = _run(doc_api, form)
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_empty_pdf_rejected(doc_api) -> None:
    patient = PatientFactory.create()
    form = make_form(patient_id=str(patient.id), document=FilePart(b"", "application/pdf"))
    resp = _run(doc_api, form)
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_oversized_pdf_rejected(doc_api) -> None:
    from capture.utils.constants import MAX_PDF_BYTES

    patient = PatientFactory.create()
    big = b"%PDF-" + b"0" * (MAX_PDF_BYTES + 1)
    form = make_form(patient_id=str(patient.id), document=FilePart(big, "application/pdf"))
    resp = _run(doc_api, form)
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_pdf_content_type_but_not_pdf_bytes_rejected(doc_api) -> None:
    """A part labeled application/pdf whose bytes aren't a PDF is rejected (magic-byte check)."""
    patient = PatientFactory.create()
    form = make_form(
        patient_id=str(patient.id),
        document=FilePart(b"GIF89a not really a pdf", "application/pdf"),
    )
    resp = _run(doc_api, form)
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST
    assert "PDF" in _body(resp).get("error", "")


@pytest.mark.django_db
def test_missing_secrets(doc_api) -> None:
    patient = PatientFactory.create()
    doc_api.secrets = {}
    resp = _run(doc_api, make_form(patient_id=str(patient.id)))
    assert resp[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.django_db
def test_happy_path_creates_document_reference(doc_api) -> None:
    patient = PatientFactory.create()
    with patch(
        "capture.api.document_api.create_document_reference",
        return_value="docref-1",
    ) as mock_create:
        resp = _run(doc_api, make_form(patient_id=str(patient.id), title="My doc"))

    assert resp[0].status_code == HTTPStatus.CREATED
    body = _body(resp)
    assert body["ok"] is True
    assert body["document_reference_id"] == "docref-1"
    kwargs = mock_create.call_args.kwargs
    assert kwargs["patient_id"] == str(patient.id)
    assert kwargs["document_type_key"] == "clinical"
    assert kwargs["title"] == "My doc"
    assert kwargs["pdf_bytes"] == PDF
    assert kwargs["reviewer_id"] == "staff-1"
    assert kwargs["clinical_date"] == "2026-06-09"


@pytest.mark.django_db
def test_missing_logged_in_user(doc_api) -> None:
    patient = PatientFactory.create()
    doc_api.request.headers = {}
    resp = _run(doc_api, make_form(patient_id=str(patient.id)))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_title_sanitized_to_single_line(doc_api) -> None:
    patient = PatientFactory.create()
    with patch(
        "capture.api.document_api.create_document_reference",
        return_value="docref-1",
    ) as mock_create:
        _run(doc_api, make_form(patient_id=str(patient.id), title="  Line one\nLine\ttwo  "))
    assert mock_create.call_args.kwargs["title"] == "Line one Line two"


@pytest.mark.django_db
def test_title_capped(doc_api) -> None:
    patient = PatientFactory.create()
    with patch(
        "capture.api.document_api.create_document_reference",
        return_value="docref-1",
    ) as mock_create:
        _run(doc_api, make_form(patient_id=str(patient.id), title="x" * 600))
    assert len(mock_create.call_args.kwargs["title"]) == 255


@pytest.mark.django_db
def test_date_canonicalized_to_zero_padded(doc_api) -> None:
    patient = PatientFactory.create()
    with patch(
        "capture.api.document_api.create_document_reference",
        return_value="docref-1",
    ) as mock_create:
        _run(doc_api, make_form(patient_id=str(patient.id), clinical_date="2026-6-9"))
    assert mock_create.call_args.kwargs["clinical_date"] == "2026-06-09"


@pytest.mark.django_db
def test_idempotent_replay_returns_existing_without_creating(doc_api) -> None:
    patient = PatientFactory.create()
    mock_cache = Mock()
    mock_cache.get.return_value = "docref-existing"
    with patch("capture.api.document_api.get_cache", return_value=mock_cache), \
         patch("capture.api.document_api.create_document_reference") as mock_create:
        form = make_form(patient_id=str(patient.id))
        form["idempotency_key"] = StrPart("key-123")
        resp = _run(doc_api, form)

    assert resp[0].status_code == HTTPStatus.OK
    body = _body(resp)
    assert body["ok"] is True
    assert body["document_reference_id"] == "docref-existing"
    mock_create.assert_not_called()


@pytest.mark.django_db
def test_idempotency_key_cached_after_create(doc_api) -> None:
    patient = PatientFactory.create()
    mock_cache = Mock()
    mock_cache.get.return_value = None
    with patch("capture.api.document_api.get_cache", return_value=mock_cache), \
         patch("capture.api.document_api.create_document_reference", return_value="docref-new"):
        form = make_form(patient_id=str(patient.id))
        form["idempotency_key"] = StrPart("key-abc")
        resp = _run(doc_api, form)

    assert resp[0].status_code == HTTPStatus.CREATED
    args, kwargs = mock_cache.set.call_args
    assert args[0].endswith("key-abc")
    assert args[1] == "docref-new"


# ---- GET /documents/notes (Exam-photo picker) ----

def test_list_notes_requires_patient(doc_api) -> None:
    doc_api.request.query_params = {}
    resp = doc_api.list_notes()
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_list_notes_requires_current_user(doc_api) -> None:
    doc_api.request.query_params = {"patient_id": "p1"}
    doc_api.request.headers = {}
    resp = doc_api.list_notes()
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_list_notes_returns_eligible_notes(doc_api) -> None:
    import datetime as _dt

    doc_api.request.query_params = {"patient_id": "p1"}
    doc_api.request.headers = {"canvas-logged-in-user-id": "staff-1"}
    note = SimpleNamespace(
        id="note-uuid", title="",
        note_type_version=SimpleNamespace(name="Office Visit"),
        datetime_of_service=_dt.datetime(2026, 6, 10, 10, 30),
    )
    cnse = MagicMock()
    cnse.filter.return_value.values_list.return_value = [101]
    notes_mgr = MagicMock()
    (notes_mgr.filter.return_value.exclude.return_value
     .select_related.return_value.order_by.return_value.__getitem__.return_value) = [note]
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", notes_mgr):
        resp = doc_api.list_notes()
    assert resp[0].status_code == HTTPStatus.OK
    body = _body(resp)
    assert body["ok"] is True
    assert body["notes"][0]["id"] == "note-uuid"
    assert body["notes"][0]["note_type"] == "Office Visit"
    assert body["notes"][0]["datetime_of_service"].startswith("2026-06-10")


# ---- POST /documents/insert-image (Exam photo → Media) ----

JPEG = b"\xff\xd8\xff\xe0 fake jpeg"


def _img_form(note_id="note-1", image=JPEG, ctype="image/jpeg", **extra):
    form = {}
    if note_id is not None:
        form["note_id"] = StrPart(note_id)
    if image is not None:
        form["image"] = FilePart(image, ctype)
    for k, v in extra.items():
        form[k] = StrPart(v)
    return form


def _run_insert(doc_api, form):
    doc_api.request.form_data.return_value = form
    return doc_api.insert_image()


def test_insert_image_requires_note_id(doc_api) -> None:
    assert _run_insert(doc_api, _img_form(note_id=None))[0].status_code == HTTPStatus.BAD_REQUEST


def test_insert_image_requires_image(doc_api) -> None:
    form = _img_form()
    del form["image"]
    assert _run_insert(doc_api, form)[0].status_code == HTTPStatus.BAD_REQUEST


def test_insert_image_rejects_non_image_content_type(doc_api) -> None:
    assert _run_insert(doc_api, _img_form(ctype="application/pdf"))[0].status_code == HTTPStatus.BAD_REQUEST


def test_insert_image_rejects_non_image_bytes(doc_api) -> None:
    resp = _run_insert(doc_api, _img_form(image=b"GIF89a not an image"))
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_insert_image_rejects_empty(doc_api) -> None:
    assert _run_insert(doc_api, _img_form(image=b""))[0].status_code == HTTPStatus.BAD_REQUEST


def test_insert_image_oversized(doc_api) -> None:
    big = b"\xff\xd8\xff" + b"0" * (da.MAX_PDF_BYTES + 1)
    assert _run_insert(doc_api, _img_form(image=big))[0].status_code == HTTPStatus.BAD_REQUEST


def _elig_mgrs(eligible=True, patient_id="pat-1", encounter_id="enc-1"):
    """Configure (CurrentNoteStateEvent, Note, Encounter) managers for the eligibility
    query: the note must be the current user's own, editable, and have an encounter."""
    note = SimpleNamespace(patient=(SimpleNamespace(id=patient_id) if patient_id else None))
    cnse = MagicMock()
    cnse.filter.return_value.values_list.return_value = [1]
    notes_mgr = MagicMock()
    (notes_mgr.filter.return_value.exclude.return_value
     .select_related.return_value.first.return_value) = (note if eligible else None)
    enc = MagicMock()
    enc.filter.return_value.first.return_value = (
        SimpleNamespace(id=encounter_id) if encounter_id else None
    )
    return cnse, notes_mgr, enc


def test_insert_image_requires_current_user(doc_api) -> None:
    doc_api.request.headers = {}
    cnse, nm, enc = _elig_mgrs()
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc):
        resp = _run_insert(doc_api, _img_form())
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_insert_image_ineligible_note_rejected(doc_api) -> None:
    # Not the user's own / locked / signed → not returned by the eligibility query.
    cnse, nm, enc = _elig_mgrs(eligible=False)
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc), \
         patch.object(da, "create_media") as mock_create:
        resp = _run_insert(doc_api, _img_form())
    assert resp[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    mock_create.assert_not_called()


def test_insert_image_no_encounter(doc_api) -> None:
    cnse, nm, enc = _elig_mgrs(encounter_id=None)
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc):
        resp = _run_insert(doc_api, _img_form())
    assert resp[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_insert_image_success(doc_api) -> None:
    cnse, nm, enc = _elig_mgrs()
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc), \
         patch.object(da, "create_media", return_value="media-1") as mock_create:
        resp = _run_insert(doc_api, _img_form(caption="Left forearm"))
    assert resp[0].status_code == HTTPStatus.CREATED
    body = _body(resp)
    assert body["ok"] is True and body["media_id"] == "media-1"
    kwargs = mock_create.call_args.kwargs
    assert kwargs["encounter_id"] == "enc-1" and kwargs["patient_id"] == "pat-1"
    assert kwargs["title"] == "Left forearm"


def test_insert_image_not_configured(doc_api) -> None:
    doc_api.secrets = {}
    cnse, nm, enc = _elig_mgrs()
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc):
        resp = _run_insert(doc_api, _img_form())
    assert resp[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_insert_image_create_failure(doc_api) -> None:
    cnse, nm, enc = _elig_mgrs()
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc), \
         patch.object(da, "create_media", side_effect=RuntimeError("boom")):
        resp = _run_insert(doc_api, _img_form())
    assert resp[0].status_code == HTTPStatus.BAD_GATEWAY


def test_insert_image_caches_after_create(doc_api) -> None:
    cnse, nm, enc = _elig_mgrs()
    mock_cache = Mock()
    mock_cache.get.return_value = None
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc), \
         patch("capture.api.document_api.get_cache", return_value=mock_cache), \
         patch.object(da, "create_media", return_value="media-2"):
        resp = _run_insert(doc_api, _img_form(idempotency_key="ik-2"))
    assert resp[0].status_code == HTTPStatus.CREATED
    args, _ = mock_cache.set.call_args
    assert args[0].endswith("ik-2") and args[1] == "media-2"


def test_insert_image_idempotent_replay(doc_api) -> None:
    cnse, nm, enc = _elig_mgrs()
    mock_cache = Mock()
    mock_cache.get.return_value = "media-existing"
    with patch.object(da.CurrentNoteStateEvent, "objects", cnse), \
         patch.object(da.Note, "objects", nm), patch.object(da.Encounter, "objects", enc), \
         patch("capture.api.document_api.get_cache", return_value=mock_cache), \
         patch.object(da, "create_media") as mock_create:
        resp = _run_insert(doc_api, _img_form(idempotency_key="ik-1"))
    assert resp[0].status_code == HTTPStatus.OK
    assert _body(resp)["media_id"] == "media-existing"
    mock_create.assert_not_called()


# ---- POST /documents/set-photo (Profile picture → Patient.photo) ----

PNG = b"\x89PNG\r\n\x1a\n fake png"


def _photo_form(patient_id="pat-1", image=PNG, ctype="image/png"):
    form = {}
    if patient_id is not None:
        form["patient_id"] = StrPart(patient_id)
    if image is not None:
        form["image"] = FilePart(image, ctype)
    return form


def _run_setphoto(doc_api, form):
    doc_api.request.form_data.return_value = form
    return doc_api.set_photo()


def test_set_photo_requires_patient(doc_api) -> None:
    f = _photo_form(patient_id=None)
    assert _run_setphoto(doc_api, f)[0].status_code == HTTPStatus.BAD_REQUEST


def test_set_photo_requires_image(doc_api) -> None:
    f = _photo_form()
    del f["image"]
    assert _run_setphoto(doc_api, f)[0].status_code == HTTPStatus.BAD_REQUEST


def test_set_photo_bad_content_type(doc_api) -> None:
    assert _run_setphoto(doc_api, _photo_form(ctype="application/pdf"))[0].status_code == HTTPStatus.BAD_REQUEST


def test_set_photo_bad_bytes(doc_api) -> None:
    assert _run_setphoto(doc_api, _photo_form(image=b"not an image"))[0].status_code == HTTPStatus.BAD_REQUEST


def test_set_photo_empty(doc_api) -> None:
    assert _run_setphoto(doc_api, _photo_form(image=b""))[0].status_code == HTTPStatus.BAD_REQUEST


def test_set_photo_oversized(doc_api) -> None:
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (da.MAX_PDF_BYTES + 1)
    assert _run_setphoto(doc_api, _photo_form(image=big))[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_set_photo_patient_not_found(doc_api) -> None:
    f = _photo_form(patient_id="00000000000000000000000000000000")
    assert _run_setphoto(doc_api, f)[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_set_photo_not_configured(doc_api) -> None:
    patient = PatientFactory.create()
    doc_api.secrets = {}
    resp = _run_setphoto(doc_api, _photo_form(patient_id=str(patient.id)))
    assert resp[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.django_db
def test_set_photo_success(doc_api) -> None:
    patient = PatientFactory.create()
    with patch.object(da, "update_patient_photo", return_value=str(patient.id)) as mock_update:
        resp = _run_setphoto(doc_api, _photo_form(patient_id=str(patient.id)))
    assert resp[0].status_code == HTTPStatus.OK
    assert _body(resp)["ok"] is True
    assert mock_update.call_args.kwargs["patient_id"] == str(patient.id)


@pytest.mark.django_db
def test_set_photo_update_failure(doc_api) -> None:
    patient = PatientFactory.create()
    with patch.object(da, "update_patient_photo", side_effect=RuntimeError("boom")):
        resp = _run_setphoto(doc_api, _photo_form(patient_id=str(patient.id)))
    assert resp[0].status_code == HTTPStatus.BAD_GATEWAY


@pytest.mark.django_db
def test_file_part_for_string_field_does_not_crash(doc_api) -> None:
    # A malformed multipart that sends patient_id as a file must not 500.
    patient = PatientFactory.create()
    form = make_form(patient_id=str(patient.id))
    form["title"] = FilePart(b"x", "text/plain")  # title sent as a file part
    resp = _run(doc_api, form)
    # title resolves to empty -> clean 400, not an unhandled 500
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_fhir_error_returns_bad_gateway(doc_api) -> None:
    patient = PatientFactory.create()
    with patch(
        "capture.api.document_api.create_document_reference",
        side_effect=RuntimeError("boom"),
    ):
        resp = _run(doc_api, make_form(patient_id=str(patient.id)))
    assert resp[0].status_code == HTTPStatus.BAD_GATEWAY
    assert _body(resp)["ok"] is False
