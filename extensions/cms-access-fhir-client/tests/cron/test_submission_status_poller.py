"""Tests for SubmissionStatusPoller — backoff schedule, state transitions, abandonment.

Polling now branches on HTTP status code (not body content):
- 202 → in-progress, leave state unchanged
- 200 + Parameters → completed successfully
- 200 + OperationOutcome → completed with errors, store detail text
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call, patch


def _utcnow():
    return datetime.now(timezone.utc)


def _make_alignment(
    dbid=1,
    submission_state="in-progress",
    submission_status_url="https://api.cms.gov/status/123",
    submission_op="align",
    poll_attempts=0,
    last_poll_at=None,
    submission_started_at=None,
):
    alignment = MagicMock()
    alignment.dbid = dbid
    alignment.submission_state = submission_state
    alignment.submission_status_url = submission_status_url
    alignment.submission_op = submission_op
    alignment.poll_attempts = poll_attempts
    alignment.last_poll_at = last_poll_at
    alignment.submission_started_at = submission_started_at
    return alignment


def _make_poller(secrets=None):
    from cms_access_fhir_client.cron.submission_status_poller import SubmissionStatusPoller
    poller = SubmissionStatusPoller.__new__(SubmissionStatusPoller)
    poller.secrets = secrets or {
        "ACCESS_OAUTH_CLIENT_ID": "cid",
        "ACCESS_OAUTH_CLIENT_SECRET": "csec",
        "ACCESS_OAUTH_TOKEN_URL": "https://auth/token",
        "ACCESS_BASE_URL": "https://cms.gov/fhir",
    }
    return poller


# poll_submission_status now returns (status_code, body)
def _make_poll_result(status_code: int, body: dict) -> tuple:
    return (status_code, body)


class TestSubmissionStatusPollerBackoff:
    def test_skips_alignment_not_yet_due(self):
        """If next poll time is in the future, alignment should be skipped."""
        poller = _make_poller()
        now = _utcnow()

        # poll_attempts=0 → interval=1 min; last_poll_at = 30 sec ago → not due yet
        alignment = _make_alignment(
            poll_attempts=0,
            last_poll_at=now - timedelta(seconds=30),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status"
            ) as mock_poll,
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            effects = poller.execute()

        assert effects == []
        assert mock_poll.mock_calls == []

    def test_polls_alignment_when_due(self):
        """If next poll time is in the past, alignment should be polled."""
        poller = _make_poller()
        now = _utcnow()

        # poll_attempts=0 → interval=1 min; last_poll_at = 90 sec ago → due
        alignment = _make_alignment(
            poll_attempts=0,
            last_poll_at=now - timedelta(seconds=90),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=_make_poll_result(200, {
                    "resourceType": "Parameters",
                    "parameter": [
                        {"name": "alignmentId", "valueString": "align-xyz"},
                    ],
                }),
            ) as mock_poll,
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            effects = poller.execute()

        assert effects == []
        assert mock_poll.mock_calls == [
            call(poller.secrets, "https://api.cms.gov/status/123")
        ]

    def test_backoff_doubles_each_attempt(self):
        """Verify interval = min(2^n, 32) minutes for n=0..5."""
        from cms_access_fhir_client.cron.submission_status_poller import _next_poll_due

        now = _utcnow()
        base = now - timedelta(hours=1)  # far in the past

        for attempts, expected_minutes in [(0, 1), (1, 2), (2, 4), (3, 8), (4, 16), (5, 32)]:
            alignment = _make_alignment(
                poll_attempts=attempts,
                last_poll_at=base,
            )
            due = _next_poll_due(alignment)
            delta = due - base
            actual_minutes = delta.total_seconds() / 60
            assert actual_minutes == expected_minutes, (
                f"poll_attempts={attempts}: expected {expected_minutes}m, got {actual_minutes}m"
            )

    def test_backoff_caps_at_32_minutes(self):
        from cms_access_fhir_client.cron.submission_status_poller import _next_poll_due
        base = _utcnow() - timedelta(hours=1)

        for attempts in [5, 6, 7, 10]:
            alignment = _make_alignment(poll_attempts=attempts, last_poll_at=base)
            due = _next_poll_due(alignment)
            delta = due - base
            actual_minutes = delta.total_seconds() / 60
            assert actual_minutes == 32, (
                f"poll_attempts={attempts}: should cap at 32m, got {actual_minutes}m"
            )


class TestSubmissionStatusPollerStateTransitions:
    def test_202_leaves_state_as_in_progress(self):
        """HTTP 202 → still processing; submission_state must not change."""
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="align",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=_make_poll_result(202, {}),
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        # State unchanged — 202 means still in flight
        assert alignment.submission_state == "in-progress"
        assert alignment.poll_attempts == 1

    def test_200_parameters_marks_align_completed(self):
        """HTTP 200 + Parameters → completed; extract alignmentId and careStartDate."""
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="align",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=_make_poll_result(200, {
                    "resourceType": "Parameters",
                    "parameter": [
                        {"name": "result", "valueCodeableConcept": {"coding": [{"code": "aligned"}]}},
                        {"name": "alignmentId", "valueString": "align-new-id"},
                        {"name": "careStartDate", "valueDate": "2026-06-01"},
                    ],
                }),
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.submission_state == "completed"
        assert alignment.status == "aligned"
        assert alignment.alignment_id == "align-new-id"

    def test_200_parameters_marks_unalign_completed(self):
        """HTTP 200 + Parameters → unaligned for unalign op."""
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="unalign",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=_make_poll_result(200, {
                    "resourceType": "Parameters",
                    "parameter": [
                        {"name": "result", "valueCodeableConcept": {"coding": [{"code": "unaligned"}]}},
                    ],
                }),
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.status == "unaligned"
        assert alignment.submission_state == "completed"

    def test_200_operation_outcome_marks_error_with_detail_text(self):
        """HTTP 200 + OperationOutcome → error; detail text stored in status_message."""
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="align",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=_make_poll_result(200, {
                    "resourceType": "OperationOutcome",
                    "issue": [
                        {
                            "severity": "error",
                            "code": "invalid",
                            "details": {"text": "Participant not enrolled in ACCESS"},
                        }
                    ],
                }),
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.submission_state == "error"
        assert alignment.status == "error"
        assert alignment.status_message == "Participant not enrolled in ACCESS"

    def test_200_operation_outcome_empty_issues_uses_unknown_error(self):
        """OperationOutcome with empty issues list → status_message = 'Unknown error'."""
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="align",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=_make_poll_result(200, {
                    "resourceType": "OperationOutcome",
                    "issue": [],
                }),
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.submission_state == "error"
        assert alignment.status_message == "Unknown error"

    def test_http_error_increments_attempts_without_state_change(self):
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            poll_attempts=2,
            last_poll_at=now - timedelta(minutes=10),
        )
        original_state = alignment.submission_state

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                side_effect=RuntimeError("HTTP 503"),
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.poll_attempts == 3
        assert alignment.last_poll_at == now
        assert alignment.submission_state == original_state  # unchanged

    def test_abandons_after_max_attempts(self):
        from cms_access_fhir_client.cron.submission_status_poller import MAX_POLL_ATTEMPTS
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(poll_attempts=MAX_POLL_ATTEMPTS)

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status"
            ) as mock_poll,
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.submission_state == "error"
        assert alignment.status == "error"
        assert mock_poll.mock_calls == []

    def test_skips_alignment_with_no_status_url(self):
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_status_url="",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=5),
        )

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status"
            ) as mock_poll,
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert mock_poll.mock_calls == []
        assert alignment.submission_state == "in-progress"


class TestApplyPollResult:
    """Unit tests for _apply_poll_result directly."""

    def test_202_is_noop(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        alignment = MagicMock()
        alignment.submission_state = "in-progress"

        _apply_poll_result(alignment, 202, {})

        # No attribute write should change submission_state
        assert alignment.submission_state == "in-progress"

    def test_200_parameters_sets_completed(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN

        _apply_poll_result(alignment, 200, {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueCodeableConcept": {"coding": [{"code": "aligned"}]}},
                {"name": "alignmentId", "valueString": "align-done"},
            ],
        })

        assert alignment.submission_state == "completed"
        assert alignment.alignment_id == "align-done"

    def test_align_not_aligned_diagnoses_maps_to_ineligible(self):
        """A completed $align with a not-aligned-* result is not an error — maps to ineligible."""
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN

        _apply_poll_result(alignment, 200, {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueCodeableConcept": {"coding": [{"code": "not-aligned-diagnoses"}]}},
            ],
        })

        assert alignment.submission_state == "completed"
        assert alignment.status == ACCESSAlignment.STATUS_INELIGIBLE
        assert alignment.status_message == "not-aligned-diagnoses"

    def test_align_already_aligned_maps_to_already_aligned(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN

        _apply_poll_result(alignment, 200, {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueCodeableConcept": {"coding": [{"code": "not-aligned-already-aligned"}]}},
            ],
        })

        assert alignment.status == ACCESSAlignment.STATUS_ALREADY_ALIGNED

    def test_unalign_patient_not_aligned_maps_to_error(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_UNALIGN

        _apply_poll_result(alignment, 200, {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueCodeableConcept": {"coding": [{"code": "patient-not-aligned"}]}},
            ],
        })

        assert alignment.status == ACCESSAlignment.STATUS_ERROR
        assert alignment.status_message == "patient-not-aligned"

    def test_unalign_pending_maps_to_pending(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_UNALIGN

        _apply_poll_result(alignment, 200, {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueCodeableConcept": {"coding": [{"code": "unalignment-pending"}]}},
            ],
        })

        assert alignment.status == ACCESSAlignment.STATUS_PENDING

    def test_200_operation_outcome_sets_error_and_message(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result

        alignment = MagicMock()

        _apply_poll_result(alignment, 200, {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "details": {"text": "Bad request"}}],
        })

        assert alignment.submission_state == "error"
        assert alignment.status == "error"
        assert alignment.status_message == "Bad request"

    def test_4xx_terminal_for_report_data_keeps_alignment_status(self):
        """A 4xx on $submission-status is terminal: stop polling, record the reporting
        error in report_result, and leave the alignment lifecycle status untouched."""
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_REPORT_DATA
        alignment.status = "already-aligned"
        alignment.status_message = "not-aligned-already-aligned"

        _apply_poll_result(alignment, 400, {
            "resourceType": "OperationOutcome",
            "issue": [{"details": {"text": "Submission rejected"}}],
        })

        assert alignment.submission_state == "error"
        assert alignment.submission_status_url == ""   # stop polling
        assert alignment.report_result == "Submission rejected"
        assert alignment.status == "already-aligned"   # lifecycle untouched
        assert alignment.status_message == "not-aligned-already-aligned"

    def test_4xx_terminal_for_alignment_op_sets_error_status(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN

        _apply_poll_result(alignment, 404, {})  # no body → falls back to "HTTP 404"

        assert alignment.submission_state == "error"
        assert alignment.submission_status_url == ""
        assert alignment.status == "error"
        assert "404" in alignment.status_message

    def test_unexpected_resource_type_sets_error(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result

        alignment = MagicMock()

        _apply_poll_result(alignment, 200, {"resourceType": "Bundle"})

        assert alignment.submission_state == "error"
        assert alignment.status == "error"


class TestApplyCompletedResult:
    def test_apply_completed_eligibility_uses_status_code(self):
        from cms_access_fhir_client.cron.submission_status_poller import _apply_completed_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_ELIGIBILITY

        result = {"parameter": [{"name": "status", "valueCode": "eligible"}]}
        _apply_completed_result(alignment, result)

        assert alignment.status == "eligible"

    def test_apply_completed_eligibility_handles_bad_date(self):
        """careStartDate with invalid date string is silently ignored."""
        from cms_access_fhir_client.cron.submission_status_poller import _apply_completed_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN

        result = {
            "parameter": [
                {"name": "result", "valueCodeableConcept": {"coding": [{"code": "aligned"}]}},
                {"name": "alignmentId", "valueString": "align-xyz"},
                {"name": "careStartDate", "valueDate": "not-a-date"},  # invalid
            ]
        }
        # Should not raise — invalid date is silently skipped
        _apply_completed_result(alignment, result)
        assert alignment.status == "aligned"
        assert alignment.alignment_id == "align-xyz"

    def test_report_data_writes_report_result_not_status(self):
        """$report-data result lands in report_result and must NOT touch the alignment
        lifecycle (status / status_message) — OM v0.9.11 p.77."""
        from cms_access_fhir_client.cron.submission_status_poller import _apply_completed_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_REPORT_DATA
        alignment.status = "pending"
        alignment.status_message = "unalignment-pending"

        _apply_completed_result(alignment, {
            "parameter": [
                {"name": "result", "valueCodeableConcept": {"coding": [{"code": "success"}]}},
            ],
        })

        assert alignment.report_result == "success"
        assert alignment.report_result_at is not None
        # Alignment lifecycle preserved.
        assert alignment.status == "pending"
        assert alignment.status_message == "unalignment-pending"

    def test_report_data_operation_outcome_does_not_clobber_status(self):
        """A report-data poll returning OperationOutcome records the error in report_result,
        leaving the alignment status intact."""
        from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_REPORT_DATA
        alignment.status = "aligned"
        alignment.status_message = "aligned"

        _apply_poll_result(alignment, 200, {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "details": {"text": "Invalid Composition"}}],
        })

        assert alignment.report_result == "Invalid Composition"
        assert alignment.status == "aligned"
        assert alignment.status_message == "aligned"
        assert alignment.submission_state == "error"

    def test_records_audit_event_on_completion(self):
        """Each completed op appends an immutable ACCESSOperationLog row with its result
        code, so history survives later overwrites of the alignment row."""
        from cms_access_fhir_client.cron.submission_status_poller import _apply_completed_result
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment

        alignment = MagicMock()
        alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN
        alignment.track = "CKM"

        with patch("cms_access_fhir_client.operation_log.record_operation_event") as rec:
            _apply_completed_result(alignment, {
                "parameter": [
                    {"name": "result", "valueCodeableConcept": {"coding": [{"code": "not-aligned-diagnoses"}]}},
                ],
            })

        rec.assert_called_once()
        kwargs = rec.call_args.kwargs
        assert kwargs["operation"] == ACCESSAlignment.SUB_OP_ALIGN
        assert kwargs["result_code"] == "not-aligned-diagnoses"
        assert kwargs["track"] == "CKM"

    def test_extract_submission_status_returns_in_progress_when_absent(self):
        from cms_access_fhir_client.cron.submission_status_poller import _extract_submission_status
        # No 'status' parameter → default to in-progress
        assert _extract_submission_status({}) == "in-progress"
        assert _extract_submission_status({"parameter": []}) == "in-progress"
