"""Pull adjudication data from Candid and generate Canvas posting effects.

Uses the encounter endpoint to get claim status, ERA data, and per-service-line
financial data (payments, adjustments, patient responsibility). Uses the
patient-payments endpoint for patient payment records.

Dedup IDs (synced ERA IDs, synced payment IDs) are written to claim metadata
in the same effect batch as the postings they cover.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect, LineItemTransaction, PaymentMethod
from canvas_sdk.v1.data import BulkPatientPosting, Claim
from canvas_sdk.v1.data.claim import ClaimQueues
from logger import log

from candid.api.broadcast import notify_claim_updated
from candid.api.client import CandidClient
from candid.api.payload_builder import OVERFLOW_CHARGE_CENTS, OVERFLOW_CPT_CODE
from candid.effect_helpers import (
    CANVAS_REPORTED_NOTE_TAG,
    DEFAULT_CLAIM_STATUS,
    ERA_DESC_PREFIX,
    META_CLAIM_STATUS,
    META_ENCOUNTERS,
    META_LAST_SYNC,
    META_REPORTED_PAYMENT_IDS,
    META_SUBMITTED_AT,
    META_SYNCED_AMOUNTS,
    META_SYNCED_ERA_IDS,
    META_SYNCED_PAYMENT_IDS,
    LOG_TYPE_SYNC,
    PATIENT_COVERAGE_ID,
    PATIENT_PAYMENT_DESC_PREFIX,
    active_coverages_ordered,
    append_sync_history,
    get_claim_metadata,
    get_claim_metadata_set,
    sync_banner,
)

# Patient-responsibility CARC codes
PR_DEDUCTIBLE = "PR-1"
PR_COINSURANCE = "PR-2"
PR_COPAY = "PR-3"
# Canvas's "Transfer" adjustment group, the code billers use for manual balance moves
TRANSFER_CODE = "TR-0"

# Medicare sequestration. Candid's encounter carries no CARCs for it (the
# per-line ERA adjustments come back empty), so it's inferred: Medicare pays
# 98% of its share, leaving 2/98 of what it paid unpaid on the primary.
SEQUESTRATION_CODE = "CO-253"
SEQUESTRATION_REASON = "253"
MEDICARE_PLAN_TYPE = "medicare"
# Opt-in per instance until billing confirms the inference everywhere.
SEQUESTRATION_SETTING = "CANDID_POST_MEDICARE_SEQUESTRATION"


def _cents_to_dollars(cents: int | None) -> Decimal | None:
    if cents is None or cents == 0:
        return None
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _match_line_item(
    candid_line: dict,
    line_items: list,
    canvas_claim_id: str,
    index: int | None = None,
) -> str | None:
    """Match a Candid service_line to a Canvas ClaimLineItem.

    Tries in order:
    1. ``external_id`` (set by the plugin at submission time)
    2. Exact ``procedure_code`` match
    3. Fallback: ``charge_amount`` + ``date_of_service`` (handles payer code remaps)
    4. Fallback: positional index (same order as submitted)
    """
    # Supplemental-split overflow placeholders (99499 at $0.01) don't correspond
    # to any Canvas line item — they exist only to carry diagnosis codes past
    # the CMS-1500 limit. Skip so their ERA adjustments aren't misrouted to
    # line_items[0] via the positional-index fallback.
    if (
        candid_line.get("procedure_code") == OVERFLOW_CPT_CODE
        and candid_line.get("charge_amount_cents") == OVERFLOW_CHARGE_CENTS
    ):
        return None

    # Pass 1: match on external_id (most reliable — set by the plugin)
    if external_id := candid_line.get("external_id"):
        match = next((li for li in line_items if str(li.id) == external_id), None)
        if match:
            return str(match.id)

    candid_proc = candid_line.get("procedure_code", "")
    candid_charge_cents = candid_line.get("charge_amount_cents")
    candid_dos = candid_line.get("date_of_service_range", {})
    candid_from_date = candid_dos.get("start_date") or candid_dos.get(
        "date_of_service"
    )
    candid_charge_dollars = _cents_to_dollars(candid_charge_cents)

    # Pass 2: match on procedure code
    if candid_proc:
        matches = [li for li in line_items if li.proc_code == candid_proc]

        # If ambiguous, narrow by date and charge
        if len(matches) > 1:
            narrowed = [
                li
                for li in matches
                if (
                    not candid_from_date
                    or str(li.from_date) == str(candid_from_date)
                )
                and (
                    candid_charge_dollars is None
                    or li.charge == candid_charge_dollars
                )
            ]
            if narrowed:
                matches = narrowed

        if len(matches) == 1:
            return str(matches[0].id)

        if len(matches) > 1:
            log.warning(
                f"Candid sync: ambiguous match for procedure {candid_proc} "
                f"on claim {canvas_claim_id} — {len(matches)} candidates, skipping"
            )
            return None

    # Pass 3: fallback on charge + date (handles payer code remaps like
    # 99487→G0023 where Candid changes the proc code after submission)
    if candid_charge_dollars is not None:
        matches = [
            li
            for li in line_items
            if li.charge == candid_charge_dollars
            and (
                not candid_from_date
                or str(li.from_date) == str(candid_from_date)
            )
        ]
        if len(matches) == 1:
            log.info(
                f"Candid sync: matched {candid_proc} to {matches[0].proc_code} "
                f"via charge+date fallback on claim {canvas_claim_id}"
            )
            return str(matches[0].id)

    # Pass 4: positional index fallback (same order as submitted)
    if index is not None and 0 <= index < len(line_items):
        li = line_items[index]
        log.info(
            f"Candid sync: matched {candid_proc} to {li.proc_code} "
            f"via index fallback (position {index}) on claim {canvas_claim_id}"
        )
        return str(li.id)

    log.warning(
        f"Candid sync: no match for procedure {candid_proc} "
        f"(charge={candid_charge_cents}c, date={candid_from_date}) "
        f"on claim {canvas_claim_id}"
    )
    return None


# ---------------------------------------------------------------------------
# Delta computation for cumulative service-line amounts
# ---------------------------------------------------------------------------


def _compute_synced_amounts(service_lines: list[dict]) -> dict[str, int]:
    """Sum the current cumulative amounts across all service lines.

    Returns ``{"primary": N, "secondary": N, "tertiary": N}`` in cents.
    """
    return {
        "primary": sum(
            sl.get("primary_paid_amount_cents") or 0 for sl in service_lines
        ),
        "secondary": sum(
            sl.get("secondary_paid_amount_cents") or 0 for sl in service_lines
        ),
        "tertiary": sum(
            sl.get("tertiary_paid_amount_cents") or 0 for sl in service_lines
        ),
    }


def _has_delta(
    current: dict[str, int], previously_synced: dict[str, int | None], tier: str
) -> bool:
    """Check if a payer tier has new amounts to post.

    Returns True when:
    - The tier was never synced before (previous is None) — even if current is 0
    - The current amount exceeds the previously synced amount
    """
    prev = previously_synced.get(tier)
    if prev is None:
        return True
    return current.get(tier, 0) > prev


# ---------------------------------------------------------------------------
# Transaction builders — from encounter service lines
# ---------------------------------------------------------------------------


def _sequestration_cents(paid_cents: int) -> int:
    """Medicare's 2% sequestration on a line it paid ``paid_cents`` on.

    2/98 of the payment, rounded half up, in whole-number math: the plugin
    sandbox doesn't allow importing decimal's rounding constants.
    """
    return (paid_cents * 2 + 49) // 98


def _build_insurance_transactions(
    service_lines: list[dict],
    line_items: list,
    canvas_claim_id: str,
    transfer_to: str | None = None,
    pr_transfer_to: str = PATIENT_COVERAGE_ID,
    sequestration: bool = False,
) -> list[LineItemTransaction]:
    """Build insurance payment + adjustment transactions from encounter service lines.

    When ``transfer_to`` is set (e.g. ``"patient"`` or a coverage UUID),
    adjustment transactions include ``transfer_remaining_balance_to`` so the
    remaining balance moves to the appropriate payer after insurance pays.
    Patient responsibility (deductible, coinsurance, copay) moves to
    ``pr_transfer_to``. With ``sequestration`` (a Medicare primary on an
    instance that opted in), each paid line also gets an inferred CO-253
    write-off unless the payer reported one.
    """
    txns: list[LineItemTransaction] = []
    line_items_by_id = {str(li.id): li for li in line_items}

    for idx, sl in enumerate(service_lines):
        line_item_id = _match_line_item(sl, line_items, canvas_claim_id, index=idx)
        if not line_item_id:
            continue

        charged = _cents_to_dollars(sl.get("charge_amount_cents"))
        allowed = _cents_to_dollars(sl.get("allowed_amount_cents"))
        payment = _cents_to_dollars(sl.get("primary_paid_amount_cents"))

        if charged or allowed or payment:
            txns.append(
                LineItemTransaction(
                    claim_line_item_id=line_item_id,
                    charged=charged,
                    allowed=allowed,
                    payment=payment or Decimal("0.00"),
                )
            )

        # Contractual adjustment: difference between the Canvas line item's
        # charge and the payer's allowed amount is the write-off the provider
        # agreed to per their payer contract. We use line_item.charge rather
        # than the ERA's charge_amount because the two often disagree.
        if allowed:
            line_item = line_items_by_id[line_item_id]
            if line_item.charge and line_item.charge > allowed:
                contractual = line_item.charge - allowed
                txns.append(
                    LineItemTransaction(
                        claim_line_item_id=line_item_id,
                        adjustment=contractual,
                        adjustment_code="CO-45",
                        write_off=True,
                    )
                )

        # Adjustments from ERA (payer-reported) and manual adjustments.
        # Both live on the service line but in different locations:
        #   - service_line_era_data.service_line_adjustments (from payer ERA)
        #   - service_line_manual_adjustments (entered manually)
        era_adjs = sl.get("service_line_era_data", {}).get(
            "service_line_adjustments", []
        )
        manual_adjs = sl.get("service_line_manual_adjustments", [])
        if sequestration:
            txns.extend(
                _sequestration_transactions(sl, line_item_id, era_adjs + manual_adjs)
            )
        for adj in era_adjs + manual_adjs:
            adj_amount = _cents_to_dollars(adj.get("adjustment_amount_cents"))
            group_code = adj.get("adjustment_group_code", "")
            reason_code = adj.get("adjustment_reason_code", "")
            adj_code = (
                f"{group_code}-{reason_code}" if group_code and reason_code else None
            )

            if adj_amount and adj_code:
                txns.append(
                    LineItemTransaction(
                        claim_line_item_id=line_item_id,
                        adjustment=adj_amount,
                        adjustment_code=adj_code,
                        transfer_remaining_balance_to=transfer_to,
                    )
                )

        for cents_field, pr_code in (
            ("deductible_cents", PR_DEDUCTIBLE),
            ("coinsurance_cents", PR_COINSURANCE),
            ("copay_cents", PR_COPAY),
        ):
            amount = _cents_to_dollars(sl.get(cents_field))
            if amount:
                txns.append(
                    LineItemTransaction(
                        claim_line_item_id=line_item_id,
                        adjustment=amount,
                        adjustment_code=pr_code,
                        transfer_remaining_balance_to=pr_transfer_to,
                    )
                )

    return txns


def _sequestration_transactions(
    sl: dict, line_item_id: str, reported_adjs: list[dict]
) -> list[LineItemTransaction]:
    """Inferred CO-253 write-off for one Medicare-paid service line, if any.

    Skipped when the payer reported a 253 itself, or when the inferred amount
    would exceed what's left of the allowed amount after Medicare's payment and
    the patient responsibility Candid reports.
    """
    if any(
        adj.get("adjustment_reason_code") == SEQUESTRATION_REASON
        for adj in reported_adjs
    ):
        return []
    paid_cents = sl.get("primary_paid_amount_cents") or 0
    allowed_cents = sl.get("allowed_amount_cents") or 0
    patient_cents = sum(
        sl.get(f) or 0 for f in ("deductible_cents", "coinsurance_cents", "copay_cents")
    )
    seq_cents = _sequestration_cents(paid_cents) if paid_cents > 0 else 0
    if not seq_cents or seq_cents > allowed_cents - paid_cents - patient_cents:
        return []
    return [
        LineItemTransaction(
            claim_line_item_id=line_item_id,
            adjustment=_cents_to_dollars(seq_cents),
            adjustment_code=SEQUESTRATION_CODE,
            write_off=True,
        )
    ]


def _build_secondary_transactions(
    service_lines: list[dict], line_items: list, canvas_claim_id: str, paid_field: str
) -> list[LineItemTransaction]:
    """Build payment transactions for secondary/tertiary payer."""
    txns: list[LineItemTransaction] = []
    for idx, sl in enumerate(service_lines):
        line_item_id = _match_line_item(sl, line_items, canvas_claim_id, index=idx)
        if not line_item_id:
            continue
        payment = _cents_to_dollars(sl.get(paid_field))
        if payment:
            txns.append(
                LineItemTransaction(claim_line_item_id=line_item_id, payment=payment)
            )
    return txns


def _coverage_balance_by_line(coverage: Any) -> dict[int, Decimal]:
    """Canvas's balance on ``coverage`` per claim line item, keyed by line dbid."""
    balances: dict[int, Decimal] = {}

    def add(line_dbid: int, amount: Decimal) -> None:
        balances[line_dbid] = balances.get(line_dbid, Decimal("0")) + amount

    # billing_line_item_id holds the ClaimLineItem dbid on every SDK version
    for transfer in coverage.transfers.active().filter(
        posting__entered_in_error__isnull=True
    ):
        add(transfer.billing_line_item_id, transfer.amount)
    for posting in coverage.postings.active():
        for payment in posting.newlineitempayments.active():
            add(payment.billing_line_item_id, -payment.amount)
        for adjustment in posting.newlineitemadjustments.active():
            if adjustment.write_off:
                add(adjustment.billing_line_item_id, -adjustment.amount)
        for transfer in posting.lineitemtransfers.active():
            add(transfer.billing_line_item_id, -transfer.amount)
    return balances


