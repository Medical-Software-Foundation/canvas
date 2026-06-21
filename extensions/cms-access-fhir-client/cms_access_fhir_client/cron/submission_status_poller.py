"""CronTask that polls outstanding CMS submission-status URLs.

Runs every minute. For each ACCESSAlignment with submission_state=in-progress,
polls the stored submission_status_url using exponential backoff:

    interval = min(2^poll_attempts minutes, MAX_INTERVAL_MINUTES)

Abandons a submission after MAX_POLL_ATTEMPTS attempts and marks it as error.

Per the CMS User Guide, the poll endpoint signals state via HTTP status code:
    202 + empty body + X-Progress header  → still processing
    200 + Parameters body                 → completed successfully
    200 + OperationOutcome body           → completed with errors
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
                if alignment.submission_op == ACCESSAlignment.SUB_OP_REPORT_DATA:
                    from datetime import datetime, timezone
                    alignment.report_result = "poll abandoned (timed out)"
                    alignment.report_result_at = datetime.now(timezone.utc)
                else:
                    alignment.status = ACCESSAlignment.STATUS_ERROR
                alignment.save()
                from cms_access_fhir_client.models import ACCESSOperationLog
                from cms_access_fhir_client.operation_log import record_operation_event

                record_operation_event(
                    patient=alignment.patient,
                    track=alignment.track,
                    operation=alignment.submission_op,
                    phase=ACCESSOperationLog.PHASE_ERROR,
                    detail=f"poll abandoned after {MAX_POLL_ATTEMPTS} attempts",
                )
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
                status_code, body = poll_submission_status(self.secrets, alignment.submission_status_url)
            except RuntimeError as exc:
                log.error(f"[cms-access] Poll HTTP error for dbid={alignment.dbid}: {exc}")
                alignment.poll_attempts = alignment.poll_attempts + 1
                alignment.last_poll_at = now
                alignment.save()
                continue

            alignment.poll_attempts = alignment.poll_attempts + 1
            alignment.last_poll_at = now
            _apply_poll_result(alignment, status_code, body)
            alignment.save()

        return []


def _apply_poll_result(alignment: ACCESSAlignment, status_code: int, body: dict) -> None:
    """Update alignment fields based on HTTP status code and response body.

    Per the User Guide:
    - 202               → in-progress, leave state unchanged
    - 200 + Parameters  → completed successfully
    - 200 + OperationOutcome → completed with errors
    """
    if status_code == 202:
        # Still processing — leave submission_state as-is, will retry next run
        return

    if status_code >= 400:
        # Terminal client error per OM v0.9.11 polling guidance (e.g. 404 submission-not-
        # found). Stop polling, surface the detail, and keep report-data results off the
        # alignment lifecycle status.
        issues = body.get("issue", []) if isinstance(body, dict) else []
        detail = (issues[0].get("details", {}).get("text") if issues else None) or f"HTTP {status_code}"
        alignment.submission_state = ACCESSAlignment.SUB_STATE_ERROR
        alignment.submission_status_url = ""  # stop polling this submission
        if alignment.submission_op == ACCESSAlignment.SUB_OP_REPORT_DATA:
            from datetime import datetime, timezone
            alignment.report_result = detail
            alignment.report_result_at = datetime.now(timezone.utc)
        else:
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = detail
        log.error(
            f"[cms-access] $submission-status HTTP {status_code} (terminal) for "
            f"ACCESSAlignment dbid={alignment.dbid}: {detail}"
        )
        from cms_access_fhir_client.models import ACCESSOperationLog
        from cms_access_fhir_client.operation_log import record_operation_event

        record_operation_event(
            patient=alignment.patient,
            track=alignment.track,
            operation=alignment.submission_op,
            phase=ACCESSOperationLog.PHASE_ERROR,
            detail=detail,
            http_status=status_code,
        )
        return

    # status_code == 200
    resource_type = body.get("resourceType")

    if resource_type == "OperationOutcome":
        issues = body.get("issue", [])
        detail = issues[0].get("details", {}).get("text", "Unknown error") if issues else "Unknown error"
        alignment.submission_state = ACCESSAlignment.SUB_STATE_ERROR
        if alignment.submission_op == ACCESSAlignment.SUB_OP_REPORT_DATA:
            # A report-data failure is a reporting outcome, not an alignment-state change.
            from datetime import datetime, timezone
            alignment.report_result = detail
            alignment.report_result_at = datetime.now(timezone.utc)
        else:
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = detail
        log.error(
            f"[cms-access] Submission OperationOutcome error for "
            f"ACCESSAlignment dbid={alignment.dbid}: {detail}"
        )
        from cms_access_fhir_client.models import ACCESSOperationLog
        from cms_access_fhir_client.operation_log import record_operation_event

        record_operation_event(
            patient=alignment.patient,
            track=alignment.track,
            operation=alignment.submission_op,
            phase=ACCESSOperationLog.PHASE_ERROR,
            detail=detail,
            http_status=200,
        )
        return

    if resource_type == "Parameters":
        alignment.submission_state = ACCESSAlignment.SUB_STATE_COMPLETED
        alignment.submission_status_url = ""
        _apply_completed_result(alignment, body)
        log.info(f"[cms-access] Submission completed for ACCESSAlignment dbid={alignment.dbid}")
        return

    # Unexpected shape — treat as error
    log.error(
        f"[cms-access] Unexpected poll response shape for "
        f"ACCESSAlignment dbid={alignment.dbid}: resourceType={resource_type!r}"
    )
    alignment.submission_state = ACCESSAlignment.SUB_STATE_ERROR
    alignment.submission_status_url = ""  # stop polling
    if alignment.submission_op == ACCESSAlignment.SUB_OP_REPORT_DATA:
        from datetime import datetime, timezone
        alignment.report_result = "unexpected response shape"
        alignment.report_result_at = datetime.now(timezone.utc)
    else:
        alignment.status = ACCESSAlignment.STATUS_ERROR


def _apply_completed_result(alignment: ACCESSAlignment, result: dict) -> None:
    """Extract final state from a completed submission-status Parameters response.

    Per OM v0.9.11, the polling response uses:
        {"name": "result", "valueCodeableConcept": {"coding": [{"code": "eligible", ...}]}}

    The raw CMS code is persisted in alignment.status_message for banner display.
    """
    op = alignment.submission_op
    raw_code = ""

    if op == ACCESSAlignment.SUB_OP_ELIGIBILITY:
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        status, raw_code = _extract_eligibility_status(result)
        from datetime import datetime, timezone
        alignment.last_eligibility_check_at = datetime.now(timezone.utc)
        # Re-checking eligibility on an already-aligned patient returns already-aligned; that
        # must NOT downgrade a patient who is aligned to us (it would hide the Unalign action).
        if not (alignment.status == ACCESSAlignment.STATUS_ALIGNED
                and status == ACCESSAlignment.STATUS_ALREADY_ALIGNED):
            alignment.status = status
            alignment.status_message = raw_code

    elif op == ACCESSAlignment.SUB_OP_ALIGN:
        from cms_access_fhir_client.api.operations_api import (
            _extract_alignment_result,
            _map_alignment_code,
        )

        raw_code = _extract_alignment_result(result)
        alignment.status = _map_alignment_code(raw_code)
        alignment.status_message = raw_code
        # Only a successful alignment carries an alignmentId / careStartDate.
        if alignment.status == ACCESSAlignment.STATUS_ALIGNED:
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
        from cms_access_fhir_client.api.operations_api import (
            _extract_unalignment_result,
            _map_unalignment_code,
        )

        raw_code = _extract_unalignment_result(result)
        alignment.status = _map_unalignment_code(raw_code)
        alignment.status_message = raw_code

    elif op == ACCESSAlignment.SUB_OP_REPORT_DATA:
        # $report-data is a reporting operation, not an alignment-state transition
        # (OM v0.9.11 p.77). Its result comes from a separate code system
        # (ACCESSReportDataResultVS). Record it in report_result and NEVER touch
        # alignment.status / status_message — doing so would clobber the alignment
        # lifecycle (e.g. a still-pending unalignment that OM p.70 says must persist
        # until finalized).
        from datetime import datetime, timezone
        raw_code = ""
        for param in result.get("parameter", []):
            if param.get("name") == "result":
                codings = param.get("valueCodeableConcept", {}).get("coding", [])
                if codings:
                    raw_code = codings[0].get("code", "")
        alignment.report_result = raw_code or "(no result code)"
        alignment.report_result_at = datetime.now(timezone.utc)

    # Append an immutable audit row so the per-operation result is never lost when a later
    # operation overwrites the alignment row's status.
    from cms_access_fhir_client.models import ACCESSOperationLog
    from cms_access_fhir_client.operation_log import record_operation_event

    record_operation_event(
        patient=alignment.patient,
        track=alignment.track,
        operation=op,
        phase=ACCESSOperationLog.PHASE_RESULT,
        result_code=raw_code,
        http_status=200,
    )


def _extract_submission_status(result: dict) -> str:
    """Extract the submission status code from a SubmissionStatus Parameters resource.

    Retained for backwards compatibility with any callers; new code should use
    _apply_poll_result() which branches on HTTP status code instead.
    """
    for param in result.get("parameter", []):
        if param.get("name") == "status":
            return param.get("valueCode", "in-progress")
    return "in-progress"
