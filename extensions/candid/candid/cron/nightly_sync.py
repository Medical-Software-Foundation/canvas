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
from django.db.models import Max
from logger import log

from candid.adjudication_sync import sync_claim_adjudications
from candid.effect_helpers import META_ENCOUNTERS
from candid.models.sync_state import LOG_TYPE_SYNC, SyncLog

SYNC_QUEUES = (
    ClaimQueues.FILED_AWAITING_RESPONSE,
    ClaimQueues.ADJUDICATED_OPEN_BALANCE,
    ClaimQueues.PATIENT_BALANCE,
    ClaimQueues.REJECTED_NEEDS_REVIEW,
)

# Queues a claim lands in once it is done; its sync logs are pure cruft.
FINISHED_QUEUES = (ClaimQueues.ZERO_BALANCE, ClaimQueues.TRASH)

TARGET_HOUR = 2  # 2 AM local time


def _prune_synclog() -> int:
    """Reclaim SyncLog rows that no longer carry information.

    Two passes, both safe to run nightly:

    1. Collapse redundant *no-op* sync rows (no ERA, no payment posted) down to
       the most recent one per claim. These dominate growth -- one row per open
       claim per night -- and an older "nothing changed" row says nothing the
       latest one doesn't.
    2. Drop every row for claims that have reached a terminal queue
       (ZeroBalance / Trash); those claims will never sync again.

    Rows that recorded an ERA or a payment are left untouched, so adjudication
    history is preserved for the life of the claim.
    """
    deleted = 0
    try:
        noop = SyncLog.objects.filter(
            log_type=LOG_TYPE_SYNC, payment_effects_count=0, era_ids=""
        )
        keep_ids = list(
            noop.values("canvas_claim_id")
            .annotate(latest_id=Max("id"))
            .values_list("latest_id", flat=True)
        )
        deleted += noop.exclude(id__in=keep_ids).delete()[0]

        finished_values = [q.value for q in FINISHED_QUEUES]
        finished_claim_ids = [
            str(cid)
            for cid in Claim.objects.filter(
                current_queue__queue_sort_ordering__in=finished_values,
                metadata__key=META_ENCOUNTERS,
            ).values_list("id", flat=True)
        ]
        if finished_claim_ids:
            deleted += SyncLog.objects.filter(
                canvas_claim_id__in=finished_claim_ids
            ).delete()[0]
    except Exception as e:
        log.warning(f"Candid nightly sync: failed to prune SyncLog: {e}")
        return deleted

    if deleted:
        log.info(f"Candid nightly sync: pruned {deleted} SyncLog rows")
    return deleted


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

        effects: list[Effect] = []
        count = claims.count()
        if count == 0:
            log.info("Candid nightly sync: no claims to sync")
        else:
            log.info(f"Candid nightly sync: syncing {count} claims")
            synced = 0
            for claim in claims.iterator(chunk_size=100):
                try:
                    effects.extend(sync_claim_adjudications(claim, self.secrets))
                    synced += 1
                except Exception as e:
                    log.warning(
                        f"Candid nightly sync: failed for claim {claim.id}: {e}"
                    )
            log.info(f"Candid nightly sync: processed {synced}/{count} claims")

        _prune_synclog()
        return effects
