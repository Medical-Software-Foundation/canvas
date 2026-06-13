"""Tests for prepare_job — ensure a completed export's JSON lands in S3."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ehi_export_tool.services.preparation import PreparationResult, prepare_job

_SVC = "ehi_export_tool.services.preparation.ExportJobService"


def _job(*, job_id="j1", pid="p-1", s3_key="", first="Ada", last="Lovelace"):
    return SimpleNamespace(
        job_id=job_id,
        batch_id="b1",
        s3_key=s3_key,
        patient=SimpleNamespace(id=pid, first_name=first, last_name=last),
    )


def test_returns_ready_when_already_uploaded() -> None:
    job = _job(s3_key="ehi-exports/b1/x.json")
    client = MagicMock()
    storage = MagicMock()
    result = prepare_job(client, storage, job)
    assert result.status == PreparationResult.READY
    assert result.s3_key == "ehi-exports/b1/x.json"
    client.get_status.assert_not_called()  # no work needed


def test_returns_pending_when_not_complete() -> None:
    job = _job()
    client = MagicMock()
    client.get_status.return_value = {"status": "in-progress", "output": []}
    storage = MagicMock()
    with patch(f"{_SVC}.update_status"):
        result = prepare_job(client, storage, job)
    assert result.status == PreparationResult.PENDING
    storage.upload_json.assert_not_called()


def test_builds_uploads_and_marks_when_complete() -> None:
    job = _job()
    client = MagicMock()
    client.get_status.return_value = {"status": "complete", "output": [{"url": "u"}]}
    client.build_patient_bundle.return_value = {"resourceType": "Bundle", "entry": {}}
    storage = MagicMock()
    storage.patient_key.return_value = "ehi-exports/b1/Lovelace_Ada_p-1.json"
    storage.upload_json.return_value = True
    with patch(f"{_SVC}.mark_uploaded") as mock_mark:
        result = prepare_job(client, storage, job)

    assert result.status == PreparationResult.READY
    assert result.s3_key == "ehi-exports/b1/Lovelace_Ada_p-1.json"
    client.build_patient_bundle.assert_called_once_with("p-1", [{"url": "u"}])
    storage.upload_json.assert_called_once()
    mock_mark.assert_called_once_with(
        "j1", "ehi-exports/b1/Lovelace_Ada_p-1.json", output=[{"url": "u"}]
    )


def test_returns_failed_when_upload_fails() -> None:
    job = _job()
    client = MagicMock()
    client.get_status.return_value = {"status": "complete", "output": [{"url": "u"}]}
    client.build_patient_bundle.return_value = {"resourceType": "Bundle"}
    storage = MagicMock()
    storage.patient_key.return_value = "k.json"
    storage.upload_json.return_value = False
    with patch(f"{_SVC}.update_status") as mock_update, patch(f"{_SVC}.mark_uploaded") as mock_mark:
        result = prepare_job(client, storage, job)

    assert result.status == PreparationResult.FAILED
    mock_mark.assert_not_called()
    mock_update.assert_called_once()  # records the S3 failure
