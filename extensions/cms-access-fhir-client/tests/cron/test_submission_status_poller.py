"""Tests for SubmissionStatusPoller — backoff schedule, state transitions, abandonment."""
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

        completed_result = {
            "parameter": [
                {"name": "status", "valueCode": "completed"},
                {"name": "alignmentId", "valueString": "align-xyz"},
            ]
        }

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=completed_result,
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
    def test_completed_align_marks_aligned(self):
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="align",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        result = {
            "parameter": [
                {"name": "status", "valueCode": "completed"},
                {"name": "alignmentId", "valueString": "align-new-id"},
                {"name": "careStartDate", "valueDate": "2026-06-01"},
            ]
        }

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=result,
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

    def test_completed_unalign_marks_unaligned(self):
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="unalign",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        result = {"parameter": [{"name": "status", "valueCode": "completed"}]}

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=result,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.status == "unaligned"
        assert alignment.submission_state == "completed"

    def test_error_result_marks_alignment_error(self):
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        result = {"parameter": [{"name": "status", "valueCode": "error"}]}

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=result,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        assert alignment.submission_state == "error"
        assert alignment.status == "error"

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

    def test_completed_eligibility_sets_status_from_response(self):
        poller = _make_poller()
        now = _utcnow()

        alignment = _make_alignment(
            submission_op="eligibility",
            poll_attempts=0,
            last_poll_at=now - timedelta(minutes=2),
        )

        result = {
            "parameter": [
                {"name": "status", "valueCode": "completed"},
                {"name": "status", "valueCode": "eligible"},
            ]
        }

        mock_qs = MagicMock()
        mock_qs.filter.return_value = [alignment]

        with (
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller.poll_submission_status",
                return_value=result,
            ),
            patch(
                "cms_access_fhir_client.cron.submission_status_poller._utcnow",
                return_value=now,
            ),
        ):
            poller.execute()

        # The completed state is set by _apply_poll_result
        assert alignment.submission_state == "completed"

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
                {"name": "status", "valueCode": "completed"},
                {"name": "alignmentId", "valueString": "align-xyz"},
                {"name": "careStartDate", "valueDate": "not-a-date"},  # invalid
            ]
        }
        # Should not raise — invalid date is silently skipped
        _apply_completed_result(alignment, result)
        assert alignment.status == "aligned"
        assert alignment.alignment_id == "align-xyz"

    def test_extract_submission_status_returns_in_progress_when_absent(self):
        from cms_access_fhir_client.cron.submission_status_poller import _extract_submission_status
        # No 'status' parameter → default to in-progress
        assert _extract_submission_status({}) == "in-progress"
        assert _extract_submission_status({"parameter": []}) == "in-progress"

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

        # Should skip without polling
        assert mock_poll.mock_calls == []
        # State unchanged
        assert alignment.submission_state == "in-progress"
