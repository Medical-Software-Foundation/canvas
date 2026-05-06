"""Tests for CandidSubmitAPI: delayed claim submission via SimpleAPI."""

from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.claim import ClaimQueues

from candid.api.submit import CandidSubmitAPI

from tests.conftest import MOCK_SECRETS


def _build_handler(claim: MagicMock | None, body: dict | None = None) -> CandidSubmitAPI:
    handler = CandidSubmitAPI.__new__(CandidSubmitAPI)
    handler.secrets = MOCK_SECRETS
    handler.request = MagicMock()
    handler.request.json.return_value = (
        {"claim_id": "claim-1"} if body is None else body
    )
    return handler


def _claim_in_submission_queue() -> MagicMock:
    claim = MagicMock()
    claim.id = "claim-1"
    claim.current_queue.queue_sort_ordering = ClaimQueues.QUEUED_FOR_SUBMISSION
    claim.current_queue.name = "QueuedForSubmission"
    return claim


# ---------------------------------------------------------------------------
# Grace-period skip
# ---------------------------------------------------------------------------


def test_submit_skips_when_claim_no_longer_in_submission_queue() -> None:
    """If the claim moved out of QueuedForSubmission during the grace period, return []."""
    claim = MagicMock()
    claim.id = "claim-1"
    claim.current_queue.queue_sort_ordering = ClaimQueues.NEEDS_CODING_REVIEW
    claim.current_queue.name = "NeedsCodingReview"

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        handler = _build_handler(claim)

        result = handler.post()

        assert result == []
        # Should never reach the build/submit code path
        mock_build.assert_not_called()
        MC.from_secrets.assert_not_called()


def test_submit_returns_empty_when_claim_not_found() -> None:
    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
    ):
        MockClaim.objects.filter.return_value.first.return_value = None
        handler = _build_handler(None)

        result = handler.post()

        assert result == []
        MC.from_secrets.assert_not_called()


def test_submit_returns_empty_when_claim_id_missing() -> None:
    with patch("candid.api.submit.CandidClient") as MC:
        handler = _build_handler(None, body={})

        result = handler.post()

        assert result == []
        MC.from_secrets.assert_not_called()


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_submit_validation_errors_route_to_failure_handler() -> None:
    """build_split_payloads returning errors → handle_submit_failure (no Candid call)."""
    claim = _claim_in_submission_queue()

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.handle_submit_success") as mock_success,
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [({}, ["Patient is missing", "DOB is missing"])]
        mock_failure.return_value = ["failure-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result == ["failure-effect"]
        mock_failure.assert_called_once()
        message = mock_failure.call_args[0][1]
        assert "Patient is missing" in message
        assert "DOB is missing" in message
        mock_success.assert_not_called()
        # No Candid HTTP call should be made
        MC.from_secrets.assert_not_called()


# ---------------------------------------------------------------------------
# Successful submission
# ---------------------------------------------------------------------------


def test_submit_success_for_single_payload() -> None:
    claim = _claim_in_submission_queue()
    payload = {"external_id": "canvas:claim-1"}

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [(payload, [])]
        client = MC.from_secrets.return_value
        client.submit_claim.return_value = (True, "encounter-1")
        mock_success.return_value = ["success-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result == ["success-effect"]
        client.submit_claim.assert_called_once_with(payload)
        encounter_records = mock_success.call_args[0][1]
        assert len(encounter_records) == 1
        assert encounter_records[0]["candid_encounter_id"] == "encounter-1"
        assert encounter_records[0]["split"] == 1
        mock_failure.assert_not_called()


def test_submit_success_for_multiple_splits() -> None:
    """All splits succeed → handle_submit_success with N encounter records."""
    claim = _claim_in_submission_queue()
    payloads = [
        ({"external_id": "canvas:claim-1-1"}, []),
        ({"external_id": "canvas:claim-1-2"}, []),
        ({"external_id": "canvas:claim-1-3"}, []),
    ]

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_success") as mock_success,
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = payloads
        client = MC.from_secrets.return_value
        client.submit_claim.side_effect = [
            (True, "enc-a"),
            (True, "enc-b"),
            (True, "enc-c"),
        ]
        mock_success.return_value = []

        handler = _build_handler(claim)
        handler.post()

        assert client.submit_claim.call_count == 3
        encounter_records = mock_success.call_args[0][1]
        assert [r["candid_encounter_id"] for r in encounter_records] == [
            "enc-a", "enc-b", "enc-c"
        ]
        assert mock_success.call_args[0][3] == 3  # total_splits


def test_submit_aborts_on_mid_split_failure() -> None:
    """If split 2 of 3 is rejected by Candid, handler short-circuits to failure."""
    claim = _claim_in_submission_queue()
    payloads = [
        ({"external_id": "canvas:claim-1-1"}, []),
        ({"external_id": "canvas:claim-1-2"}, []),
        ({"external_id": "canvas:claim-1-3"}, []),
    ]

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.handle_submit_success") as mock_success,
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = payloads
        client = MC.from_secrets.return_value
        client.submit_claim.side_effect = [
            (True, "enc-a"),
            (False, "<400 ValidationError> patient.zip missing"),
            (True, "enc-c"),  # should never be reached
        ]
        mock_failure.return_value = ["failure-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result == ["failure-effect"]
        # Stopped after the second submit
        assert client.submit_claim.call_count == 2
        mock_success.assert_not_called()
        message = mock_failure.call_args[0][1]
        assert "split 2/3" in message
        assert "patient.zip missing" in message


def test_submit_handles_exception_during_submit_call() -> None:
    """If submit_claim raises, handler routes to handle_submit_failure."""
    claim = _claim_in_submission_queue()

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [({"external_id": "canvas:claim-1"}, [])]
        client = MC.from_secrets.return_value
        client.submit_claim.side_effect = RuntimeError("network down")
        mock_failure.return_value = ["failure-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result == ["failure-effect"]
        message = mock_failure.call_args[0][1]
        assert "network down" in message
