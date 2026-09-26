"""Tests for ExportAPI — the staff-only EHI export SimpleAPI handler.

Covers: auth gating, static asset routes, patient listing (serialization +
pagination response shape), and the start/status/bundle endpoints including
fail-closed behavior when credentials are missing.

Handlers are exercised on real ``ExportAPI`` instances built with ``__new__`` so
that internal calls (``self._build_client``, ``self._serialize_patient``, …)
resolve to the real methods; only the external ``EHIExportClient`` and the
``Patient`` data model are patched.
"""

import json
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from requests.exceptions import HTTPError

from ehi_export_tool.handlers.export_api import _CACHE_BUST, ExportAPI, _parse_int
from ehi_export_tool.utils.fhir_client import EHIConfigError, EHIExportError
from tests.conftest import FakeQuerySet, make_patient

CONFIGURED_SECRETS = {
    "CANVAS_FHIR_CLIENT_ID": "cid",
    "CANVAS_FHIR_CLIENT_SECRET": "secret",
}
S3_SECRETS = {
    "S3_ACCESS_KEY": "ak",
    "S3_SECRET_KEY": "sk",
    "S3_REGION": "us-east-1",
    "S3_BUCKET": "my-bucket",
}

_CLIENT_PATH = "ehi_export_tool.handlers.export_api.EHIExportClient"
_PATIENT_PATH = "ehi_export_tool.handlers.export_api.Patient"


def _api(*, query_params=None, json_body=None, secrets=None, headers=None) -> ExportAPI:
    """Build a real ExportAPI instance without running SimpleAPI.__init__."""
    inst = ExportAPI.__new__(ExportAPI)
    inst.request = MagicMock()
    inst.request.query_params = query_params or {}
    inst.request.headers = headers or {}
    if json_body is not None:
        inst.request.json.return_value = json_body
    inst.secrets = secrets if secrets is not None else {}
    return inst


def _json_body(response) -> dict:
    """Extract the decoded JSON payload from a JSONResponse-like object."""
    content = response.content
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    return json.loads(content)


# ── auth ──────────────────────────────────────────────────────────────────────


def test_auth_accepts_staff(mock_staff_credentials: MagicMock) -> None:
    assert ExportAPI.authenticate(MagicMock(), mock_staff_credentials) is True


def test_auth_rejects_patient(mock_patient_credentials: MagicMock) -> None:
    with pytest.raises(InvalidCredentialsError):
        ExportAPI.authenticate(MagicMock(), mock_patient_credentials)


# ── static asset routes ───────────────────────────────────────────────────────


def test_get_html_returns_200() -> None:
    inst = _api()
    with patch(
        "ehi_export_tool.handlers.export_api.render_to_string", return_value="<html></html>"
    ) as mock_render:
        result = inst.get_html()

    assert result[0].status_code == HTTPStatus.OK
    assert mock_render.call_args[0][0] == "templates/index.html"
    assert mock_render.call_args[0][1]["cache_bust"] == _CACHE_BUST


def test_get_js_served_as_javascript() -> None:
    inst = _api()
    with patch("ehi_export_tool.handlers.export_api.render_to_string", return_value="// js"):
        result = inst.get_js()
    assert result[0].headers["Content-Type"].startswith("application/javascript")


def test_get_css_served_as_css() -> None:
    inst = _api()
    with patch("ehi_export_tool.handlers.export_api.render_to_string", return_value="body{}"):
        result = inst.get_css()
    assert result[0].headers["Content-Type"].startswith("text/css")


# ── config status ────────────────────────────────────────────────────────────


def test_get_config_reports_configured() -> None:
    inst = _api(secrets=CONFIGURED_SECRETS)
    result = inst.get_config()
    assert result[0].status_code == HTTPStatus.OK
    body = _json_body(result[0])
    assert body["configured"] is True
    assert body["s3_configured"] is False  # no S3 secrets here


