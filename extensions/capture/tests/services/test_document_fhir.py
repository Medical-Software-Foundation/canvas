"""Tests for the document_fhir service."""

import base64
from unittest.mock import patch

from capture.services.document_fhir import (
    build_document_reference_payload,
    create_document_reference,
)
from capture.utils.constants import (
    CLINICAL_DATE_EXTENSION,
    REQUIRES_SIGNATURE_EXTENSION,
    REVIEW_MODE_EXTENSION,
    REVIEWER_EXTENSION,
)

PDF = b"%PDF-1.4 fake pdf bytes"


def _extensions_by_url(payload):
    return {ext["url"]: ext for ext in payload["extension"]}


def test_payload_clinical_mapping() -> None:
    payload = build_document_reference_payload(
        patient_id="pat-1",
        document_type_key="clinical",
        title="Cardiology note",
        pdf_bytes=PDF,
        reviewer_id="staff-1",
        clinical_date="2026-06-08",
    )
    assert payload["resourceType"] == "DocumentReference"
    assert payload["status"] == "current"
    assert payload["type"]["coding"][0]["system"] == "http://loinc.org"
    assert payload["type"]["coding"][0]["code"] == "34109-9"
    assert payload["type"]["text"] == "Uncategorized Clinical Document"
    assert (
        payload["category"][0]["coding"][0]["code"] == "uncategorizedclinicaldocument"
    )
    assert payload["subject"]["reference"] == "Patient/pat-1"
    assert payload["description"] == "Cardiology note"
    att = payload["content"][0]["attachment"]
    assert att["contentType"] == "application/pdf"
    assert att["title"] == "Cardiology note"
    assert base64.b64decode(att["data"]) == PDF


def test_payload_required_extensions() -> None:
    payload = build_document_reference_payload(
        patient_id="pat-1",
        document_type_key="clinical",
        title="Note",
        pdf_bytes=PDF,
        reviewer_id="staff-9",
        clinical_date="2026-06-08",
    )
    exts = _extensions_by_url(payload)
    assert exts[CLINICAL_DATE_EXTENSION]["valueDate"] == "2026-06-08"
    assert (
        exts[REVIEWER_EXTENSION]["valueReference"]["reference"]
        == "Practitioner/staff-9"
    )
    assert exts[REQUIRES_SIGNATURE_EXTENSION]["valueBoolean"] is False
    assert exts[REVIEW_MODE_EXTENSION]["valueCode"] == "RN"


def test_payload_administrative_mapping() -> None:
    payload = build_document_reference_payload(
        patient_id="pat-2",
        document_type_key="administrative",
        title="Insurance card",
        pdf_bytes=PDF,
        reviewer_id="staff-1",
        clinical_date="2026-06-08",
    )
    assert payload["type"]["coding"][0]["code"] == "51851-4"
    assert (
        payload["category"][0]["coding"][0]["code"] == "patientadministrativedocument"
    )


def _patched_client_and_http():
    """Patch CanvasFhir (auth/base_url) and Http (the POST). Returns (CanvasFhir, Http)."""
    return (
        patch("capture.services.document_fhir.CanvasFhir"),
        patch("capture.services.document_fhir.Http"),
    )


def test_create_document_reference_posts_and_reads_location() -> None:
    cf, ht = _patched_client_and_http()
    with cf as MockClient, ht as MockHttp:
        client = MockClient.return_value
        client._base_url = "https://fumage-x.canvasmedical.com"
        client._get_headers.return_value = {"Authorization": "Bearer t"}
        resp = MockHttp.return_value.post.return_value
        resp.raise_for_status.return_value = None
        resp.headers = {
            "Location": "https://fumage-x.canvasmedical.com/DocumentReference/docref-999/_history/1"
        }

        result = create_document_reference(
            client_id="cid",
            client_secret="secret",
            patient_id="pat-3",
            document_type_key="clinical",
            title="Note",
            pdf_bytes=PDF,
            reviewer_id="staff-1",
        )

        MockClient.assert_called_once_with("cid", "secret")
        args, kwargs = MockHttp.return_value.post.call_args
        assert args[0].endswith("/DocumentReference")
        assert kwargs["headers"] == {"Authorization": "Bearer t"}
        payload = kwargs["json"]
        assert payload["subject"]["reference"] == "Patient/pat-3"
        # clinical_date defaults to today (YYYY-MM-DD) when not provided
        clinical = _extensions_by_url(payload)[CLINICAL_DATE_EXTENSION]["valueDate"]
        assert len(clinical) == 10 and clinical[4] == "-" and clinical[7] == "-"
        assert result == "docref-999"


def test_create_document_reference_uses_explicit_clinical_date() -> None:
    """An explicit clinical_date is passed through verbatim (default is not applied)."""
    cf, ht = _patched_client_and_http()
    with cf as MockClient, ht as MockHttp:
        client = MockClient.return_value
        client._base_url = "https://fumage-x.canvasmedical.com"
        client._get_headers.return_value = {"Authorization": "Bearer t"}
        resp = MockHttp.return_value.post.return_value
        resp.raise_for_status.return_value = None
        resp.headers = {
            "Location": "https://fumage-x.canvasmedical.com/DocumentReference/docref-7"
        }

        create_document_reference(
            client_id="cid",
            client_secret="secret",
            patient_id="pat-9",
            document_type_key="administrative",
            title="Note",
            pdf_bytes=PDF,
            reviewer_id="staff-1",
            clinical_date="2025-01-15",
        )

        payload = MockHttp.return_value.post.call_args.kwargs["json"]
        clinical = _extensions_by_url(payload)[CLINICAL_DATE_EXTENSION]["valueDate"]
        assert clinical == "2025-01-15"


def test_create_document_reference_location_fallback() -> None:
    cf, ht = _patched_client_and_http()
    with cf as MockClient, ht as MockHttp:
        MockClient.return_value._base_url = "https://fumage-x.canvasmedical.com"
        MockClient.return_value._get_headers.return_value = {}
        resp = MockHttp.return_value.post.return_value
        resp.raise_for_status.return_value = None
        resp.headers = {"Location": "https://fumage-x.canvasmedical.com/some/path/abc-123"}

        result = create_document_reference(
            client_id="c", client_secret="s", patient_id="p",
            document_type_key="clinical", title="t", pdf_bytes=PDF, reviewer_id="staff-1",
        )
        assert result == "abc-123"


def test_create_document_reference_surfaces_error_body() -> None:
    cf, ht = _patched_client_and_http()
    with cf as MockClient, ht as MockHttp:
        MockClient.return_value._base_url = "https://fumage-x.canvasmedical.com"
        MockClient.return_value._get_headers.return_value = {}
        resp = MockHttp.return_value.post.return_value
        resp.raise_for_status.side_effect = RuntimeError("400 Client Error")
        resp.text = '{"resourceType":"OperationOutcome","issue":[{"diagnostics":"boom"}]}'

        try:
            create_document_reference(
                client_id="c",
                client_secret="s",
                patient_id="p",
                document_type_key="clinical",
                title="t",
                pdf_bytes=PDF,
                reviewer_id="staff-1",
            )
            raise AssertionError("expected RuntimeError")
        except RuntimeError as raised:
            assert "OperationOutcome" in str(raised)
