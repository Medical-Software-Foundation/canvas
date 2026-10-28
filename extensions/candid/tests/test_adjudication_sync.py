"""Tests for Candid adjudication sync logic."""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from candid.adjudication_sync import (
    PR_COINSURANCE,
    PR_COPAY,
    PR_DEDUCTIBLE,
    TRANSFER_CODE,
    _build_insurance_transactions,
    _cents_to_dollars,
    _coverage_balance_by_line,
    _determine_target_queue,
    _match_line_item,
    sync_claim_adjudications,
)
from canvas_sdk.v1.data.claim import ClaimQueues
from candid.effect_helpers import (
    ERA_DESC_PREFIX,
    META_SYNCED_AMOUNTS,
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
    dbid: int = 101,
) -> MagicMock:
    li = MagicMock()
    li.proc_code = proc_code
    li.charge = charge
    li.from_date = from_date
    li.id = li_id
    li.dbid = dbid
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


def test_match_line_item_skips_supplemental_overflow() -> None:
    """A supplemental-split 99499 placeholder ($0.01) is not a real charge and
    must not be index-matched to a Canvas line item."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    overflow = _candid_service_line(procedure_code="99499", charge_amount_cents=1)
    assert _match_line_item(overflow, [li], CANVAS_CLAIM_ID, index=0) is None


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


def test_contractual_uses_line_item_charge_not_era_charge() -> None:
    """ERA charge_amount often disagrees with the Canvas line item's charge;
    the contractual write-off is computed against the Canvas charge."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    # ERA reports a different charge ($120) than the Canvas line item ($100).
    service_lines = [
        _candid_service_line(
            charge_amount_cents=12000,
            primary_paid_amount_cents=7000,
            allowed_amount_cents=9500,
        )
    ]
    txns = _build_insurance_transactions(service_lines, [li], CANVAS_CLAIM_ID)
    assert len(txns) == 2
    # The "charged" reported on the txn still echoes the ERA value.
    assert txns[0].charged == Decimal("120.00")
    # But the contractual write-off uses the Canvas line item's charge:
    # $100 charged - $95 allowed = $5 (not $120 - $95 = $25).
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
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        ce.post_payment.assert_not_called()


def test_sync_skips_when_no_encounters_metadata() -> None:
    """No encounters metadata → early return, no sync history written."""
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


def test_insurance_pr_transfers_to_given_target() -> None:
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    service_lines = [
        _candid_service_line(
            primary_paid_amount_cents=7000,
            deductible_cents=1500,
            coinsurance_cents=500,
            copay_cents=2000,
        )
    ]

    default_txns = _build_insurance_transactions(service_lines, [li], CANVAS_CLAIM_ID)
    secondary_txns = _build_insurance_transactions(
        service_lines, [li], CANVAS_CLAIM_ID, pr_transfer_to="cov-secondary"
    )

    def pr_targets(txns: list) -> dict[str, str]:
        return {
            t.adjustment_code: t.transfer_remaining_balance_to
            for t in txns
            if t.adjustment_code in (PR_DEDUCTIBLE, PR_COINSURANCE, PR_COPAY)
        }

    assert pr_targets(default_txns) == dict.fromkeys(
        (PR_DEDUCTIBLE, PR_COINSURANCE, PR_COPAY), "patient"
    )
    assert pr_targets(secondary_txns) == dict.fromkeys(
        (PR_DEDUCTIBLE, PR_COINSURANCE, PR_COPAY), "cov-secondary"
    )


