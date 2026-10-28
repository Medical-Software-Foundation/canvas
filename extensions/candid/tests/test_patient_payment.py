"""Tests for patient payment reporting — handler dispatch + SimpleAPI endpoint."""

from unittest.mock import MagicMock, patch

from candid.handlers.on_patient_payment import OnPatientPaymentProcessed
from tests.conftest import MOCK_SECRETS

ENVIRONMENT = {"CUSTOMER_IDENTIFIER": "canvas-test"}


def _payment_context(
    patient_id: str = "patient-key-123",
    total_cents: str = "10000.00",
    claim_payments: list[dict] | None = None,
    payment_method: str = "card",
) -> dict:
    ctx = {
        "patient_id": patient_id,
        "total_amount_cents": total_cents,
        "timestamp": "2026-04-24T12:00:00+00:00",
        "payment_method_and_description": payment_method,
    }
    if claim_payments is not None:
        ctx["claim_payments"] = claim_payments
    return ctx


# ---------------------------------------------------------------------------
# Handler: just forwards event context to /report-payment
# ---------------------------------------------------------------------------


def test_handler_dispatches_event_context() -> None:
    """Handler dispatches the raw event context to /report-payment."""
    context = _payment_context(
        claim_payments=[{"claim_id": "abc-123", "allocated_cents": "10000.00"}]
    )

    with patch(
        "candid.handlers.on_patient_payment.schedule_async_post",
        return_value="dispatched-effect",
    ) as mock_dispatch:
        handler = OnPatientPaymentProcessed.__new__(OnPatientPaymentProcessed)
        handler.event = MagicMock()
        handler.event.context = context
        handler.secrets = MOCK_SECRETS
        handler.environment = ENVIRONMENT

        effects = handler.compute()

    assert effects == ["dispatched-effect"]
    mock_dispatch.assert_called_once_with(
        ENVIRONMENT, MOCK_SECRETS, "report-payment", context
    )


# ---------------------------------------------------------------------------
# SimpleAPI endpoint: /report-payment
# ---------------------------------------------------------------------------


def _run_endpoint(body: dict, submit_result: tuple = (True, "pay-id-456")):
    """Run the /report-payment endpoint and return (effects, mock_client)."""
    from candid.api.report_payment import CandidReportPaymentAPI

    mock_claims = []
    for cp in body.get("claim_payments", []):
        mc = MagicMock()
        mc.id = cp.get("claim_id", "")
        mock_claims.append(mc)

    with (
        patch("candid.api.report_payment.CandidClient") as MockClient,
        patch("candid.api.report_payment.ClaimEffect"),
        patch("candid.api.report_payment.Claim") as MockClaim,
        patch("candid.api.report_payment.get_claim_metadata_set", return_value=set()),
        patch("candid.api.report_payment.notify_claim_updated", return_value=MagicMock()),
    ):
        client = MockClient.from_secrets.return_value
        client.submit_payment.return_value = submit_result
        MockClaim.objects.filter.return_value = mock_claims

        handler = CandidReportPaymentAPI.__new__(CandidReportPaymentAPI)
        handler.secrets = MOCK_SECRETS
        handler.request = MagicMock()
        handler.request.json.return_value = body

        effects = handler.post()
        return effects, client


def test_endpoint_builds_allocations_from_claim_payments() -> None:
    """Endpoint builds allocations using canvas:{claim_id} format."""
    effects, client = _run_endpoint(
        _payment_context(
            claim_payments=[{"claim_id": "abc-123", "allocated_cents": "10000.00"}]
        )
    )

    client.submit_payment.assert_called_once()
    payload = client.submit_payment.call_args[0][0]
    assert payload["patient_external_id"] == "canvas:patient-key-123"
    assert payload["amount_cents"] == 10000
    assert len(payload["allocations"]) == 1
    assert payload["allocations"][0]["target"]["type"] == "claim_by_encounter_external_id"
    assert payload["allocations"][0]["target"]["value"] == "canvas:abc-123"


def test_endpoint_unattributed_when_no_claim_payments() -> None:
    """Without claim_payments, full amount goes as unattributed."""
    _, client = _run_endpoint(_payment_context(total_cents="5000.00"))

    payload = client.submit_payment.call_args[0][0]
    assert len(payload["allocations"]) == 1
    assert payload["allocations"][0]["target"]["type"] == "unattributed"
    assert payload["allocations"][0]["amount_cents"] == 5000


def test_endpoint_partial_allocation_remainder_unattributed() -> None:
    """Unallocated remainder goes as unattributed."""
    _, client = _run_endpoint(
        _payment_context(
            total_cents="15000.00",
            claim_payments=[{"claim_id": "abc-123", "allocated_cents": "10000.00"}],
        )
    )

    payload = client.submit_payment.call_args[0][0]
    assert len(payload["allocations"]) == 2
    assert payload["allocations"][0]["target"]["value"] == "canvas:abc-123"
    assert payload["allocations"][0]["amount_cents"] == 10000
    assert payload["allocations"][1]["target"]["type"] == "unattributed"
    assert payload["allocations"][1]["amount_cents"] == 5000


