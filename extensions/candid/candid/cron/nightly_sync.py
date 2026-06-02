"""Nightly cron job to sync adjudication data from Candid for pending claims.

Queries Canvas for all claims in FiledAwaitingResponse, AdjudicatedOpenBalance,
and PatientBalance queues that have Candid encounter metadata, then runs
``sync_claim_adjudications`` on each to pull ERA data, patient payments, and
post them back to Canvas.

The cron fires every hour but only does work at 2 AM in the instance's
configured time zone (``INSTALLATION_TIME_ZONE``). This avoids hardcoding
a UTC hour that maps to a different local time for each customer.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.claim import Claim, ClaimQueues
from logger import log

from candid.adjudication_sync import sync_claim_adjudications
from candid.effect_helpers import META_ENCOUNTERS
from candid.models.sync_state import SyncLog

SYNC_QUEUES = (
    ClaimQueues.FILED_AWAITING_RESPONSE,
    ClaimQueues.ADJUDICATED_OPEN_BALANCE,
    ClaimQueues.PATIENT_BALANCE,
    ClaimQueues.REJECTED_NEEDS_REVIEW,
)

TARGET_HOUR = 2  # 2 AM local time
SYNCLOG_RETENTION_DAYS = 90

# Claims in these queues are "done" — their SyncLog rows can be pruned.
FINISHED_QUEUES = (
    ClaimQueues.ZERO_BALANCE,
    ClaimQueues.TRASH,
)


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

        _prune_synclog()

        return effects


def _prune_synclog() -> None:
    """Delete SyncLog rows for claims that have reached a terminal queue
    (ZeroBalance, Trash) or that are older than the retention period.

    Runs as part of the nightly sync to keep the table bounded.
    """
    try:
        # Prune rows for claims in terminal queues. canvas_claim_id is stored as
        # text, so the UUIDs must be stringified to match.
        finished_queue_values = [q.value for q in FINISHED_QUEUES]
        finished_str_ids = {
            str(cid)
            for cid in Claim.objects.filter(
                current_queue__queue_sort_ordering__in=finished_queue_values,
            ).values_list("id", flat=True)
        }
        if finished_str_ids:
            deleted_finished, _ = SyncLog.objects.filter(
                canvas_claim_id__in=finished_str_ids
            ).delete()
            if deleted_finished:
                log.info(
                    f"Candid nightly sync: pruned {deleted_finished} SyncLog rows "
                    f"for {len(finished_str_ids)} finished claims"
                )

        # Prune rows older than retention period regardless of queue
        cutoff = datetime.now(UTC) - timedelta(days=SYNCLOG_RETENTION_DAYS)
        deleted_old, _ = SyncLog.objects.filter(synced_at__lt=cutoff).delete()
        if deleted_old:
            log.info(
                f"Candid nightly sync: pruned {deleted_old} SyncLog rows "
                f"older than {SYNCLOG_RETENTION_DAYS} days"
            )
    except Exception:
        log.warning("Candid nightly sync: failed to prune SyncLog", exc_info=True)