def test_get_config_reports_unconfigured() -> None:
    inst = _api(secrets={"CANVAS_FHIR_CLIENT_ID": "only-id"})
    assert _json_body(inst.get_config()[0])["configured"] is False


def test_get_config_unconfigured_when_empty() -> None:
    inst = _api(secrets={})
    assert _json_body(inst.get_config()[0])["configured"] is False


def test_get_config_reports_s3_configured() -> None:
    inst = _api(secrets={**CONFIGURED_SECRETS, **S3_SECRETS})
    assert _json_body(inst.get_config()[0])["s3_configured"] is True


# ── jobs endpoint ─────────────────────────────────────────────────────────────


def test_get_jobs_parses_ids_and_returns_jobs() -> None:
    inst = _api(query_params={"patient_ids": "p-1, p-2 ,"})
    with patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.latest_for_patient_ids",
        return_value={"p-1": {"status": "complete", "job_id": "j1"}},
    ) as mock_latest:
        result = inst.get_jobs()

    mock_latest.assert_called_once_with(["p-1", "p-2"])  # trimmed, empties dropped
    assert _json_body(result[0]) == {"jobs": {"p-1": {"status": "complete", "job_id": "j1"}}}


def test_get_jobs_empty_param() -> None:
    inst = _api(query_params={})
    with patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.latest_for_patient_ids",
        return_value={},
    ) as mock_latest:
        result = inst.get_jobs()
    mock_latest.assert_called_once_with([])
    assert _json_body(result[0]) == {"jobs": {}}


# ── download endpoint ─────────────────────────────────────────────────────────

_PREP = "ehi_export_tool.handlers.export_api.prepare_job"
_STORAGE = "ehi_export_tool.handlers.export_api.ExportStorage"


def test_get_download_requires_job_id() -> None:
    inst = _api(query_params={}, secrets={**CONFIGURED_SECRETS, **S3_SECRETS})
    assert inst.get_download()[0].status_code == HTTPStatus.BAD_REQUEST


def test_get_download_404_when_job_missing() -> None:
    inst = _api(query_params={"job_id": "j1"}, secrets={**CONFIGURED_SECRETS, **S3_SECRETS})
    with patch(_STORAGE) as MockStorage, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.get_with_patient", return_value=None
    ):
        MockStorage.from_secrets.return_value = MagicMock()
        result = inst.get_download()
    assert result[0].status_code == HTTPStatus.NOT_FOUND


def test_get_download_redirects_to_presigned_when_s3() -> None:
    inst = _api(query_params={"job_id": "j1"}, secrets={**CONFIGURED_SECRETS, **S3_SECRETS})
    from ehi_export_tool.services.preparation import PreparationResult

    storage = MagicMock()
    storage.presigned_url.return_value = "https://signed-url"
    with patch(_STORAGE) as MockStorage, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.get_with_patient",
        return_value=MagicMock(),
    ), patch(_CLIENT_PATH, return_value=MagicMock()), patch(
        _PREP, return_value=PreparationResult(PreparationResult.READY, "ehi-exports/b1/x.ndjson")
    ):
        MockStorage.from_secrets.return_value = storage
        result = inst.get_download()

    assert result[0].status_code == HTTPStatus.FOUND  # 302 redirect
    assert result[0].headers["Location"] == "https://signed-url"


def test_get_download_inline_streams_bytes_even_with_s3() -> None:
    """inline=1 bypasses the S3 redirect and streams same-origin bytes (for the
    client-side ZIP builder, which can't read a cross-origin presigned redirect)."""
    inst = _api(
        query_params={"job_id": "j1", "inline": "1"},
        secrets={**CONFIGURED_SECRETS, **S3_SECRETS},
    )
    patient = SimpleNamespace(id="p-1", first_name="Ada", last_name="Lovelace")
    job = SimpleNamespace(job_id="j1", patient=patient)
    client = MagicMock()
    client.get_status.return_value = {"status": "complete", "output": [{"url": "u"}]}
    client.build_patient_ndjson.return_value = '{"resourceType":"Patient","id":"p-1"}'
    storage = MagicMock()
    with patch(_STORAGE) as MockStorage, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.get_with_patient", return_value=job
    ), patch(_CLIENT_PATH, return_value=client), patch(_PREP) as mock_prep:
        MockStorage.from_secrets.return_value = storage  # S3 IS configured
        result = inst.get_download()

    resp = result[0]
    assert resp.status_code == HTTPStatus.OK  # not a 302 redirect
    assert resp.headers["Content-Type"].startswith("application/x-ndjson")
    assert resp.content == b'{"resourceType":"Patient","id":"p-1"}'
    mock_prep.assert_not_called()  # never staged to S3
    storage.presigned_url.assert_not_called()