def test_endpoint_unattributed_when_claim_has_no_encounter_metadata() -> None:
    """Claims without Candid encounter metadata still send payment as unattributed."""
    from candid.api.report_payment import CandidReportPaymentAPI

    mock_claim = MagicMock()
    mock_claim.id = "abc-123"

    with (
        patch("candid.api.report_payment.CandidClient") as MockClient,
        patch("candid.api.report_payment.ClaimEffect"),
        patch("candid.api.report_payment.Claim") as MockClaim,
        patch("candid.api.report_payment.get_claim_metadata", return_value=None),
        patch("candid.api.report_payment.get_claim_metadata_set", return_value=set()),
        patch("candid.api.report_payment.notify_claim_updated", return_value=MagicMock()),
    ):
        client = MockClient.from_secrets.return_value
        client.submit_payment.return_value = (True, "pay-id-456")
        MockClaim.objects.filter.return_value = [mock_claim]

        handler = CandidReportPaymentAPI.__new__(CandidReportPaymentAPI)
        handler.secrets = MOCK_SECRETS
        handler.request = MagicMock()
        handler.request.json.return_value = _payment_context(
            total_cents="10000.00",
            claim_payments=[{"claim_id": "abc-123", "allocated_cents": "10000.00"}],
        )

        handler.post()

    client.submit_payment.assert_called_once()
    payload = client.submit_payment.call_args[0][0]
    assert len(payload["allocations"]) == 1
    assert payload["allocations"][0]["target"]["type"] == "unattributed"
    assert payload["allocations"][0]["amount_cents"] == 10000


def test_endpoint_skips_candid_originated_payments() -> None:
    """Payments with an embedded ID that's already synced are not re-reported."""
    from candid.api.report_payment import CandidReportPaymentAPI

    mock_claim = MagicMock()
    mock_claim.id = "claim-1"

    with (
        patch("candid.api.report_payment.CandidClient") as MockClient,
        patch("candid.api.report_payment.Claim") as MockClaim,
        patch(
            "candid.api.report_payment.get_claim_metadata_set",
            return_value={"pay-123"},
        ),
    ):
        client = MockClient.from_secrets.return_value
        MockClaim.objects.filter.return_value = [mock_claim]

        handler = CandidReportPaymentAPI.__new__(CandidReportPaymentAPI)
        handler.secrets = MOCK_SECRETS
        handler.request = MagicMock()
        handler.request.json.return_value = _payment_context(
            payment_method="other: Candid patient payment pay-123",
            claim_payments=[{"claim_id": "claim-1", "allocated_cents": "10000.00"}],
        )

        effects = handler.post()

    assert effects == []
    client.submit_payment.assert_not_called()


def test_endpoint_creates_task_on_failure() -> None:
    """Endpoint creates a Task when Candid rejects the payment."""
    from candid.api.report_payment import CandidReportPaymentAPI

    with (
        patch("candid.api.report_payment.CandidClient") as MockClient,
        patch("candid.api.report_payment.AddTask") as MockAddTask,
    ):
        client = MockClient.from_secrets.return_value
        client.submit_payment.return_value = (False, "<422> bad data")

        handler = CandidReportPaymentAPI.__new__(CandidReportPaymentAPI)
        handler.secrets = MOCK_SECRETS
        handler.request = MagicMock()
        handler.request.json.return_value = _payment_context()

        effects = handler.post()

    assert len(effects) == 1
    MockAddTask.assert_called_once()
    assert "Payment Notification Failed" in MockAddTask.call_args.kwargs["title"]
    assert "bad data" in MockAddTask.call_args.kwargs["title"]


def test_endpoint_dedupes_repeated_claim_id_into_one_effect_set():
    """A claim appearing in multiple claim_payments gets one set of post-success
    effects -- two writes to the same metadata key in one batch would race and
    clobber candid_sync_history. Allocations are still sent per claim_payment."""
    from candid.api.report_payment import CandidReportPaymentAPI
    from candid.effect_helpers import META_REPORTED_PAYMENT_IDS

    claim = MagicMock()
    claim.id = "abc-123"

    with (
        patch("candid.api.report_payment.CandidClient") as MockClient,
        patch("candid.api.report_payment.ClaimEffect") as MockCE,
        patch("candid.api.report_payment.Claim") as MockClaim,
        patch(
            "candid.api.report_payment.get_claim_metadata",
            return_value=[{"candid_encounter_id": "enc-1"}],
        ),
        patch("candid.api.report_payment.get_claim_metadata_set", return_value=set()),
        patch(
            "candid.api.report_payment.notify_claim_updated", return_value="notify"
        ) as mock_notify,
    ):
        client = MockClient.from_secrets.return_value
        client.submit_payment.return_value = (True, "pay-1")
        MockClaim.objects.filter.return_value = [claim]
        MockCE.return_value.upsert_metadata.return_value = "upsert"

        handler = CandidReportPaymentAPI.__new__(CandidReportPaymentAPI)
        handler.secrets = MOCK_SECRETS
        handler.request = MagicMock()
        handler.request.json.return_value = _payment_context(
            total_cents="10000.00",
            claim_payments=[
                {"claim_id": "abc-123", "allocated_cents": "4000.00"},
                {"claim_id": "abc-123", "allocated_cents": "6000.00"},
            ],
        )

        handler.post()

    # both allocations are still sent (they sum at the encounter on Candid's side)
    payload = client.submit_payment.call_args[0][0]
    assert len(payload["allocations"]) == 2

    # ...but the claim's post-success effects fire once, not twice
    assert mock_notify.call_count == 1
    reported_upserts = [
        c
        for c in MockCE.return_value.upsert_metadata.call_args_list
        if c.kwargs.get("key") == META_REPORTED_PAYMENT_IDS
    ]
    assert len(reported_upserts) == 1


