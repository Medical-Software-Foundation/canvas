"""Tests for the FHIR document client (search + content streaming)."""

from unittest.mock import MagicMock, patch

import pytest

from portal_content.shared import fhir_documents

FHIR_URL = "https://fumage-example.canvasmedical.com/DiagnosticReport/x/files/presentedForm"


def _token_resp(token="tok", status=200):
    r = MagicMock(status_code=status)
    r.json.return_value = {"access_token": token} if token else {}
    return r


# ----------------------------------------------------------------- search

@patch("portal_content.shared.fhir_documents.Http")
def test_search_documents_maps_entries(http_cls):
    http = http_cls.return_value
    http.post.return_value = _token_resp()
    search = MagicMock(status_code=200)
    search.json.return_value = {
        "entry": [
            {"resource": {"id": "ref1", "description": "Hemoglobin A1C", "date": "2026-01-14",
                          "content": [{"attachment": {"url": "https://h/DiagnosticReport/dr-9/files/presentedForm"}}]}},
            {"resource": {"id": "ref2", "type": {"text": "Laboratory report"}}},
            {"resource": {}},  # no id -> skipped
        ]
    }
    http.get.return_value = search

    reports = fhir_documents.search_documents("inst", "c", "s", "p1", "labreport")

    assert reports == [
        {"report_id": "ref1", "report_name": "Hemoglobin A1C", "date": "2026-01-14",
         "content_url": "/plugin-io/api/portal_content/app/document?ref_id=ref1",
         "diagnostic_report_id": "dr-9"},
        {"report_id": "ref2", "report_name": "Laboratory report", "date": None,
         "content_url": "/plugin-io/api/portal_content/app/document?ref_id=ref2",
         "diagnostic_report_id": None},
    ]


@patch("portal_content.shared.fhir_documents.Http")
def test_search_documents_raises_on_non_200(http_cls):
    http = http_cls.return_value
    http.post.return_value = _token_resp()
    http.get.return_value = MagicMock(status_code=403)
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.search_documents("inst", "c", "s", "p1", "labreport")


# -------------------------------------------------------------- content

def _meta(subject="Patient/p1", url=FHIR_URL, ctype="application/pdf"):
    m = MagicMock(status_code=200)
    m.json.return_value = {
        "subject": {"reference": subject},
        "content": [{"attachment": {"url": url, "contentType": ctype}}],
    }
    return m


@patch("portal_content.shared.fhir_documents.Http")
def test_fetch_returns_bytes_and_content_type(http_cls):
    http = http_cls.return_value
    http.post.return_value = _token_resp()
    http.get.side_effect = [_meta(), MagicMock(status_code=200, content=b"%PDF-1.4")]
    content, ctype = fhir_documents.fetch_document_content("inst", "c", "s", "p1", "ref1")
    assert content == b"%PDF-1.4"
    assert ctype == "application/pdf"


@patch("portal_content.shared.fhir_documents.log")
@patch("portal_content.shared.fhir_documents.Http")
def test_fetch_rejects_wrong_patient(http_cls, mock_log):
    http = http_cls.return_value
    http.post.return_value = _token_resp()
    http.get.side_effect = [_meta(subject="Patient/someone-else")]
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.fetch_document_content("inst", "c", "s", "p1", "ref1")
    # the denial log must not leak the document owner's identifier (PHI)
    logged = " ".join(str(c.args) for c in mock_log.warning.call_args_list)
    assert "someone-else" not in logged


@patch("portal_content.shared.fhir_documents.Http")
def test_fetch_token_failure_raises(http_cls):
    http = http_cls.return_value
    http.post.return_value = _token_resp(token=None)
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.fetch_document_content("inst", "c", "s", "p1", "ref1")


# ------------------------------------------------------- error branches

@patch("portal_content.shared.fhir_documents.Http")
def test_token_non_200_raises(http_cls):
    http = http_cls.return_value
    http.post.return_value = MagicMock(status_code=401)
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.search_documents("inst", "c", "s", "p1", "labreport")


@patch("portal_content.shared.fhir_documents.Http")
def test_token_request_exception_raises(http_cls):
    from requests import RequestException

    http = http_cls.return_value
    http.post.side_effect = RequestException("net")
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.search_documents("inst", "c", "s", "p1", "labreport")


@patch("portal_content.shared.fhir_documents.Http")
def test_search_request_exception_raises(http_cls):
    from requests import RequestException

    http = http_cls.return_value
    http.post.return_value = _token_resp()
    http.get.side_effect = RequestException("net")
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.search_documents("inst", "c", "s", "p1", "labreport")


@patch("portal_content.shared.fhir_documents.Http")
def test_fetch_meta_non_200_raises(http_cls):
    http = http_cls.return_value
    http.post.return_value = _token_resp()
    http.get.side_effect = [MagicMock(status_code=404)]
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.fetch_document_content("inst", "c", "s", "p1", "ref1")


@patch("portal_content.shared.fhir_documents.Http")
def test_fetch_binary_non_200_raises(http_cls):
    http = http_cls.return_value
    http.post.return_value = _token_resp()
    http.get.side_effect = [_meta(), MagicMock(status_code=500)]
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.fetch_document_content("inst", "c", "s", "p1", "ref1")


@patch("portal_content.shared.fhir_documents.Http")
def test_fetch_binary_request_exception_raises(http_cls):
    from requests import RequestException

    http = http_cls.return_value
    http.post.return_value = _token_resp()
    http.get.side_effect = [_meta(), RequestException("net")]
    with pytest.raises(fhir_documents.DocumentFetchError):
        fhir_documents.fetch_document_content("inst", "c", "s", "p1", "ref1")
