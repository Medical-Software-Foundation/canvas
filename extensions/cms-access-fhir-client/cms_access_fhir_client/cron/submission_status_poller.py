"""CronTask that polls outstanding CMS submission-status URLs.

Runs every minute. For each ACCESSAlignment with submission_state=in-progress,
polls the stored submission_status_url using exponential backoff:

    interval = min(2^poll_attempts minutes, MAX_INTERVAL_MINUTES)

Abandons a submission after MAX_POLL_ATTEMPTS attempts and marks it as error.
"""
from datetime import datetime, timezone, timedelta

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from cms_access_fhir_client.cms_client import poll_submission_status
from cms_access_fhir_client.models import ACCESSAlignment

# Backoff: 1m, 2m, 4m, 8m, 16m, max 32m
MAX_INTERVAL_MINUTES = 32
MAX_POLL_ATTEMPTS = 10  # ~32m * 10 ≈ abandon after ~5 hours


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_poll_due(alignment: ACCESSAlignment) -> datetime:
    """Return the earliest UTC time at which we should next poll this alignment."""
    interval_minutes = min(2 ** alignment.poll_attempts, MAX_INTERVAL_MINUTES)
    base = alignment.last_poll_at or alignment.submission_started_at or _utcnow()
    return base + timedelta(minutes=interval_minutes)


class SubmissionStatusPoller(CronTask):
    """Poll outstanding CMS async submissions and update alignment state."""

    SCHEDULE = "* * * * *"  # every minute; backoff logic gates actual HTTP calls

    def execute(self) -> list[Effect]:
        now = _utcnow()
        pending = ACCESSAlignment.objects.filter(
            submission_state=ACCESSAlignment.SUB_STATE_IN_PROGRESS,
        )

        for alignment in pending:
            if not alignment.submission_status_url:
                log.warning(
                    f"[cms-access] ACCESSAlignment dbid={alignment.dbid} has "
                    "submission_state=in-progress but no submission_status_url — skipping"
                )
                continue

            if alignment.poll_attempts >= MAX_POLL_ATTEMPTS:
                log.error(
                    f"[cms-access] Abandoning poll for ACCESSAlignment dbid={alignment.dbid} "
                    f"after {MAX_POLL_ATTEMPTS} attempts"
                )
                alignment.submission_state = ACCESSAlignment.SUB_STATE_ERROR
                alignment.status = ACCESSAlignment.STATUS_ERROR
                alignment.save()
                continue

            if _next_poll_due(alignment) > now:
                # Not yet time to poll this one
                continue

            log.info(
                f"[cms-access] Polling submission_status_url for "
                f"ACCESSAlignment dbid={alignment.dbid}, "
                f"attempt={alignment.poll_attempts + 1}"
            )

            try:
                result = poll_submission_status(self.secrets, alignment.submission_status_url)
            except RuntimeError as exc:
                log.error(f"[cms-access] Poll HTTP error for dbid={alignment.dbid}: {exc}")
                alignment.poll_attempts = alignment.poll_attempts + 1
                alignment.last_poll_at = now
                alignment.save()
                continue

            alignment.poll_attempts = alignment.poll_attempts + 1
            alignment.last_poll_at = now
            _apply_poll_result(alignment, result)
            alignment.save()

        return []


def _apply_poll_result(alignment: ACCESSAlignment, result: dict) -> None:
    """Update alignment fields based on the SubmissionStatus response."""
    status = _extract_submission_status(result)

    if status == "completed":
        alignment.submission_state = ACCESSAlignment.SUB_STATE_COMPLETED
        alignment.submission_status_url = ""
        _apply_completed_result(alignment, result)
        log.info(f"[cms-access] Submission completed for ACCESSAlignment dbid={alignment.dbid}")

    elif status == "error":
        alignment.submission_state = ACCESSAlignment.SUB_STATE_ERROR
        alignment.status = ACCESSAlignment.STATUS_ERROR
        log.error(
            f"[cms-access] Submission errored for ACCESSAlignment dbid={alignment.dbid}: "
            f"{result}"
        )
    # in-progress: leave as-is, will poll again


def _apply_completed_result(alignment: ACCESSAlignment, result: dict) -> None:
    """Extract final state from a completed submission-status response."""
    op = alignment.submission_op

    if op == ACCESSAlignment.SUB_OP_ELIGIBILITY:
        for param in result.get("parameter", []):
            if param.get("name") == "status":
                code = param.get("valueCode", "")
                alignment.status = code if code else ACCESSAlignment.STATUS_ERROR
        from datetime import datetime, timezone
        alignment.last_eligibility_check_at = datetime.now(timezone.utc)

    elif op == ACCESSAlignment.SUB_OP_ALIGN:
        alignment.status = ACCESSAlignment.STATUS_ALIGNED
        for param in result.get("parameter", []):
            if param.get("name") == "alignmentId":
                alignment.alignment_id = param.get("valueString", "")
            elif param.get("name") == "careStartDate":
                from datetime import date
                try:
                    alignment.care_start_date = date.fromisoformat(
                        param.get("valueDate", "")
                    )
                except ValueError:
                    pass

    elif op == ACCESSAlignment.SUB_OP_UNALIGN:
        alignment.status = ACCESSAlignment.STATUS_UNALIGNED


def _extract_submission_status(result: dict) -> str:
    """Extract the submission status code from a SubmissionStatus Parameters resource."""
    for param in result.get("parameter", []):
        if param.get("name") == "status":
            return param.get("valueCode", "in-progress")
    return "in-progress"
