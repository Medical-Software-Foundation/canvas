"""Tests for Candid adjudication sync logic."""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from candid.adjudication_sync import (
    PR_COINSURANCE,
    PR_COPAY,
    PR_DEDUCTIBLE,
    _build_insurance_transactions,
    _cents_to_dollars,
    _determine_target_queue,
    _match_line_item,
    sync_claim_adjudications,
)
from canvas_sdk.v1.data.claim import ClaimQueues
from candid.effect_helpers import (
    ERA_DESC_PREFIX,
    META_SYNCED_ERA_IDS,
    META_SYNCED_PAYMENT_IDS,
    PATIENT_PAYMENT_DESC_PREFIX,
)

from tests.conftest import MOCK_SECRETS


def _fake_line_item(
    proc_code: str,
    charge: Decimal,
    from_date: str = "2026-01-15",
    li_id: str = "li-1",
) -> MagicMock:
    li = MagicMock()
    li.proc_code = proc_code
    li.charge = charge
    li.from_date = from_date
    li.id = li_id
    return li


def _fake_coverage(coverage_id: str, payer_order: str) -> MagicMock:
    cov = MagicMock()
    cov.id = coverage_id
    cov.active = True
    cov.payer_order = payer_order
    return cov


def _fake_claim(
    line_items: list,
    coverages: list | None = None,
    metadata: dict | None = None,
) -> MagicMock:
    claim = MagicMock()
    claim.id = "00000000-0000-0000-0000-000000000001"
    claim.line_items.all.return_value = line_items
    claim.line_items.first.return_value = line_items[0] if line_items else None
    claim.get_active_claim_line_items.return_value = line_items

    if coverages is None:
        coverages = [_fake_coverage("cov-primary", "Primary")]
    claim.coverages.all.return_value = coverages
    claim.coverages.active.return_value = [c for c in coverages if c.active]

    stored_meta = metadata or {}

    def filter_meta(key=None):
        if key in stored_meta:
            mock_obj = MagicMock()
            mock_obj.value = (
                stored_meta[key]
                if isinstance(stored_meta[key], str)
                else json.dumps(stored_meta[key])
            )
            result = MagicMock()
            result.first.return_value = mock_obj
            result.exists.return_value = True
            return result
        result = MagicMock()
        result.first.return_value = None
        result.exists.return_value = False
        return result

    claim.metadata.filter = filter_meta
    return claim


def _candid_service_line(
    procedure_code: str = "99213",
    charge_amount_cents: int = 10000,
    primary_paid_amount_cents: int | None = None,
    allowed_amount_cents: int | None = None,
    secondary_paid_amount_cents: int | None = None,
    tertiary_paid_amount_cents: int | None = None,
    manual_adjustments: list[dict] | None = None,
    era_adjustments: list[dict] | None = None,
    deductible_cents: int | None = None,
    coinsurance_cents: int | None = None,
    copay_cents: int | None = None,
    insurance_balance_cents: int | None = None,
    patient_balance_cents: int | None = None,
    date_of_service: str = "2026-01-15",
) -> dict:
    """Build a mock Candid service line matching the real API schema."""
    line: dict = {
        "procedure_code": procedure_code,
        "charge_amount_cents": charge_amount_cents,
        "date_of_service_range": {"start_date": date_of_service},
        "service_line_era_data": {
            "service_line_adjustments": era_adjustments or [],
            "remittance_advice_remark_codes": [],
        },
        "service_line_manual_adjustments": manual_adjustments or [],
    }
    if primary_paid_amount_cents is not None:
        line["primary_paid_amount_cents"] = primary_paid_amount_cents
    if allowed_amount_cents is not None:
        line["allowed_amount_cents"] = allowed_amount_cents
    if secondary_paid_amount_cents is not None:
        line["secondary_paid_amount_cents"] = secondary_paid_amount_cents
    if tertiary_paid_amount_cents is not None:
        line["tertiary_paid_amount_cents"] = tertiary_paid_amount_cents
    if deductible_cents is not None:
        line["deductible_cents"] = deductible_cents
    if coinsurance_cents is not None:
        line["coinsurance_cents"] = coinsurance_cents
    if copay_cents is not None:
        line["copay_cents"] = copay_cents
    if insurance_balance_cents is not None:
        line["insurance_balance_cents"] = insurance_balance_cents
    if patient_balance_cents is not None:
        line["patient_balance_cents"] = patient_balance_cents
    return line


CANVAS_CLAIM_ID = "00000000-0000-0000-0000-000000000001"