def test_get_download_ccda_streams_xml() -> None:
    """A C-CDA job streams the fetched XML with an .xml filename (no S3)."""
    inst = _api(query_params={"job_id": "j1"}, secrets=CONFIGURED_SECRETS)  # no S3
    patient = SimpleNamespace(id="p-1", first_name="Ada", last_name="Lovelace")
    job = SimpleNamespace(
        job_id="j1", patient=patient, format="ccda",
        document_type="continuity", start_date="", end_date="",
    )
    client = MagicMock()
    client.fetch_ccda.return_value = "<ClinicalDocument/>"
    with patch(_STORAGE) as MockStorage, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.get_with_patient", return_value=job
    ), patch(_CLIENT_PATH, return_value=client):
        MockStorage.from_secrets.return_value = None  # no S3
        result = inst.get_download()

    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers["Content-Type"].startswith("application/xml")
    assert "Lovelace_Ada_p-1.xml" in resp.headers["Content-Disposition"]
    assert resp.content == b"<ClinicalDocument/>"
    client.fetch_ccda.assert_called_once_with(
        patient_key="p-1", document_type="continuity", start_date="", end_date=""
    )
    client.get_status.assert_not_called()  # synchronous


def test_get_download_conflict_when_pending() -> None:
    inst = _api(query_params={"job_id": "j1"}, secrets={**CONFIGURED_SECRETS, **S3_SECRETS})
    from ehi_export_tool.services.preparation import PreparationResult

    with patch(_STORAGE) as MockStorage, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.get_with_patient",
        return_value=MagicMock(),
    ), patch(_CLIENT_PATH, return_value=MagicMock()), patch(
        _PREP, return_value=PreparationResult(PreparationResult.PENDING)
    ):
        MockStorage.from_secrets.return_value = MagicMock()
        result = inst.get_download()
    assert result[0].status_code == HTTPStatus.CONFLICT


def test_get_download_proxies_ndjson_without_s3() -> None:
    """No S3: the plugin builds and streams the patient's NDJSON directly."""
    inst = _api(query_params={"job_id": "j1"}, secrets=CONFIGURED_SECRETS)  # no S3
    patient = SimpleNamespace(id="p-1", first_name="Ada", last_name="Lovelace")
    job = SimpleNamespace(job_id="j1", patient=patient)
    client = MagicMock()
    client.get_status.return_value = {"status": "complete", "output": [{"url": "u"}]}
    client.build_patient_ndjson.return_value = '{"resourceType":"Patient","id":"p-1"}'
    with patch(_STORAGE) as MockStorage, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.get_with_patient", return_value=job
    ), patch(_CLIENT_PATH, return_value=client):
        MockStorage.from_secrets.return_value = None  # no S3
        result = inst.get_download()

    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers["Content-Type"].startswith("application/x-ndjson")
    assert "Lovelace_Ada_p-1.ndjson" in resp.headers["Content-Disposition"]
    assert resp.content == b'{"resourceType":"Patient","id":"p-1"}'


