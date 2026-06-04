"""Legacy SyncLog model — retained only for the one-time history backfill.

Activity is now stored on claim metadata under ``META_SYNC_HISTORY`` (see
``effect_helpers.append_sync_history``). This model exists solely so the nightly
backfill (``cron.nightly_sync._backfill_sync_history``) can read the rows that
predate that change and fold them into metadata. The backfill deletes rows as it
migrates them, so once it has run in every environment this module and its table
can be dropped in a follow-up.
"""

from django.db.models import DateTimeField, IntegerField, TextField

from canvas_sdk.v1.data.base import CustomModel


class SyncLog(CustomModel):
    """One row per activity event per claim. Read-only; no longer written."""

    canvas_claim_id = TextField()
    log_type = TextField(default="sync")
    candid_claim_status = TextField(default="")
    payment_effects_count = IntegerField(default=0)
    era_ids = TextField(default="")
    detail = TextField(default="")
    synced_at = DateTimeField(auto_now_add=True)
