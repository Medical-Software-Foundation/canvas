"""One-time cron that migrates legacy SyncLog rows into claim metadata.

Sync activity used to live in a ``SyncLog`` custom model; it now lives on each
claim's ``candid_sync_history`` metadata. This cron folds any pre-migration
``SyncLog`` rows into that metadata so existing timelines are preserved.

It runs at **midnight** local time -- two hours ahead of ``NightlyCandidSync``
(2 AM) -- on purpose. Both this backfill and the sync's ``append_sync_history``
write the ``candid_sync_history`` key, and an effect reads the pre-handler DB
snapshot. If they ran in the same effect batch the sync's write would clobber
the backfill's merge (last-write-wins). Running two hours earlier lets the
merged metadata commit before the sync reads it.

Self-terminating: rows are deleted as they are migrated, so once every
environment has run this the ``SyncLog`` table is empty and the cron is a no-op.
Once it has run everywhere, this module, ``models/sync_state.py``, and the table
can be dropped in a follow-up.
"""

import json
from collections import defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.claim import Claim
from logger import log

from candid.effect_helpers import (
    META_SYNC_HISTORY,
    MAX_SYNC_HISTORY,
    get_claim_metadata,
)
from candid.models.sync_state import SyncLog

BACKFILL_HOUR = 0  # midnight local time, two hours ahead of NightlyCandidSync


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
    """Migrate legacy SyncLog rows into ``candid_sync_history`` metadata.

    Self-terminating: rows are deleted as they are migrated, so once the table
    is drained this returns immediately. Safe to re-run -- ``_merge_history``
    dedupes, so a partial failure just retries the next night. Orphaned rows
    (claim no longer exists) are dropped without a metadata write.
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


class CandidSyncHistoryBackfill(CronTask):
    """Migrate legacy SyncLog rows into metadata at midnight local time.

    Fires every hour (``SCHEDULE = "0 * * * *"``); ``execute()`` returns early
    unless it's the backfill hour. A no-op once the SyncLog table is drained.
    """

    SCHEDULE = "0 * * * *"

    def execute(self) -> list[Effect]:
        tz_name = self.environment.get("INSTALLATION_TIME_ZONE")
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("US/Central")
        local_hour = datetime.now(UTC).astimezone(tz).hour
        if local_hour != BACKFILL_HOUR:
            return []
        return _backfill_sync_history()
