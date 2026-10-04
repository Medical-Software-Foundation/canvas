"""Replay-prevention record for syncs already applied to this target.

When the target plugin receives `POST /sync` with a `sync_id` already in
this table, it short-circuits with status=succeeded instead of re-dispatching
all the effects. Retention is forever per Beau's decision (no auto-prune),
so re-syncs of the same sync_id are no-ops indefinitely.

Lives in the plugin's custom_data namespace (`patient_sync_target`), which
is declared `read_write` in `CANVAS_MANIFEST.json`.
"""

from __future__ import annotations

from django.db.models import DateTimeField, TextField, UniqueConstraint

from canvas_sdk.v1.data.base import CustomModel


class AppliedSync(CustomModel):
    """One row per sync_id the target has successfully accepted."""

    sync_id: TextField[str, str] = TextField()
    applied_at: DateTimeField = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["sync_id"], name="uq_applied_sync_sync_id"),
        ]
