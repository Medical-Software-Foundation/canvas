"""Tests for OnClaimQueueMoved handler: submit-on-queue and sync-on-queue."""

import sys
import types
from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.claim import ClaimQueues

# The locked canvas_sdk in this plugin's venv doesn't yet expose
# canvas_sdk.effects.http_request; stub it so on_queue_moved imports cleanly.
if "canvas_sdk.effects.http_request" not in sys.modules:
    stub = types.ModuleType("canvas_sdk.effects.http_request")
    stub.HttpRequestEffect = MagicMock()
    sys.modules["canvas_sdk.effects.http_request"] = stub

from candid.handlers.on_queue_moved import GRACE_PERIOD_SECONDS, OnClaimQueueMoved


SECRETS = {
    "CANVAS_INSTANCE_URL": "https://canvas.test/",
    "CANDID_API_KEY": "test-api-key",
    "CANDID_BASE_URL": "https://api.candid.test",
    "CANDID_CLIENT_ID": "client-id",
    "CANDID_CLIENT_SECRET": "client-secret",
}


def _build_handler(queue_entered_id: str | None, claim_id: str = "claim-1") -> OnClaimQueueMoved:
    handler = OnClaimQueueMoved.__new__(OnClaimQueueMoved)
    handler.secrets = SECRETS
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
        patch("candid.handlers.on_queue_moved.HttpRequestEffect") as MockHttp,
    ):
        # The chain: HttpRequestEffect(...).apply().set_async(delay_seconds=...)
        applied = MockHttp.return_value.apply.return_value
        applied.set_async.return_value = "scheduled-effect"

        result = handler.compute()

        assert result == ["scheduled-effect"]
        MockHttp.assert_called_once()
        kwargs = MockHttp.call_args.kwargs
        assert kwargs["url"] == "https://canvas.test/plugin-io/api/candid/submit"
        assert kwargs["method"] == "POST"
        assert kwargs["headers"]["Authorization"] == "test-api-key"
        assert '"claim_id": "claim-99"' in kwargs["body"]
        applied.set_async.assert_called_once_with(delay_seconds=GRACE_PERIOD_SECONDS)


# ---------------------------------------------------------------------------
# Patient-balance sync path
# ---------------------------------------------------------------------------


def test_patient_balance_triggers_sync_patient_payments() -> None:
    handler = _build_handler(queue_entered_id="queue-row-id", claim_id="claim-7")
    fake_claim = MagicMock()
    with (
        _patch_queue_lookup(ClaimQueues.PATIENT_BALANCE),
        patch("candid.handlers.on_queue_moved.Claim") as MockClaim,
        patch(
            "candid.handlers.on_queue_moved.sync_patient_payments",
            return_value=["sync-effect"],
        ) as mock_sync,
    ):
        MockClaim.objects.filter.return_value.first.return_value = fake_claim

        result = handler.compute()

        assert result == ["sync-effect"]
        mock_sync.assert_called_once_with(fake_claim, SECRETS)


def test_patient_balance_with_missing_claim_returns_empty() -> None:
    handler = _build_handler(queue_entered_id="queue-row-id", claim_id="claim-missing")
    with (
        _patch_queue_lookup(ClaimQueues.PATIENT_BALANCE),
        patch("candid.handlers.on_queue_moved.Claim") as MockClaim,
        patch("candid.handlers.on_queue_moved.sync_patient_payments") as mock_sync,
    ):
        MockClaim.objects.filter.return_value.first.return_value = None

        assert handler.compute() == []
        mock_sync.assert_not_called()
