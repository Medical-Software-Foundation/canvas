"""Tests for the PortalContentAPI router: routing, auth-scoped data, gating, errors."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from portal_content.handlers.portal_api import PortalContentAPI

# secrets with FHIR creds configured (needed for document endpoints)
WITH_CREDS = {"ENABLED_COMPONENTS": "", "NOTE_TYPES": "off", "CLIENT_ID": "c", "CLIENT_SECRET": "s"}


def _api(secrets=None, query=None, patient="patient-1"):
    """A handler instance with request/secrets set, bypassing runtime __init__."""
    api = PortalContentAPI.__new__(PortalContentAPI)
    api.secrets = secrets if secrets is not None else dict(WITH_CREDS)
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": patient}
    params = query or {}
    request.query_params.get.side_effect = lambda key, default=None: params.get(key, default)
    api.request = request
    api.environment = {"CUSTOMER_IDENTIFIER": "test-inst"}
    return api


def _decode(responses):
    return responses[0].status_code, json.loads(responses[0].content)


# ------------------------------------------------------------------- pages

@patch("portal_content.handlers.portal_api.render_to_string", return_value="<html>page</html>")
def test_pages_render_html(render):
    for method in ("records_page", "profile_page"):
        responses = getattr(_api(), method)()
        assert responses[0].__class__.__name__ == "HTMLResponse"
        assert responses[0].status_code == HTTPStatus.OK
        assert b"page" in responses[0].content


# ------------------------------------------------------------------ visits

@patch("portal_content.handlers.portal_api.list_notes")
def test_visits_list_success(list_notes):
    list_notes.return_value = {"summaries": [{"note_id": "n1"}], "total": 1, "has_more": False}
    status, body = _decode(_api(secrets={"ENABLED_COMPONENTS": "", "NOTE_TYPES": "off"}).visits_list())
    assert status == HTTPStatus.OK
    assert body["data"]["total"] == 1


def test_visits_list_empty_when_no_note_types():
    status, body = _decode(_api(secrets={"ENABLED_COMPONENTS": "", "NOTE_TYPES": ""}).visits_list())
    assert status == HTTPStatus.OK
    assert body["data"]["summaries"] == []


def test_visits_list_forbidden_when_disabled():
    status, body = _decode(_api(secrets={"ENABLED_COMPONENTS": "labs", "NOTE_TYPES": "off"}).visits_list())
    assert status == HTTPStatus.FORBIDDEN


def test_visit_avs_invalid_id():
    status, _ = _decode(_api(query={"note_id": "bad id!"}).visit_avs())
    assert status == HTTPStatus.BAD_REQUEST


@patch("portal_content.handlers.portal_api.render_avs", return_value="<div>AVS</div>")
def test_visit_avs_success(render_avs):
    status, body = _decode(_api(query={"note_id": "n1"}).visit_avs())
    assert status == HTTPStatus.OK
    assert body["data"]["avs_html"] == "<div>AVS</div>"


@patch("portal_content.handlers.portal_api.render_avs", return_value=None)
def test_visit_avs_not_found(render_avs):
    status, _ = _decode(_api(query={"note_id": "n1"}).visit_avs())
    assert status == HTTPStatus.NOT_FOUND


@patch("portal_content.handlers.portal_api.get_note_document", return_value={"content_url": "u", "content_type": "application/pdf"})
def test_visit_note_success(get_doc):
    status, body = _decode(_api(query={"note_id": "n1"}).visit_note())
    assert status == HTTPStatus.OK
    assert body["data"]["content_url"] == "u"


@patch("portal_content.handlers.portal_api.get_note_document", return_value=None)
def test_visit_note_not_found(get_doc):
    status, _ = _decode(_api(query={"note_id": "n1"}).visit_note())
    assert status == HTTPStatus.NOT_FOUND


# --------------------------------------------------------------- documents

def test_documents_unknown_component():
    status, _ = _decode(_api(query={"component": "bogus"}).documents_list())
    assert status == HTTPStatus.BAD_REQUEST


def test_documents_forbidden_when_disabled():
    api = _api(secrets={"ENABLED_COMPONENTS": "visits", "CLIENT_ID": "c", "CLIENT_SECRET": "s"},
               query={"component": "labs"})
    status, _ = _decode(api.documents_list())
    assert status == HTTPStatus.FORBIDDEN


def test_documents_not_configured_without_credentials():
    api = _api(secrets={"ENABLED_COMPONENTS": ""}, query={"component": "labs"})
    status, _ = _decode(api.documents_list())
    assert status == HTTPStatus.INTERNAL_SERVER_ERROR


@patch("portal_content.handlers.portal_api.list_documents", return_value=[{"report_id": "d1"}])
def test_documents_success(list_documents):
    api = _api(query={"component": "labs"})
    status, body = _decode(api.documents_list())
    assert status == HTTPStatus.OK
    assert body["data"]["reports"] == [{"report_id": "d1"}]
    list_documents.assert_called_once_with("test-inst", "c", "s", "patient-1", "labs")


# --------------------------------------------------------------- document file

@patch("portal_content.handlers.portal_api.fetch_document_content", return_value=(b"%PDF-1.4", "application/pdf"))
def test_document_streams_pdf(fetch):
    responses = _api(query={"ref_id": "ref1"}).document()
    assert responses[0].status_code == HTTPStatus.OK
    assert responses[0].content == b"%PDF-1.4"
    fetch.assert_called_once_with("test-inst", "c", "s", "patient-1", "ref1")


def test_document_invalid_id():
    responses = _api(query={"ref_id": "bad id!"}).document()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_document_not_configured_without_credentials():
    responses = _api(secrets={"ENABLED_COMPONENTS": ""}, query={"ref_id": "ref1"}).document()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@patch("portal_content.handlers.portal_api.fetch_document_content")
def test_document_fetch_error_renders_unavailable_message(fetch):
    from portal_content.shared.fhir_documents import DocumentFetchError

    fetch.side_effect = DocumentFetchError("boom")
    responses = _api(query={"ref_id": "ref1"}).document()
    assert responses[0].__class__.__name__ == "HTMLResponse"
    assert responses[0].status_code == HTTPStatus.OK
    assert b"isn't available" in responses[0].content


# ----------------------------------------------------------------- profile

@patch("portal_content.handlers.portal_api.get_demographics", return_value={"full_name": "Jane"})
def test_profile_info_success(get_demographics):
    status, body = _decode(_api().profile_info())
    assert status == HTTPStatus.OK
    assert body["data"]["full_name"] == "Jane"


@patch("portal_content.handlers.portal_api.get_demographics", return_value=None)
def test_profile_info_not_found(get_demographics):
    status, _ = _decode(_api().profile_info())
    assert status == HTTPStatus.NOT_FOUND


@patch("portal_content.handlers.portal_api.list_coverages", return_value=[{"payer_name": "Aetna"}])
def test_profile_coverage_success(list_coverages):
    status, body = _decode(_api().profile_coverage())
    assert status == HTTPStatus.OK
    assert body["data"]["coverages"][0]["payer_name"] == "Aetna"


@patch("portal_content.handlers.portal_api.filter_reviewed", return_value=[{"report_id": "r1", "diagnostic_report_id": "dr1"}])
@patch("portal_content.handlers.portal_api.list_documents", return_value=[
    {"report_id": "r1", "diagnostic_report_id": "dr1"},
    {"report_id": "r2", "diagnostic_report_id": "dr2"},
])
def test_documents_gates_and_strips_dr_id_when_hold_enabled(list_documents, filter_reviewed):
    api = _api(secrets={"ENABLED_COMPONENTS": "", "CLIENT_ID": "c", "CLIENT_SECRET": "s",
                        "HOLD_UNREVIEWED_RESULTS": "true"}, query={"component": "labs"})
    status, body = _decode(api.documents_list())
    assert status == HTTPStatus.OK
    filter_reviewed.assert_called_once()
    # gated to r1, and the internal diagnostic_report_id is stripped from output
    assert body["data"]["reports"] == [{"report_id": "r1"}]


@patch("portal_content.handlers.portal_api.filter_reviewed")
@patch("portal_content.handlers.portal_api.list_documents", return_value=[{"report_id": "r1", "diagnostic_report_id": "dr1"}])
def test_documents_no_gating_when_hold_disabled(list_documents, filter_reviewed):
    api = _api(query={"component": "labs"})  # default secrets: no HOLD flag
    status, body = _decode(api.documents_list())
    assert status == HTTPStatus.OK
    filter_reviewed.assert_not_called()
    assert body["data"]["reports"] == [{"report_id": "r1"}]