def _sync_pr_transfer_targets(coverages: list, eras: list[dict]) -> list:
    """Run a sync for a claim with PR amounts; return each PR txn's transfer target."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim(
        [li],
        coverages=coverages,
        metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]},
    )
    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=7000,
                allowed_amount_cents=9500,
                coinsurance_cents=2000,
                copay_cents=500,
            )
        ],
        eras=eras,
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        primary_call = next(
            c
            for c in ce.post_payment.call_args_list
            if c.kwargs["claim_coverage_id"] == "cov-primary"
        )
        return [
            t.transfer_remaining_balance_to
            for t in primary_call.kwargs["line_item_transactions"]
            if t.adjustment_code in (PR_COINSURANCE, PR_COPAY)
        ]


def test_sync_moves_pr_to_secondary_when_claim_has_secondary() -> None:
    targets = _sync_pr_transfer_targets(
        coverages=[
            _fake_coverage("cov-primary", "Primary"),
            _fake_coverage("cov-secondary", "Secondary"),
        ],
        eras=[{"era_id": "era-1"}],
    )

    assert targets == ["cov-secondary", "cov-secondary"]


def test_sync_moves_pr_to_patient_without_secondary() -> None:
    targets = _sync_pr_transfer_targets(
        coverages=[_fake_coverage("cov-primary", "Primary")],
        eras=[{"era_id": "era-1"}],
    )

    assert targets == ["patient", "patient"]


# ---------------------------------------------------------------------------
# Secondary leftover (what the secondary didn't pay)
# ---------------------------------------------------------------------------


def _txn(line_dbid: int, amount: str, write_off: bool = False) -> MagicMock:
    txn = MagicMock()
    txn.billing_line_item_id = line_dbid
    txn.amount = Decimal(amount)
    txn.write_off = write_off
    return txn


def _fake_secondary(
    transferred_in: list | None = None,
    payments: list | None = None,
    adjustments: list | None = None,
    transfers_out: list | None = None,
) -> MagicMock:
    """A secondary coverage whose Canvas balance comes from these transactions."""
    cov = _fake_coverage("cov-secondary", "Secondary")
    cov.transfers.active.return_value.filter.return_value = transferred_in or []
    posting = MagicMock()
    posting.newlineitempayments.active.return_value = payments or []
    posting.newlineitemadjustments.active.return_value = adjustments or []
    posting.lineitemtransfers.active.return_value = transfers_out or []
    cov.postings.active.return_value = [posting]
    return cov


def test_coverage_balance_by_line() -> None:
    cov = _fake_secondary(
        transferred_in=[_txn(101, "20.00"), _txn(102, "10.00")],
        payments=[_txn(101, "15.00")],
        adjustments=[_txn(101, "2.00", write_off=True), _txn(101, "3.00")],
        transfers_out=[_txn(101, "1.00")],
    )

    # A non-write-off adjustment doesn't change what the coverage owes.
    assert _coverage_balance_by_line(cov) == {
        101: Decimal("2.00"),
        102: Decimal("10.00"),
    }


def _sync_secondary_posting(
    secondary: MagicMock,
    next_responsible: str,
    metadata: dict | None = None,
    eras: list[dict] | None = None,
    secondary_paid_cents: int = 1500,
    service_lines: list[dict] | None = None,
) -> list:
    """Sync a claim with a $20 coinsurance and the secondary's ERA; return its txns."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1", dbid=101)
    claim = _fake_claim(
        [li],
        coverages=[_fake_coverage("cov-primary", "Primary"), secondary],
        metadata={
            "candid_encounters": [{"candid_encounter_id": "enc-abc"}],
            **(metadata or {}),
        },
    )
    encounter = _encounter_response(
        service_lines=service_lines
        or [
            _candid_service_line(
                primary_paid_amount_cents=7000,
                allowed_amount_cents=9000,
                coinsurance_cents=2000,
                secondary_paid_amount_cents=secondary_paid_cents,
            )
        ],
        eras=eras or [{"era_id": "era-1"}, {"era_id": "era-2"}],
    )
    encounter["next_responsible_party"] = next_responsible

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        secondary_call = next(
            c
            for c in ce.post_payment.call_args_list
            if c.kwargs["claim_coverage_id"] == "cov-secondary"
        )
        return secondary_call.kwargs["line_item_transactions"]


# The primary was posted on an earlier sync; only the secondary's ERA is new.
PRIMARY_ALREADY_POSTED = {
    META_SYNCED_ERA_IDS: ["era-1"],
    "candid_synced_amounts": {"primary": 7000, "secondary": 0, "tertiary": 0},
}


def test_secondary_leftover_moves_to_patient_when_candid_says_patient() -> None:
    txns = _sync_secondary_posting(
        _fake_secondary(transferred_in=[_txn(101, "20.00")]),
        next_responsible="patient",
        metadata=PRIMARY_ALREADY_POSTED,
    )

    assert txns[0].payment == Decimal("15.00")
    assert txns[1].adjustment == Decimal("5.00")
    assert txns[1].adjustment_code == TRANSFER_CODE
    assert txns[1].transfer_remaining_balance_to == "patient"


