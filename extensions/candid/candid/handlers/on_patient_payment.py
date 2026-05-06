"""Report patient payments to Candid when processed in Canvas.

Listens for ``PATIENT_PAYMENT_PROCESSED`` events and submits the payment
to Candid's ``/api/patient-payments/v4`` endpoint. Allocations use
``canvas:{claim_id}`` as the encounter external_id — matching what was
set at submission time — same as the home-app built-in integration.
"""

import json
from decimal import Decimal

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Claim
from logger import log

from candid.api.client import CandidClient
from candid.effect_helpers import META_REPORTED_PAYMENT_IDS, get_claim_metadata_set
from candid.models.sync_state import LOG_TYPE_PAYMENT_REPORTED, SyncLog


class OnPatientPaymentProcessed(BaseHandler):
    """Report a patient payment to Candid when it is processed in Canvas."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_PAYMENT_PROCESSED)

    def compute(self) -> list[Effect]:
        context = self.event.context
        patient_id = context.get("patient_id", "")
        total_amount_cents = context.get("total_amount_cents", "0")
        timestamp = context.get("timestamp", "")
        payment_method = context.get("payment_method_and_description", "")
        claim_payments = context.get("claim_payments", [])

        total_cents = int(Decimal(total_amount_cents))

        # Build allocations — identical to home-app's candid_integration/tasks.py.
        # Each claim_payment maps to an encounter via canvas:{claim_id}, which is
        # the external_id set at submission time.
        if claim_payments:
            allocations = []
            unallocated_cents = total_cents
            for cp in claim_payments:
                claim_ext_id = cp.get("claim_id", "")
                cp_cents = int(Decimal(cp.get("allocated_cents", "0")))
                allocations.append(
                    {
                        "target": {
                            "type": "claim_by_encounter_external_id",
                            "value": f"canvas:{claim_ext_id}",
                        },
                        "amount_cents": cp_cents,
                    }
                )
                unallocated_cents -= cp_cents
            if unallocated_cents > 0:
                allocations.append(
                    {
                        "target": {"type": "unattributed"},
                        "amount_cents": unallocated_cents,
                    }
                )
        else:
            allocations = [
                {
                    "target": {"type": "unattributed"},
                    "amount_cents": total_cents,
                }
            ]

        client = CandidClient.from_secrets(self.secrets)

        payload = {
            "patient_external_id": f"canvas:{patient_id}",
            "amount_cents": total_cents,
            "payment_timestamp": timestamp,
            "payment_note": payment_method,
            "allocations": allocations,
        }

        success, payment_id = client.submit_payment(payload)
        if not success:
            log.warning(
                f"Candid: failed to report patient payment for patient "
                f"{patient_id}: {payment_id}"
            )
            return []

        log.info(
            f"Candid: patient payment reported for patient {patient_id} "
            f"(patient_payment_id={payment_id})"
        )

        if not payment_id:
            return []

        # Store the Candid payment ID on each associated claim so the
        # adjudication sync knows not to re-post it. Merge with any existing
        # IDs — upsert_metadata replaces the value, so writing just [payment_id]
        # would clobber prior reported payments.
        effects: list[Effect] = []
        for cp in claim_payments:
            claim_ext_id = cp.get("claim_id")
            if claim_ext_id:
                claim = Claim.objects.filter(id=claim_ext_id).first()
                existing = (
                    get_claim_metadata_set(claim, META_REPORTED_PAYMENT_IDS)
                    if claim
                    else set()
                )
                merged = sorted(existing | {payment_id})
                effects.append(
                    ClaimEffect(claim_id=claim_ext_id).upsert_metadata(
                        key=META_REPORTED_PAYMENT_IDS,
                        value=json.dumps(merged),
                    )
                )
                SyncLog.objects.create(
                    canvas_claim_id=claim_ext_id,
                    log_type=LOG_TYPE_PAYMENT_REPORTED,
                    detail=f"${total_cents / 100:.2f} | payment_id={payment_id}",
                )

        return effects