def test_get_download_proxy_conflict_when_not_complete() -> None:
    inst = _api(query_params={"job_id": "j1"}, secrets=CONFIGURED_SECRETS)  # no S3
    job = SimpleNamespace(job_id="j1", patient=SimpleNamespace(id="p-1"))
    client = MagicMock()
    client.get_status.return_value = {"status": "in-progress", "output": []}
    with patch(_STORAGE) as MockStorage, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.get_with_patient", return_value=job
    ), patch(_CLIENT_PATH, return_value=client):
        MockStorage.from_secrets.return_value = None
        result = inst.get_download()
    assert result[0].status_code == HTTPStatus.CONFLICT


# ── enqueue ───────────────────────────────────────────────────────────────────

_ENQ_IDS = "ehi_export_tool.handlers.export_api.ExportJobService.enqueue_patient_ids"
_ENQ_QS = "ehi_export_tool.handlers.export_api.ExportJobService.enqueue_queryset"


def test_enqueue_explicit_ids() -> None:
    inst = _api(
        json_body={"patient_ids": ["p-1", "p-2"]},
        headers={"canvas-logged-in-user-id": "s-1"},
    )
    with patch(_ENQ_IDS, return_value=2) as mock_enq:
        result = inst.enqueue_export()

    pids, batch_id, staff_id = mock_enq.call_args[0]
    assert pids == ["p-1", "p-2"]
    assert staff_id == "s-1"
    assert batch_id  # server-generated
    body = _json_body(result[0])
    assert body["queued"] == 2 and body["batch_id"]


def test_enqueue_requires_patients() -> None:
    inst = _api(json_body={})
    assert inst.enqueue_export()[0].status_code == HTTPStatus.BAD_REQUEST


def test_enqueue_all_matching() -> None:
    inst = _api(json_body={"all_matching": True, "search": "", "export": ""})
    with patch(_ENQ_QS, return_value=42) as mock_enq, patch(_PATIENT_PATH) as MockPatient:
        MockPatient.objects.all.return_value = FakeQuerySet([])
        result = inst.enqueue_export()

    mock_enq.assert_called_once()
    body = _json_body(result[0])
    assert body["queued"] == 42 and body["batch_id"]


def test_enqueue_defaults_to_ehi_format() -> None:
    inst = _api(json_body={"patient_ids": ["p-1"]})
    with patch(_ENQ_IDS, return_value=1) as mock_enq:
        inst.enqueue_export()
    assert mock_enq.call_args.kwargs["format"] == "ehi"


def test_enqueue_ccda_passes_format_and_document_type() -> None:
    inst = _api(
        json_body={
            "patient_ids": ["p-1"],
            "format": "ccda",
            "document_type": "continuity",
            "start_date": "2025-01-01",
            "end_date": "2025-11-20",
        }
    )
    with patch(_ENQ_IDS, return_value=1) as mock_enq:
        result = inst.enqueue_export()
    kwargs = mock_enq.call_args.kwargs
    assert kwargs["format"] == "ccda"
    assert kwargs["document_type"] == "continuity"
    assert kwargs["start_date"] == "2025-01-01"
    assert kwargs["end_date"] == "2025-11-20"
    assert result[0].status_code == HTTPStatus.OK


def test_enqueue_rejects_unknown_format() -> None:
    inst = _api(json_body={"patient_ids": ["p-1"], "format": "pdf"})
    assert inst.enqueue_export()[0].status_code == HTTPStatus.BAD_REQUEST


def test_enqueue_ccda_requires_valid_document_type() -> None:
    inst = _api(json_body={"patient_ids": ["p-1"], "format": "ccda", "document_type": "bogus"})
    assert inst.enqueue_export()[0].status_code == HTTPStatus.BAD_REQUEST


# ── start records the job ─────────────────────────────────────────────────────


def test_start_export_records_job_with_batch() -> None:
    inst = _api(json_body={"patient_id": "p-1", "batch_id": "b-9"}, secrets=CONFIGURED_SECRETS)
    fake_client = MagicMock()
    fake_client.start_export.return_value = "job-7"
    with patch(_CLIENT_PATH, return_value=fake_client), patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.record_started"
    ) as mock_record:
        result = inst.start_export()

    assert result[0].status_code == HTTPStatus.OK
    mock_record.assert_called_once_with("p-1", "job-7", "b-9", "")