def test_secondary_leftover_stays_when_candid_says_nobody_owes() -> None:
    txns = _sync_secondary_posting(
        _fake_secondary(transferred_in=[_txn(101, "20.00")]),
        next_responsible="none",
        metadata=PRIMARY_ALREADY_POSTED,
    )

    assert [t.payment for t in txns] == [Decimal("15.00")]


def test_secondary_leftover_moves_when_the_secondary_pays_nothing() -> None:
    """A secondary denial pays $0, so its ERA is the only sign it adjudicated."""
    txns = _sync_secondary_posting(
        _fake_secondary(transferred_in=[_txn(101, "20.00")]),
        next_responsible="patient",
        metadata=PRIMARY_ALREADY_POSTED,
        secondary_paid_cents=0,
    )

    assert [
        (t.payment, t.adjustment, t.adjustment_code, t.transfer_remaining_balance_to)
        for t in txns
    ] == [(None, Decimal("20.00"), TRANSFER_CODE, "patient")]


def test_secondary_leftover_counts_pr_moved_in_the_same_sync() -> None:
    """Primary and secondary ERAs arrive together: PR moves to the secondary, then
    the secondary's leftover moves on to the patient."""
    txns = _sync_secondary_posting(_fake_secondary(), next_responsible="patient")

    leftover = [t for t in txns if t.adjustment_code == TRANSFER_CODE]
    assert [(t.adjustment, t.transfer_remaining_balance_to) for t in leftover] == [
        (Decimal("5.00"), "patient")
    ]


def test_secondary_leftover_moves_once_when_candid_lines_share_a_canvas_line() -> None:
    """Two Candid lines match the one Canvas line; its $20 balance moves on once."""
    txns = _sync_secondary_posting(
        _fake_secondary(transferred_in=[_txn(101, "20.00")]),
        next_responsible="patient",
        metadata=PRIMARY_ALREADY_POSTED,
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=3500,
                coinsurance_cents=1000,
                secondary_paid_amount_cents=1500,
            ),
            _candid_service_line(
                primary_paid_amount_cents=3500,
                coinsurance_cents=1000,
                secondary_paid_amount_cents=0,
            ),
        ],
    )

    assert [
        (t.payment, t.adjustment, t.adjustment_code, t.transfer_remaining_balance_to)
        for t in txns
    ] == [
        (Decimal("15.00"), None, None, None),
        (None, Decimal("5.00"), TRANSFER_CODE, "patient"),
    ]


def test_secondary_leftover_skips_when_balance_was_never_on_the_secondary() -> None:
    """Claims posted before this fix left PR on the patient; don't move it twice."""
    txns = _sync_secondary_posting(
        _fake_secondary(),
        next_responsible="patient",
        metadata=PRIMARY_ALREADY_POSTED,
    )

    assert [t.payment for t in txns] == [Decimal("15.00")]


def test_pr_stays_on_secondary_until_the_secondary_adjudicates() -> None:
    """Primary-only ERA: PR waits on the secondary even when Candid says patient."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1", dbid=101)
    claim = _fake_claim(
        [li],
        coverages=[_fake_coverage("cov-primary", "Primary"), _fake_secondary()],
        metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]},
    )
    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=7000,
                allowed_amount_cents=9000,
                coinsurance_cents=2000,
            )
        ],
        eras=[{"era_id": "era-1"}],
    )
    encounter["next_responsible_party"] = "patient"

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        coverage_ids = [
            c.kwargs["claim_coverage_id"] for c in ce.post_payment.call_args_list
        ]
        assert coverage_ids == ["cov-primary"]


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


SPLIT_ENCOUNTERS = [
    {"split": 1, "candid_encounter_id": "enc-1"},
    {"split": 2, "candid_encounter_id": "enc-2"},
]


def _overflow_encounter(status: str, eras: list[dict] | None = None) -> dict:
    """Split 2 of a claim with over 12 diagnoses: only the $0.01 99499 placeholder."""
    encounter = _encounter_response(
        service_lines=[
            _candid_service_line(
                procedure_code="99499",
                charge_amount_cents=1,
                insurance_balance_cents=1,
            )
        ],
        eras=eras,
        status=status,
    )
    encounter["claims"][0]["claim_id"] = "candid-claim-2"
    return encounter


def test_split_claim_queue_and_status_follow_split_1() -> None:
    """The overflow split is synced last, but split 1 decides the queue and banner."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim([li], metadata={"candid_encounters": SPLIT_ENCOUNTERS})
    split_1 = _encounter_response(
        service_lines=[
            _candid_service_line(
                primary_paid_amount_cents=6000,
                allowed_amount_cents=8000,
                deductible_cents=2000,
                insurance_balance_cents=0,
                patient_balance_cents=2000,
            )
        ],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner") as mock_banner,
    ):
        MC.from_secrets.return_value.get_encounter.side_effect = [
            split_1,
            _overflow_encounter(status="coded"),
        ]
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        ce.move_to_queue.assert_called_once_with(ClaimQueues.PATIENT_BALANCE.label)
        assert mock_banner.call_args.kwargs["claim_status"] == "era_received"


