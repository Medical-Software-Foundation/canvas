"""SimpleAPI endpoint that reports a patient payment to Candid."""

import json
from decimal import Decimal

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.effects.task.task import AddTask
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPIRoute
from canvas_sdk.v1.data import Claim
from logger import log

from candid.adjudication_sync import PATIENT_PAYMENT_DESC_PREFIX
from candid.api.broadcast import notify_claim_updated
from candid.api.client import CandidClient
from candid.effect_helpers import (
    META_ENCOUNTERS,
    META_REPORTED_PAYMENT_IDS,
    META_SYNCED_PAYMENT_IDS,
    get_claim_metadata,
    get_claim_metadata_set,
)
from candid.models.sync_state import LOG_TYPE_PAYMENT_REPORTED, SyncLog


def _unattributed(amount_cents: int) -> dict:
    return {"target": {"type": "unattributed"}, "amount_cents": amount_cents}


class CandidReportPaymentAPI(SimpleAPIRoute):
    """Report a patient payment to Candid's API."""

    PATH = "/report-payment"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        # Sender %2C-encodes commas; see candid.effect_helpers.schedule_async_post.
        return credentials.key.replace("%2C", ",") == self.secrets["CANDID_CLIENT_SECRET"]

    def post(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id", "")
        total_amount_cents = body.get("total_amount_cents", "0")
        timestamp = body.get("timestamp", "")
        payment_method = body.get("payment_method_and_description", "")
        claim_payments = body.get("claim_payments", [])

        total_cents = int(Decimal(total_amount_cents))

        # Skip refunds (negative amounts). Candid's /patient-payments/v4
        # only accepts positive amounts — refunds/reversals require a
        # separate workflow on Candid's side.
        if total_cents <= 0:
            log.info(
                f"Candid: skipping refund/zero payment for patient {patient_id} "
                f"(amount_cents={total_cents})"
            )
            return []

        # Extract embedded payment_id if this looks like a Candid-originated payment.
        # The event's payment_method_and_description is e.g.
        # "other: Candid patient payment 019e1cdb-..." (lowercase method prefix).
        prefix = PATIENT_PAYMENT_DESC_PREFIX.strip()
        embedded_id = ""
        if prefix in payment_method:
            embedded_id = payment_method.split(prefix, 1)[1].strip()

        claim_ids = [cp.get("claim_id") for cp in claim_payments if cp.get("claim_id")]
        claims_by_id = (
            {str(c.id): c for c in Claim.objects.filter(id__in=claim_ids)}
            if claim_ids
            else {}
        )

        allocations: list[dict] = []
        # (claim_id, reported_payment_ids_set) — cached so the success path
        # doesn't re-read META_REPORTED_PAYMENT_IDS for each claim.
        reportable_claims: list[tuple[str, set[str]]] = []
        unallocated_cents = total_cents

        for cp in claim_payments:
            claim_ext_id = cp.get("claim_id", "")
            cp_cents = int(Decimal(cp.get("allocated_cents", "0")))
            claim = claims_by_id.get(claim_ext_id)
            reported_set = (
                get_claim_metadata_set(claim, META_REPORTED_PAYMENT_IDS)
                if claim
                else set()
            )

            # Skip if the embedded payment_id is already synced or reported
            if embedded_id and claim:
                synced_set = get_claim_metadata_set(claim, META_SYNCED_PAYMENT_IDS)
                if embedded_id in synced_set | reported_set:
                    log.info(
                        f"Candid: skipping claim {claim_ext_id} — {embedded_id} "
                        f"is already synced or reported"
                    )
                    continue

            # Only allocate to a Candid encounter if the claim was actually
            # submitted to Candid (has encounter metadata). Claims that predate
            # the plugin won't have this — send their portion as unattributed.
            has_encounter = bool(
                claim and get_claim_metadata(claim, META_ENCOUNTERS)
            )
            if has_encounter:
                allocations.append(
                    {
                        "target": {
                            "type": "claim_by_encounter_external_id",
                            "value": f"canvas:{claim_ext_id}",
                        },
                        "amount_cents": cp_cents,
                    }
                )
                reportable_claims.append((claim_ext_id, reported_set))
            else:
                log.info(
                    f"Candid: claim {claim_ext_id} has no encounter metadata — "
                    f"allocating ${cp_cents / 100:.2f} as unattributed"
                )
                allocations.append(_unattributed(cp_cents))
            unallocated_cents -= cp_cents

        if not allocations:
            if claim_ids:
                # Every claim was skipped via the embedded-ID dedup above —
                # this payment originated in Candid; reporting it back would loop.
                log.info("Candid: skipping payment report — all claims already synced")
                return []
            allocations.append(_unattributed(total_cents))
        elif unallocated_cents > 0:
            allocations.append(_unattributed(unallocated_cents))

        client = CandidClient.from_secrets(self.secrets)

        payload = {
            "patient_external_id": f"canvas:{patient_id}",
            "amount_cents": total_cents,
            "payment_timestamp": timestamp,
            "payment_note": payment_method,
            "allocations": allocations,
        }

        success, result_msg = client.submit_payment(payload)
        if not success:
            log.warning(
                f"Candid: failed to report patient payment for patient "
                f"{patient_id}: {result_msg}"
            )
            return [
                AddTask(
                    patient_id=patient_id,
                    title=f"Candid: Payment Notification Failed — {result_msg}",
                    labels=["Candid Integration"],
                ).apply()
            ]

        payment_id = result_msg
        log.info(
            f"Candid: patient payment reported for patient {patient_id} "
            f"(patient_payment_id={payment_id})"
        )

        effects: list[Effect] = []
        for claim_ext_id, reported_set in reportable_claims:
            merged = sorted(reported_set | {payment_id})
            effects.append(
                ClaimEffect(claim_id=claim_ext_id).upsert_metadata(
                    key=META_REPORTED_PAYMENT_IDS,
                    value=json.dumps(merged),
                )
            )
            try:
                SyncLog.objects.create(
                    canvas_claim_id=claim_ext_id,
                    log_type=LOG_TYPE_PAYMENT_REPORTED,
                    detail=f"${total_cents / 100:.2f} | payment_id={payment_id}",
                )
            except Exception:
                log.warning(f"Candid: failed to write SyncLog for claim {claim_ext_id}")
            effects.append(notify_claim_updated(claim_ext_id))

        return effects
