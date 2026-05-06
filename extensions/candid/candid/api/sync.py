"""SimpleAPI endpoint that triggers full adjudication sync for a single claim.

Called manually or by future automation to pull ERA data, insurance payments,
adjustments, and patient payments from Candid for a specific claim.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPIRoute
from canvas_sdk.v1.data.claim import Claim
from logger import log

from candid.adjudication_sync import sync_claim_adjudications


class CandidSyncAPI(SimpleAPIRoute):
    """Trigger full adjudication sync for a single claim."""

    PATH = "/sync"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        return credentials.key == self.secrets["CANDID_API_KEY"]

    def post(self) -> list[Response | Effect]:
        body = self.request.json()
        canvas_claim_id = body.get("claim_id")
        if not canvas_claim_id:
            return [JSONResponse({"error": "claim_id is required"}, status_code=400)]

        claim = Claim.objects.filter(id=canvas_claim_id).first()
        if not claim:
            log.warning(f"Candid sync: claim {canvas_claim_id} not found")
            return [JSONResponse({"error": "claim not found"}, status_code=404)]

        effects = sync_claim_adjudications(claim, self.secrets)
        log.info(
            f"Candid sync: triggered for claim {canvas_claim_id}, "
            f"{len(effects)} effects generated"
        )
        return effects