def test_overflow_split_era_keeps_split_1_synced_amounts() -> None:
    """A denial ERA for the overflow split posts nothing and doesn't zero the synced
    amounts, which would make split 1's next ERA re-post its primary payment."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim([li], metadata={"candid_encounters": SPLIT_ENCOUNTERS})
    split_1 = _encounter_response(
        service_lines=[_candid_service_line(primary_paid_amount_cents=7000)],
        eras=[{"era_id": "era-1"}],
    )

    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
    ):
        MC.from_secrets.return_value.get_encounter.side_effect = [
            split_1,
            _overflow_encounter(status="finalized_denied", eras=[{"era_id": "era-x"}]),
        ]
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        ce = MCE.return_value

        sync_claim_adjudications(claim, MOCK_SECRETS)

        assert [
            c.kwargs["claim_description"] for c in ce.post_payment.call_args_list
        ] == [f"{ERA_DESC_PREFIX}era-1"]
        upserts = {
            c.kwargs["key"]: c.kwargs["value"]
            for c in ce.upsert_metadata.call_args_list
        }
        assert json.loads(upserts[META_SYNCED_AMOUNTS]) == {
            "primary": 7000,
            "secondary": 0,
            "tertiary": 0,
        }
        assert json.loads(upserts[META_SYNCED_ERA_IDS]) == ["era-1", "era-x"]


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


# ---------------------------------------------------------------------------
# PLUGIN-498: patient payments Canvas sent to Candid, and split payments
# ---------------------------------------------------------------------------


def _patient_payment_sync(payments: list[dict], echo_exists: bool = False):
    """Run a full sync whose Candid claim returns ``payments``; return (ce, BulkPatientPosting mock)."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim(
        [li],
        metadata={
            "candid_encounters": [{"candid_encounter_id": "enc-abc"}],
            META_SYNCED_ERA_IDS: ["era-1"],
        },
    )
    encounter = _encounter_response(
        service_lines=[_candid_service_line()], eras=[{"era_id": "era-1"}]
    )
    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.BulkPatientPosting") as MBPP,
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = payments
        MBPP.objects.filter.return_value.exists.return_value = echo_exists
        sync_claim_adjudications(claim, MOCK_SECRETS)
        return MCE.return_value, MBPP


def _patient_postings(ce: MagicMock) -> list:
    return [
        c for c in ce.post_payment.call_args_list
        if c.kwargs["claim_coverage_id"] == "patient"
    ]


def test_sync_skips_payment_tagged_as_sent_from_canvas() -> None:
    """A payment Canvas reported is never imported, even with its ID missing from metadata."""
    from candid.effect_helpers import CANVAS_REPORTED_NOTE_TAG

    ce, MBPP = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-echo",
                "amount_cents": 16000,
                "payment_note": f"card {CANVAS_REPORTED_NOTE_TAG}",
                "allocations": [
                    {"amount_cents": 4000, "target": {"type": "claim", "claim_id": "candid-claim-1"}}
                ],
            }
        ]
    )

    assert _patient_postings(ce) == []
    MBPP.objects.filter.assert_not_called()