def test_start_export_records_logged_in_staff() -> None:
    inst = _api(
        json_body={"patient_id": "p-1", "batch_id": "b-9"},
        secrets=CONFIGURED_SECRETS,
        headers={"canvas-logged-in-user-id": "staff-123"},
    )
    fake_client = MagicMock()
    fake_client.start_export.return_value = "job-7"
    with patch(_CLIENT_PATH, return_value=fake_client), patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.record_started"
    ) as mock_record:
        inst.start_export()
    mock_record.assert_called_once_with("p-1", "job-7", "b-9", "staff-123")


# ── batch endpoints ───────────────────────────────────────────────────────────


def test_get_batches_returns_paginated() -> None:
    inst = _api(query_params={"limit": "5", "search": "ada"})
    with patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.list_batches_page",
        return_value=([{"batch_id": "b1"}], 12),
    ) as mock_page:
        result = inst.get_batches()

    mock_page.assert_called_once_with(
        search="ada", progress="", offset=0, limit=5, sort="started", dir="desc"
    )
    body = _json_body(result[0])
    assert body["batches"] == [{"batch_id": "b1"}]
    assert body["total"] == 12
    assert body["has_more"] is True  # 0 + 5 < 12


def test_get_batches_passes_valid_progress_filter() -> None:
    inst = _api(query_params={"progress": "completed_with_errors"})
    with patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.list_batches_page",
        return_value=([], 0),
    ) as mock_page:
        inst.get_batches()
    assert mock_page.call_args.kwargs["progress"] == "completed_with_errors"


def test_get_batches_rejects_unknown_progress_filter() -> None:
    inst = _api(query_params={"progress": "bogus"})
    with patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.list_batches_page",
        return_value=([], 0),
    ) as mock_page:
        inst.get_batches()
    assert mock_page.call_args.kwargs["progress"] == ""


def test_get_batch_requires_batch_id() -> None:
    inst = _api(query_params={})
    result = inst.get_batch()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_get_batch_returns_paginated_jobs_and_counts() -> None:
    inst = _api(query_params={"batch_id": "b1", "status": "complete", "offset": "0", "limit": "2"})
    jobs = [{"patient_id": "p-1", "patient_name": "Lovelace, Ada", "status": "complete"}]
    with patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.jobs_for_batch_page",
        return_value=(jobs, 5),
    ) as mock_page, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.batch_counts",
        return_value={"total": 5, "complete": 3, "error": 1, "in_progress": 1},
    ):
        result = inst.get_batch()

    mock_page.assert_called_once_with("b1", status="complete", search="", offset=0, limit=2)
    body = _json_body(result[0])
    assert body["batch_id"] == "b1"
    assert body["jobs"] == jobs
    assert body["counts"]["complete"] == 3
    assert body["total"] == 5
    assert body["has_more"] is True  # offset 0 + limit 2 < 5
    assert "s3_prefix" in body and "s3_bucket" in body


def test_get_batch_ignores_invalid_status() -> None:
    inst = _api(query_params={"batch_id": "b1", "status": "bogus"})
    with patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.jobs_for_batch_page",
        return_value=([], 0),
    ) as mock_page, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.batch_counts",
        return_value={"total": 0, "complete": 0, "error": 0, "in_progress": 0},
    ):
        inst.get_batch()
    # invalid status falls back to "" (all)
    assert mock_page.call_args.kwargs["status"] == ""


def test_start_export_succeeds_even_if_recording_fails() -> None:
    """A persistence failure must not fail the export the user just started."""
    inst = _api(json_body={"patient_id": "p-1"}, secrets=CONFIGURED_SECRETS)
    fake_client = MagicMock()
    fake_client.start_export.return_value = "job-7"
    with patch(_CLIENT_PATH, return_value=fake_client), patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.record_started",
        side_effect=RuntimeError("db down"),
    ):
        result = inst.start_export()

    assert result[0].status_code == HTTPStatus.OK
    assert _json_body(result[0])["job_id"] == "job-7"


