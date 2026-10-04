"""Tests for ExportPoller — the background CronTask that advances export jobs.

Built on real instances via ``__new__`` so the SCHEDULE property and execute()
logic run for real; the FHIR client, service, and secrets are mocked.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ehi_export_tool.handlers.export_poller import _DEFAULT_SCHEDULE, ExportPoller

_SVC = "ehi_export_tool.handlers.export_poller.ExportJobService"
_CLIENT = "ehi_export_tool.handlers.export_poller.EHIExportClient"
_STORAGE = "ehi_export_tool.handlers.export_poller.ExportStorage"
_PREP = "ehi_export_tool.handlers.export_poller.prepare_job"

CONFIGURED = {"CANVAS_FHIR_CLIENT_ID": "cid", "CANVAS_FHIR_CLIENT_SECRET": "secret"}
S3 = {"S3_ACCESS_KEY": "ak", "S3_SECRET_KEY": "sk", "S3_REGION": "us-east-1", "S3_BUCKET": "b"}


def _poller(secrets: dict) -> ExportPoller:
    inst = ExportPoller.__new__(ExportPoller)
    inst.secrets = secrets
    return inst


@pytest.fixture(autouse=True)
def _stub_queue():
    """Default the queue stage to no-op so existing tests focus on their stage."""
    with patch(f"{_SVC}.count_in_flight", return_value=0), patch(
        f"{_SVC}.queued_jobs", return_value=[]
    ):
        yield


# ── SCHEDULE property ─────────────────────────────────────────────────────────


def test_schedule_defaults_when_unset() -> None:
    assert _poller({}).SCHEDULE == _DEFAULT_SCHEDULE


def test_schedule_uses_configured_value() -> None:
    assert _poller({"EHI_POLL_SCHEDULE": "*/15 * * * *"}).SCHEDULE == "*/15 * * * *"


def test_schedule_falls_back_on_invalid_expression() -> None:
    assert _poller({"EHI_POLL_SCHEDULE": "not-a-cron"}).SCHEDULE == _DEFAULT_SCHEDULE


# ── execute ───────────────────────────────────────────────────────────────────


def test_execute_noop_without_credentials() -> None:
    inst = _poller({})
    with patch(_CLIENT) as MockClient, patch(f"{_SVC}.in_progress_jobs") as mock_jobs:
        result = inst.execute()
    assert result == []
    MockClient.assert_not_called()
    mock_jobs.assert_not_called()


def test_execute_noop_when_no_in_progress_jobs() -> None:
    inst = _poller(CONFIGURED)
    with patch(f"{_SVC}.in_progress_jobs", return_value=[]), patch(_CLIENT) as MockClient:
        result = inst.execute()
    assert result == []
    MockClient.assert_not_called()  # don't even build a client if nothing to do


def test_execute_advances_completed_job() -> None:
    inst = _poller(CONFIGURED)
    job = SimpleNamespace(job_id="j1")
    client = MagicMock()
    client.get_status.return_value = {
        "status": "complete",
        "output": [{"url": "a"}, {"url": "b"}],
        "errors": [],
    }
    with patch(f"{_SVC}.in_progress_jobs", return_value=[job]), patch(
        _CLIENT, return_value=client
    ), patch(f"{_SVC}.update_status") as mock_update:
        inst.execute()

    mock_update.assert_called_once()
    args, kwargs = mock_update.call_args
    assert args[0] == "j1"
    assert args[1] == "complete"
    assert kwargs["output"] == [{"url": "a"}, {"url": "b"}]


def test_execute_touches_still_in_progress_job() -> None:
    inst = _poller(CONFIGURED)
    job = SimpleNamespace(job_id="j1")
    client = MagicMock()
    client.get_status.return_value = {"status": "in-progress", "output": []}
    with patch(f"{_SVC}.in_progress_jobs", return_value=[job]), patch(
        _CLIENT, return_value=client
    ), patch(f"{_SVC}.update_status") as mock_update:
        inst.execute()

    mock_update.assert_called_once_with("j1", "in-progress", output=[], error="")


def test_execute_prepares_completed_jobs_when_s3_configured() -> None:
    from ehi_export_tool.services.preparation import PreparationResult

    inst = _poller({**CONFIGURED, **S3})
    pending_job = SimpleNamespace(job_id="j-complete")
    with patch(f"{_SVC}.in_progress_jobs", return_value=[]), patch(
        f"{_SVC}.complete_jobs_without_s3", return_value=[pending_job]
    ), patch(_STORAGE) as MockStorage, patch(_CLIENT, return_value=MagicMock()), patch(
        _PREP, return_value=PreparationResult(PreparationResult.READY, "k.json")
    ) as mock_prep:
        MockStorage.from_secrets.return_value = MagicMock()
        inst.execute()

    mock_prep.assert_called_once()


def test_execute_skips_prepare_when_s3_not_configured() -> None:
    inst = _poller(CONFIGURED)  # no S3 secrets
    with patch(f"{_SVC}.in_progress_jobs", return_value=[]), patch(
        f"{_SVC}.complete_jobs_without_s3"
    ) as mock_complete, patch(_CLIENT) as MockClient:
        inst.execute()
    # No S3 -> never even queries for jobs to prepare, never builds a client.
    mock_complete.assert_not_called()
    MockClient.assert_not_called()


def test_execute_continues_past_one_job_error() -> None:
    """A status-poll failure on one job must not stop the others."""
    from ehi_export_tool.utils.fhir_client import EHIExportError

    inst = _poller(CONFIGURED)
    j1 = SimpleNamespace(job_id="j1")
    j2 = SimpleNamespace(job_id="j2")
    client = MagicMock()
    client.get_status.side_effect = [
        EHIExportError("boom"),
        {"status": "complete", "output": [{"url": "x"}], "errors": []},
    ]
    with patch(f"{_SVC}.in_progress_jobs", return_value=[j1, j2]), patch(
        _CLIENT, return_value=client
    ), patch(f"{_SVC}.update_status") as mock_update:
        inst.execute()

    # j1 errored (skipped), j2 still advanced
    mock_update.assert_called_once()
    assert mock_update.call_args[0][0] == "j2"


# ── queue (start stage) ───────────────────────────────────────────────────────


def test_execute_starts_queued_jobs() -> None:
    inst = _poller(CONFIGURED)
    q1 = SimpleNamespace(job_id="", patient=SimpleNamespace(id="p-1"))
    q2 = SimpleNamespace(job_id="", patient=SimpleNamespace(id="p-2"))
    client = MagicMock()
    client.start_export.side_effect = ["job-1", "job-2"]
    with patch(f"{_SVC}.count_in_flight", return_value=0), patch(
        f"{_SVC}.queued_jobs", return_value=[q1, q2]
    ), patch(f"{_SVC}.in_progress_jobs", return_value=[]), patch(
        _CLIENT, return_value=client
    ), patch(f"{_SVC}.mark_started") as mock_started:
        inst.execute()

    assert mock_started.call_count == 2
    assert client.start_export.call_count == 2


def test_execute_respects_in_flight_cap() -> None:
    inst = _poller({**CONFIGURED, "EHI_MAX_IN_FLIGHT": "5"})
    mock_queued = MagicMock(return_value=[])
    with patch(f"{_SVC}.count_in_flight", return_value=5), patch(
        f"{_SVC}.queued_jobs", mock_queued
    ), patch(f"{_SVC}.in_progress_jobs", return_value=[]), patch(_CLIENT) as MockClient:
        inst.execute()
    # 5 in flight, cap 5 -> 0 slots -> ask for 0 queued, and (nothing else) no client.
    mock_queued.assert_called_once_with(limit=0)
    MockClient.assert_not_called()


def test_execute_marks_kickoff_failure() -> None:
    from ehi_export_tool.utils.fhir_client import EHIExportError

    inst = _poller(CONFIGURED)
    q1 = SimpleNamespace(job_id="", patient=SimpleNamespace(id="p-1"))
    client = MagicMock()
    client.start_export.side_effect = EHIExportError("403 forbidden")
    with patch(f"{_SVC}.count_in_flight", return_value=0), patch(
        f"{_SVC}.queued_jobs", return_value=[q1]
    ), patch(f"{_SVC}.in_progress_jobs", return_value=[]), patch(
        _CLIENT, return_value=client
    ), patch(f"{_SVC}.mark_failed_job") as mock_failed, patch(f"{_SVC}.mark_started") as mock_started:
        inst.execute()

    mock_failed.assert_called_once()
    mock_started.assert_not_called()
