"""Nightly cron job to sync adjudication data from Candid for pending claims.

Queries Canvas for all claims in FiledAwaitingResponse, AdjudicatedOpenBalance,
PatientBalance and RejectedNeedsReview queues that have Candid encounter metadata, then runs
``sync_claim_adjudications`` on each to pull ERA data, patient payments, and
post them back to Canvas.

The cron fires every hour. A sync cycle starts at the hour set in
``CANDID_SYNC_START_HOUR`` (0-23, default 2 AM) in the instance's configured
time zone (``INSTALLATION_TIME_ZONE``) and works through the claims one batch
per hour, so no single run returns more effects than the plugin runner can send
back (its responses are capped at 64 MB). A cycle already under way keeps going
until it finishes, whatever the hour, and at most one cycle starts per local
day (so the fall-back hour, or an hour changed after today's cycle, never starts
a second full sync the same day).
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_sdk.caching.plugins import get_cache
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
    ClaimQueues.REJECTED_NEEDS_REVIEW,
)

DEFAULT_START_HOUR = 2  # 2 AM local time
START_HOUR_VARIABLE = "CANDID_SYNC_START_HOUR"

# A batch must end before the next hourly tick, and its effects must stay far
# below the 64 MB cap (one unbatched run over ~24k claims was ~78 MB).
BATCH_TIME_BUDGET = timedelta(minutes=45)
MAX_CLAIMS_PER_BATCH = 4000

CURSOR_CACHE_KEY = "candid_nightly_sync_cursor"
CURSOR_TTL_SECONDS = 20 * 60 * 60
LOCK_CACHE_KEY = "candid_nightly_sync_lock"
LOCK_TTL_SECONDS = 90 * 60
# The local date the last cycle started on, so one day never starts two cycles.
LAST_START_CACHE_KEY = "candid_nightly_sync_last_start_date"
LAST_START_TTL_SECONDS = 26 * 60 * 60


def start_hour(secrets: dict) -> int:
    """The local hour a sync cycle starts: ``CANDID_SYNC_START_HOUR``, else 2.

    A blank value means the default. Anything that isn't a whole number from 0
    to 23 also falls back to the default, with a warning, so a typo never stops
    the nightly sync.
    """
    raw = (secrets or {}).get(START_HOUR_VARIABLE)
    if raw is None or str(raw).strip() == "":
        return DEFAULT_START_HOUR
    text = str(raw).strip()
    # ASCII digits only: str.isdigit() also accepts characters like "²" that int() rejects.
    if 1 <= len(text) <= 2 and all("0" <= ch <= "9" for ch in text) and int(text) <= 23:
        return int(text)
    log.warning(
        f"Candid nightly sync: {START_HOUR_VARIABLE}={text!r} is not an hour from 0 to 23; "
        f"starting at {DEFAULT_START_HOUR}"
    )
    return DEFAULT_START_HOUR


class NightlyCandidSync(CronTask):
    """Sync adjudication data from the configured start hour, one batch per hour."""

    SCHEDULE = "0 * * * *"

    def execute(self) -> list[Effect]:
        tz_name = self.environment.get("INSTALLATION_TIME_ZONE")
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("US/Central")
        started = datetime.now(UTC)
        cache = get_cache()

        cursor = cache.get(CURSOR_CACHE_KEY)
        if not cursor:
            local = started.astimezone(tz)
            if local.hour != start_hour(self.secrets):
                return []
            today = local.date().isoformat()
            if cache.get(LAST_START_CACHE_KEY) == today:
                return []
            cache.set(LAST_START_CACHE_KEY, today, timeout_seconds=LAST_START_TTL_SECONDS)

        if cache.get(LOCK_CACHE_KEY):
            log.info("Candid nightly sync: previous batch still running, skipping")
            return []

        cache.set(LOCK_CACHE_KEY, started.isoformat(), timeout_seconds=LOCK_TTL_SECONDS)
        try:
            return self._sync_batch(cache, cursor, started)
        finally:
            cache.delete(LOCK_CACHE_KEY)

    def _sync_batch(self, cache, cursor: str | None, started: datetime) -> list[Effect]:
        queue_values = [q.value for q in SYNC_QUEUES]
        claims = Claim.objects.filter(
            current_queue__queue_sort_ordering__in=queue_values,
            metadata__key=META_ENCOUNTERS,
        ).order_by("id")
        if cursor:
            claims = claims.filter(id__gt=cursor)

        effects: list[Effect] = []
        processed = 0
        synced = 0
        last_claim_id = None
        for claim in claims.iterator(chunk_size=100):
            if (
                processed >= MAX_CLAIMS_PER_BATCH
                or datetime.now(UTC) - started > BATCH_TIME_BUDGET
            ):
                cache.set(
                    CURSOR_CACHE_KEY, last_claim_id, timeout_seconds=CURSOR_TTL_SECONDS
                )
                log.info(
                    f"Candid nightly sync: synced {synced}/{processed} claims, "
                    "continuing next hour"
                )
                return effects

            processed = processed + 1
            last_claim_id = str(claim.id)
            try:
                effects.extend(sync_claim_adjudications(claim, self.secrets))
                synced = synced + 1
            except Exception as e:
                log.warning(f"Candid nightly sync: failed for claim {claim.id}: {e}")

        cache.delete(CURSOR_CACHE_KEY)
        log.info(
            f"Candid nightly sync: synced {synced}/{processed} claims, cycle complete"
        )
        return effects