# ── patient listing ──────────────────────────────────────────────────────────


def test_get_patients_serializes_and_paginates() -> None:
    rows = [
        make_patient(pid="p-1", first_name="Ada", last_name="Lovelace"),
        make_patient(pid="p-2", first_name="Alan", last_name="Turing"),
    ]
    inst = _api(query_params={"limit": "50", "offset": "0"})

    with patch(_PATIENT_PATH) as MockPatient:
        MockPatient.objects.all.return_value = FakeQuerySet(rows)
        result = inst.get_patients()

    payload = _json_body(result[0])
    assert payload["total"] == 2
    assert payload["has_more"] is False
    assert payload["patients"][0] == {
        "id": "p-1",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "name": "Lovelace, Ada",
        "dob": "1990-01-02",
        "active": True,
    }
    assert payload["patients"][1]["first_name"] == "Alan"
    assert payload["patients"][1]["last_name"] == "Turing"


def test_get_patients_reports_has_more() -> None:
    rows = [make_patient(pid=f"p-{i}") for i in range(10)]
    inst = _api(query_params={"limit": "5", "offset": "0"})

    with patch(_PATIENT_PATH) as MockPatient:
        MockPatient.objects.all.return_value = FakeQuerySet(rows)
        result = inst.get_patients()

    payload = _json_body(result[0])
    assert payload["total"] == 10
    assert payload["limit"] == 5
    assert payload["has_more"] is True
    assert len(payload["patients"]) == 5


def test_get_patients_with_single_term_search() -> None:
    rows = [make_patient(pid="p-1", first_name="Ada", last_name="Lovelace")]
    inst = _api(query_params={"search": "Lovelace", "include_inactive": "true"})

    with patch(_PATIENT_PATH) as MockPatient:
        MockPatient.objects.all.return_value = FakeQuerySet(rows)
        result = inst.get_patients()

    payload = _json_body(result[0])
    assert payload["total"] == 1
    assert payload["patients"][0]["name"] == "Lovelace, Ada"


def test_get_patients_with_two_term_search() -> None:
    rows = [make_patient(pid="p-1", first_name="Ada", last_name="Lovelace")]
    inst = _api(query_params={"search": "Ada Lovelace"})

    with patch(_PATIENT_PATH) as MockPatient:
        MockPatient.objects.all.return_value = FakeQuerySet(rows)
        result = inst.get_patients()

    assert _json_body(result[0])["total"] == 1


def test_order_by_defaults_to_last_name_asc() -> None:
    assert ExportAPI._order_by(None, None) == ["last_name", "first_name", "id"]
    assert ExportAPI._order_by("bogus", "asc") == ["last_name", "first_name", "id"]


def test_order_by_first_name_desc() -> None:
    assert ExportAPI._order_by("first_name", "desc") == ["-first_name", "last_name", "id"]


def test_order_by_dob_maps_to_birth_date() -> None:
    assert ExportAPI._order_by("dob", "asc") == ["birth_date", "last_name", "first_name", "id"]


def test_order_by_id_desc() -> None:
    assert ExportAPI._order_by("id", "desc") == ["-id", "last_name", "first_name"]


def test_order_by_active() -> None:
    assert ExportAPI._order_by("active", "desc") == ["-active", "last_name", "first_name", "id"]


def test_get_patients_passes_sort_to_queryset() -> None:
    rows = [make_patient(pid="p-1")]
    inst = _api(query_params={"sort": "dob", "dir": "desc"})
    with patch(_PATIENT_PATH) as MockPatient:
        qs = FakeQuerySet(rows)
        qs.order_by = MagicMock(return_value=qs)  # capture the order_by args
        MockPatient.objects.all.return_value = qs
        inst.get_patients()
    qs.order_by.assert_called_once_with("-birth_date", "last_name", "first_name", "id")


