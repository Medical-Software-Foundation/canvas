"""Nightly cron job to sync adjudication data from Candid for pending claims.

Queries Canvas for all claims in FiledAwaitingResponse, AdjudicatedOpenBalance,
and PatientBalance queues that have Candid encounter metadata, then runs
``sync_claim_adjudications`` on each to pull ERA data, patient payments, and
post them back to Canvas.

The cron fires every hour but only does work at 2 AM in the instance's
configured time zone (``INSTALLATION_TIME_ZONE``). This avoids hardcoding
a UTC hour that maps to a different local time for each customer.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

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

TARGET_HOUR = 2  # 2 AM local time


class NightlyCandidSync(CronTask):
    """Sync adjudication data at 2 AM in the instance's local time zone.

    Fires every hour (``SCHEDULE = "0 * * * *"``), but ``execute()`` checks
    the current local hour and returns early unless it's the target hour.
    """

    SCHEDULE = "0 * * * *"

    def execute(self) -> list[Effect]:
        tz_name = self.environment.get("INSTALLATION_TIME_ZONE")
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("US/Central")
        local_hour = datetime.now(UTC).astimezone(tz).hour
        if local_hour != TARGET_HOUR:
            return []
        queue_values = [q.value for q in SYNC_QUEUES]
        claims = Claim.objects.filter(
            current_queue__queue_sort_ordering__in=queue_values,
            metadata__key=META_ENCOUNTERS,
        ).prefetch_related("metadata", "coverages", "line_items")

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