def test_sync_skips_untagged_payment_matching_a_canvas_collection() -> None:
    """Reported before the tag existed (the report timed out): matched by patient, total and time."""
    ce, MBPP = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-old-echo",
                "amount_cents": 16000,
                "patient_external_id": "canvas:patient-key-1",
                "payment_timestamp": "2026-09-01T14:18:11Z",
                "payment_note": "card",
                "allocations": [
                    {"amount_cents": 4000, "target": {"type": "claim", "claim_id": "candid-claim-1"}}
                ],
            }
        ],
        echo_exists=True,
    )

    assert _patient_postings(ce) == []
    kwargs = MBPP.objects.filter.call_args.kwargs
    assert kwargs["payer__id"] == "patient-key-1"
    assert kwargs["total_paid"] == Decimal("160.00")
    assert kwargs["created__gte"].isoformat() == "2026-09-01T14:16:11+00:00"
    assert kwargs["created__lte"].isoformat() == "2026-09-01T14:20:11+00:00"


def test_sync_posts_only_this_claims_share_of_a_split_payment() -> None:
    """A $160 Candid payment split over four claims posts $40 here, not $160."""
    ce, _ = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-split",
                "amount_cents": 16000,
                "patient_external_id": "canvas:patient-key-1",
                "payment_timestamp": "2026-09-01T14:18:11Z",
                "allocations": [
                    {"amount_cents": 4000, "target": {"type": "claim", "claim_id": "candid-claim-1"}},
                    {"amount_cents": 4000, "target": {"type": "claim", "claim_id": "candid-claim-2"}},
                    {"amount_cents": 4000, "target": {"type": "service_line", "claim_id": "candid-claim-3", "service_line_id": "sl-3"}},
                    {"amount_cents": 4000, "target": {"type": "claim", "claim_id": "candid-claim-4"}},
                ],
            }
        ]
    )

    postings = _patient_postings(ce)
    assert len(postings) == 1
    txns = postings[0].kwargs["line_item_transactions"]
    assert [t.payment for t in txns] == [Decimal("40.00")]


def test_sync_sums_service_line_allocations_on_the_same_claim() -> None:
    ce, _ = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-lines",
                "amount_cents": 3000,
                "allocations": [
                    {"amount_cents": 1000, "target": {"type": "service_line", "claim_id": "candid-claim-1", "service_line_id": "a"}},
                    {"amount_cents": 1500, "target": {"type": "service_line", "claim_id": "candid-claim-1", "service_line_id": "b"}},
                    {"amount_cents": 500, "target": {"type": "unattributed"}},
                ],
            }
        ]
    )

    txns = _patient_postings(ce)[0].kwargs["line_item_transactions"]
    assert [t.payment for t in txns] == [Decimal("25.00")]


def test_sync_skips_payment_with_nothing_allocated_to_this_claim() -> None:
    ce, _ = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-elsewhere",
                "amount_cents": 3000,
                "allocations": [
                    {"amount_cents": 3000, "target": {"type": "claim", "claim_id": "candid-claim-9"}}
                ],
            }
        ]
    )

    assert _patient_postings(ce) == []


def test_sync_posts_genuine_candid_payment_without_a_canvas_match() -> None:
    """No tag, no matching Canvas collection: a real Candid payment still posts."""
    ce, MBPP = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-real",
                "amount_cents": 2348,
                "patient_external_id": "canvas:patient-key-1",
                "payment_timestamp": "2026-10-16T20:50:00+00:00",
                "payment_note": "Paid on Candid portal",
                "allocations": [
                    {"amount_cents": 2348, "target": {"type": "claim", "claim_id": "candid-claim-1"}}
                ],
            }
        ],
        echo_exists=False,
    )

    MBPP.objects.filter.assert_called_once()
    txns = _patient_postings(ce)[0].kwargs["line_item_transactions"]
    assert [t.payment for t in txns] == [Decimal("23.48")]