def test_serialize_patient_handles_missing_name_and_dob() -> None:
    p = make_patient(pid="p-x", first_name="", last_name="")
    p.birth_date = None
    serialized = ExportAPI._serialize_patient(p)
    assert serialized["id"] == "p-x"
    assert serialized["name"] == "(unnamed)"
    assert serialized["dob"] == ""


# ── _build_client (fail-closed) ──────────────────────────────────────────────


def test_build_client_raises_config_error_without_secrets() -> None:
    inst = _api(secrets={})
    with pytest.raises(EHIConfigError):
        inst._build_client()


def test_build_client_constructs_when_configured() -> None:
    inst = _api(secrets=CONFIGURED_SECRETS)
    with patch(_CLIENT_PATH, return_value="client-sentinel") as MockClient:
        assert inst._build_client() == "client-sentinel"
    MockClient.assert_called_once_with("cid", "secret")


def test_build_client_translates_token_failure_to_export_error() -> None:
    """A 403 from the OAuth token request becomes a clear EHIExportError."""
    inst = _api(secrets=CONFIGURED_SECRETS)
    response = MagicMock()
    response.status_code = 403
    response.text = '{"error": "unauthorized_client"}'
    http_error = HTTPError("403 Forbidden", response=response)

    with patch(_CLIENT_PATH, side_effect=http_error):
        with pytest.raises(EHIExportError) as exc_info:
            inst._build_client()

    message = str(exc_info.value)
    assert "403" in message
    assert "client-credentials" in message
    assert "unauthorized_client" in message  # the OAuth error body is surfaced


def test_build_client_reraises_non_http_errors() -> None:
    """A non-HTTP error during construction is not masked as an auth failure."""
    inst = _api(secrets=CONFIGURED_SECRETS)
    with patch(_CLIENT_PATH, side_effect=ValueError("boom")):
        with pytest.raises(ValueError):
            inst._build_client()


def test_start_export_surfaces_auth_failure() -> None:
    """An auth failure during client build is reported as a 502 with the reason."""
    inst = _api(json_body={"patient_id": "p-1"}, secrets=CONFIGURED_SECRETS)
    response = MagicMock()
    response.status_code = 403
    response.text = '{"error": "unauthorized_client"}'
    with patch(_CLIENT_PATH, side_effect=HTTPError("403", response=response)):
        result = inst.start_export()

    assert result[0].status_code == HTTPStatus.BAD_GATEWAY
    assert "403" in _json_body(result[0])["error"]


# ── start_export ─────────────────────────────────────────────────────────────


def test_start_export_requires_patient_id() -> None:
    inst = _api(json_body={})
    result = inst.start_export()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_start_export_fails_closed_without_secrets() -> None:
    inst = _api(json_body={"patient_id": "p-1"}, secrets={})
    result = inst.start_export()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST
    assert "credentials" in _json_body(result[0])["error"]


def test_start_export_success_returns_job_id() -> None:
    inst = _api(json_body={"patient_id": "p-1"}, secrets=CONFIGURED_SECRETS)
    fake_client = MagicMock()
    fake_client.start_export.return_value = "job-7"
    with patch(_CLIENT_PATH, return_value=fake_client):
        result = inst.start_export()

    assert result[0].status_code == HTTPStatus.OK
    assert _json_body(result[0]) == {"patient_id": "p-1", "job_id": "job-7"}


def test_start_export_forced_failure() -> None:
    """EHI_FORCE_FAILURE=true makes start fail (for testing the failure UI)."""
    inst = _api(
        json_body={"patient_id": "p-1"},
        secrets={**CONFIGURED_SECRETS, "EHI_FORCE_FAILURE": "true"},
    )
    with patch(_CLIENT_PATH) as MockClient, patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.record_failed"
    ) as mock_failed:
        result = inst.start_export()
    assert result[0].status_code == HTTPStatus.BAD_GATEWAY
    assert "Simulated" in _json_body(result[0])["error"]
    MockClient.assert_not_called()  # short-circuits before touching the FHIR client
    # failure is recorded so it shows on the main page after the modal closes
    mock_failed.assert_called_once_with(
        "p-1", "", "Simulated export failure (EHI_FORCE_FAILURE is enabled).", ""
    )


