"""ExportPoller — background CronTask that advances in-progress EHI exports.

This is what makes the export fire-and-forget: once "Export selected" kicks off
the per-patient ``$export`` jobs and records them, this task polls ``bulkstatus``
for each in-progress job on a schedule and marks them complete (saving the file
URLs) — so the user can close the workspace and check back later.

The cadence is configurable via the ``EHI_POLL_SCHEDULE`` variable (a cron
expression, default ``*/5 * * * *``). Because ``CronTask`` evaluates
``self.SCHEDULE`` at runtime, exposing it as a property lets the schedule change
from the config page with no redeploy. The poller only polls status — it never
downloads the (potentially large) NDJSON; files are fetched on demand at
download time.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from ehi_export_tool.services.export_jobs import ExportJobService
from ehi_export_tool.services.preparation import PreparationResult, prepare_job
from ehi_export_tool.services.storage import ExportStorage
from ehi_export_tool.utils.fhir_client import EHIExportClient, EHIExportError

_DEFAULT_SCHEDULE = "*/5 * * * *"
# Bound the work per tick so a large backlog can't make one run hang.
_MAX_PER_TICK = 50
# Preparing a patient's JSON downloads ~31 NDJSON files + an S3 upload, so cap
# how many we prepare per tick to keep each run bounded.
_PREP_PER_TICK = 5
# Throttle the server-side kickoff. Because $export is respond-async (the start
# returns immediately), the meaningful limit is how many jobs are concurrently
# *in-progress* on Canvas (= concurrent server-side file generation), not how
# fast we start them. Both are configurable so load can be tuned per instance.
_DEFAULT_MAX_IN_FLIGHT = 10
_DEFAULT_START_PER_TICK = 10


def _int_secret(secrets: dict, name: str, default: int) -> int:
    """Parse a positive int from a variable, falling back to ``default``."""
    try:
        value = int((secrets.get(name) or "").strip())
        return value if value >= 0 else default
    except (ValueError, AttributeError):
        return default


class ExportPoller(CronTask):
    """Advances in-progress export jobs to completion in the background."""

    @property
    def SCHEDULE(self) -> str:  # noqa: N802 - overrides CronTask.SCHEDULE class attr
        """Cron expression from the EHI_POLL_SCHEDULE variable.

        Falls back to the default if the variable is unset or isn't a 5-field
        cron expression. (The SDK's CronTask parses it with cron_converter, which
        the plugin sandbox forbids us from importing directly — so we do a light
        structural check here rather than fully validating.)
        """
        configured = (self.secrets.get("EHI_POLL_SCHEDULE") or "").strip()
        if not configured:
            return _DEFAULT_SCHEDULE
        if len(configured.split()) != 5:
            log.warning(
                "ExportPoller: EHI_POLL_SCHEDULE %r is not a 5-field cron expression; "
                "using default %s",
                configured,
                _DEFAULT_SCHEDULE,
            )
            return _DEFAULT_SCHEDULE
        return configured

    def execute(self) -> list[Effect]:
        """Start queued jobs (throttled), advance in-progress ones, prepare S3 files."""
        client_id = self.secrets.get("CANVAS_FHIR_CLIENT_ID")
        client_secret = self.secrets.get("CANVAS_FHIR_CLIENT_SECRET")
        if not client_id or not client_secret:
            # Nothing to do until credentials are configured.
            return []

        # Decide how many queued jobs we may start this tick, bounded by the
        # global in-flight cap (concurrent server-side generation on Canvas).
        max_in_flight = _int_secret(self.secrets, "EHI_MAX_IN_FLIGHT", _DEFAULT_MAX_IN_FLIGHT)
        start_per_tick = _int_secret(self.secrets, "EHI_START_PER_TICK", _DEFAULT_START_PER_TICK)
        in_flight = ExportJobService.count_in_flight()
        slots = max(0, min(start_per_tick, max_in_flight - in_flight))
        to_start = ExportJobService.queued_jobs(limit=slots)

        in_progress = ExportJobService.in_progress_jobs(limit=_MAX_PER_TICK)
        storage = ExportStorage.from_secrets(self.secrets)
        to_prepare = (
            ExportJobService.complete_jobs_without_s3(limit=_PREP_PER_TICK)
            if storage is not None
            else []
        )
        if not to_start and not in_progress and not to_prepare:
            return []

        client = EHIExportClient(client_id, client_secret)

        # 0) Start queued jobs up to the available in-flight slots.
        started = 0
        for job in to_start:
            try:
                job_id = client.start_export(str(job.patient.id))
            except EHIExportError as exc:
                log.warning("ExportPoller: kickoff failed for patient %s: %s", job.patient.id, exc)
                ExportJobService.mark_failed_job(job, str(exc))
                continue
            ExportJobService.mark_started(job, job_id)
            started += 1

        # 1) Advance in-progress jobs by polling bulkstatus.
        advanced = 0
        for job in in_progress:
            try:
                status = client.get_status(job.job_id)
            except EHIExportError as exc:
                log.warning("ExportPoller: status poll failed for job %s: %s", job.job_id, exc)
                continue
            errors = status.get("errors") or []
            ExportJobService.update_status(
                job.job_id,
                status["status"],
                output=status.get("output"),
                error="; ".join(str(e) for e in errors) if errors else "",
            )
            if status["status"] != "in-progress":
                advanced += 1

        # 2) Upload prepared JSON to S3 for completed jobs not yet stored.
        uploaded = 0
        if storage is not None:
            for job in to_prepare:
                try:
                    result = prepare_job(client, storage, job)
                except EHIExportError as exc:
                    log.warning("ExportPoller: prepare failed for job %s: %s", job.job_id, exc)
                    continue
                if result.status == PreparationResult.READY:
                    uploaded += 1

        if started or advanced or uploaded:
            log.info(
                "ExportPoller: started %d, advanced %d, uploaded %d (in-flight was %d/%d)",
                started, advanced, uploaded, in_flight, max_in_flight,
            )
        return []