def test_sync_skips_echo_check_without_patient_or_timestamp() -> None:
    """Missing patient or unparseable timestamp: no DB lookup, payment posts."""
    ce, MBPP = _patient_payment_sync(
        [
            {"patient_payment_id": "p1", "amount_cents": 500, "payment_timestamp": "2026-10-16T20:50:00Z"},
            {"patient_payment_id": "p2", "amount_cents": 500, "patient_external_id": "canvas:x", "payment_timestamp": "not a date"},
            {"patient_payment_id": "p3", "amount_cents": 500, "patient_external_id": "canvas:x", "payment_timestamp": "2026-10-16T20:50:00"},
        ]
    )

    assert len(_patient_postings(ce)) == 3
    # Only p3 (naive timestamp, read as UTC) reaches the lookup
    MBPP.objects.filter.assert_called_once()
    assert MBPP.objects.filter.call_args.kwargs["created__gte"].isoformat() == "2026-10-16T20:48:00+00:00"


# ---------------------------------------------------------------------------
# PLUGIN-496: inferred Medicare sequestration (CO-253)
# ---------------------------------------------------------------------------

SEQ_SECRETS = {**MOCK_SECRETS, "CANDID_POST_MEDICARE_SEQUESTRATION": "true"}


def _medicare_sync(
    service_lines: list[dict], secrets: dict, plan_type: str = "medicare"
) -> list:
    """Sync a new primary ERA; return the primary posting's transactions."""
    li = _fake_line_item("90836", Decimal("300.00"), "2026-01-15", "li-1")
    primary = _fake_coverage("cov-primary", "Primary")
    primary.payer_plan_type = plan_type
    claim = _fake_claim(
        [li], coverages=[primary], metadata={"candid_encounters": [{"candid_encounter_id": "enc-abc"}]}
    )
    encounter = _encounter_response(service_lines=service_lines, eras=[{"era_id": "era-1"}])
    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
    ):
        MC.from_secrets.return_value.get_encounter.return_value = encounter
        MC.from_secrets.return_value.get_patient_payments.return_value = []
        sync_claim_adjudications(claim, secrets)
        calls = [
            c for c in MCE.return_value.post_payment.call_args_list
            if c.kwargs["claim_coverage_id"] == "cov-primary"
        ]
    assert len(calls) == 1
    return calls[0].kwargs["line_item_transactions"]


def _adjustments(txns: list, code: str) -> list:
    return [t for t in txns if t.adjustment_code == code]


def test_sequestration_posts_co253_for_medicare_primary() -> None:
    """Medicare allowed $77.07, paid $60.43: 2/98 of the payment is $1.23, written off as CO-253."""
    txns = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=6043, allowed_amount_cents=7707)],
        SEQ_SECRETS,
    )

    seq = _adjustments(txns, "CO-253")
    assert [(t.adjustment, t.write_off) for t in seq] == [(Decimal("1.23"), True)]
    # The computed contractual stays single
    assert [t.adjustment for t in _adjustments(txns, "CO-45")] == [Decimal("222.93")]


def test_sequestration_matches_second_line_rounding() -> None:
    """$62.57 paid → 2/98 = 127.69 cents → $1.28 (rounds half up)."""
    txns = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=6257, allowed_amount_cents=7981)],
        SEQ_SECRETS,
    )

    assert [t.adjustment for t in _adjustments(txns, "CO-253")] == [Decimal("1.28")]


def test_sequestration_off_by_default() -> None:
    txns = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=6043, allowed_amount_cents=7707)],
        MOCK_SECRETS,
    )

    assert _adjustments(txns, "CO-253") == []


def test_sequestration_ignored_for_non_medicare_primary() -> None:
    """Medicare Advantage plans are typed commercial and get nothing inferred."""
    txns = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=6043, allowed_amount_cents=7707)],
        SEQ_SECRETS,
        plan_type="commercial",
    )

    assert _adjustments(txns, "CO-253") == []


def test_sequestration_not_inferred_when_payer_reports_253() -> None:
    """If Candid ever sends the 253 again, post the payer's, not a second one."""
    txns = _medicare_sync(
        [
            _candid_service_line(
                "90836", 30000, primary_paid_amount_cents=6043, allowed_amount_cents=7707,
                era_adjustments=[{"adjustment_group_code": "CO", "adjustment_reason_code": "253", "adjustment_amount_cents": 123}],
            )
        ],
        SEQ_SECRETS,
    )

    assert [t.adjustment for t in _adjustments(txns, "CO-253")] == [Decimal("1.23")]