def _secondary_leftover_transactions(
    state: "_SyncState", service_lines: list[dict], next_responsible: str
) -> list[LineItemTransaction]:
    """Move what the secondary left unpaid to whoever Candid says owes the rest."""
    if next_responsible == "patient":
        target = PATIENT_COVERAGE_ID
    elif next_responsible == "tertiary" and state.tertiary_id:
        target = state.tertiary_id
    else:
        return []

    balances = _coverage_balance_by_line(state.secondary_coverage)
    dbid_by_line_id = {str(li.id): li.dbid for li in state.line_items}
    # Several Candid lines can match one Canvas line; its leftover moves once
    paid_by_line: dict[str, Decimal] = {}
    for idx, sl in enumerate(service_lines):
        line_item_id = _match_line_item(
            sl, state.line_items, state.canvas_claim_id, index=idx
        )
        if not line_item_id:
            continue
        paid = _cents_to_dollars(sl.get("secondary_paid_amount_cents")) or Decimal("0")
        paid_by_line[line_item_id] = paid_by_line.get(line_item_id, Decimal("0")) + paid

    txns: list[LineItemTransaction] = []
    for line_item_id, paid in paid_by_line.items():
        on_secondary = balances.get(
            dbid_by_line_id[line_item_id], Decimal("0")
        ) + state.moved_to_secondary.get(line_item_id, Decimal("0"))
        leftover = on_secondary - paid
        if leftover > 0:
            txns.append(
                LineItemTransaction(
                    claim_line_item_id=line_item_id,
                    adjustment=leftover,
                    adjustment_code=TRANSFER_CODE,
                    transfer_remaining_balance_to=target,
                )
            )
    return txns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coverage_id_at(coverages_ordered: list, payer_order: int) -> str | None:
    if payer_order < len(coverages_ordered):
        return str(coverages_ordered[payer_order].id)
    return None