def _encounter_response(
    service_lines: list[dict],
    eras: list[dict] | None = None,
    status: str = "era_received",
) -> dict:
    """Build a mock encounter response matching Candid's actual schema."""
    return {
        "encounter_id": "enc-abc",
        "claims": [
            {
                "claim_id": "candid-claim-1",
                "status": status,
                "service_lines": service_lines,
                "eras": eras or [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# _cents_to_dollars
# ---------------------------------------------------------------------------


def test_cents_to_dollars_converts() -> None:
    assert _cents_to_dollars(10000) == Decimal("100.00")
    assert _cents_to_dollars(1) == Decimal("0.01")


def test_cents_to_dollars_none_and_zero() -> None:
    assert _cents_to_dollars(None) is None
    assert _cents_to_dollars(0) is None


# ---------------------------------------------------------------------------
# _match_line_item
# ---------------------------------------------------------------------------


def test_match_line_item_exact_match() -> None:
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-match")
    candid_line = _candid_service_line(
        procedure_code="99213", charge_amount_cents=10000
    )
    assert _match_line_item(candid_line, [li], CANVAS_CLAIM_ID) == "li-match"


def test_match_line_item_no_match() -> None:
    li = _fake_line_item("99214", Decimal("150.00"), "2026-01-15", "li-1")
    candid_line = _candid_service_line(
        procedure_code="99213", charge_amount_cents=10000
    )
    assert _match_line_item(candid_line, [li], CANVAS_CLAIM_ID) is None


def test_match_line_item_ambiguous() -> None:
    li1 = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    li2 = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-2")
    candid_line = _candid_service_line(
        procedure_code="99213", charge_amount_cents=10000
    )
    assert _match_line_item(candid_line, [li1, li2], CANVAS_CLAIM_ID) is None


# ---------------------------------------------------------------------------
# _build_insurance_transactions
# ---------------------------------------------------------------------------


def test_insurance_payment_from_service_line() -> None:
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    service_lines = [
        _candid_service_line(primary_paid_amount_cents=7000, allowed_amount_cents=9500)
    ]
    txns = _build_insurance_transactions(service_lines, [li], CANVAS_CLAIM_ID)
    assert len(txns) == 2
    assert txns[0].charged == Decimal("100.00")
    assert txns[0].allowed == Decimal("95.00")
    assert txns[0].payment == Decimal("70.00")
    # Contractual adjustment: $100 charged - $95 allowed = $5 write-off
    assert txns[1].adjustment == Decimal("5.00")
    assert txns[1].adjustment_code == "CO-45"
    assert txns[1].write_off is True


def test_insurance_manual_adjustments() -> None:
    """Manual adjustments (service_line_manual_adjustments) are picked up."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    service_lines = [
        _candid_service_line(
            primary_paid_amount_cents=7000,
            manual_adjustments=[
                {
                    "adjustment_amount_cents": 2500,
                    "adjustment_group_code": "CO",
                    "adjustment_reason_code": "45",
                },
            ],
        )
    ]
    txns = _build_insurance_transactions(service_lines, [li], CANVAS_CLAIM_ID)
    assert len(txns) == 2
    assert txns[1].adjustment == Decimal("25.00")
    assert txns[1].adjustment_code == "CO-45"


def test_insurance_era_adjustments() -> None:
    """ERA-reported adjustments (service_line_era_data) are picked up."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    service_lines = [
        _candid_service_line(
            primary_paid_amount_cents=7000,
            era_adjustments=[
                {
                    "adjustment_amount_cents": 3000,
                    "adjustment_group_code": "PR",
                    "adjustment_reason_code": "1",
                },
            ],
        )
    ]
    txns = _build_insurance_transactions(service_lines, [li], CANVAS_CLAIM_ID)
    assert len(txns) == 2
    assert txns[1].adjustment == Decimal("30.00")
    assert txns[1].adjustment_code == "PR-1"


def test_insurance_multi_service_line() -> None:
    """Each service line gets its own transactions with the correct claim_line_item_id."""
    li_1 = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    li_2 = _fake_line_item("99214", Decimal("150.00"), "2026-01-15", "li-2")
    service_lines = [
        _candid_service_line(
            procedure_code="99213",
            charge_amount_cents=10000,
            primary_paid_amount_cents=7000,
            allowed_amount_cents=9500,
            era_adjustments=[
                {
                    "adjustment_amount_cents": 500,
                    "adjustment_group_code": "CO",
                    "adjustment_reason_code": "45",
                },
            ],
        ),
        _candid_service_line(
            procedure_code="99214",
            charge_amount_cents=15000,
            primary_paid_amount_cents=12000,
            allowed_amount_cents=14000,
            era_adjustments=[
                {
                    "adjustment_amount_cents": 1000,
                    "adjustment_group_code": "CO",
                    "adjustment_reason_code": "45",
                },
            ],
        ),
    ]
    txns = _build_insurance_transactions(service_lines, [li_1, li_2], CANVAS_CLAIM_ID)
    # Per service line: payment + contractual CO-45 + ERA CO-45 = 3 txns × 2 lines = 6
    assert len(txns) == 6
    # First service line → li-1
    assert txns[0].claim_line_item_id == "li-1"
    assert txns[0].charged == Decimal("100.00")
    assert txns[0].payment == Decimal("70.00")
    assert txns[1].adjustment == Decimal("5.00")  # contractual write-off
    assert txns[1].adjustment_code == "CO-45"
    assert txns[1].write_off is True
    assert txns[2].adjustment == Decimal("5.00")  # ERA adjustment
    assert txns[2].adjustment_code == "CO-45"
    # Second service line → li-2
    assert txns[3].claim_line_item_id == "li-2"
    assert txns[3].charged == Decimal("150.00")
    assert txns[3].payment == Decimal("120.00")
    assert txns[4].adjustment == Decimal("10.00")  # contractual write-off
    assert txns[4].write_off is True
    assert txns[5].adjustment == Decimal("10.00")  # ERA adjustment


# ---------------------------------------------------------------------------
# sync_claim_adjudications (integration)
# ---------------------------------------------------------------------------


def test_sync_posts_from_era_and_schedules_verify() -> None:
    """Sync finds ERA on claim, posts insurance payment, schedules verify."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    encounters_meta = [{"candid_encounter_id": "enc-abc"}]
    claim = _fake_claim([li], metadata={"candid_encounters": encounters_meta})

    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=7000, allowed_amount_cents=9500
            )
        ],
        eras=[
            {"era_id": "era-1", "check_number": "CHK001", "check_date": "2026-01-20"}
        ],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        ce.post_payment.assert_called_once()
        assert (
            ce.post_payment.call_args.kwargs["claim_description"]
            == f"{ERA_DESC_PREFIX}era-1"
        )
        assert ce.post_payment.call_args.kwargs["check_number"] == "CHK001"

        # Dedup metadata written directly (no verify-sync)
        upsert_calls = ce.upsert_metadata.call_args_list
        era_meta = [c for c in upsert_calls if c.kwargs.get("key") == META_SYNCED_ERA_IDS]
        assert len(era_meta) == 1


def test_sync_skips_already_synced_era() -> None:
    """ERA ID in metadata is skipped."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    encounters_meta = [{"candid_encounter_id": "enc-abc"}]
    claim = _fake_claim(
        [li],
        metadata={
            "candid_encounters": encounters_meta,
            META_SYNCED_ERA_IDS: ["era-1"],
        },
    )

    encounter = _encounter_response(
        service_lines=[_candid_service_line(primary_paid_amount_cents=7000)],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        ce.post_payment.assert_not_called()


def test_sync_skips_when_no_encounters_metadata() -> None:
    """No encounters metadata → early return, no SyncLog written."""
    claim = _fake_claim([], metadata={})

    with patch("candid.adjudication_sync.ClaimEffect"):
        effects = sync_claim_adjudications(claim, MOCK_SECRETS)

    assert len(effects) == 0


def test_sync_posts_patient_payment() -> None:
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    encounters_meta = [{"candid_encounter_id": "enc-abc"}]
    claim = _fake_claim(
        [li],
        metadata={
            "candid_encounters": encounters_meta,
            META_SYNCED_ERA_IDS: ["era-1"],
        },
    )

    encounter = _encounter_response(
        service_lines=[_candid_service_line()],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = [
            {"patient_payment_id": "pay-1", "amount_cents": 2500},
        ]
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        ce.post_payment.assert_called_once()
        assert ce.post_payment.call_args.kwargs["claim_coverage_id"] == "patient"

        # Dedup metadata written directly
        upsert_calls = ce.upsert_metadata.call_args_list
        pmt_meta = [c for c in upsert_calls if c.kwargs.get("key") == META_SYNCED_PAYMENT_IDS]
        assert len(pmt_meta) == 1


def test_sync_skips_already_synced_patient_payment() -> None:
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    encounters_meta = [{"candid_encounter_id": "enc-abc"}]
    claim = _fake_claim(
        [li],
        metadata={
            "candid_encounters": encounters_meta,
            META_SYNCED_ERA_IDS: ["era-1"],
            META_SYNCED_PAYMENT_IDS: ["pay-1"],
        },
    )

    encounter = _encounter_response(
        service_lines=[_candid_service_line()],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = [
            {"patient_payment_id": "pay-1", "amount_cents": 2500},
        ]
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        ce.post_payment.assert_not_called()


def test_sync_extracts_status_from_claim() -> None:
    """Claim status comes from claims[].status, not encounter-level."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    encounters_meta = [{"candid_encounter_id": "enc-abc"}]
    claim = _fake_claim([li], metadata={"candid_encounters": encounters_meta})

    encounter = _encounter_response(
        service_lines=[_candid_service_line()],
        eras=[],
        status="finalized_paid",
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner") as mock_banner,
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []

        sync_claim_adjudications(claim, MOCK_SECRETS)

        # Banner should reflect the claim status
        mock_banner.assert_called_once()
        assert mock_banner.call_args.kwargs["claim_status"] == "finalized_paid"


# ---------------------------------------------------------------------------
# _determine_target_queue
# ---------------------------------------------------------------------------


def _balance_encounter(insurance: int, patient: int) -> dict:
    return {
        "claims": [
            {
                "service_lines": [
                    {
                        "insurance_balance_cents": insurance,
                        "patient_balance_cents": patient,
                    }
                ]
            }
        ]
    }


def test_determine_target_queue_patient_only_balance() -> None:
    queue = _determine_target_queue(_balance_encounter(insurance=0, patient=2500))
    assert queue == ClaimQueues.PATIENT_BALANCE.label


def test_determine_target_queue_insurance_only_balance() -> None:
    queue = _determine_target_queue(_balance_encounter(insurance=4000, patient=0))
    assert queue == ClaimQueues.ADJUDICATED_OPEN_BALANCE.label


def test_determine_target_queue_both_balances() -> None:
    queue = _determine_target_queue(_balance_encounter(insurance=4000, patient=2500))
    assert queue == ClaimQueues.ADJUDICATED_OPEN_BALANCE.label


def test_determine_target_queue_zero_balances() -> None:
    queue = _determine_target_queue(_balance_encounter(insurance=0, patient=0))
    assert queue == ClaimQueues.ADJUDICATED_OPEN_BALANCE.label


def test_determine_target_queue_sums_across_service_lines() -> None:
    """Balances sum across all service lines in all claims of an encounter."""
    encounter = {
        "claims": [
            {
                "service_lines": [
                    {"insurance_balance_cents": 0, "patient_balance_cents": 1000},
                    {"insurance_balance_cents": 0, "patient_balance_cents": 1500},
                ]
            }
        ]
    }
    assert _determine_target_queue(encounter) == ClaimQueues.PATIENT_BALANCE.label


# ---------------------------------------------------------------------------
# Secondary/tertiary insurance posting (integration through sync_claim_adjudications)
# ---------------------------------------------------------------------------


def test_sync_posts_secondary_insurance_payment() -> None:
    """When a claim has a secondary coverage and ERA reports secondary payment,
    a separate post_payment runs with claim_coverage_id == secondary.id."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim(
        [li],
        coverages=[
            _fake_coverage("cov-primary", "Primary"),
            _fake_coverage("cov-secondary", "Secondary"),
        ],
        metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]},
    )
    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=7000,
                secondary_paid_amount_cents=2000,
            )
        ],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        coverage_ids = [c.kwargs["claim_coverage_id"] for c in ce.post_payment.call_args_list]
        assert "cov-primary" in coverage_ids
        assert "cov-secondary" in coverage_ids


def test_sync_posts_tertiary_insurance_payment() -> None:
    """Tertiary payment posts under the tertiary coverage_id."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim(
        [li],
        coverages=[
            _fake_coverage("cov-primary", "Primary"),
            _fake_coverage("cov-secondary", "Secondary"),
            _fake_coverage("cov-tertiary", "Tertiary"),
        ],
        metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]},
    )
    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=7000,
                tertiary_paid_amount_cents=500,
            )
        ],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        coverage_ids = [c.kwargs["claim_coverage_id"] for c in ce.post_payment.call_args_list]
        assert "cov-tertiary" in coverage_ids


def test_sync_skips_secondary_when_no_secondary_coverage() -> None:
    """Secondary paid amount with no secondary coverage on claim → skipped, not posted."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim(
        [li],
        metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]},
    )
    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=7000,
                secondary_paid_amount_cents=2000,
            )
        ],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        coverage_ids = [c.kwargs["claim_coverage_id"] for c in ce.post_payment.call_args_list]
        # only primary should post
        assert coverage_ids == ["cov-primary"]