def test_sequestration_skipped_for_unpaid_or_overfull_lines() -> None:
    """No payment (deductible), or an amount above what's left of allowed: nothing inferred."""
    unpaid = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=0, allowed_amount_cents=7707)],
        SEQ_SECRETS,
    )
    paid_in_full = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=7707, allowed_amount_cents=7707)],
        SEQ_SECRETS,
    )

    assert _adjustments(unpaid, "CO-253") == []
    assert _adjustments(paid_in_full, "CO-253") == []


def test_sequestration_setting_values() -> None:
    from candid.adjudication_sync import SEQUESTRATION_SETTING, _setting_enabled

    for value in ("true", "TRUE", " yes ", "1", "on"):
        assert _setting_enabled({SEQUESTRATION_SETTING: value}, SEQUESTRATION_SETTING)
    for value in ("", "false", "no", "0", None):
        assert not _setting_enabled({SEQUESTRATION_SETTING: value}, SEQUESTRATION_SETTING)


def test_sync_matches_encounter_external_id_allocations() -> None:
    """Create-form targets (as Mock Candid echoes them) match by Canvas claim ID."""
    ce, _ = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-mock",
                "amount_cents": 3000,
                "allocations": [
                    {"amount_cents": 1200, "target": {"type": "claim_by_encounter_external_id", "value": "canvas:00000000-0000-0000-0000-000000000001"}},
                    {"amount_cents": 1800, "target": {"type": "claim_by_encounter_external_id", "value": "canvas:other-claim"}},
                ],
            }
        ]
    )

    txns = _patient_postings(ce)[0].kwargs["line_item_transactions"]
    assert [t.payment for t in txns] == [Decimal("12.00")]


def test_sync_posts_full_amount_when_no_allocation_names_a_claim() -> None:
    """Unknown target shapes fall back to the old full-amount posting."""
    ce, _ = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-odd",
                "amount_cents": 3000,
                "allocations": [{"amount_cents": 3000, "target": {"type": "something_new", "id": "x"}}],
            }
        ]
    )

    txns = _patient_postings(ce)[0].kwargs["line_item_transactions"]
    assert [t.payment for t in txns] == [Decimal("30.00")]


def test_sequestration_counts_reported_patient_responsibility() -> None:
    """Allowed fully explained by payment + PR (Mock Candid's standard remit): no CO-253."""
    explained = _medicare_sync(
        [_candid_service_line("90836", 10000, primary_paid_amount_cents=6000, allowed_amount_cents=8000,
                              deductible_cents=1000, coinsurance_cents=1000)],
        SEQ_SECRETS,
    )
    leftover = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=6043, allowed_amount_cents=7707,
                              coinsurance_cents=1541)],
        SEQ_SECRETS,
    )

    assert _adjustments(explained, "CO-253") == []
    assert [t.adjustment for t in _adjustments(leftover, "CO-253")] == [Decimal("1.23")]


def test_sync_skips_echo_lookup_when_nothing_is_allocated_here() -> None:
    """No share on this claim: no BulkPatientPosting query at all."""
    ce, MBPP = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-other-claim",
                "amount_cents": 3000,
                "patient_external_id": "canvas:patient-key-1",
                "payment_timestamp": "2026-10-16T20:50:00Z",
                "allocations": [
                    {"amount_cents": 3000, "target": {"type": "claim", "claim_id": "candid-claim-9"}}
                ],
            }
        ]
    )

    assert _patient_postings(ce) == []
    MBPP.objects.filter.assert_not_called()


# ---------------------------------------------------------------------------
# Review fixes: overflow splits, empty allocations, saved echoes, rounding
# ---------------------------------------------------------------------------