def test_start_export_not_failed_when_flag_absent() -> None:
    inst = _api(json_body={"patient_id": "p-1"}, secrets=CONFIGURED_SECRETS)
    fake_client = MagicMock()
    fake_client.start_export.return_value = "job-1"
    with patch(_CLIENT_PATH, return_value=fake_client), patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.record_started"
    ):
        result = inst.start_export()
    assert result[0].status_code == HTTPStatus.OK


def test_start_export_maps_client_error_to_bad_gateway() -> None:
    inst = _api(json_body={"patient_id": "p-1"}, secrets=CONFIGURED_SECRETS)
    fake_client = MagicMock()
    fake_client.start_export.side_effect = EHIExportError("upstream boom")
    with patch(_CLIENT_PATH, return_value=fake_client), patch(
        "ehi_export_tool.handlers.export_api.ExportJobService.record_failed"
    ) as mock_failed:
        result = inst.start_export()
    assert result[0].status_code == HTTPStatus.BAD_GATEWAY
    mock_failed.assert_called_once()  # real start failures are recorded too


# ── export_status ────────────────────────────────────────────────────────────


def test_export_status_requires_job_id() -> None:
    inst = _api(query_params={})
    result = inst.export_status()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_export_status_reports_ready_when_complete() -> None:
    inst = _api(query_params={"job_id": "job-1"}, secrets=CONFIGURED_SECRETS)
    fake_client = MagicMock()
    fake_client.get_status.return_value = {
        "status": "complete",
        "progress": "complete",
        "output": [{"url": "x"}, {"url": "y"}],
    }
    with patch(_CLIENT_PATH, return_value=fake_client):
        result = inst.export_status()

    payload = _json_body(result[0])
    assert payload["ready"] is True
    assert payload["file_count"] == 2


# ── export_bundle ────────────────────────────────────────────────────────────


def test_export_bundle_requires_both_params() -> None:
    inst = _api(query_params={"job_id": "job-1"})
    result = inst.export_bundle()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_export_bundle_conflict_when_not_complete() -> None:
    inst = _api(query_params={"job_id": "job-1", "patient_id": "p-1"}, secrets=CONFIGURED_SECRETS)
    fake_client = MagicMock()
    fake_client.get_status.return_value = {"status": "in-progress", "output": []}
    with patch(_CLIENT_PATH, return_value=fake_client):
        result = inst.export_bundle()
    assert result[0].status_code == HTTPStatus.CONFLICT


def test_export_bundle_returns_merged_bundle() -> None:
    inst = _api(query_params={"job_id": "job-1", "patient_id": "p-1"}, secrets=CONFIGURED_SECRETS)
    bundle = {"resourceType": "Bundle", "total": 1, "entry": [{"resource": {"id": "x"}}]}
    fake_client = MagicMock()
    fake_client.get_status.return_value = {"status": "complete", "output": [{"url": "x"}]}
    fake_client.build_patient_bundle.return_value = bundle
    with patch(_CLIENT_PATH, return_value=fake_client):
        result = inst.export_bundle()

    assert result[0].status_code == HTTPStatus.OK
    assert _json_body(result[0])["resourceType"] == "Bundle"
    fake_client.build_patient_bundle.assert_called_once_with("p-1", [{"url": "x"}])


# ── _parse_int ───────────────────────────────────────────────────────────────


def test_parse_int_default_on_garbage() -> None:
    assert _parse_int("abc", default=7) == 7
    assert _parse_int(None, default=7) == 7


def test_parse_int_clamps_to_bounds() -> None:
    assert _parse_int("999", default=50, minimum=1, maximum=200) == 200
    assert _parse_int("-5", default=50, minimum=0) == 0