# How far a Candid payment's timestamp may be from a Canvas-collected payment
# for the same patient and amount and still count as Canvas's own payment.
ECHO_WINDOW = timedelta(minutes=10)


def _allocated_to(target: dict, candid_claim_id: str, canvas_claim_id: str) -> bool:
    """Whether an allocation target points at this claim.

    Candid answers with ``claim`` / ``service_line`` targets carrying
    ``claim_id``; the create-time ``claim_by_encounter_external_id`` form
    (which Mock Candid echoes back) is matched by the Canvas claim ID.
    """
    if target.get("type") == "claim_by_encounter_external_id":
        return target.get("value") == f"canvas:{canvas_claim_id}"
    return target.get("claim_id") == candid_claim_id


def _claim_share_cents(
    payment: dict, candid_claim_id: str, canvas_claim_id: str
) -> int:
    """Cents of a Candid patient payment allocated to one Candid claim.

    A payment split across several claims comes back from every claim's
    lookup, so posting its full ``amount_cents`` would count it once per claim.
    Falls back to the full amount when the response has no allocations, or
    when none of them names a claim.
    """
    allocations = payment.get("allocations")
    if allocations is None:
        return payment.get("amount_cents") or 0
    targets = [alloc.get("target") or {} for alloc in allocations]
    if allocations and not any(
        "claim_id" in t or t.get("type") == "claim_by_encounter_external_id"
        for t in targets
    ):
        # A target shape we don't know: post the full amount, as before,
        # rather than silently dropping a real payment.
        log.warning(
            f"Candid sync: patient payment {payment.get('patient_payment_id')} "
            f"has no claim-level allocation; posting its full amount"
        )
        return payment.get("amount_cents") or 0
    return sum(
        alloc.get("amount_cents") or 0
        for alloc in allocations
        if _allocated_to(alloc.get("target") or {}, candid_claim_id, canvas_claim_id)
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_canvas_payment(payment: dict) -> bool:
    """True if this Candid patient payment is one Canvas reported to Candid.

    Payments reported by this plugin carry ``CANVAS_REPORTED_NOTE_TAG``. Older
    ones don't, so also match a Canvas-collected payment for the same patient
    and total within ``ECHO_WINDOW`` of the Candid payment.
    """
    if CANVAS_REPORTED_NOTE_TAG in (payment.get("payment_note") or ""):
        return True
    patient_key = (payment.get("patient_external_id") or "").removeprefix("canvas:")
    paid_at = _parse_timestamp(payment.get("payment_timestamp"))
    total = _cents_to_dollars(payment.get("amount_cents"))
    if not (patient_key and paid_at and total):
        return False
    return BulkPatientPosting.objects.filter(
        payer__id=patient_key,
        total_paid=total,
        created__gte=paid_at - ECHO_WINDOW,
        created__lte=paid_at + ECHO_WINDOW,
    ).exists()


def _post_patient_payments(
    claim_effect: ClaimEffect,
    candid_payments: list[dict],
    known_payment_ids: set[str],
    first_line_id: str,
    candid_claim_id: str,
    canvas_claim_id: str,
) -> tuple[list[Effect], list[str]]:
    """Build post_payment effects for new patient payments on one Candid claim.

    Posts only the share each payment allocates to ``candid_claim_id`` and
    skips payments Canvas itself reported. Mutates ``known_payment_ids`` so
    callers across encounters/claims dedupe against payments already queued in
    this run. Returns ``(effects, attempted_payment_ids)``.
    """
    effects: list[Effect] = []
    attempted: list[str] = []
    for payment in candid_payments:
        payment_id = payment.get("patient_payment_id")
        if not payment_id or payment_id in known_payment_ids:
            continue

        if _is_canvas_payment(payment):
            log.info(
                f"Candid sync: skipping patient payment {payment_id}, "
                f"which Canvas reported to Candid"
            )
            continue

        amount_dollars = _cents_to_dollars(
            _claim_share_cents(payment, candid_claim_id, canvas_claim_id)
        )
        if not amount_dollars:
            continue

        description = f"{PATIENT_PAYMENT_DESC_PREFIX}{payment_id}"
        effects.append(
            claim_effect.post_payment(
                claim_coverage_id=PATIENT_COVERAGE_ID,
                line_item_transactions=[
                    LineItemTransaction(
                        claim_line_item_id=first_line_id,
                        payment=amount_dollars,
                    )
                ],
                method=PaymentMethod.OTHER,
                claim_description=description,
                payment_description=description,
            )
        )
        attempted.append(payment_id)
        known_payment_ids.add(payment_id)
    return effects, attempted


def _era_kwargs(era: dict) -> dict:
    """Extract check_number / check_date kwargs for ``post_payment`` from an ERA."""
    kwargs: dict = {}
    if era.get("check_number"):
        kwargs["check_number"] = str(era["check_number"])
    if era.get("check_date"):
        try:
            kwargs["check_date"] = date.fromisoformat(era["check_date"])
        except (ValueError, TypeError):
            pass
    return kwargs


def _era_at(all_eras: list[dict], index: int) -> dict:
    """Get the ERA at the given payer-tier index, falling back to the last one."""
    if index < len(all_eras):
        return all_eras[index]
    return all_eras[-1]


def _determine_target_queue(encounter_data: dict) -> str:
    """Determine which Canvas queue the claim should move to based on balances.

    Sums ``insurance_balance_cents`` and ``patient_balance_cents`` across all
    service lines in the encounter:
    - Patient balance only (no insurance balance) → PatientBalance
    - Otherwise (insurance balance remaining, or both zero) → AdjudicatedOpenBalance
    """
    insurance_balance = 0
    patient_balance = 0
    for candid_claim in encounter_data.get("claims", []):
        for sl in candid_claim.get("service_lines", []):
            insurance_balance += sl.get("insurance_balance_cents") or 0
            patient_balance += sl.get("patient_balance_cents") or 0

    if insurance_balance == 0 and patient_balance > 0:
        return ClaimQueues.PATIENT_BALANCE.label
    return ClaimQueues.ADJUDICATED_OPEN_BALANCE.label


# ---------------------------------------------------------------------------
# Main sync functions
# ---------------------------------------------------------------------------


@dataclass
class _SyncState:
    """Accumulates effects and metadata while syncing a single Canvas claim.

    Holds both the read-once configuration (coverages, dedup ID sets, line
    items) and the mutable accumulators that build up across the encounters /
    Candid claims being processed.
    """

    canvas_claim_id: str
    claim_effect: ClaimEffect
    line_items: list
    first_line: Any | None
    primary_id: str | None
    secondary_id: str | None
    tertiary_id: str | None
    synced_era_ids: set[str]
    synced_pmt_ids: set[str]
    known_payment_ids: set[str]
    prev_synced_amounts: dict[str, int | None]
    post_sequestration: bool = False

    effects: list[Effect] = field(default_factory=list)
    attempted_era_ids: list[str] = field(default_factory=list)
    attempted_payment_ids: list[str] = field(default_factory=list)
    era_totals: dict[str, int] = field(default_factory=dict)
    payment_effect_count: int = 0
    claim_status: str = DEFAULT_CLAIM_STATUS
    primary_encounter_data: dict | None = None
    secondary_coverage: Any | None = None
    moved_to_secondary: dict[str, Decimal] = field(default_factory=dict)


def _setting_enabled(secrets: dict, key: str) -> bool:
    return (secrets.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}


def _init_sync_state(claim: Claim, secrets: dict | None = None) -> _SyncState:
    """Read the claim's coverages, line items, and dedup metadata into a state object."""
    canvas_claim_id = str(claim.id)
    line_items = list(claim.get_active_claim_line_items())
    coverages_ordered = active_coverages_ordered(claim)
    synced_pmt_ids = get_claim_metadata_set(claim, META_SYNCED_PAYMENT_IDS)
    reported_pmt_ids = get_claim_metadata_set(claim, META_REPORTED_PAYMENT_IDS)

    return _SyncState(
        canvas_claim_id=canvas_claim_id,
        claim_effect=ClaimEffect(claim_id=canvas_claim_id),
        line_items=line_items,
        first_line=line_items[0] if line_items else None,
        primary_id=_coverage_id_at(coverages_ordered, 0),
        secondary_id=_coverage_id_at(coverages_ordered, 1),
        tertiary_id=_coverage_id_at(coverages_ordered, 2),
        synced_era_ids=get_claim_metadata_set(claim, META_SYNCED_ERA_IDS),
        synced_pmt_ids=synced_pmt_ids,
        known_payment_ids=synced_pmt_ids | reported_pmt_ids,
        prev_synced_amounts=get_claim_metadata(claim, META_SYNCED_AMOUNTS)
        or {
            "primary": None,
            "secondary": None,
            "tertiary": None,
        },
        secondary_coverage=coverages_ordered[1] if len(coverages_ordered) > 1 else None,
        post_sequestration=bool(
            coverages_ordered
            and getattr(coverages_ordered[0], "payer_plan_type", None)
            == MEDICARE_PLAN_TYPE
            and _setting_enabled(secrets or {}, SEQUESTRATION_SETTING)
        ),
    )


def _resolve_transfer_target(state: _SyncState, next_responsible: str) -> str | None:
    """Determine where the remaining balance transfers after this insurance posting.

    For adjustments (CO-45 etc.) the transfer goes to whoever is next
    responsible. Patient responsibility amounts (deductible, coinsurance,
    copay) are routed separately — see ``_post_era_payments``.
    """
    if next_responsible == "patient":
        return "patient"
    if next_responsible == "secondary" and state.secondary_id:
        return state.secondary_id
    if next_responsible == "tertiary" and state.tertiary_id:
        return state.tertiary_id
    if next_responsible == "primary" and state.primary_id:
        return state.primary_id
    return None


def _post_era_payments(
    state: _SyncState,
    candid_claim: dict,
    service_lines: list[dict],
    new_eras: list[dict],
    transfer_to: str | None,
    next_responsible: str,
) -> None:
    """Post primary/secondary/tertiary insurance payments for the new ERAs on a Candid claim."""
    # ERAs are ordered: index 0 = primary, 1 = secondary, 2 = tertiary.
    # Use the full eras array (not just new) so position maps to payer tier.
    all_eras = candid_claim.get("eras", [])

    # Compute delta: what's new since last sync?
    current_amounts = _compute_synced_amounts(service_lines)

    cumulative_total = (
        current_amounts["primary"]
        + current_amounts["secondary"]
        + current_amounts["tertiary"]
    )
    for era in new_eras:
        eid = str(era["era_id"])
        state.era_totals[eid] = cumulative_total
        state.attempted_era_ids.append(eid)

    # Primary insurance (ERA index 0)
    if (
        _has_delta(current_amounts, state.prev_synced_amounts, "primary")
        and state.primary_id
    ):
        primary_era = _era_at(all_eras, 0)
        # Like Canvas's ERA posting: PR goes to the next coverage, else the patient.
        insurance_txns = _build_insurance_transactions(
            service_lines,
            state.line_items,
            state.canvas_claim_id,
            transfer_to=transfer_to,
            pr_transfer_to=state.secondary_id or PATIENT_COVERAGE_ID,
            sequestration=state.post_sequestration,
        )
        if insurance_txns:
            _append_payment_effect(state, state.primary_id, insurance_txns, primary_era)
            for txn in insurance_txns:
                if (
                    state.secondary_id
                    and txn.transfer_remaining_balance_to == state.secondary_id
                ):
                    line_id = str(txn.claim_line_item_id)
                    state.moved_to_secondary[line_id] = (
                        state.moved_to_secondary.get(line_id, Decimal("0"))
                        + txn.adjustment
                    )

    # Secondary (ERA index 1) / Tertiary (ERA index 2)
    new_era_ids = {str(era["era_id"]) for era in new_eras}
    # A $0 secondary (a denial, its own deductible) sends an ERA but no paid delta
    secondary_adjudicated = current_amounts["secondary"] > 0 or any(
        str(era.get("era_id") or "") in new_era_ids for era in all_eras[1:]
    )
    for coverage_id, paid_field, tier, era_index in (
        (state.secondary_id, "secondary_paid_amount_cents", "secondary", 1),
        (state.tertiary_id, "tertiary_paid_amount_cents", "tertiary", 2),
    ):
        if not coverage_id:
            continue
        txns: list[LineItemTransaction] = []
        if _has_delta(current_amounts, state.prev_synced_amounts, tier):
            txns = _build_secondary_transactions(
                service_lines, state.line_items, state.canvas_claim_id, paid_field
            )
        if tier == "secondary" and secondary_adjudicated:
            txns.extend(
                _secondary_leftover_transactions(state, service_lines, next_responsible)
            )
        if not txns:
            continue
        _append_payment_effect(state, coverage_id, txns, _era_at(all_eras, era_index))

    # Roll the cumulative amounts forward so the next sync computes against this point
    state.prev_synced_amounts = current_amounts


def _append_payment_effect(
    state: _SyncState,
    coverage_id: str,
    txns: list[LineItemTransaction],
    era: dict,
) -> None:
    """Build and append a ``post_payment`` effect for one payer/ERA, bumping the counter."""
    description = f"{ERA_DESC_PREFIX}{era.get('era_id', '')}"
    method = PaymentMethod.CHECK if era.get("check_number") else PaymentMethod.OTHER
    state.effects.append(
        state.claim_effect.post_payment(
            claim_coverage_id=coverage_id,
            line_item_transactions=txns,
            method=method,
            claim_description=description,
            payment_description=description,
            **_era_kwargs(era),
        )
    )
    state.payment_effect_count = state.payment_effect_count + 1


def _post_patient_payments_for_candid_claim(
    state: _SyncState, client: CandidClient, candid_claim_id: str
) -> None:
    """Fetch and post patient payments for one Candid claim. No-op without line items or a claim_id."""
    if not (state.first_line and candid_claim_id):
        return

    try:
        candid_payments = client.get_patient_payments(candid_claim_id)
    except Exception as e:
        log.warning(
            f"Candid sync: failed to fetch patient payments for "
            f"Candid claim {candid_claim_id} on claim {state.canvas_claim_id}: {e}"
        )
        return

    payment_effects, attempted = _post_patient_payments(
        state.claim_effect,
        candid_payments,
        state.known_payment_ids,
        str(state.first_line.id),
        candid_claim_id,
        state.canvas_claim_id,
    )
    state.effects.extend(payment_effects)
    state.payment_effect_count = state.payment_effect_count + len(payment_effects)
    state.attempted_payment_ids.extend(attempted)


def _process_encounter(
    state: _SyncState, encounter_data: dict, client: CandidClient, overflow: bool
) -> None:
    """Process all Candid claims inside one Candid encounter response."""
    # Split 1 holds the claim's real lines, so only it sets status and queue
    if not overflow:
        state.primary_encounter_data = encounter_data
    next_responsible = (encounter_data.get("next_responsible_party") or "").lower()
    transfer_to = _resolve_transfer_target(state, next_responsible)

    for candid_claim in encounter_data.get("claims", []):
        candid_claim_id = candid_claim.get("claim_id", "")
        if not overflow and (candid_claim_status := candid_claim.get("status")):
            state.claim_status = candid_claim_status

        service_lines = candid_claim.get("service_lines", [])

        new_eras = [
            era
            for era in candid_claim.get("eras", [])
            if (era_id := str(era.get("era_id") or ""))
            and era_id not in state.synced_era_ids
        ]
        if new_eras and overflow:
            # Its only line is the $0.01 placeholder, which isn't on the Canvas claim
            state.attempted_era_ids.extend(str(era["era_id"]) for era in new_eras)
        elif new_eras:
            _post_era_payments(
                state,
                candid_claim,
                service_lines,
                new_eras,
                transfer_to,
                next_responsible,
            )

        _post_patient_payments_for_candid_claim(state, client, candid_claim_id)


def _finalize_effects(state: _SyncState, claim: Claim) -> None:
    """Append metadata, banner, queue-move, and dedup-list effects after all encounters processed."""
    now = datetime.now(UTC).isoformat()
    state.effects.append(
        state.claim_effect.upsert_metadata(key=META_LAST_SYNC, value=now)
    )
    state.effects.append(
        state.claim_effect.upsert_metadata(
            key=META_CLAIM_STATUS, value=state.claim_status
        )
    )

    submitted_at = get_claim_metadata(claim, META_SUBMITTED_AT)
    state.effects.append(
        sync_banner(
            claim_id=state.canvas_claim_id,
            claim_status=state.claim_status,
            last_sync_at=now,
            submitted_at=submitted_at if isinstance(submitted_at, str) else None,
        )
    )

    if state.payment_effect_count > 0 and state.primary_encounter_data:
        target_queue = _determine_target_queue(state.primary_encounter_data)
        state.effects.append(state.claim_effect.move_to_queue(target_queue))
        log.info(f"Candid sync: moving claim {state.canvas_claim_id} to {target_queue}")

    if state.attempted_era_ids:
        updated_era_ids = sorted(state.synced_era_ids | set(state.attempted_era_ids))
        state.effects.append(
            state.claim_effect.upsert_metadata(
                key=META_SYNCED_ERA_IDS,
                value=json.dumps(updated_era_ids),
            )
        )
        # Cumulative amounts so the next sync can compute deltas
        state.effects.append(
            state.claim_effect.upsert_metadata(
                key=META_SYNCED_AMOUNTS,
                value=json.dumps(state.prev_synced_amounts),
            )
        )
    if state.attempted_payment_ids:
        updated_pmt_ids = sorted(
            state.synced_pmt_ids | set(state.attempted_payment_ids)
        )
        state.effects.insert(
            0,
            state.claim_effect.upsert_metadata(
                key=META_SYNCED_PAYMENT_IDS,
                value=json.dumps(updated_pmt_ids),
            ),
        )

    era_details = [
        f"{eid}: ${state.era_totals.get(eid, 0) / 100:.2f}"
        for eid in state.attempted_era_ids
    ]
    state.effects.append(
        append_sync_history(
            claim,
            state.claim_effect,
            {
                "synced_at": now,
                "log_type": LOG_TYPE_SYNC,
                "status": state.claim_status,
                "effects": state.payment_effect_count,
                "era_ids": list(state.attempted_era_ids),
                "detail": " | ".join(era_details) if era_details else "",
            },
        )
    )


def sync_claim_adjudications(claim: Claim, secrets: dict) -> list[Effect]:
    """Pull adjudication and patient payment data from Candid for a single claim.

    IDs in play:
    - ``canvas_claim_id``: Canvas's internal claim UUID (``claim.id``)
    - ``candid_encounter_id``: returned by Candid at submission time, stored in metadata
    - ``candid_claim_id``: nested inside the encounter response (``claims[].claim_id``),
      used to query patient payments — ephemeral, not stored

    Per encounter:
    1. ``GET /encounters/v4/{candid_encounter_id}`` → claims[] with status, eras[], service_lines[]
    2. For each Candid claim with new ERA IDs: post primary/secondary/tertiary insurance payments
    3. ``GET /patient-payments/v4?claim_id={candid_claim_id}`` → patient payments

    Dedup IDs are appended to claim metadata in the same effect batch.
    """
    encounters_meta = get_claim_metadata(claim, META_ENCOUNTERS)
    if not encounters_meta:
        log.info(
            f"Candid sync: no candid_encounters metadata for claim {claim.id}, skipping"
        )
        return []

    client = CandidClient.from_secrets(secrets)
    state = _init_sync_state(claim, secrets)

    for encounter_record in encounters_meta:
        candid_encounter_id = encounter_record.get("candid_encounter_id")
        if not candid_encounter_id:
            continue
        try:
            encounter_data = client.get_encounter(candid_encounter_id)
        except Exception as e:
            log.warning(
                f"Candid sync: failed to fetch encounter {candid_encounter_id} "
                f"for claim {state.canvas_claim_id}: {e}"
            )
            continue
        _process_encounter(
            state,
            encounter_data,
            client,
            overflow=(encounter_record.get("split") or 1) > 1,
        )

    _finalize_effects(state, claim)

    log.info(
        f"Candid sync: generated {state.payment_effect_count} payment effects "
        f"for claim {state.canvas_claim_id} (status={state.claim_status})"
    )

    state.effects.append(notify_claim_updated(state.canvas_claim_id))
    return state.effects


def sync_patient_payments(claim: Claim, secrets: dict) -> list[Effect]:
    """Pull only patient payments from Candid for a single claim.

    Fetches each encounter to discover Candid ``claim_id``s, then queries
    patient payments by those IDs. See ``sync_claim_adjudications`` docstring
    for the ID glossary.
    """
    encounters_meta = get_claim_metadata(claim, META_ENCOUNTERS)
    if not encounters_meta:
        log.info(
            f"Candid sync: no candid_encounters metadata for claim "
            f"{claim.id}, skipping"
        )
        return []

    first_line = claim.line_items.first()
    if not first_line:
        return []

    client = CandidClient.from_secrets(secrets)
    canvas_claim_id = str(claim.id)
    synced_pmt_ids = get_claim_metadata_set(claim, META_SYNCED_PAYMENT_IDS)
    reported_pmt_ids = get_claim_metadata_set(claim, META_REPORTED_PAYMENT_IDS)

    # Reuse the full sync's per-Candid-claim payment posting so the dedup and
    # posting logic lives in one place; the coverage/ERA fields stay empty
    # since this path only touches patient payments.
    state = _SyncState(
        canvas_claim_id=canvas_claim_id,
        claim_effect=ClaimEffect(claim_id=canvas_claim_id),
        line_items=[],
        first_line=first_line,
        primary_id=None,
        secondary_id=None,
        tertiary_id=None,
        synced_era_ids=set(),
        synced_pmt_ids=synced_pmt_ids,
        known_payment_ids=synced_pmt_ids | reported_pmt_ids,
        prev_synced_amounts={},
    )

    for encounter_record in encounters_meta:
        candid_encounter_id = encounter_record.get("candid_encounter_id")
        if not candid_encounter_id:
            continue
        try:
            encounter_data = client.get_encounter(candid_encounter_id)
        except Exception as e:
            log.warning(
                f"Candid sync: failed to fetch encounter {candid_encounter_id} "
                f"for claim {canvas_claim_id}: {e}"
            )
            continue
        for candid_claim in encounter_data.get("claims", []):
            _post_patient_payments_for_candid_claim(
                state, client, candid_claim.get("claim_id", "")
            )

    if state.effects:
        now = datetime.now(UTC).isoformat()
        state.effects.append(
            state.claim_effect.upsert_metadata(key=META_LAST_SYNC, value=now)
        )

    if state.attempted_payment_ids:
        updated_pmt_ids = sorted(synced_pmt_ids | set(state.attempted_payment_ids))
        state.effects.insert(
            0,
            state.claim_effect.upsert_metadata(
                key=META_SYNCED_PAYMENT_IDS,
                value=json.dumps(updated_pmt_ids),
            ),
        )

    log.info(
        f"Candid sync: posted {len(state.attempted_payment_ids)} patient payments "
        f"for claim {canvas_claim_id}"
    )
    if state.effects:
        state.effects.append(notify_claim_updated(canvas_claim_id))
    return state.effects