def test_sync_posts_full_share_of_payment_split_over_overflow_encounters() -> None:
    """$60 on split 1's Candid claim + $40 on split 2's: one $100 posting, not $60."""
    li = _fake_line_item("99213", Decimal("100.00"), "2026-01-15", "li-1")
    claim = _fake_claim([li], metadata={"candid_encounters": SPLIT_ENCOUNTERS})
    enc1 = _encounter_response(service_lines=[_candid_service_line()], eras=[])
    enc2 = _encounter_response(service_lines=[_candid_service_line()], eras=[])
    enc2["claims"][0]["claim_id"] = "candid-claim-2"
    payment = {
        "patient_payment_id": "pay-split-overflow",
        "amount_cents": 10000,
        "allocations": [
            {"amount_cents": 6000, "target": {"type": "claim", "claim_id": "candid-claim-1"}},
            {"amount_cents": 4000, "target": {"type": "claim", "claim_id": "candid-claim-2"}},
        ],
    }
    with (
        patch("candid.adjudication_sync.CandidClient") as MC,
        patch("candid.adjudication_sync.ClaimEffect") as MCE,
        patch("candid.adjudication_sync.sync_banner"),
        patch("candid.adjudication_sync.BulkPatientPosting") as MBPP,
    ):
        MC.from_secrets.return_value.get_encounter.side_effect = [enc1, enc2]
        MC.from_secrets.return_value.get_patient_payments.return_value = [payment]
        MBPP.objects.filter.return_value.exists.return_value = False
        sync_claim_adjudications(claim, MOCK_SECRETS)
        postings = _patient_postings(MCE.return_value)

    assert len(postings) == 1
    assert [t.payment for t in postings[0].kwargs["line_item_transactions"]] == [Decimal("100.00")]


def test_sync_matches_split_encounter_external_ids() -> None:
    ce, _ = _patient_payment_sync(
        [
            {
                "patient_payment_id": "pay-split-ext",
                "amount_cents": 1000,
                "allocations": [
                    {"amount_cents": 1000, "target": {"type": "claim_by_encounter_external_id", "value": "canvas:00000000-0000-0000-0000-000000000001-2"}},
                ],
            }
        ]
    )

    txns = _patient_postings(ce)[0].kwargs["line_item_transactions"]
    assert [t.payment for t in txns] == [Decimal("10.00")]


def test_sync_posts_full_amount_for_empty_allocations() -> None:
    ce, _ = _patient_payment_sync(
        [{"patient_payment_id": "pay-empty", "amount_cents": 2500, "allocations": []}]
    )

    txns = _patient_postings(ce)[0].kwargs["line_item_transactions"]
    assert [t.payment for t in txns] == [Decimal("25.00")]


def test_sync_saves_skipped_canvas_payments_as_reported() -> None:
    """Tagged and matched echoes are saved to reported IDs so later syncs skip them free."""
    from candid.effect_helpers import (
        CANVAS_REPORTED_NOTE_TAG,
        META_REPORTED_PAYMENT_IDS,
    )

    ce, _ = _patient_payment_sync(
        [
            {"patient_payment_id": "pay-tagged", "amount_cents": 500, "payment_note": f"card {CANVAS_REPORTED_NOTE_TAG}"},
            {
                "patient_payment_id": "pay-matched",
                "amount_cents": 3000,
                "patient_external_id": "canvas:patient-key-1",
                "payment_timestamp": "2026-10-16T20:50:00Z",
            },
        ],
        echo_exists=True,
    )

    assert _patient_postings(ce) == []
    saved = [
        c.kwargs["value"] for c in ce.upsert_metadata.call_args_list
        if c.kwargs.get("key") == META_REPORTED_PAYMENT_IDS
    ]
    assert saved == [json.dumps(["pay-matched", "pay-tagged"])]


def test_sync_tagged_payment_skips_share_work_and_warning() -> None:
    """A tagged payment with an unknown target shape is skipped without the full-amount warning."""
    from candid.effect_helpers import CANVAS_REPORTED_NOTE_TAG

    with patch("candid.adjudication_sync.log") as mock_log:
        ce, _ = _patient_payment_sync(
            [
                {
                    "patient_payment_id": "pay-tagged-odd",
                    "amount_cents": 500,
                    "payment_note": f"card {CANVAS_REPORTED_NOTE_TAG}",
                    "allocations": [{"amount_cents": 500, "target": {"type": "something_new"}}],
                }
            ]
        )

    assert _patient_postings(ce) == []
    mock_log.warning.assert_not_called()


def test_sequestration_writes_off_remainder_when_medicare_rounded_down() -> None:
    """Estimate 53¢ but only 52¢ left (Medicare rounded its 2% down): write off the 52¢."""
    txns = _medicare_sync(
        [_candid_service_line("90836", 30000, primary_paid_amount_cents=2573, allowed_amount_cents=2625)],
        SEQ_SECRETS,
    )

    assert [t.adjustment for t in _adjustments(txns, "CO-253")] == [Decimal("0.52")]
