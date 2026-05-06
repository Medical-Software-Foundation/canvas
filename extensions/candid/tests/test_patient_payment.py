"""Tests for OnPatientPaymentProcessed handler — patient payment reporting to Candid."""

import json
from unittest.mock import MagicMock, patch

from candid.handlers.on_patient_payment import OnPatientPaymentProcessed
from tests.conftest import MOCK_SECRETS


def _payment_context(
    patient_id: str = "patient-key-123",
    total_cents: str = "10000.00",
    claim_payments: list[dict] | None = None,
) -> dict:
    """Build a minimal payment_event_context dict."""
    ctx = {
        "patient_id": patient_id,
        "total_amount_cents": total_cents,
        "timestamp": "2026-04-24T12:00:00+00:00",
        "payment_method_and_description": "card",
    }
    if claim_payments is not None:
        ctx["claim_payments"] = claim_payments
    return ctx


def _run_handler(
    context: dict, existing_payment_ids: list[str] | None = None
) -> tuple[MagicMock, MagicMock]:
    """Run the handler and return the mock CandidClient and ClaimEffect."""
    with (
        patch("candid.handlers.on_patient_payment.CandidClient") as MockClient,
        patch("candid.handlers.on_patient_payment.ClaimEffect") as MockClaimEffect,
        patch("candid.handlers.on_patient_payment.SyncLog"),
        patch("candid.handlers.on_patient_payment.Claim") as MockClaim,
        patch(
            "candid.handlers.on_patient_payment.get_claim_metadata_set",
            return_value=set(existing_payment_ids or []),
        ),
    ):
        client = MockClient.from_secrets.return_value
        client.submit_payment.return_value = (True, "pay-id-123")
        MockClaim.objects.filter.return_value.first.return_value = MagicMock()

        handler = OnPatientPaymentProcessed.__new__(OnPatientPaymentProcessed)
        handler.event = MagicMock()
        handler.event.context = context
        handler.secrets = MOCK_SECRETS

        handler.compute()
        return client, MockClaimEffect


# ---------------------------------------------------------------------------
# Allocation mapping
# ---------------------------------------------------------------------------


def test_payment_with_claim_allocations() -> None:
    """Claim allocations use canvas:{claim_id} as encounter external_id."""
    client, _ = _run_handler(
        _payment_context(
            total_cents="10000.00",
            claim_payments=[
                {
                    "claim_id": "abc-123",
                    "allocated_cents": "10000.00",
                },
            ],
        )
    )

    client.submit_payment.assert_called_once()
    payload = client.submit_payment.call_args[0][0]
    assert payload["patient_external_id"] == "canvas:patient-key-123"
    assert payload["amount_cents"] == 10000
    assert len(payload["allocations"]) == 1
    assert payload["allocations"][0]["target"]["type"] == "claim_by_encounter_external_id"
    assert payload["allocations"][0]["target"]["value"] == "canvas:abc-123"
    assert payload["allocations"][0]["amount_cents"] == 10000


def test_payment_without_claim_allocations() -> None:
    """Payment without claim_payments goes as unattributed."""
    client, _ = _run_handler(_payment_context(total_cents="5000.00"))

    payload = client.submit_payment.call_args[0][0]
    assert len(payload["allocations"]) == 1
    assert payload["allocations"][0]["target"]["type"] == "unattributed"
    assert payload["allocations"][0]["amount_cents"] == 5000


def test_payment_partial_allocation_remainder_unattributed() -> None:
    """Amount not allocated to claims goes as unattributed."""
    client, _ = _run_handler(
        _payment_context(
            total_cents="15000.00",
            claim_payments=[
                {
                    "claim_id": "abc-123",
                    "allocated_cents": "10000.00",
                },
            ],
        )
    )

    payload = client.submit_payment.call_args[0][0]
    assert len(payload["allocations"]) == 2
    assert payload["allocations"][0]["target"]["type"] == "claim_by_encounter_external_id"
    assert payload["allocations"][0]["target"]["value"] == "canvas:abc-123"
    assert payload["allocations"][0]["amount_cents"] == 10000
    assert payload["allocations"][1]["target"]["type"] == "unattributed"
    assert payload["allocations"][1]["amount_cents"] == 5000


def test_payment_multiple_claims() -> None:
    """Payment split across multiple claims allocates to each."""
    client, _ = _run_handler(
        _payment_context(
            total_cents="15000.00",
            claim_payments=[
                {
                    "claim_id": "claim-1",
                    "allocated_cents": "10000.00",
                },
                {
                    "claim_id": "claim-2",
                    "allocated_cents": "5000.00",
                },
            ],
        )
    )

    payload = client.submit_payment.call_args[0][0]
    assert len(payload["allocations"]) == 2
    assert payload["allocations"][0]["target"]["value"] == "canvas:claim-1"
    assert payload["allocations"][0]["amount_cents"] == 10000
    assert payload["allocations"][1]["target"]["value"] == "canvas:claim-2"
    assert payload["allocations"][1]["amount_cents"] == 5000


# ---------------------------------------------------------------------------
# Reported payment IDs metadata
# ---------------------------------------------------------------------------


def test_reported_payment_ids_merged_with_existing() -> None:
    """New payment_id is merged into existing reported IDs, not overwriting them."""
    _, MockClaimEffect = _run_handler(
        _payment_context(
            claim_payments=[{"claim_id": "abc-123", "allocated_cents": "10000.00"}],
        ),
        existing_payment_ids=["pay-id-001", "pay-id-002"],
    )

    upsert_call = MockClaimEffect.return_value.upsert_metadata.call_args
    written = json.loads(upsert_call.kwargs["value"])
    assert written == ["pay-id-001", "pay-id-002", "pay-id-123"]
