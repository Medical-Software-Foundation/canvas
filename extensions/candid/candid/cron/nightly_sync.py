"""Nightly cron job to sync adjudication data from Candid for pending claims.

Queries Canvas for all claims in FiledAwaitingResponse, AdjudicatedOpenBalance,
and PatientBalance queues that have Candid encounter metadata, then runs
``sync_claim_adjudications`` on each to pull ERA data, patient payments, and
post them back to Canvas.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.claim import Claim, ClaimQueues
from logger import log

from candid.adjudication_sync import sync_claim_adjudications
from candid.effect_helpers import META_ENCOUNTERS

SYNC_QUEUES = (
    ClaimQueues.FILED_AWAITING_RESPONSE,
    ClaimQueues.ADJUDICATED_OPEN_BALANCE,
    ClaimQueues.PATIENT_BALANCE,
)


class NightlyCandidSync(CronTask):
    """Run at 2 AM daily — sync adjudication data for all pending Candid claims.

    Finds claims in the three queues where we expect adjudication activity,
    filters to those with ``candid_encounters`` metadata, and calls
    ``sync_claim_adjudications`` on each.
    """

    SCHEDULE = "0 2 * * *"

    def execute(self) -> list[Effect]:
        queue_values = [q.value for q in SYNC_QUEUES]
        claims = Claim.objects.filter(
            current_queue__queue_sort_ordering__in=queue_values,
            metadata__key=META_ENCOUNTERS,
        )

        count = claims.count()
        if count == 0:
            log.info("Candid nightly sync: no claims to sync")
            return []

        log.info(f"Candid nightly sync: syncing {count} claims")

        effects: list[Effect] = []
        synced = 0
        for claim in claims.iterator(chunk_size=100):
            try:
                effects.extend(sync_claim_adjudications(claim, self.secrets))
                synced += 1
            except Exception as e:
                log.warning(f"Candid nightly sync: failed for claim {claim.id}: {e}")

        log.info(f"Candid nightly sync: processed {synced}/{count} claims")
        return effects
