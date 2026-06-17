"""Tests for EHIExportClient — the EHI bulk-export extension of CanvasFhir.

Construction of the parent ``CanvasFhir`` performs a network token fetch, so we
build instances with ``__new__`` and set the attributes the methods rely on
(``_base_url`` and a ``_get_headers`` stub), then patch the module-level ``Http``.
"""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from ehi_export_tool.utils.fhir_client import (
    STATUS_COMPLETE,
    STATUS_ERROR,
    STATUS_IN_PROGRESS,
    EHIExportClient,
    EHIExportError,
)

FHIR_BASE = "https://fumage-local.canvasmedical.com"


def _make_client() -> EHIExportClient:
    """Build an EHIExportClient without triggering the parent's token fetch."""
    client = EHIExportClient.__new__(EHIExportClient)
    client._base_url = FHIR_BASE
    client._get_headers = lambda: {"Authorization": "Bearer test-token"}  # type: ignore[method-assign]
    return client


def _response(*, status_code=HTTPStatus.OK, headers=None, text="", json_body=None, ok=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    resp.ok = ok if ok is not None else (200 <= int(status_code) < 300)
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


# ── _job_id_from_content_location ───────────────────────────────────────────


def test_job_id_parsed_from_bulkstatus_url() -> None:
    cl = "https://fumage-local.canvasmedical.com/bulkstatus/41dc90ae-c47c-4b10-9c0f-823f32f278b4"
    assert (
        EHIExportClient._job_id_from_content_location(cl)
        == "41dc90ae-c47c-4b10-9c0f-823f32f278b4"
    )


def test_job_id_strips_query_string() -> None:
    cl = "https://x/bulkstatus/abc-123?foo=bar"
    assert EHIExportClient._job_id_from_content_location(cl) == "abc-123"


def test_job_id_empty_for_blank_header() -> None:
    assert EHIExportClient._job_id_from_content_location("") == ""


# ── start_export ─────────────────────────────────────────────────────────────


def test_start_export_returns_job_id_on_202() -> None:
    client = _make_client()
    resp = _response(
        status_code=HTTPStatus.ACCEPTED,
        headers={"Content-Location": f"{FHIR_BASE}/bulkstatus/job-99"},
    )
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        job_id = client.start_export("patient-1")

    assert job_id == "job-99"
    # the $export URL and respond-async header must be used
    called_url = MockHttp.return_value.get.call_args[0][0]
    called_headers = MockHttp.return_value.get.call_args.kwargs["headers"]
    assert called_url == f"{FHIR_BASE}/Patient/patient-1/$export"
    assert called_headers["Prefer"] == "respond-async"
    assert called_headers["Authorization"] == "Bearer test-token"


def test_start_export_raises_on_non_202() -> None:
    client = _make_client()
    resp = _response(status_code=HTTPStatus.FORBIDDEN, text="nope")
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        with pytest.raises(EHIExportError, match="expected 202"):
            client.start_export("patient-1")


def test_start_export_raises_without_content_location() -> None:
    client = _make_client()
    resp = _response(status_code=HTTPStatus.ACCEPTED, headers={})
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        with pytest.raises(EHIExportError, match="Content-Location"):
            client.start_export("patient-1")


# ── get_status ───────────────────────────────────────────────────────────────


def test_get_status_in_progress_on_202() -> None:
    client = _make_client()
    resp = _response(status_code=HTTPStatus.ACCEPTED, headers={"X-Progress": "42% done"})
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        status = client.get_status("job-1")

    assert status["status"] == STATUS_IN_PROGRESS
    assert status["progress"] == "42% done"
    assert status["output"] == []


def test_get_status_complete_on_200_with_output() -> None:
    client = _make_client()
    output = [{"type": "Patient", "url": "https://x/file1"}]
    resp = _response(status_code=HTTPStatus.OK, json_body={"output": output, "error": []})
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        status = client.get_status("job-1")

    assert status["status"] == STATUS_COMPLETE
    assert status["output"] == output


def test_get_status_error_on_unexpected_code() -> None:
    client = _make_client()
    resp = _response(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, text="boom")
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        status = client.get_status("job-1")

    assert status["status"] == STATUS_ERROR
    assert "500" in status["progress"]


# ── _fetch_text (with retry) ─────────────────────────────────────────────────


def test_fetch_text_returns_body() -> None:
    client = _make_client()
    resp = _response(status_code=HTTPStatus.OK, text="line1\nline2", ok=True)
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        assert client._fetch_text("https://x/file1") == "line1\nline2"


def test_fetch_text_raises_on_error_response() -> None:
    client = _make_client()
    resp = _response(status_code=HTTPStatus.NOT_FOUND, text="missing", ok=False)
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.return_value = resp
        with pytest.raises(EHIExportError, match="failed to download"):
            client._fetch_text("https://x/file1")


def test_fetch_text_retries_transient_503_then_succeeds() -> None:
    client = _make_client()
    bad = _response(status_code=HTTPStatus.SERVICE_UNAVAILABLE, text="503", ok=False)
    good = _response(status_code=HTTPStatus.OK, text='{"resourceType":"Patient"}', ok=True)
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp, patch(
        "ehi_export_tool.utils.fhir_client.time.sleep"
    ) as mock_sleep:
        MockHttp.return_value.get.side_effect = [bad, good]
        client._fetch_text("https://x/file1")
    assert MockHttp.return_value.get.call_count == 2
    mock_sleep.assert_called_once()


def test_fetch_text_gives_up_after_max_attempts() -> None:
    client = _make_client()
    bad = _response(status_code=HTTPStatus.SERVICE_UNAVAILABLE, text="503 down", ok=False)
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp, patch(
        "ehi_export_tool.utils.fhir_client.time.sleep"
    ):
        MockHttp.return_value.get.return_value = bad
        with pytest.raises(EHIExportError, match="failed to download"):
            client._fetch_text("https://x/file1")
    assert MockHttp.return_value.get.call_count == 4  # initial + 3 retries


def test_fetch_text_does_not_retry_non_5xx() -> None:
    client = _make_client()
    bad = _response(status_code=HTTPStatus.FORBIDDEN, text="403", ok=False)
    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp, patch(
        "ehi_export_tool.utils.fhir_client.time.sleep"
    ):
        MockHttp.return_value.get.return_value = bad
        with pytest.raises(EHIExportError):
            client._fetch_text("https://x/file1")
    assert MockHttp.return_value.get.call_count == 1


# ── build_patient_ndjson ─────────────────────────────────────────────────────


def test_build_patient_ndjson_concatenates_all_files() -> None:
    client = _make_client()
    output = [
        {"type": "Patient", "url": "https://x/patients"},
        {"type": "Observation", "url": "https://x/observations"},
        {"type": "Empty", "url": None},  # missing url is skipped
    ]
    files = {
        "https://x/patients": '{"resourceType":"Patient","id":"p1"}\n',
        "https://x/observations": (
            '{"resourceType":"Observation","id":"o1"}\n'
            "\n"  # blank lines dropped
            '{"resourceType":"Observation","id":"o2"}'
        ),
    }

    def fake_get(url, headers=None):
        return _response(status_code=HTTPStatus.OK, text=files[url], ok=True)

    with patch("ehi_export_tool.utils.fhir_client.Http") as MockHttp:
        MockHttp.return_value.get.side_effect = fake_get
        ndjson = client.build_patient_ndjson(output)

    lines = ndjson.split("\n")
    assert lines == [
        '{"resourceType":"Patient","id":"p1"}',
        '{"resourceType":"Observation","id":"o1"}',
        '{"resourceType":"Observation","id":"o2"}',
    ]


def test_build_patient_ndjson_empty_output() -> None:
    client = _make_client()
    with patch("ehi_export_tool.utils.fhir_client.Http"):
        assert client.build_patient_ndjson([]) == ""