# ---------------------------------------------------------------------------
# Patient responsibility (integration)
# ---------------------------------------------------------------------------


def test_sync_does_not_create_separate_patient_posting_for_pr() -> None:
    """Patient responsibility (deductible/coinsurance/copay) does NOT create a separate patient posting.

    The balance transfer to patient is handled by ``transfer_remaining_balance_to="patient"``
    on the insurance posting's adjustments, not by a separate patient posting.
    """
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim(
        [li],
        metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]},
    )
    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=7000,
                deductible_cents=1500,
                coinsurance_cents=500,
                copay_cents=2000,
            )
        ],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        # Only insurance posting, no separate patient posting
        patient_calls = [
            c for c in ce.post_payment.call_args_list
            if c.kwargs["claim_coverage_id"] == "patient"
        ]
        assert len(patient_calls) == 0

        # Insurance posting should exist
        insurance_calls = [
            c for c in ce.post_payment.call_args_list
            if c.kwargs["claim_coverage_id"] != "patient"
        ]
        assert len(insurance_calls) == 1


# ---------------------------------------------------------------------------
# Multi-encounter / cross-encounter dedup
# ---------------------------------------------------------------------------


def test_sync_dedupes_patient_payment_across_encounters() -> None:
    """Same patient_payment_id returned by both encounters → posted only once."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    encounters_meta = [
        {"candid_encounter_id": "enc-1"},
        {"candid_encounter_id": "enc-2"},
    ]
    claim = _fake_claim([li], metadata={"candid_encounters": encounters_meta})

    encounter_1 = _encounter_response(
        service_lines=[_candid_service_line()], eras=[]
    )
    encounter_2 = _encounter_response(
        service_lines=[_candid_service_line()], eras=[]
    )
    encounter_2["claims"][0]["claim_id"] = "candid-claim-2"

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        client_mock = MC.from_secrets.return_value
        client_mock.get_encounter.side_effect = [encounter_1, encounter_2]
        # Same payment_id appears under both Candid claim_ids
        client_mock.get_patient_payments.return_value = [
            {"patient_payment_id": "pay-shared", "amount_cents": 2500},
        ]
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        patient_payment_calls = [
            c for c in ce.post_payment.call_args_list
            if c.kwargs["claim_coverage_id"] == "patient"
        ]
        assert len(patient_payment_calls) == 1


# ---------------------------------------------------------------------------
# Resilience: encounter / patient-payment fetch failures
# ---------------------------------------------------------------------------


def test_sync_skips_encounter_on_fetch_failure_and_continues() -> None:
    """If get_encounter raises on encounter A, encounter B still gets processed."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    encounters_meta = [
        {"candid_encounter_id": "enc-broken"},
        {"candid_encounter_id": "enc-ok"},
    ]
    claim = _fake_claim([li], metadata={"candid_encounters": encounters_meta})

    encounter_ok = _encounter_response(
        service_lines=[_candid_service_line(primary_paid_amount_cents=7000)],
        eras=[{"era_id": "era-ok"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        client_mock = MC.from_secrets.return_value
        client_mock.get_encounter.side_effect = [
            RuntimeError("boom"),
            encounter_ok,
        ]
        client_mock.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        # Effect generated only from encounter_ok
        ce.post_payment.assert_called_once()
        assert (
            ce.post_payment.call_args.kwargs["claim_description"]
            == f"{ERA_DESC_PREFIX}era-ok"
        )


def test_sync_continues_when_patient_payments_fetch_fails() -> None:
    """get_patient_payments raising does not blow up ERA processing for the same encounter."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim(
        [li],
        metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]},
    )
    encounter = _encounter_response(
        service_lines=[_candid_service_line(primary_paid_amount_cents=7000)],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.SyncLog"),
    ):
        client_mock = MC.from_secrets.return_value
        client_mock.get_encounter.return_value = encounter
        client_mock.get_patient_payments.side_effect = RuntimeError("boom")
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        # ERA payment was still posted
        ce.post_payment.assert_called_once()
        assert (
            ce.post_payment.call_args.kwargs["claim_description"]
            == f"{ERA_DESC_PREFIX}era-1"
        )
