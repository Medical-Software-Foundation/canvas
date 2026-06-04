"""Nightly cron job to sync adjudication data from Candid for pending claims.

Queries Canvas for all claims in FiledAwaitingResponse, AdjudicatedOpenBalance,
and PatientBalance queues that have Candid encounter metadata, then runs
``sync_claim_adjudications`` on each to pull ERA data, patient payments, and
post them back to Canvas.

The cron fires every hour but only does work at 2 AM in the instance's
configured time zone (``INSTALLATION_TIME_ZONE``). This avoids hardcoding
a UTC hour that maps to a different local time for each customer.
"""

import json
from collections import defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.claim import Claim, ClaimQueues
from logger import log

from candid.adjudication_sync import sync_claim_adjudications
from candid.effect_helpers import (
    META_ENCOUNTERS,
    META_SYNC_HISTORY,
    MAX_SYNC_HISTORY,
    get_claim_metadata,
)
from candid.models.sync_state import SyncLog

SYNC_QUEUES = (
    ClaimQueues.FILED_AWAITING_RESPONSE,
    ClaimQueues.ADJUDICATED_OPEN_BALANCE,
    ClaimQueues.PATIENT_BALANCE,
    ClaimQueues.REJECTED_NEEDS_REVIEW,
)

TARGET_HOUR = 2  # 2 AM local time


def _row_to_entry(row: SyncLog) -> dict:
    """Render a legacy SyncLog row in the metadata sync-history entry shape."""
    return {
        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
        "log_type": row.log_type,
        "status": row.candid_claim_status,
        "effects": row.payment_effects_count,
        "era_ids": row.era_ids.split(",") if row.era_ids else [],
        "detail": row.detail,
    }


def _merge_history(existing: list, legacy: list) -> list:
    """Fold legacy entries under any existing (post-migration) ones.

    Existing entries win on collision so a backfill can never clobber history
    written since the migration. Deduped by (synced_at, log_type, detail), sorted
    newest-first, capped at MAX_SYNC_HISTORY.
    """
    seen: set[tuple] = set()
    merged: list = []
    for entry in [*existing, *legacy]:
        key = (entry.get("synced_at"), entry.get("log_type"), entry.get("detail"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    merged.sort(key=lambda e: e.get("synced_at") or "", reverse=True)
    return merged[:MAX_SYNC_HISTORY]


def _backfill_sync_history() -> list[Effect]:
    """One-time migration of legacy SyncLog rows into claim metadata.

    Self-terminating: rows are deleted as they are migrated, so once every
    environment has run this the SyncLog table is empty and this is a no-op.
    Safe to re-run -- ``_merge_history`` dedupes, so a partial failure just
    retries the next night. Orphaned rows (claim no longer exists) are dropped.
    """
    queryset = SyncLog.objects.all()
    rows = list(queryset)
    if not rows:
        return []

    rows_by_claim: dict[str, list[SyncLog]] = defaultdict(list)
    for row in rows:
        rows_by_claim[row.canvas_claim_id].append(row)

    claims = {
        str(c.id): c
        for c in Claim.objects.filter(id__in=list(rows_by_claim.keys()))
    }

    effects: list[Effect] = []
    for claim_id, claim_rows in rows_by_claim.items():
        claim = claims.get(claim_id)
        if claim is None:
            continue  # orphaned rows -- deleted below, nowhere to migrate to
        existing = get_claim_metadata(claim, META_SYNC_HISTORY)
        existing = existing if isinstance(existing, list) else []
        merged = _merge_history(existing, [_row_to_entry(r) for r in claim_rows])
        effects.append(
            ClaimEffect(claim_id=claim_id).upsert_metadata(
                key=META_SYNC_HISTORY,
                value=json.dumps(merged),
            )
        )

    deleted = queryset.delete()[0]
    log.info(
        f"Candid sync-history backfill: migrated {len(effects)} claims, "
        f"deleted {deleted} legacy rows"
    )
    return effects


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

        # One-time legacy backfill; a no-op once the SyncLog table is drained.
        effects: list[Effect] = _backfill_sync_history()

        queue_values = [q.value for q in SYNC_QUEUES]
        claims = Claim.objects.filter(
            current_queue__queue_sort_ordering__in=queue_values,
            metadata__key=META_ENCOUNTERS,
        )

        count = claims.count()
        if count == 0:
            log.info("Candid nightly sync: no claims to sync")
        else:
            log.info(f"Candid nightly sync: syncing {count} claims")
            synced = 0
            for claim in claims.iterator(chunk_size=100):
                try:
                    effects.extend(sync_claim_adjudications(claim, self.secrets))
                    synced = synced + 1
                except Exception as e:
                    log.warning(
                        f"Candid nightly sync: failed for claim {claim.id}: {e}"
                    )
            log.info(f"Candid nightly sync: processed {synced}/{count} claims")

        return effects
