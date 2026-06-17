"""ExportAPI — staff-only SimpleAPI serving the EHI export workspace.

Routes (all under /plugin-io/api/ehi_export_tool/):
  GET  /app/                  — HTML shell
  GET  /app/main.js           — vanilla JS client (orchestration + JSZip)
  GET  /app/styles.css        — CSS
  GET  /app/patients          — JSON list of patients (search + pagination)
      query params: search, offset, limit, include_inactive
  POST /app/export/start      — body {patient_id}; kicks off $export -> {job_id}
  GET  /app/export/status     — query job_id; polls bulkstatus -> {status, ...}
  GET  /app/export/bundle     — query job_id + patient_id; returns merged Bundle JSON

The browser orchestrates the per-patient start -> poll -> fetch-bundle loop with a
small concurrency cap and assembles the final ZIP client-side (JSZip), so the
server stays stateless and no single request has to export the whole instance.

Auth: StaffSessionAuthMixin — non-staff sessions are rejected at the mixin level.
These endpoints expose full patient records, so staff-session auth is mandatory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from logger import log

from ehi_export_tool.services.export_jobs import ExportJobService
from ehi_export_tool.services.preparation import PreparationResult, prepare_job
from ehi_export_tool.services.storage import ExportStorage
from ehi_export_tool.utils.fhir_client import (
    EHIConfigError,
    EHIExportClient,
    EHIExportError,
)

# Cache-bust token — generated once at module load so each deploy serves fresh assets.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))

_PREFIX = "ehi_export_tool"

# Pagination guardrails for the patient list.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


class ExportAPI(StaffSessionAuthMixin, SimpleAPI):
    """Staff-only HTTP API that serves and drives the EHI export workspace."""

    PREFIX = "/app"

    # ── static assets ──────────────────────────────────────────────────────

    @api.get("/")
    def get_html(self) -> list[Response | Effect]:
        """Serve the HTML shell for the export workspace."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        log.info("ExportAPI.get_html staff=%s", staff_id)
        content = render_to_string(
            "templates/index.html",
            {"cache_bust": _CACHE_BUST, "api_prefix": f"/plugin-io/api/{_PREFIX}"},
        )
        return [HTMLResponse(content, status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def get_js(self) -> list[Response | Effect]:
        """Serve the vanilla JS client."""
        content = render_to_string(
            "templates/main.js",
            {"cache_bust": _CACHE_BUST, "api_prefix": f"/plugin-io/api/{_PREFIX}"},
        )
        return [
            Response(
                content=content.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={"Content-Type": "application/javascript; charset=utf-8"},
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the workspace CSS."""
        content = render_to_string("templates/styles.css", {})
        return [
            Response(
                content=content.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={"Content-Type": "text/css; charset=utf-8"},
            )
        ]

    # ── configuration status ─────────────────────────────────────────────────

    @api.get("/config")
    def get_config(self) -> list[Response | Effect]:
        """Report whether the FHIR OAuth credentials are configured.

        Used by the UI to warn up front (before any export) if the plugin is
        missing credentials. Never returns the secret values themselves.
        """
        configured = bool(
            self.secrets.get("CANVAS_FHIR_CLIENT_ID")
            and self.secrets.get("CANVAS_FHIR_CLIENT_SECRET")
        )
        return [
            JSONResponse(
                {
                    "configured": configured,
                    "s3_configured": ExportStorage.is_configured(self.secrets),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    # ── patient listing ──────────────────────────────────────────────────────

    @api.get("/patients")
    def get_patients(self) -> list[Response | Effect]:
        """Return a paginated, optionally filtered list of patients.

        Query params:
          search            — case-insensitive match on first/last name (optional)
          offset            — int, default 0
          limit             — int, default 50, capped at 200
          include_inactive  — "true" to include inactive patients (default: active only)
          export            — completed | failed | in_progress | none (latest export status)
          sort              — last_name | first_name | dob | id (default: last_name)
          dir               — asc | desc (default: asc)
        """
        params = self.request.query_params
        offset = _parse_int(params.get("offset"), default=0, minimum=0)
        limit = _parse_int(params.get("limit"), default=_DEFAULT_LIMIT, minimum=1, maximum=_MAX_LIMIT)

        queryset = self._filtered_patients(
            search=(params.get("search") or "").strip(),
            include_inactive=(params.get("include_inactive") or "").strip().lower() == "true",
            export=(params.get("export") or "").strip(),
        )
        queryset = queryset.order_by(*self._order_by(params.get("sort"), params.get("dir")))

        total = queryset.count()
        page = queryset[offset : offset + limit]
        patients = [self._serialize_patient(p) for p in page]

        return [
            JSONResponse(
                {
                    "patients": patients,
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "has_more": (offset + limit) < total,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    def _filtered_patients(self, *, search: str, include_inactive: bool, export: str):
        """Build the (unordered) patient queryset for the given filters.

        Shared by the patient list and "Export all matching" so they always agree
        on what "matching" means. Enqueue assigns the FK by dbid, so plain Patient
        rows are fine here.
        """
        queryset = Patient.objects.all()
        if not include_inactive:
            queryset = queryset.filter(active=True)
        if search:
            queryset = self._apply_name_search(queryset, search)
        if export:
            queryset = ExportJobService.apply_export_filter(queryset, export)
        return queryset

    # UI sort key -> Patient model field.
    _SORT_FIELDS = {
        "last_name": "last_name",
        "first_name": "first_name",
        "dob": "birth_date",
        "active": "active",
        "id": "id",
    }

    @classmethod
    def _order_by(cls, sort: str | None, direction: str | None) -> list[str]:
        """Build a stable order_by list from the requested sort key + direction.

        Falls back to last_name ascending for unknown keys. The chosen field
        leads (with the requested direction); the remaining name/id fields follow
        as ascending tie-breakers for deterministic paging.
        """
        field = cls._SORT_FIELDS.get((sort or "").strip(), "last_name")
        prefix = "-" if (direction or "").strip().lower() == "desc" else ""
        order = [f"{prefix}{field}"]
        for tiebreaker in ("last_name", "first_name", "id"):
            if tiebreaker != field:
                order.append(tiebreaker)
        return order

    @staticmethod
    def _apply_name_search(queryset, search: str):
        """Filter a Patient queryset by a free-text name search.

        A single term matches first OR last name; two+ terms match the first
        term against the first name AND the last term against the last name.
        """
        from django.db.models import Q

        # Patient key (the id) is matched against the full search string.
        match = Q(id__icontains=search)
        terms = search.split()
        if len(terms) >= 2:
            match |= Q(first_name__icontains=terms[0], last_name__icontains=terms[-1]) | Q(
                last_name__icontains=terms[0], first_name__icontains=terms[-1]
            )
        else:
            match |= Q(first_name__icontains=search) | Q(last_name__icontains=search)
        return queryset.filter(match)

    @staticmethod
    def _serialize_patient(patient: Patient) -> dict[str, str]:
        """Project a Patient row to the minimal shape the UI needs.

        ``first_name``/``last_name`` drive the separate table columns; ``name``
        ("Last, First") is kept for download filenames and progress labels.
        """
        first = patient.first_name or ""
        last = patient.last_name or ""
        name = f"{last}, {first}".strip(", ") or "(unnamed)"
        return {
            "id": str(patient.id),
            "first_name": first,
            "last_name": last,
            "name": name,
            "dob": patient.birth_date.strftime("%Y-%m-%d") if patient.birth_date else "",
            "active": bool(patient.active),
        }

    @api.get("/jobs")
    def get_jobs(self) -> list[Response | Effect]:
        """Return the latest export job per patient for a set of patient ids.

        Query param ``patient_ids`` is a comma-separated list (typically the
        ids on the current patient-list page). Response shape:
        ``{"jobs": {"<patient_id>": {status, job_id, updated_at, ...}}}``.
        """
        raw = (self.request.query_params.get("patient_ids") or "").strip()
        patient_ids = [pid for pid in (p.strip() for p in raw.split(",")) if pid]
        jobs = ExportJobService.latest_for_patient_ids(patient_ids)
        return [JSONResponse({"jobs": jobs}, status_code=HTTPStatus.OK)]

    @api.get("/batches")
    def get_batches(self) -> list[Response | Effect]:
        """Return export runs (batches), newest first — paginated and searchable.

        Query params: limit (default 25, cap 200), offset, search (matches the
        staff who started the run, or a patient in it), progress (running |
        completed | completed_with_errors), sort, dir. The main-page panel asks
        for the latest few; the "all runs" page paginates with search + progress.
        """
        params = self.request.query_params
        limit = _parse_int(params.get("limit"), default=25, minimum=1, maximum=200)
        offset = _parse_int(params.get("offset"), default=0, minimum=0)
        search = (params.get("search") or "").strip()
        progress = (params.get("progress") or "").strip()
        if progress not in ExportJobService.BATCH_PROGRESS_FILTERS:
            progress = ""
        sort = (params.get("sort") or "started").strip()
        direction = (params.get("dir") or "desc").strip()
        batches, total = ExportJobService.list_batches_page(
            search=search, progress=progress, offset=offset, limit=limit, sort=sort, dir=direction
        )
        return [
            JSONResponse(
                {
                    "batches": batches,
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "has_more": (offset + limit) < total,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    # Valid status filters for the run view.
    _BATCH_STATUSES = {"complete", "error", "in-progress"}

    @api.get("/batch")
    def get_batch(self) -> list[Response | Effect]:
        """Return one run's status counts + a filtered, paginated page of its patients.

        Query params: batch_id (required), status (complete|error|in-progress|""),
        search, offset, limit (default 100, capped at 500).
        """
        params = self.request.query_params
        batch_id = (params.get("batch_id") or "").strip()
        if not batch_id:
            return [_error("batch_id is required", HTTPStatus.BAD_REQUEST)]

        status = (params.get("status") or "").strip()
        if status not in self._BATCH_STATUSES:
            status = ""  # treat anything else as "all"
        search = (params.get("search") or "").strip()
        offset = _parse_int(params.get("offset"), default=0, minimum=0)
        limit = _parse_int(params.get("limit"), default=100, minimum=1, maximum=500)

        jobs, total = ExportJobService.jobs_for_batch_page(
            batch_id, status=status, search=search, offset=offset, limit=limit
        )
        storage = ExportStorage.from_secrets(self.secrets)
        return [
            JSONResponse(
                {
                    "batch_id": batch_id,
                    "counts": ExportJobService.batch_counts(batch_id),
                    "jobs": jobs,
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "has_more": (offset + limit) < total,
                    "s3_bucket": self.secrets.get("S3_BUCKET", ""),
                    "s3_prefix": storage.batch_prefix(batch_id) if storage else "",
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/download")
    def get_download(self) -> list[Response | Effect]:
        """Download one patient's export as a single ``.ndjson``.

        No S3 needed: if S3 is configured the file is staged there and we redirect
        to a presigned URL; otherwise the plugin builds the NDJSON on demand and
        streams it back directly (the user never hits a raw Canvas endpoint).
        Returns 409 if the export isn't complete yet.
        """
        job_id = (self.request.query_params.get("job_id") or "").strip()
        if not job_id:
            return [_error("job_id is required", HTTPStatus.BAD_REQUEST)]

        job = ExportJobService.get_with_patient(job_id)
        if job is None:
            return [_error("export job not found", HTTPStatus.NOT_FOUND)]

        storage = ExportStorage.from_secrets(self.secrets)
        try:
            client = self._build_client()
            if storage is not None:
                # Stage to S3 (if not already) and redirect the browser to a
                # short-lived presigned URL — download streams straight from S3.
                result = prepare_job(client, storage, job)
                if result.status == PreparationResult.PENDING:
                    return [_error("export is still processing", HTTPStatus.CONFLICT)]
                if result.status == PreparationResult.FAILED:
                    return [_error("failed to store export file", HTTPStatus.BAD_GATEWAY)]
                url = storage.presigned_url(result.s3_key)
                if not url:
                    return [_error("could not generate a download URL", HTTPStatus.BAD_GATEWAY)]
                return [Response(status_code=HTTPStatus.FOUND, headers={"Location": url})]

            # No S3: build the NDJSON on demand and stream it back.
            status = client.get_status(job.job_id)
            if status["status"] != "complete":
                return [_error("export is still processing", HTTPStatus.CONFLICT)]
            ndjson = client.build_patient_ndjson(status["output"])
        except EHIConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except EHIExportError as exc:
            log.error("ExportAPI.get_download failed for job %s: %s", job_id, exc)
            return [_error(str(exc), HTTPStatus.BAD_GATEWAY)]

        filename = _ndjson_filename(job)
        return [
            Response(
                content=ndjson.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={
                    "Content-Type": "application/x-ndjson; charset=utf-8",
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )
        ]

    # ── export flow ──────────────────────────────────────────────────────────

    @api.post("/export/enqueue")
    def enqueue_export(self) -> list[Response | Effect]:
        """Queue an export run without starting it (the cron starts jobs, throttled).

        Body is either:
          {"patient_ids": [...]}                     — queue these specific patients
          {"all_matching": true, "search","export","include_inactive"} — queue the
                                                        whole filtered set, server-side
        Returns ``{batch_id, queued}``. Fire-and-forget: no $export here, so the
        browser can queue thousands instantly and close the tab.
        """
        body = self.request.json()
        staff_id = (self.request.headers.get("canvas-logged-in-user-id") or "").strip()
        batch_id = str(uuid4())

        if body.get("all_matching"):
            queryset = self._filtered_patients(
                search=(body.get("search") or "").strip(),
                include_inactive=bool(body.get("include_inactive")),
                export=(body.get("export") or "").strip(),
            )
            queued = ExportJobService.enqueue_queryset(queryset, batch_id, staff_id)
        else:
            patient_ids = [pid for pid in (body.get("patient_ids") or []) if pid]
            if not patient_ids:
                return [_error("no patients to export", HTTPStatus.BAD_REQUEST)]
            queued = ExportJobService.enqueue_patient_ids(patient_ids, batch_id, staff_id)

        log.info("ExportAPI.enqueue_export: queued %d job(s) in batch %s", queued, batch_id)
        return [JSONResponse({"batch_id": batch_id, "queued": queued}, status_code=HTTPStatus.OK)]

    @api.post("/export/start")
    def start_export(self) -> list[Response | Effect]:
        """Initiate an EHI export for one patient and return its bulkstatus job id."""
        body = self.request.json()
        patient_id = (body.get("patient_id") or "").strip()
        batch_id = (body.get("batch_id") or "").strip()
        staff_id = (self.request.headers.get("canvas-logged-in-user-id") or "").strip()
        if not patient_id:
            return [_error("patient_id is required", HTTPStatus.BAD_REQUEST)]

        # Test hook: set the EHI_FORCE_FAILURE variable to "true" to make every
        # export fail, so the failure UI (per-patient error + summary banner) can
        # be exercised without a real outage. Remove the variable to restore.
        if (self.secrets.get("EHI_FORCE_FAILURE") or "").strip().lower() == "true":
            log.warning("ExportAPI.start_export: EHI_FORCE_FAILURE is set — failing on purpose")
            message = "Simulated export failure (EHI_FORCE_FAILURE is enabled)."
            self._record_failure(patient_id, batch_id, message, staff_id)
            return [_error(message, HTTPStatus.BAD_GATEWAY)]

        try:
            client = self._build_client()
            job_id = client.start_export(patient_id)
        except EHIConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except EHIExportError as exc:
            log.error("ExportAPI.start_export failed for %s: %s", patient_id, exc)
            self._record_failure(patient_id, batch_id, str(exc), staff_id)
            return [_error(str(exc), HTTPStatus.BAD_GATEWAY)]

        # Best-effort: record the job so it survives a refresh and the patient
        # list can show its status. A persistence failure must not fail the
        # export the user just started, so we log and continue.
        try:
            ExportJobService.record_started(patient_id, job_id, batch_id, staff_id)
        except Exception as exc:  # noqa: BLE001 - audit write is non-critical
            log.error("ExportAPI.start_export: failed to record job %s: %s", job_id, exc)

        return [JSONResponse({"patient_id": patient_id, "job_id": job_id}, status_code=HTTPStatus.OK)]

    @api.get("/export/status")
    def export_status(self) -> list[Response | Effect]:
        """Poll a bulkstatus job and report its progress."""
        job_id = (self.request.query_params.get("job_id") or "").strip()
        if not job_id:
            return [_error("job_id is required", HTTPStatus.BAD_REQUEST)]

        try:
            client = self._build_client()
            status = client.get_status(job_id)
        except EHIConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except EHIExportError as exc:
            log.error("ExportAPI.export_status failed for %s: %s", job_id, exc)
            return [_error(str(exc), HTTPStatus.BAD_GATEWAY)]

        # Best-effort: keep the persisted record in sync with each poll.
        try:
            ExportJobService.update_status(
                job_id, status["status"], output=status.get("output")
            )
        except Exception as exc:  # noqa: BLE001 - audit write is non-critical
            log.error("ExportAPI.export_status: failed to update job %s: %s", job_id, exc)

        return [
            JSONResponse(
                {
                    "job_id": job_id,
                    "status": status["status"],
                    "progress": status.get("progress", ""),
                    "ready": status["status"] == "complete",
                    "file_count": len(status.get("output", [])),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/export/bundle")
    def export_bundle(self) -> list[Response | Effect]:
        """Download all NDJSON files for a completed job, merged into one Bundle.

        Re-polls bulkstatus to obtain the current output URLs (the browser only
        holds the job id), then streams back the merged JSON. The browser zips
        these per-patient bundles together client-side.
        """
        params = self.request.query_params
        job_id = (params.get("job_id") or "").strip()
        patient_id = (params.get("patient_id") or "").strip()
        if not job_id or not patient_id:
            return [_error("job_id and patient_id are required", HTTPStatus.BAD_REQUEST)]

        try:
            client = self._build_client()
            status = client.get_status(job_id)
            if status["status"] != "complete":
                return [
                    _error(
                        f"job {job_id} is not complete (status: {status['status']})",
                        HTTPStatus.CONFLICT,
                    )
                ]
            bundle = client.build_patient_bundle(patient_id, status["output"])
        except EHIConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except EHIExportError as exc:
            log.error("ExportAPI.export_bundle failed for %s/%s: %s", patient_id, job_id, exc)
            return [_error(str(exc), HTTPStatus.BAD_GATEWAY)]

        # Best-effort: snapshot the completed job's output URLs for the record.
        try:
            ExportJobService.update_status(job_id, "complete", output=status["output"])
        except Exception as exc:  # noqa: BLE001 - audit write is non-critical
            log.error("ExportAPI.export_bundle: failed to update job %s: %s", job_id, exc)

        return [JSONResponse(bundle, status_code=HTTPStatus.OK)]

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _record_failure(patient_id: str, batch_id: str, message: str, staff_id: str = "") -> None:
        """Best-effort: persist a start-time failure so it shows on the main page."""
        try:
            ExportJobService.record_failed(patient_id, batch_id, message, staff_id)
        except Exception as exc:  # noqa: BLE001 - audit write is non-critical
            log.error("ExportAPI: failed to record failed export for %s: %s", patient_id, exc)

    def _build_client(self) -> EHIExportClient:
        """Construct the EHI client from secrets.

        Raises ``EHIConfigError`` if credentials are missing, or ``EHIExportError``
        with a human-readable message (including the OAuth error body) if the
        client-credentials token request is rejected — so the UI can show why.
        """
        client_id = self.secrets.get("CANVAS_FHIR_CLIENT_ID")
        client_secret = self.secrets.get("CANVAS_FHIR_CLIENT_SECRET")
        if not client_id or not client_secret:
            log.error("ExportAPI: CANVAS_FHIR_CLIENT_ID / CANVAS_FHIR_CLIENT_SECRET not configured")
            raise EHIConfigError(
                "EHI export credentials are not configured. Set CANVAS_FHIR_CLIENT_ID and "
                "CANVAS_FHIR_CLIENT_SECRET on the plugin configuration page."
            )
        try:
            # Construction performs the OAuth client-credentials token fetch.
            return EHIExportClient(client_id, client_secret)
        except Exception as exc:
            # The SDK raises requests' HTTPError on a rejected token request, but the
            # plugin sandbox forbids importing requests.exceptions — so detect an HTTP
            # error by its `.response` attribute instead. Anything without one is an
            # unexpected error and is re-raised so its traceback reaches the logs.
            response = getattr(exc, "response", None)
            if response is None:
                raise
            status = getattr(response, "status_code", None)
            body = (getattr(response, "text", "") or "")[:200]
            status_part = f" ({status})" if status else ""
            body_part = f" Response: {body}" if body else ""
            log.error("ExportAPI: FHIR token request failed%s: %s", status_part, body)
            raise EHIExportError(
                f"Could not authenticate to the Canvas FHIR API{status_part}. Verify the OAuth "
                "application uses the client-credentials grant (Confidential client type) and that "
                f"the client id/secret are correct.{body_part}"
            ) from exc


# ── module helpers ───────────────────────────────────────────────────────────


def _error(message: str, status_code: HTTPStatus) -> JSONResponse:
    """Build a uniform JSON error response."""
    return JSONResponse({"error": message}, status_code=status_code)


def _ndjson_filename(job) -> str:
    """A safe ``<Last>_<First>_<id>.ndjson`` download filename for a job's patient."""
    import re

    patient = job.patient
    last = (getattr(patient, "last_name", "") or "").strip()
    first = (getattr(patient, "first_name", "") or "").strip()
    base = f"{last}_{first}_{patient.id}".strip("_")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")[:120] or str(patient.id)
    return f"{base}.ndjson"


def _parse_int(
    value: str | None,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Parse an int query param, clamping to [minimum, maximum] and falling back to default."""
    try:
        parsed = int((value or "").strip())
    except (ValueError, AttributeError):
        return default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed
