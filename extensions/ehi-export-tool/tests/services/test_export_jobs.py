"""Tests for ExportJobService.

The Canvas test harness here is not wired for a live Django test DB, so the ORM
(``ExportJob.objects`` / ``CustomPatient.objects``) is mocked. These tests verify
the service's logic — which row it creates/updates, attempt incrementing, and the
latest-per-patient dedup — rather than exercising the database.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ehi_export_tool.services.export_jobs import ExportJobService

_SVC = "ehi_export_tool.services.export_jobs"


def _job(*, pid="p-1", job_id="job-1", status="complete", attempts=1, output=None,
         last_error="", updated="2026-06-09T22:00:00+00:00", batch_id="", s3_key=""):
    return SimpleNamespace(
        patient=SimpleNamespace(id=pid),
        started_by=None,
        batch_id=batch_id,
        s3_key=s3_key,
        job_id=job_id,
        status=status,
        attempts=attempts,
        output=output if output is not None else [{"url": "x"}],
        last_error=last_error,
        updated_at=SimpleNamespace(isoformat=lambda: updated),
        save=MagicMock(),
    )


# ── record_started ────────────────────────────────────────────────────────────


def test_record_started_creates_in_progress_row() -> None:
    patient = SimpleNamespace(id="p-1")
    with patch(f"{_SVC}.CustomPatient") as MockPatient, patch(f"{_SVC}.ExportJob") as MockJob:
        MockPatient.objects.filter.return_value.first.return_value = patient
        MockJob.objects.create.return_value = "created"
        result = ExportJobService.record_started("p-1", "job-9")

    assert result == "created"
    kwargs = MockJob.objects.create.call_args.kwargs
    assert kwargs["patient"] is patient
    assert kwargs["job_id"] == "job-9"
    assert kwargs["status"] == "in-progress"
    assert kwargs["attempts"] == 0


def test_enqueue_patient_ids_bulk_creates() -> None:
    with patch(f"{_SVC}.CustomPatient") as MockPatient, patch(
        f"{_SVC}.CustomStaff"
    ) as MockStaff, patch(f"{_SVC}.ExportJob") as MockJob:
        MockPatient.objects.filter.return_value.values_list.return_value = [("p-1", 11), ("p-2", 22)]
        MockStaff.objects.filter.return_value.values_list.return_value.first.return_value = 99
        n = ExportJobService.enqueue_patient_ids(["p-1", "p-2"], "b1", "s-1")

    assert n == 2
    MockJob.objects.bulk_create.assert_called_once()
    created = MockJob.objects.bulk_create.call_args[0][0]
    assert len(created) == 2


def test_enqueue_patient_ids_empty() -> None:
    assert ExportJobService.enqueue_patient_ids([], "b1", "s-1") == 0


def test_enqueue_queryset_streams_dbids() -> None:
    qs = MagicMock()
    qs.values_list.return_value.iterator.return_value = iter([1, 2, 3])
    with patch(f"{_SVC}.CustomStaff") as MockStaff, patch(f"{_SVC}.ExportJob") as MockJob:
        MockStaff.objects.filter.return_value.values_list.return_value.first.return_value = None
        n = ExportJobService.enqueue_queryset(qs, "b1", "")

    assert n == 3
    MockJob.objects.bulk_create.assert_called_once()  # 3 < 500 -> single flush


def test_queued_jobs_zero_limit() -> None:
    assert ExportJobService.queued_jobs(0) == []


def test_mark_started_and_failed() -> None:
    job = MagicMock()
    ExportJobService.mark_started(job, "job-9")
    assert job.job_id == "job-9" and job.status == "in-progress"
    job.save.assert_called_once()

    job2 = MagicMock()
    ExportJobService.mark_failed_job(job2, "boom")
    assert job2.status == "error" and job2.last_error == "boom"


def test_record_started_resolves_staff() -> None:
    patient = SimpleNamespace(id="p-1")
    staff = SimpleNamespace(id="s-1")
    with patch(f"{_SVC}.CustomPatient") as MockPatient, patch(
        f"{_SVC}.CustomStaff"
    ) as MockStaff, patch(f"{_SVC}.ExportJob") as MockJob:
        MockPatient.objects.filter.return_value.first.return_value = patient
        MockStaff.objects.filter.return_value.first.return_value = staff
        ExportJobService.record_started("p-1", "job-9", "b1", "s-1")
    assert MockJob.objects.create.call_args.kwargs["started_by"] is staff


def test_record_started_returns_none_for_unknown_patient() -> None:
    with patch(f"{_SVC}.CustomPatient") as MockPatient, patch(f"{_SVC}.ExportJob") as MockJob:
        MockPatient.objects.filter.return_value.first.return_value = None
        result = ExportJobService.record_started("missing", "job-9")

    assert result is None
    MockJob.objects.create.assert_not_called()


# ── update_status ─────────────────────────────────────────────────────────────


def test_update_status_updates_and_increments_attempts() -> None:
    job = _job(status="in-progress", attempts=2)
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value.order_by.return_value.first.return_value = job
        result = ExportJobService.update_status(
            "job-1", "complete", output=[{"url": "a"}, {"url": "b"}]
        )

    assert result is job
    assert job.status == "complete"
    assert job.attempts == 3
    assert job.output == [{"url": "a"}, {"url": "b"}]
    job.save.assert_called_once()


def test_update_status_records_error() -> None:
    job = _job(status="in-progress", attempts=0)
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value.order_by.return_value.first.return_value = job
        ExportJobService.update_status("job-1", "error", error="503 down")

    assert job.status == "error"
    assert job.last_error == "503 down"


def test_update_status_returns_none_when_missing() -> None:
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value.order_by.return_value.first.return_value = None
        assert ExportJobService.update_status("nope", "complete") is None


# ── latest_for_patient_ids ────────────────────────────────────────────────────


def test_latest_for_patient_ids_empty_returns_empty() -> None:
    assert ExportJobService.latest_for_patient_ids([]) == {}


def test_latest_for_patient_ids_keeps_newest_per_patient() -> None:
    # Two jobs for p-1 (newest first) and one for p-2; dedup keeps the first seen.
    newest_p1 = _job(pid="p-1", job_id="p1-new", status="complete")
    older_p1 = _job(pid="p-1", job_id="p1-old", status="error")
    p2 = _job(pid="p-2", job_id="p2", status="in-progress")
    qs = MagicMock()
    qs.order_by.return_value.select_related.return_value = [newest_p1, older_p1, p2]
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value = qs
        result = ExportJobService.latest_for_patient_ids(["p-1", "p-2"])

    assert set(result.keys()) == {"p-1", "p-2"}
    assert result["p-1"]["job_id"] == "p1-new"  # newest wins
    assert result["p-2"]["status"] == "in-progress"


def test_serialize_shape() -> None:
    job = _job(job_id="j", status="complete", attempts=4, output=[{"url": "a"}, {"url": "b"}])
    job.batch_id = "b1"
    job.s3_key = "ehi-exports/b1/Lovelace_Ada_p-1.json"
    out = ExportJobService.serialize(job)
    assert out == {
        "job_id": "j",
        "batch_id": "b1",
        "status": "complete",
        "attempts": 4,
        "file_count": 2,
        "last_error": "",
        "has_file": True,
        "updated_at": "2026-06-09T22:00:00+00:00",
    }


# ── record_started with batch ─────────────────────────────────────────────────


def test_record_started_passes_batch_id() -> None:
    patient = SimpleNamespace(id="p-1")
    with patch(f"{_SVC}.CustomPatient") as MockPatient, patch(f"{_SVC}.ExportJob") as MockJob:
        MockPatient.objects.filter.return_value.first.return_value = patient
        ExportJobService.record_started("p-1", "job-9", "batch-7")
    assert MockJob.objects.create.call_args.kwargs["batch_id"] == "batch-7"


# ── list_batches_page ─────────────────────────────────────────────────────────


def _grouped_chain(rows, total):
    """Mock the ExportJob grouped-aggregation chain for list_batches_page."""
    grouped = MagicMock()
    grouped.count.return_value = total
    grouped.__getitem__.return_value = rows
    base = MagicMock()
    base.filter.return_value = base
    base.values.return_value.annotate.return_value.order_by.return_value = grouped
    base.values_list.return_value.distinct.return_value = []
    return base


def test_list_batches_page_shapes_rows_and_total() -> None:
    row = {
        "batch_id": "b1",
        "created": SimpleNamespace(isoformat=lambda: "2026-06-10T10:00:00+00:00"),
        "total": 5, "complete": 2, "failed": 0, "queued": 2, "in_progress": 1,
        "staff_first": "Ada", "staff_last": "Lovelace",
    }
    base = _grouped_chain([row], total=9)
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.exclude.return_value = base
        rows, total = ExportJobService.list_batches_page(offset=0, limit=50)

    assert total == 9
    assert rows[0] == {
        "batch_id": "b1",
        "created_at": "2026-06-10T10:00:00+00:00",
        "started_by": "Ada Lovelace",
        "total": 5, "complete": 2, "failed": 0, "queued": 2, "in_progress": 1,
    }


def test_list_batches_page_search_filters_by_batch_id() -> None:
    base = _grouped_chain([], total=0)
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.exclude.return_value = base
        ExportJobService.list_batches_page(search="smith", offset=0, limit=50)
    # search path applies a filter (by staff/patient match -> batch_id__in)
    assert base.filter.called


def test_list_batches_page_sort_by_started_by() -> None:
    base = _grouped_chain([], total=0)
    grouped = base.values.return_value.annotate.return_value
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.exclude.return_value = base
        ExportJobService.list_batches_page(sort="started_by", dir="asc", limit=50)
    grouped.order_by.assert_called_once_with("staff_last", "staff_first", "-created")


# ── jobs_for_batch ────────────────────────────────────────────────────────────


def test_jobs_for_batch_page_empty_id_returns_empty() -> None:
    assert ExportJobService.jobs_for_batch_page("") == ([], 0)


def test_jobs_for_batch_page_filters_paginates_and_shapes_rows() -> None:
    job = _job(pid="p-1", status="complete")
    job.batch_id = "b1"
    job.patient = SimpleNamespace(
        id="p-1", first_name="Ada", last_name="Lovelace", birth_date=date(1990, 1, 2), active=True
    )

    # Build a queryset chain: filter -> (filter status) -> (filter search) -> order_by -> count / slice
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.select_related.return_value = qs
    qs.order_by.return_value = qs
    qs.count.return_value = 7
    qs.__getitem__.return_value = [job]
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value = qs
        rows, total = ExportJobService.jobs_for_batch_page(
            "b1", status="complete", search="lov", offset=0, limit=2
        )

    assert total == 7
    assert rows[0]["patient_id"] == "p-1"
    assert rows[0]["patient_name"] == "Lovelace, Ada"
    assert rows[0]["status"] == "complete"


def test_apply_export_filter_unknown_returns_unchanged() -> None:
    qs = MagicMock()
    assert ExportJobService.apply_export_filter(qs, "bogus") is qs
    qs.annotate.assert_not_called()


def test_apply_export_filter_completed_filters_on_status() -> None:
    qs = MagicMock()
    annotated = qs.annotate.return_value
    with patch(f"{_SVC}.ExportJob"):
        ExportJobService.apply_export_filter(qs, "completed")
    qs.annotate.assert_called_once()
    annotated.filter.assert_called_once_with(latest_export_status="complete")


def test_apply_export_filter_none_filters_isnull() -> None:
    qs = MagicMock()
    annotated = qs.annotate.return_value
    with patch(f"{_SVC}.ExportJob"):
        ExportJobService.apply_export_filter(qs, "none")
    annotated.filter.assert_called_once_with(latest_export_status__isnull=True)


def test_batch_counts() -> None:
    base = MagicMock()
    base.count.return_value = 10  # total
    base.filter.return_value.count.side_effect = [6, 1, 2]  # complete=6, error=1, queued=2
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value = base
        counts = ExportJobService.batch_counts("b1")

    assert counts == {"total": 10, "complete": 6, "error": 1, "queued": 2, "in_progress": 1}


# ── in_progress_jobs ──────────────────────────────────────────────────────────


def test_record_failed_creates_error_row() -> None:
    patient = SimpleNamespace(id="p-1")
    with patch(f"{_SVC}.CustomPatient") as MockPatient, patch(f"{_SVC}.ExportJob") as MockJob:
        MockPatient.objects.filter.return_value.first.return_value = patient
        ExportJobService.record_failed("p-1", "b1", "boom")
    kwargs = MockJob.objects.create.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["batch_id"] == "b1"
    assert kwargs["job_id"] == ""
    assert kwargs["last_error"] == "boom"


def test_mark_uploaded_sets_key_and_complete() -> None:
    job = _job(status="in-progress", s3_key="")
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value.order_by.return_value.first.return_value = job
        ExportJobService.mark_uploaded("job-1", "ehi-exports/b1/x.json", output=[{"url": "u"}])
    assert job.status == "complete"
    assert job.s3_key == "ehi-exports/b1/x.json"
    assert job.output == [{"url": "u"}]
    job.save.assert_called_once()


def test_complete_jobs_without_s3_filters() -> None:
    with patch(f"{_SVC}.ExportJob") as MockJob:
        chain = MockJob.objects.filter.return_value.order_by.return_value.select_related.return_value
        chain.__getitem__.return_value = ["x"]
        result = ExportJobService.complete_jobs_without_s3(limit=5)
    MockJob.objects.filter.assert_called_once_with(status="complete", s3_key="")
    assert result == ["x"]


def test_in_progress_jobs_filters_and_limits() -> None:
    sentinel = [object(), object()]
    with patch(f"{_SVC}.ExportJob") as MockJob:
        MockJob.objects.filter.return_value.order_by.return_value.__getitem__.return_value = sentinel
        result = ExportJobService.in_progress_jobs(limit=10)
    MockJob.objects.filter.assert_called_once_with(status="in-progress")
    assert result == sentinel
