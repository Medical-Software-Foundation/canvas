"""Tests for the DocumentAPI SimpleAPI endpoint."""

import json
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory

from patient_document_capture.api.document_api import DocumentAPI

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
    from patient_document_capture.utils.constants import MAX_PDF_BYTES

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
        "patient_document_capture.api.document_api.create_document_reference",
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
        "patient_document_capture.api.document_api.create_document_reference",
        return_value="docref-1",
    ) as mock_create:
        _run(doc_api, make_form(patient_id=str(patient.id), title="  Line one\nLine\ttwo  "))
    assert mock_create.call_args.kwargs["title"] == "Line one Line two"


@pytest.mark.django_db
def test_title_capped(doc_api) -> None:
    patient = PatientFactory.create()
    with patch(
        "patient_document_capture.api.document_api.create_document_reference",
        return_value="docref-1",
    ) as mock_create:
        _run(doc_api, make_form(patient_id=str(patient.id), title="x" * 600))
    assert len(mock_create.call_args.kwargs["title"]) == 255


@pytest.mark.django_db
def test_date_canonicalized_to_zero_padded(doc_api) -> None:
    patient = PatientFactory.create()
    with patch(
        "patient_document_capture.api.document_api.create_document_reference",
        return_value="docref-1",
    ) as mock_create:
        _run(doc_api, make_form(patient_id=str(patient.id), clinical_date="2026-6-9"))
    assert mock_create.call_args.kwargs["clinical_date"] == "2026-06-09"


@pytest.mark.django_db
def test_idempotent_replay_returns_existing_without_creating(doc_api) -> None:
    patient = PatientFactory.create()
    mock_cache = Mock()
    mock_cache.get.return_value = "docref-existing"
    with patch("patient_document_capture.api.document_api.get_cache", return_value=mock_cache), \
         patch("patient_document_capture.api.document_api.create_document_reference") as mock_create:
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
    with patch("patient_document_capture.api.document_api.get_cache", return_value=mock_cache), \
         patch("patient_document_capture.api.document_api.create_document_reference", return_value="docref-new"):
        form = make_form(patient_id=str(patient.id))
        form["idempotency_key"] = StrPart("key-abc")
        resp = _run(doc_api, form)

    assert resp[0].status_code == HTTPStatus.CREATED
    args, kwargs = mock_cache.set.call_args
    assert args[0].endswith("key-abc")
    assert args[1] == "docref-new"


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
        "patient_document_capture.api.document_api.create_document_reference",
        side_effect=RuntimeError("boom"),
    ):
        resp = _run(doc_api, make_form(patient_id=str(patient.id)))
    assert resp[0].status_code == HTTPStatus.BAD_GATEWAY
    assert _body(resp)["ok"] is False
