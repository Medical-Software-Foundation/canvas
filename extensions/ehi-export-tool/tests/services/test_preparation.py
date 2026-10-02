"""Tests for prepare_job — ensure a completed export's JSON lands in S3."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ehi_export_tool.services.preparation import PreparationResult, prepare_job

_SVC = "ehi_export_tool.services.preparation.ExportJobService"


def _job(
    *, job_id="j1", pid="p-1", s3_key="", first="Ada", last="Lovelace",
    format="ehi", document_type="", start_date="", end_date="",
):
    return SimpleNamespace(
        job_id=job_id,
        batch_id="b1",
        s3_key=s3_key,
        format=format,
        document_type=document_type,
        start_date=start_date,
        end_date=end_date,
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
    client.build_patient_ndjson.return_value = '{"resourceType":"Patient"}'
    storage = MagicMock()
    storage.patient_key.return_value = "ehi-exports/b1/Lovelace_Ada_p-1.ndjson"
    storage.upload_ndjson.return_value = True
    with patch(f"{_SVC}.mark_uploaded") as mock_mark:
        result = prepare_job(client, storage, job)

    assert result.status == PreparationResult.READY
    assert result.s3_key == "ehi-exports/b1/Lovelace_Ada_p-1.ndjson"
    client.build_patient_ndjson.assert_called_once_with([{"url": "u"}])
    storage.upload_ndjson.assert_called_once()
    mock_mark.assert_called_once_with(
        "j1", "ehi-exports/b1/Lovelace_Ada_p-1.ndjson", output=[{"url": "u"}]
    )


def test_ccda_fetches_xml_and_uploads_without_polling() -> None:
    job = _job(format="ccda", document_type="continuity", start_date="2025-01-01")
    client = MagicMock()
    client.fetch_ccda.return_value = "<ClinicalDocument/>"
    storage = MagicMock()
    storage.ccda_key.return_value = "ehi-exports/b1/Lovelace_Ada_p-1.xml"
    storage.upload_xml.return_value = True
    with patch(f"{_SVC}.mark_uploaded") as mock_mark:
        result = prepare_job(client, storage, job)

    assert result.status == PreparationResult.READY
    assert result.s3_key == "ehi-exports/b1/Lovelace_Ada_p-1.xml"
    client.fetch_ccda.assert_called_once_with(
        patient_key="p-1", document_type="continuity", start_date="2025-01-01", end_date=""
    )
    client.get_status.assert_not_called()  # synchronous, no bulkstatus
    storage.upload_xml.assert_called_once()
    mock_mark.assert_called_once_with("j1", "ehi-exports/b1/Lovelace_Ada_p-1.xml")


def test_ccda_returns_failed_when_upload_fails() -> None:
    job = _job(format="ccda", document_type="referral")
    client = MagicMock()
    client.fetch_ccda.return_value = "<x/>"
    storage = MagicMock()
    storage.ccda_key.return_value = "k.xml"
    storage.upload_xml.return_value = False
    with patch(f"{_SVC}.update_status") as mock_update, patch(f"{_SVC}.mark_uploaded") as mock_mark:
        result = prepare_job(client, storage, job)
    assert result.status == PreparationResult.FAILED
    mock_mark.assert_not_called()
    mock_update.assert_called_once()


def test_returns_failed_when_upload_fails() -> None:
    job = _job()
    client = MagicMock()
    client.get_status.return_value = {"status": "complete", "output": [{"url": "u"}]}
    client.build_patient_ndjson.return_value = '{"resourceType":"Patient"}'
    storage = MagicMock()
    storage.patient_key.return_value = "k.ndjson"
    storage.upload_ndjson.return_value = False
    with patch(f"{_SVC}.update_status") as mock_update, patch(f"{_SVC}.mark_uploaded") as mock_mark:
        result = prepare_job(client, storage, job)

    assert result.status == PreparationResult.FAILED
    mock_mark.assert_not_called()
    mock_update.assert_called_once()  # records the S3 failure
