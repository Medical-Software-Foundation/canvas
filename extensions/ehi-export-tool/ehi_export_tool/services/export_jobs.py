"""ExportJobService — persistence logic for EHI export job records.

Kept separate from the SimpleAPI handler so the rules can be exercised without
the Canvas request machinery. All methods are best-effort from the handler's
perspective: a persistence failure must never abort an in-flight export, so the
handler wraps these calls and logs rather than propagating.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from logger import log

from ehi_export_tool.models import CustomPatient, CustomStaff, ExportJob

# Canvas can only generate a C-CDA when it can resolve a document author. Per
# home-app's get_team_lead(): use the patient's care-team lead if set, else fall
# back to the provider on one of the patient's notes — EXCLUDING the Canvas Bot
# and Root system staff. If neither exists it raises 400 "Team Lead is required
# when exporting CCDAs". We replicate that rule to pre-flight eligibility (so
# ineligible patients surface as a clear error up front) and to power the C-CDA
# filter. These system-staff keys are stable Canvas constants.
BOT_STAFF_KEY = "5eede137ecfe4124b8b773040e33be14"
ROOT_STAFF_KEY = "4150cd20de8a470aa570a852859ac87e"
_SYSTEM_STAFF_KEYS = (BOT_STAFF_KEY, ROOT_STAFF_KEY)

NO_TEAM_LEAD_ERROR = (
    "C-CDA export needs a document author: assign a care team lead, or record a "
    "note by a provider for this patient, then re-run."
)


def _ccda_extras(document_type: str, start_date: str, end_date: str) -> dict[str, str]:
    """Per-job CCDA fields (empty for EHI jobs)."""
    return {
        "document_type": document_type or "",
        "start_date": start_date or "",
        "end_date": end_date or "",
    }


def _ccda_eligible_dbids(dbids: list[int]) -> set[int]:
    """Subset of patient dbids that can produce a C-CDA (have a document author).

    Eligible = has an active care-team lead OR has a note authored by a real
    (non-Bot/Root) provider — mirroring home-app's get_team_lead fallback.
    """
    if not dbids:
        return set()
    from canvas_sdk.v1.data import CareTeamMembership, Note

    leads = set(
        CareTeamMembership.objects.filter(
            patient_id__in=list(dbids), lead=True, status="active"
        ).values_list("patient_id", flat=True)
    )
    note_providers = set(
        Note.objects.filter(patient_id__in=list(dbids))
        .exclude(provider__id__in=_SYSTEM_STAFF_KEYS)
        .exclude(provider__isnull=True)
        .values_list("patient_id", flat=True)
    )
    return leads | note_providers


def _new_job(
    dbid: int,
    staff_dbid: int | None,
    batch_id: str,
    format: str,
    is_ccda: bool,
    lead_dbids: set[int],
    extras: dict[str, str],
) -> ExportJob:
    """Build one unsaved ExportJob row for bulk_create.

    EHI -> queued (poller starts it). CCDA -> complete with a synthetic download
    handle, unless the patient has no team lead, in which case it's an error row
    so the missing-lead reason is visible immediately.
    """
    if not is_ccda:
        return ExportJob(
            patient_id=dbid, started_by_id=staff_dbid, batch_id=batch_id,
            job_id="", status="queued", format=format, output=[], attempts=0, **extras,
        )
    has_lead = dbid in lead_dbids
    return ExportJob(
        patient_id=dbid,
        started_by_id=staff_dbid,
        batch_id=batch_id,
        job_id=str(uuid4()),
        status="complete" if has_lead else "error",
        last_error="" if has_lead else NO_TEAM_LEAD_ERROR,
        format=format,
        output=[],
        attempts=0,
        **extras,
    )


class ExportJobService:
    """Create and update :class:`ExportJob` rows and read them back for the UI."""

    @staticmethod
    def record_started(
        patient_id: str, job_id: str, batch_id: str = "", staff_id: str = ""
    ) -> ExportJob | None:
        """Create an in-progress job row for a freshly started export.

        ``batch_id`` groups all jobs from one "Export selected" click; ``staff_id``
        is the logged-in user who kicked it off. Returns ``None`` if the patient
        can't be resolved (the export still runs; it just won't be tracked).
        """
        patient = CustomPatient.objects.filter(id=patient_id).first()
        if patient is None:
            log.warning("ExportJobService: cannot record job, unknown patient %s", patient_id)
            return None
        return ExportJob.objects.create(
            patient=patient,
            started_by=_resolve_staff(staff_id),
            batch_id=batch_id,
            job_id=job_id,
            status="in-progress",
            output=[],
            attempts=0,
        )

    @staticmethod
    def update_status(
        job_id: str,
        status: str,
        *,
        output: list[dict[str, Any]] | None = None,
        error: str = "",
    ) -> ExportJob | None:
        """Update the latest row for ``job_id`` with a new status / output / error.

        Increments the attempt counter on each call. Returns the updated row, or
        ``None`` if no row exists for the job id.
        """
        job = ExportJob.objects.filter(job_id=job_id).order_by("-updated_at").first()
        if job is None:
            return None
        job.status = status
        job.attempts = (job.attempts or 0) + 1
        if output is not None:
            job.output = output
        if error:
            job.last_error = error
        job.save()
        return job

    @staticmethod
    def latest_for_patient_ids(patient_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return the most recent job per patient id, as UI-ready dicts.

        Fetches all jobs for the given patients in one query (ordered newest
        first) and keeps the first seen per patient.
        """
        if not patient_ids:
            return {}
        jobs = (
            ExportJob.objects.filter(patient__id__in=patient_ids)
            .order_by("-updated_at")
            .select_related("patient")
        )
        latest: dict[str, dict[str, Any]] = {}
        for job in jobs:
            pid = str(job.patient.id)
            if pid not in latest:
                latest[pid] = ExportJobService.serialize(job)
        return latest

    @staticmethod
    def record_failed(
        patient_id: str, batch_id: str, error: str, staff_id: str = ""
    ) -> ExportJob | None:
        """Record a job that failed before/at start (so it shows on the main page).

        Start-time failures never get a bulkstatus job id, so ``job_id`` is empty;
        the row exists purely to surface the failure in the patient list and run.
        """
        patient = CustomPatient.objects.filter(id=patient_id).first()
        if patient is None:
            return None
        return ExportJob.objects.create(
            patient=patient,
            started_by=_resolve_staff(staff_id),
            batch_id=batch_id,
            job_id="",
            status="error",
            output=[],
            attempts=0,
            last_error=(error or "")[:1000],
        )

    # ── queue (server-driven, throttled kickoff) ───────────────────────────

    @staticmethod
    def enqueue_patient_ids(
        patient_ids: list[str],
        batch_id: str,
        staff_id: str = "",
        *,
        format: str = "ehi",
        document_type: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> int:
        """Create jobs for an explicit set of patients. Returns the count.

        EHI jobs are ``queued`` (the poller starts ``$export`` at a controlled
        rate). CCDA jobs are synchronous — the document is generated on demand at
        download time — so they're created ``complete`` with a synthetic
        ``job_id`` (their download handle). Uses bulk_create for large selections.
        """
        if not patient_ids:
            return 0
        id_to_dbid = dict(
            CustomPatient.objects.filter(id__in=patient_ids).values_list("id", "dbid")
        )
        staff_dbid = _resolve_staff_dbid(staff_id)
        is_ccda = format == "ccda"
        extras = _ccda_extras(document_type, start_date, end_date)
        dbids = [id_to_dbid[pid] for pid in patient_ids if pid in id_to_dbid]
        lead_dbids = _dbids_with_team_lead(dbids) if is_ccda else set()
        jobs = [
            _new_job(dbid, staff_dbid, batch_id, format, is_ccda, lead_dbids, extras)
            for dbid in dbids
        ]
        ExportJob.objects.bulk_create(jobs, batch_size=500)
        return len(jobs)

    @staticmethod
    def enqueue_queryset(
        patient_queryset,
        batch_id: str,
        staff_id: str = "",
        *,
        format: str = "ehi",
        document_type: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> int:
        """Create jobs for every patient in a queryset (streamed).

        Used by "Export all matching" so the whole filtered set is enqueued
        server-side without the browser enumerating ids. EHI -> queued; CCDA ->
        complete with a synthetic job_id (see :meth:`enqueue_patient_ids`).
        """
        staff_dbid = _resolve_staff_dbid(staff_id)
        is_ccda = format == "ccda"
        extras = _ccda_extras(document_type, start_date, end_date)
        count = 0
        buffer: list[int] = []  # patient dbids; rows are built per flush

        def flush(dbids: list[int]) -> int:
            lead_dbids = _dbids_with_team_lead(dbids) if is_ccda else set()
            rows = [
                _new_job(dbid, staff_dbid, batch_id, format, is_ccda, lead_dbids, extras)
                for dbid in dbids
            ]
            ExportJob.objects.bulk_create(rows)
            return len(rows)

        for dbid in patient_queryset.values_list("dbid", flat=True).iterator(chunk_size=1000):
            buffer.append(dbid)
            if len(buffer) >= 500:
                count += flush(buffer)
                buffer = []
        if buffer:
            count += flush(buffer)
        return count

    @staticmethod
    def queued_jobs(limit: int) -> list[ExportJob]:
        """Oldest queued jobs awaiting kickoff (for the poller)."""
        if limit <= 0:
            return []
        return list(
            ExportJob.objects.filter(status="queued")
            .order_by("created_at")
            .select_related("patient")[:limit]
        )

    @staticmethod
    def count_in_flight() -> int:
        """Number of jobs currently in-progress (Canvas generating files)."""
        return ExportJob.objects.filter(status="in-progress").count()

    @staticmethod
    def mark_started(job: ExportJob, job_id: str) -> None:
        """Transition a queued job to in-progress with its bulkstatus id."""
        job.job_id = job_id
        job.status = "in-progress"
        job.save()

    @staticmethod
    def mark_failed_job(job: ExportJob, error: str) -> None:
        """Mark a specific job row as failed (used when kickoff fails)."""
        job.status = "error"
        job.last_error = (error or "")[:1000]
        job.save()

    @staticmethod
    def mark_uploaded(job_id: str, s3_key: str, output: list[dict[str, Any]] | None = None) -> None:
        """Record the S3 key for a prepared job and mark it complete."""
        job = ExportJob.objects.filter(job_id=job_id).order_by("-updated_at").first()
        if job is None:
            return
        job.status = "complete"
        job.s3_key = s3_key
        if output is not None:
            job.output = output
        job.save()

    @staticmethod
    def in_progress_jobs(limit: int = 50) -> list[ExportJob]:
        """Return the oldest in-progress jobs for the background poller to advance."""
        return list(
            ExportJob.objects.filter(status="in-progress").order_by("updated_at")[:limit]
        )

    @staticmethod
    def complete_jobs_without_s3(limit: int = 5) -> list[ExportJob]:
        """Return completed jobs whose JSON hasn't been uploaded to S3 yet."""
        return list(
            ExportJob.objects.filter(status="complete", s3_key="")
            .order_by("updated_at")
            .select_related("patient")[:limit]
        )

    @staticmethod
    def get_with_patient(job_id: str) -> ExportJob | None:
        """Fetch one job (latest for the id) with its patient preloaded."""
        return (
            ExportJob.objects.filter(job_id=job_id)
            .order_by("-updated_at")
            .select_related("patient")
            .first()
        )

    # UI sort key -> grouped-query ordering field.
    BATCH_SORTS = {"started": "created", "started_by": "staff_last"}

    @classmethod
    def list_batches_page(
        cls,
        *,
        search: str = "",
        progress: str = "",
        offset: int = 0,
        limit: int = 25,
        sort: str = "started",
        dir: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        """Summarize export runs (batches) — grouped, searchable, sortable, paginated.

        ``search`` matches a run by the staff member who started it OR by any
        patient it contains — name or patient key (id), case-insensitive.
        ``progress`` filters by the run's derived state — running | completed |
        completed_with_errors (see ``BATCH_PROGRESS_FILTERS``). ``sort`` is
        started | started_by; ``dir`` asc | desc. Returns ``(rows, total)``;
        counts always reflect the whole run even when the search matched on a
        single patient.
        """
        from django.db.models import Count, Max, Min, Q

        base = ExportJob.objects.exclude(batch_id="")
        if search:
            matching_ids = (
                base.filter(
                    Q(started_by__first_name__icontains=search)
                    | Q(started_by__last_name__icontains=search)
                    | Q(patient__first_name__icontains=search)
                    | Q(patient__last_name__icontains=search)
                    | Q(patient__id__icontains=search)
                )
                .values_list("batch_id", flat=True)
                .distinct()
            )
            base = base.filter(batch_id__in=matching_ids)

        grouped = base.values("batch_id").annotate(
            created=Min("created_at"),
            total=Count("dbid"),
            complete=Count("dbid", filter=Q(status="complete")),
            failed=Count("dbid", filter=Q(status="error")),
            queued=Count("dbid", filter=Q(status="queued")),
            in_progress=Count("dbid", filter=Q(status="in-progress")),
            # All jobs in a batch share one starter; Max over the join picks it.
            staff_first=Max("started_by__first_name"),
            staff_last=Max("started_by__last_name"),
        )

        # Filter by the run's derived progress, evaluated on the aggregated counts.
        progress_filter = cls._batch_progress_q(progress, Q)
        if progress_filter is not None:
            grouped = grouped.filter(progress_filter)

        prefix = "-" if (dir or "").lower() == "desc" else ""
        field = cls.BATCH_SORTS.get(sort, "created")
        if field == "staff_last":
            ordering = [f"{prefix}staff_last", f"{prefix}staff_first", "-created"]
        else:
            ordering = [f"{prefix}created"]
        grouped = grouped.order_by(*ordering)

        total = grouped.count()
        page = list(grouped[offset : offset + limit])

        rows = [
            {
                "batch_id": row["batch_id"],
                "created_at": row["created"].isoformat() if row["created"] else "",
                "started_by": f"{row['staff_first'] or ''} {row['staff_last'] or ''}".strip(),
                "total": row["total"],
                "complete": row["complete"],
                "failed": row["failed"],
                "queued": row["queued"],
                "in_progress": row["in_progress"],
            }
            for row in page
        ]
        return rows, total

    # Valid run-progress filter values for the "all runs" page.
    BATCH_PROGRESS_FILTERS = ("running", "completed", "completed_with_errors")

    @staticmethod
    def _batch_progress_q(progress: str, Q: Any) -> Any:
        """Build a ``Q`` over the aggregated run counts for the given progress value.

        ``running`` = still has queued or in-progress jobs; ``completed`` = all
        done with no failures; ``completed_with_errors`` = all done, some failed.
        Returns ``None`` for an empty/unknown value (no filter).
        """
        value = (progress or "").strip()
        if value == "running":
            return Q(queued__gt=0) | Q(in_progress__gt=0)
        if value == "completed":
            return Q(queued=0, in_progress=0, failed=0)
        if value == "completed_with_errors":
            return Q(queued=0, in_progress=0, failed__gt=0)
        return None

    # UI export-filter value -> ExportJob.status (None sentinel = "no export").
    EXPORT_FILTERS = {
        "completed": "complete",
        "failed": "error",
        "in_progress": "in-progress",
        "queued": "queued",
        "none": None,
    }

    @classmethod
    def apply_export_filter(cls, patient_queryset, export: str):
        """Filter a Patient queryset by each patient's LATEST export status.

        ``export`` is one of completed | failed | in_progress | none (no export).
        Unknown/empty returns the queryset unchanged. Implemented as a correlated
        subquery on the latest ExportJob per patient (joined on dbid), so it works
        across the whole instance with normal pagination.
        """
        if export not in cls.EXPORT_FILTERS:
            return patient_queryset
        from django.db.models import OuterRef, Subquery

        latest_status = (
            ExportJob.objects.filter(patient_id=OuterRef("dbid"))
            .order_by("-updated_at")
            .values("status")[:1]
        )
        annotated = patient_queryset.annotate(latest_export_status=Subquery(latest_status))
        target = cls.EXPORT_FILTERS[export]
        if target is None:
            return annotated.filter(latest_export_status__isnull=True)
        return annotated.filter(latest_export_status=target)

    @staticmethod
    def batch_counts(batch_id: str) -> dict[str, int]:
        """Status breakdown for a whole run: total/complete/error/in_progress/queued."""
        base = ExportJob.objects.filter(batch_id=batch_id)
        total = base.count()
        complete = base.filter(status="complete").count()
        error = base.filter(status="error").count()
        queued = base.filter(status="queued").count()
        return {
            "total": total,
            "complete": complete,
            "error": error,
            "queued": queued,
            "in_progress": total - complete - error - queued,
        }

    @staticmethod
    def jobs_for_batch_page(
        batch_id: str,
        *,
        status: str = "",
        search: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a page of a batch's jobs (filtered by status/search) and the match total.

        ``status`` is one of "" (all), "complete", "error", "in-progress".
        """
        if not batch_id:
            return [], 0
        from django.db.models import Q

        qs = ExportJob.objects.filter(batch_id=batch_id).select_related("patient")
        if status:
            qs = qs.filter(status=status)
        if search:
            qs = qs.filter(
                Q(patient__first_name__icontains=search)
                | Q(patient__last_name__icontains=search)
                | Q(patient__id__icontains=search)
            )
        # NB: CustomModel's primary key is "dbid", not "id".
        qs = qs.order_by("patient__last_name", "patient__first_name", "dbid")

        total = qs.count()
        rows = []
        for job in qs[offset : offset + limit]:
            data = ExportJobService.serialize(job)
            patient = job.patient
            data["patient_id"] = str(patient.id)
            data["patient_name"] = _patient_name(patient)
            # Same patient fields the main table shows, so the run table can match it.
            data["first_name"] = patient.first_name or ""
            data["last_name"] = patient.last_name or ""
            data["dob"] = patient.birth_date.strftime("%Y-%m-%d") if patient.birth_date else ""
            data["patient_active"] = bool(patient.active)
            rows.append(data)
        return rows, total

    @staticmethod
    def serialize(job: ExportJob) -> dict[str, Any]:
        """Project an ExportJob to the minimal shape the UI needs."""
        return {
            "job_id": job.job_id,
            "batch_id": job.batch_id,
            "status": job.status,
            "format": getattr(job, "format", "ehi") or "ehi",
            "document_type": getattr(job, "document_type", "") or "",
            "attempts": job.attempts,
            "file_count": len(job.output or []),
            "last_error": job.last_error,
            "has_file": bool(job.s3_key),
            "updated_at": job.updated_at.isoformat() if job.updated_at else "",
        }


def _patient_name(patient: Any) -> str:
    """Format a patient's display name as 'Last, First'."""
    last = (getattr(patient, "last_name", "") or "").strip()
    first = (getattr(patient, "first_name", "") or "").strip()
    return f"{last}, {first}".strip(", ") or "(unnamed)"


def _resolve_staff(staff_id: str) -> CustomStaff | None:
    """Look up the CustomStaff for a staff UUID, or None if missing/unknown."""
    if not staff_id:
        return None
    return CustomStaff.objects.filter(id=staff_id).first()


def _resolve_staff_dbid(staff_id: str) -> Any:
    """Return the staff dbid for a UUID (for bulk FK assignment), or None."""
    if not staff_id:
        return None
    return CustomStaff.objects.filter(id=staff_id).values_list("dbid", flat=True).first()


def _staff_name(staff: Any) -> str:
    """Format a staff member's display name, or '' if not set."""
    if staff is None:
        return ""
    full = (getattr(staff, "full_name", "") or "").strip()
    if full:
        return full
    last = (getattr(staff, "last_name", "") or "").strip()
    first = (getattr(staff, "first_name", "") or "").strip()
    return f"{first} {last}".strip()
