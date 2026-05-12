"""Pull adjudication data from Candid and generate Canvas posting effects.

Uses the encounter endpoint to get claim status, ERA data, and per-service-line
financial data (payments, adjustments, patient responsibility). Uses the
patient-payments endpoint for patient payment records.

Dedup IDs (synced ERA IDs, synced payment IDs) are written to claim metadata
in the same effect batch as the postings they cover.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect, LineItemTransaction, PaymentMethod
from canvas_sdk.v1.data import Claim
from canvas_sdk.v1.data.claim import ClaimQueues
from logger import log

from candid.api.broadcast import notify_claim_updated
from candid.api.client import CandidClient
from candid.effect_helpers import (
    DEFAULT_CLAIM_STATUS,
    META_CLAIM_STATUS,
    META_ENCOUNTERS,
    META_LAST_SYNC,
    META_REPORTED_PAYMENT_IDS,
    META_SUBMITTED_AT,
    META_SYNCED_ERA_IDS,
    META_SYNCED_PAYMENT_IDS,
    PATIENT_COVERAGE_ID,
    active_coverages_ordered,
    get_claim_metadata,
    get_claim_metadata_set,
    sync_banner,
)
from candid.models.sync_state import SyncLog

# Patient-responsibility CARC codes
PR_DEDUCTIBLE = "PR-1"
PR_COINSURANCE = "PR-2"
PR_COPAY = "PR-3"

# Description prefixes for dedup verification
ERA_DESC_PREFIX = "Candid ERA "
PATIENT_PAYMENT_DESC_PREFIX = "Candid patient payment "


def _cents_to_dollars(cents: int | None) -> Decimal | None:
    if cents is None or cents == 0:
        return None
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _match_line_item(
    candid_line: dict, line_items: list, canvas_claim_id: str
) -> str | None:
    """Match a Candid service_line to a Canvas ClaimLineItem by external_id, then on proc_code, date, charge."""
    # First pass: match on external_id
    if external_id := candid_line.get("external_id"):
        match = next((li for li in line_items if str(li.id) == external_id), None)
        if match:
            return str(match.id)

    # Second pass: match on procedure code alone
    candid_proc = candid_line.get("procedure_code", "")
    if not candid_proc:
        return None

    matches = [li for li in line_items if li.proc_code == candid_proc]

    # If ambiguous, narrow by date and charge
    if len(matches) > 1:
        candid_charge_cents = candid_line.get("charge_amount_cents")
        candid_dos = candid_line.get("date_of_service_range", {})
        candid_from_date = candid_dos.get("start_date") or candid_dos.get(
            "date_of_service"
        )
        candid_charge_dollars = _cents_to_dollars(candid_charge_cents)

        narrowed = [
            li
            for li in matches
            if (not candid_from_date or str(li.from_date) == str(candid_from_date))
            and (candid_charge_dollars is None or li.charge == candid_charge_dollars)
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
    else:
        log.warning(
            f"Candid sync: no match for procedure {candid_proc} "
            f"on claim {canvas_claim_id}"
        )
    return None


# ---------------------------------------------------------------------------
# Transaction builders — from encounter service lines
# ---------------------------------------------------------------------------


def _build_insurance_transactions(
    service_lines: list[dict],
    line_items: list,
    canvas_claim_id: str,
    transfer_to_patient: bool = False,
) -> list[LineItemTransaction]:
    """Build insurance payment + adjustment transactions from encounter service lines.

    When ``transfer_to_patient`` is True, adjustment transactions include
    ``transfer_remaining_balance_to="patient"`` so the remaining balance
    moves to the patient after insurance pays.
    """
    txns: list[LineItemTransaction] = []

    for sl in service_lines:
        line_item_id = _match_line_item(sl, line_items, canvas_claim_id)
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

        # Adjustments from ERA (payer-reported) and manual adjustments.
        # Both live on the service line but in different locations:
        #   - service_line_era_data.service_line_adjustments (from payer ERA)
        #   - service_line_manual_adjustments (entered manually)
        era_adjs = sl.get("service_line_era_data", {}).get(
            "service_line_adjustments", []
        )
        manual_adjs = sl.get("service_line_manual_adjustments", [])
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
                        transfer_remaining_balance_to="patient"
                        if transfer_to_patient
                        else None,
                    )
                )

    return txns


def _build_patient_responsibility_transactions(
    service_lines: list[dict], line_items: list, canvas_claim_id: str
) -> list[LineItemTransaction]:
    """Build patient responsibility transactions (PR-1, PR-2, PR-3)."""
    txns: list[LineItemTransaction] = []

    for sl in service_lines:
        line_item_id = _match_line_item(sl, line_items, canvas_claim_id)
        if not line_item_id:
            continue

        deductible = _cents_to_dollars(sl.get("deductible_cents"))
        coinsurance = _cents_to_dollars(sl.get("coinsurance_cents"))
        copay = _cents_to_dollars(sl.get("copay_cents"))

        is_first = True
        for amount, code in [
            (deductible, PR_DEDUCTIBLE),
            (coinsurance, PR_COINSURANCE),
            (copay, PR_COPAY),
        ]:
            if amount:
                txn_kwargs: dict = {
                    "claim_line_item_id": line_item_id,
                    "adjustment": amount,
                    "adjustment_code": code,
                }
                if is_first:
                    txn_kwargs["payment"] = Decimal("0.00")
                    is_first = False
                txns.append(LineItemTransaction(**txn_kwargs))

    return txns


def _build_secondary_transactions(
    service_lines: list[dict], line_items: list, canvas_claim_id: str, field: str
) -> list[LineItemTransaction]:
    """Build payment transactions for secondary/tertiary payer."""
    txns: list[LineItemTransaction] = []
    for sl in service_lines:
        line_item_id = _match_line_item(sl, line_items, canvas_claim_id)
        if not line_item_id:
            continue
        payment = _cents_to_dollars(sl.get(field))
        if payment:
            txns.append(
                LineItemTransaction(claim_line_item_id=line_item_id, payment=payment)
            )
    return txns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coverage_id_at(coverages_ordered: list, payer_order: int) -> str | None:
    if payer_order < len(coverages_ordered):
        return str(coverages_ordered[payer_order].id)
    return None


def _post_patient_payments(
    claim_effect: ClaimEffect,
    candid_payments: list[dict],
    known_payment_ids: set[str],
    first_line_id: str,
) -> tuple[list[Effect], list[str]]:
    """Build post_payment effects for new patient payments.

    Mutates ``known_payment_ids`` so callers across encounters/claims dedupe
    against payments already queued in this run. Returns ``(effects,
    attempted_payment_ids)``.
    """
    effects: list[Effect] = []
    attempted: list[str] = []
    for payment in candid_payments:
        payment_id = payment.get("patient_payment_id")
        if not payment_id or payment_id in known_payment_ids:
            continue

        amount_dollars = _cents_to_dollars(payment.get("amount_cents", 0))
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
    canvas_claim_id = str(claim.id)
    claim_effect = ClaimEffect(claim_id=canvas_claim_id)

    encounters_meta = get_claim_metadata(claim, META_ENCOUNTERS)
    if not encounters_meta:
        log.info(
            f"Candid sync: no candid_encounters metadata for claim "
            f"{canvas_claim_id}, skipping"
        )
        return []

    client = CandidClient.from_secrets(secrets)

    line_items = list(claim.get_active_claim_line_items())
    first_line = line_items[0] if line_items else None
    coverages_ordered = active_coverages_ordered(claim)
    primary_id = _coverage_id_at(coverages_ordered, 0)
    secondary_id = _coverage_id_at(coverages_ordered, 1)
    tertiary_id = _coverage_id_at(coverages_ordered, 2)

    synced_era_ids = get_claim_metadata_set(claim, META_SYNCED_ERA_IDS)
    synced_pmt_ids = get_claim_metadata_set(claim, META_SYNCED_PAYMENT_IDS)
    reported_pmt_ids = get_claim_metadata_set(claim, META_REPORTED_PAYMENT_IDS)
    known_payment_ids = synced_pmt_ids | reported_pmt_ids

    effects: list[Effect] = []
    attempted_era_ids: list[str] = []
    attempted_payment_ids: list[str] = []
    era_totals: dict[str, int] = {}
    payment_effect_count = 0
    claim_status = DEFAULT_CLAIM_STATUS
    last_encounter_data: dict | None = None

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

        last_encounter_data = encounter_data
        next_responsible = encounter_data.get("next_responsible_party") or ""
        transfer_to_patient = next_responsible.lower() == "patient"

        for candid_claim in encounter_data.get("claims", []):
            candid_claim_id = candid_claim.get("claim_id", "")
            candid_claim_status = candid_claim.get("status")
            if candid_claim_status:
                claim_status = candid_claim_status

            service_lines = candid_claim.get("service_lines", [])

            for era in candid_claim.get("eras", []):
                era_id = str(era.get("era_id") or "")
                if not era_id or era_id in synced_era_ids:
                    continue

                description = f"{ERA_DESC_PREFIX}{era_id}"

                # Sum total paid across all service lines for this ERA
                era_paid_cents = sum(
                    (sl.get("primary_paid_amount_cents") or 0)
                    + (sl.get("secondary_paid_amount_cents") or 0)
                    + (sl.get("tertiary_paid_amount_cents") or 0)
                    for sl in service_lines
                )
                era_totals[era_id] = era_paid_cents

                # Insurance payment (primary)
                insurance_txns = _build_insurance_transactions(
                    service_lines,
                    line_items,
                    canvas_claim_id,
                    transfer_to_patient=transfer_to_patient,
                )
                if insurance_txns and primary_id:
                    era_kwargs: dict = {}
                    if era.get("check_number"):
                        era_kwargs["check_number"] = str(era["check_number"])
                    if era.get("check_date"):
                        try:
                            era_kwargs["check_date"] = date.fromisoformat(
                                era["check_date"]
                            )
                        except (ValueError, TypeError):
                            pass

                    method = (
                        PaymentMethod.CHECK
                        if era.get("check_number")
                        else PaymentMethod.OTHER
                    )
                    effects.append(
                        claim_effect.post_payment(
                            claim_coverage_id=primary_id,
                            line_item_transactions=insurance_txns,
                            method=method,
                            claim_description=description,
                            payment_description=description,
                            **era_kwargs,
                        )
                    )
                    payment_effect_count += 1

                for coverage_id, field in (
                    (secondary_id, "secondary_paid_amount_cents"),
                    (tertiary_id, "tertiary_paid_amount_cents"),
                ):
                    if not coverage_id:
                        continue
                    txns = _build_secondary_transactions(
                        service_lines, line_items, canvas_claim_id, field
                    )
                    if not txns:
                        continue
                    effects.append(
                        claim_effect.post_payment(
                            claim_coverage_id=coverage_id,
                            line_item_transactions=txns,
                            method=PaymentMethod.OTHER,
                            claim_description=description,
                            payment_description=description,
                        )
                    )
                    payment_effect_count += 1

                pr_txns = _build_patient_responsibility_transactions(
                    service_lines, line_items, canvas_claim_id
                )
                if pr_txns:
                    effects.append(
                        claim_effect.post_payment(
                            claim_coverage_id=PATIENT_COVERAGE_ID,
                            line_item_transactions=pr_txns,
                            method=PaymentMethod.OTHER,
                            claim_description=description,
                            payment_description=description,
                        )
                    )
                    payment_effect_count += 1

                attempted_era_ids.append(era_id)

            # Patient payments (queried by Candid's claim_id, not encounter_id)
            try:
                candid_payments = client.get_patient_payments(candid_claim_id)
            except Exception as e:
                log.warning(
                    f"Candid sync: failed to fetch patient payments for "
                    f"Candid claim {candid_claim_id} on claim {canvas_claim_id}: {e}"
                )
                candid_payments = []

            if first_line:
                payment_effects, attempted = _post_patient_payments(
                    claim_effect,
                    candid_payments,
                    known_payment_ids,
                    str(first_line.id),
                )
                effects.extend(payment_effects)
                payment_effect_count += len(payment_effects)
                attempted_payment_ids.extend(attempted)

    now = datetime.now(UTC).isoformat()
    effects.append(claim_effect.upsert_metadata(key=META_LAST_SYNC, value=now))
    effects.append(
        claim_effect.upsert_metadata(key=META_CLAIM_STATUS, value=claim_status)
    )

    submitted_at = get_claim_metadata(claim, META_SUBMITTED_AT)
    effects.append(
        sync_banner(
            claim_id=canvas_claim_id,
            claim_status=claim_status,
            last_sync_at=now,
            submitted_at=submitted_at if isinstance(submitted_at, str) else None,
        )
    )

    if payment_effect_count > 0 and last_encounter_data:
        target_queue = _determine_target_queue(last_encounter_data)
        effects.append(claim_effect.move_to_queue(target_queue))
        log.info(f"Candid sync: moving claim {canvas_claim_id} to {target_queue}")

    if attempted_era_ids:
        updated_era_ids = sorted(synced_era_ids | set(attempted_era_ids))
        effects.append(
            claim_effect.upsert_metadata(
                key=META_SYNCED_ERA_IDS,
                value=json.dumps(updated_era_ids),
            )
        )
    if attempted_payment_ids:
        updated_pmt_ids = sorted(synced_pmt_ids | set(attempted_payment_ids))
        effects.insert(
            0,
            claim_effect.upsert_metadata(
                key=META_SYNCED_PAYMENT_IDS,
                value=json.dumps(updated_pmt_ids),
            ),
        )

    log.info(
        f"Candid sync: generated {payment_effect_count} payment effects "
        f"for claim {canvas_claim_id} (status={claim_status})"
    )

    era_details = [
        f"{eid}: ${era_totals.get(eid, 0) / 100:.2f}" for eid in attempted_era_ids
    ]
    try:
        SyncLog.objects.create(
            canvas_claim_id=canvas_claim_id,
            candid_claim_status=claim_status,
            payment_effects_count=payment_effect_count,
            era_ids=",".join(attempted_era_ids),
            detail=" | ".join(era_details) if era_details else "",
        )
    except Exception:
        log.warning(f"Candid sync: failed to write SyncLog for claim {canvas_claim_id}")

    effects.append(notify_claim_updated(canvas_claim_id))
    return effects


def sync_patient_payments(claim: Claim, secrets: dict) -> list[Effect]:
    """Pull only patient payments from Candid for a single claim.

    Fetches each encounter to discover Candid ``claim_id``s, then queries
    patient payments by those IDs. See ``sync_claim_adjudications`` docstring
    for the ID glossary.
    """
    canvas_claim_id = str(claim.id)
    claim_effect = ClaimEffect(claim_id=canvas_claim_id)

    encounters_meta = get_claim_metadata(claim, META_ENCOUNTERS)
    if not encounters_meta:
        log.info(
            f"Candid sync: no candid_encounters metadata for claim "
            f"{canvas_claim_id}, skipping"
        )
        return []

    client = CandidClient.from_secrets(secrets)

    first_line = claim.line_items.first()
    if not first_line:
        return []

    synced_pmt_ids = get_claim_metadata_set(claim, META_SYNCED_PAYMENT_IDS)
    reported_pmt_ids = get_claim_metadata_set(claim, META_REPORTED_PAYMENT_IDS)
    known_payment_ids = synced_pmt_ids | reported_pmt_ids
    first_line_id = str(first_line.id)

    effects: list[Effect] = []
    attempted_payment_ids: list[str] = []

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
            candid_claim_id = candid_claim.get("claim_id", "")
            if not candid_claim_id:
                continue

            try:
                candid_payments = client.get_patient_payments(candid_claim_id)
            except Exception as e:
                log.warning(
                    f"Candid sync: failed to fetch patient payments for "
                    f"Candid claim {candid_claim_id} on claim {canvas_claim_id}: {e}"
                )
                continue

            payment_effects, attempted = _post_patient_payments(
                claim_effect, candid_payments, known_payment_ids, first_line_id
            )
            effects.extend(payment_effects)
            attempted_payment_ids.extend(attempted)

    if effects:
        now = datetime.now(UTC).isoformat()
        effects.append(claim_effect.upsert_metadata(key=META_LAST_SYNC, value=now))

    if attempted_payment_ids:
        updated_pmt_ids = sorted(synced_pmt_ids | set(attempted_payment_ids))
        effects.insert(
            0,
            claim_effect.upsert_metadata(
                key=META_SYNCED_PAYMENT_IDS,
                value=json.dumps(updated_pmt_ids),
            ),
        )

    log.info(
        f"Candid sync: posted {len(attempted_payment_ids)} patient payments "
        f"for claim {canvas_claim_id}"
    )
    if effects:
        effects.append(notify_claim_updated(canvas_claim_id))
    return effects
