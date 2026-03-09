from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Claim
from canvas_sdk.v1.data.claim import ClaimQueues

from auto_submit_clean_claims.helpers.claim_processor import process_claim
from auto_submit_clean_claims.helpers.fhir_client import FhirClient


class AutoSubmitCleanClaims(BaseHandler):
    """
    Automatically moves claims from the Coding queue to the Submission queue
    if they pass all scrub checks (no errors).

    Mirrors the built-in Canvas claim scrubber logic from:
    quality_and_revenue/claim_automation/claim_error.py

    Not covered (requires internal ontologies service):
    - NCCI/MUE edits
    """

    RESPONDS_TO = [
        EventType.Name(EventType.CLAIM_CREATED),
        EventType.Name(EventType.CLAIM_UPDATED),
    ]

    def compute(self) -> list[Effect]:
        claim_id = self.target

        claim = (
            Claim.objects.select_related("current_queue", "provider", "patient")
            .prefetch_related("line_items", "diagnosis_codes", "coverages")
            .get(id=claim_id)
        )

        if claim.current_queue.name != ClaimQueues.NEEDS_CODING_REVIEW.label:
            return []

        fhir_client = FhirClient(
            client_id=self.secrets["CANVAS_FHIR_CLIENT_ID"],
            client_secret=self.secrets["CANVAS_FHIR_CLIENT_SECRET"],
            customer_identifier=self.environment["CUSTOMER_IDENTIFIER"],
        )

        return process_claim(claim, fhir_client)
