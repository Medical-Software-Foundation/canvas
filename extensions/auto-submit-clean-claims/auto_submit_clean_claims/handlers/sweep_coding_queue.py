from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data import Claim
from canvas_sdk.v1.data.claim import ClaimQueues

from auto_submit_clean_claims.helpers.claim_processor import process_claim
from auto_submit_clean_claims.helpers.fhir_client import FhirClient
from logger import log


class SweepCodingQueue(CronTask):
    """
    Periodically sweeps claims in the Coding queue and moves clean ones
    to the Submission queue. Runs every 5 hours.
    """

    SCHEDULE = "0 */5 * * *"

    def execute(self) -> list[Effect]:
        log.info("SweepCodingQueue starting")

        claims = list(
            Claim.objects.select_related("current_queue", "provider", "patient")
            .prefetch_related("line_items", "diagnosis_codes", "coverages")
            .filter(current_queue__name=ClaimQueues.NEEDS_CODING_REVIEW.label)
        )

        if not claims:
            log.info("SweepCodingQueue found no claims in Coding queue")
            return []

        log.info(f"SweepCodingQueue found {len(claims)} claim(s) to process")

        fhir_client = FhirClient(
            client_id=self.secrets["CANVAS_FHIR_CLIENT_ID"],
            client_secret=self.secrets["CANVAS_FHIR_CLIENT_SECRET"],
            customer_identifier=self.environment["CUSTOMER_IDENTIFIER"],
        )

        effects: list[Effect] = []
        for claim in claims:
            effects.extend(process_claim(claim, fhir_client))

        log.info(f"SweepCodingQueue finished — produced {len(effects)} effect(s)")
        return effects
