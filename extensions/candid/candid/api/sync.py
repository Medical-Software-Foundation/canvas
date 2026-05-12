"""SimpleAPI endpoints that trigger Candid sync for a single claim.

Two routes share the same shape (auth + ``{claim_id}`` body) but call into
different sync functions:

- ``CandidSyncAPI`` (``/sync``) — full adjudication sync: ERA data, insurance
  payments, adjustments, and patient payments.
- ``CandidSyncPatientPaymentsAPI`` (``/sync-patient-payments``) — patient
  payments only. Invoked asynchronously by ``OnClaimQueueMoved`` when a claim
  enters the Patient Balance queue.

Authentication uses ``CANDID_CLIENT_SECRET`` as a shared API key.
"""

from typing import Callable

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPIRoute
from canvas_sdk.v1.data.claim import Claim
from logger import log

from candid.adjudication_sync import sync_claim_adjudications, sync_patient_payments


def _sync_handler(
    sync_fn: Callable[[Claim, dict], list[Effect]], label: str
) -> Callable:
    """Build a ``post`` method for a sync SimpleAPIRoute."""

    def post(self: SimpleAPIRoute) -> list[Response | Effect]:
        body = self.request.json()
        canvas_claim_id = body.get("claim_id")
        if not canvas_claim_id:
            return [JSONResponse({"error": "claim_id is required"}, status_code=400)]

        claim = Claim.objects.filter(id=canvas_claim_id).first()
        if not claim:
            log.warning(f"Candid {label}: claim {canvas_claim_id} not found")
            return [JSONResponse({"error": "claim not found"}, status_code=404)]

        effects = sync_fn(claim, self.secrets)
        log.info(
            f"Candid {label}: triggered for claim {canvas_claim_id}, "
            f"{len(effects)} effects generated"
        )
        return effects

    return post


class CandidSyncAPI(SimpleAPIRoute):
    """Trigger full adjudication sync for a single claim."""

    PATH = "/sync"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        return credentials.key == self.secrets["CANDID_CLIENT_SECRET"]

    post = _sync_handler(sync_claim_adjudications, "sync")


class CandidSyncPatientPaymentsAPI(SimpleAPIRoute):
    """Trigger patient payment sync for a single claim (async from queue move)."""

    PATH = "/sync-patient-payments"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        return credentials.key == self.secrets["CANDID_CLIENT_SECRET"]

    post = _sync_handler(sync_patient_payments, "patient payment sync")
