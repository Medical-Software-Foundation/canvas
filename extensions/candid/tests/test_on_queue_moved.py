"""Tests for OnClaimQueueMoved handler: submit-on-queue and sync-on-queue."""

from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.claim import ClaimQueues

from candid.handlers.on_queue_moved import GRACE_PERIOD_SECONDS, OnClaimQueueMoved


SECRETS = {
    "CANDID_BASE_URL": "https://api.candid.test",
    "CANDID_CLIENT_ID": "client-id",
    "CANDID_CLIENT_SECRET": "client-secret",
}

ENVIRONMENT = {
    "CUSTOMER_IDENTIFIER": "canvas-test",
}


def _build_handler(queue_entered_id: str | None, claim_id: str = "claim-1") -> OnClaimQueueMoved:
    handler = OnClaimQueueMoved.__new__(OnClaimQueueMoved)
    handler.secrets = SECRETS
    handler.environment = ENVIRONMENT
    handler.event = MagicMock()
    handler.event.context = {
        "queue_entered": {"id": queue_entered_id} if queue_entered_id else {},
    }
    handler.event.target.id = claim_id
    return handler


def _patch_queue_lookup(queue_value: int | None):
    """Patch ClaimQueue.objects.values_list(...).filter(id=...).first() to return queue_value."""
    return patch(
        "candid.handlers.on_queue_moved.ClaimQueue.objects.values_list",
        return_value=MagicMock(
            filter=MagicMock(
                return_value=MagicMock(first=MagicMock(return_value=queue_value))
            )
        ),
    )


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------


def test_returns_empty_when_no_queue_entered_id() -> None:
    handler = _build_handler(queue_entered_id=None)
    assert handler.compute() == []


def test_returns_empty_for_unrelated_queue() -> None:
    handler = _build_handler(queue_entered_id="queue-row-id")
    with _patch_queue_lookup(ClaimQueues.NEEDS_CLINICIAN_REVIEW):
        assert handler.compute() == []


# ---------------------------------------------------------------------------
# Submission-queue path
# ---------------------------------------------------------------------------


def test_submission_queue_schedules_delayed_http_request() -> None:
    handler = _build_handler(queue_entered_id="queue-row-id", claim_id="claim-99")
    with (
        _patch_queue_lookup(ClaimQueues.QUEUED_FOR_SUBMISSION),
        patch(
            "candid.handlers.on_queue_moved.schedule_async_post",
            return_value="scheduled-effect",
        ) as mock_dispatch,
    ):
        result = handler.compute()

        assert result == ["scheduled-effect"]
        mock_dispatch.assert_called_once_with(
            ENVIRONMENT,
            SECRETS,
            "submit",
            {"claim_id": "claim-99"},
            delay_seconds=GRACE_PERIOD_SECONDS,
        )


# ---------------------------------------------------------------------------
# Patient-balance sync path
# ---------------------------------------------------------------------------


def test_patient_balance_schedules_async_patient_payment_sync() -> None:
    handler = _build_handler(queue_entered_id="queue-row-id", claim_id="claim-7")
    with (
        _patch_queue_lookup(ClaimQueues.PATIENT_BALANCE),
        patch(
            "candid.handlers.on_queue_moved.schedule_async_post",
            return_value="scheduled-sync",
        ) as mock_dispatch,
    ):
        result = handler.compute()

        assert result == ["scheduled-sync"]
        mock_dispatch.assert_called_once_with(
            ENVIRONMENT,
            SECRETS,
            "sync-patient-payments",
            {"claim_id": "claim-7"},
            delay_seconds=0,
        )