# ---------------------------------------------------------------------------
# PLUGIN-498: tagging, no-answer handling, overlapping reports
# ---------------------------------------------------------------------------


def test_endpoint_tags_payment_note_as_sent_from_canvas() -> None:
    """The payment note carries the tag the sync uses to skip Canvas's own payments."""
    from candid.effect_helpers import CANVAS_REPORTED_NOTE_TAG

    _, client = _run_endpoint(
        _payment_context(
            payment_method="card",
            claim_payments=[{"claim_id": "abc-123", "allocated_cents": "10000.00"}],
        )
    )

    payload = client.submit_payment.call_args[0][0]
    assert payload["payment_note"] == f"card {CANVAS_REPORTED_NOTE_TAG}"


def test_endpoint_timeout_creates_unconfirmed_task_and_writes_no_metadata() -> None:
    """Candid accepts the payment but answers too late: one task, no retry, no metadata."""
    from requests import RequestException

    from candid.api.report_payment import CandidReportPaymentAPI

    mock_claim = MagicMock()
    mock_claim.id = "abc-123"

    with (
        patch("candid.api.report_payment.CandidClient") as MockClient,
        patch("candid.api.report_payment.ClaimEffect") as MockEffect,
        patch("candid.api.report_payment.Claim") as MockClaim,
        patch("candid.api.report_payment.get_claim_metadata_set", return_value=set()),
        patch("candid.api.report_payment.AddTask") as MockTask,
    ):
        client = MockClient.from_secrets.return_value
        client.submit_payment.side_effect = RequestException("Read timed out")
        MockClaim.objects.filter.return_value = [mock_claim]

        handler = CandidReportPaymentAPI.__new__(CandidReportPaymentAPI)
        handler.secrets = MOCK_SECRETS
        handler.request = MagicMock()
        handler.request.json.return_value = _payment_context(
            claim_payments=[{"claim_id": "abc-123", "allocated_cents": "10000.00"}]
        )

        effects = handler.post()

    client.submit_payment.assert_called_once()
    assert effects == [MockTask.return_value.apply.return_value]
    assert "Unconfirmed" in MockTask.call_args.kwargs["title"]
    assert "RequestException" in MockTask.call_args.kwargs["title"]
    MockEffect.return_value.upsert_metadata.assert_not_called()


def test_endpoint_keeps_ids_saved_by_an_overlapping_report() -> None:
    """A report saved another ID on the claim while ours was in flight: both are kept."""
    import json

    from candid.api.report_payment import CandidReportPaymentAPI
    from candid.effect_helpers import META_REPORTED_PAYMENT_IDS

    mock_claim = MagicMock()
    mock_claim.id = "claim-1"
    # First read (before submit) sees nothing; the re-read after submit sees
    # the overlapping report's ID.
    reads = iter([set(), {"pay-other"}])

    with (
        patch("candid.api.report_payment.CandidClient") as MockClient,
        patch("candid.api.report_payment.ClaimEffect") as MockEffect,
        patch("candid.api.report_payment.Claim") as MockClaim,
        patch("candid.api.report_payment.get_claim_metadata", return_value=[{"x": 1}]),
        patch(
            "candid.api.report_payment.get_claim_metadata_set",
            side_effect=lambda claim, key: next(reads) if key == META_REPORTED_PAYMENT_IDS else set(),
        ),
        patch("candid.api.report_payment.append_sync_history"),
        patch("candid.api.report_payment.notify_claim_updated"),
    ):
        MockClient.from_secrets.return_value.submit_payment.return_value = (True, "pay-mine")
        MockClaim.objects.filter.return_value = [mock_claim]

        handler = CandidReportPaymentAPI.__new__(CandidReportPaymentAPI)
        handler.secrets = MOCK_SECRETS
        handler.request = MagicMock()
        handler.request.json.return_value = _payment_context(
            claim_payments=[{"claim_id": "claim-1", "allocated_cents": "10000.00"}]
        )

        handler.post()

    upsert = MockEffect.return_value.upsert_metadata
    written = [c.kwargs["value"] for c in upsert.call_args_list if c.kwargs["key"] == META_REPORTED_PAYMENT_IDS]
    assert written == [json.dumps(["pay-mine", "pay-other"])]
