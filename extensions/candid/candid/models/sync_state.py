"""Activity log stored as custom data.

Records Candid activity per claim: adjudication syncs, patient payment
reports, etc. Used by the claim timeline application.
"""

from django.db.models import DateTimeField, IntegerField, TextField

from canvas_sdk.v1.data.base import CustomModel

LOG_TYPE_SYNC = "sync"
LOG_TYPE_PAYMENT_REPORTED = "payment_reported"


class SyncLog(CustomModel):
    """One row per activity event per claim."""

    canvas_claim_id = TextField()
    log_type = TextField(default=LOG_TYPE_SYNC)
    candid_claim_status = TextField(default="")
    payment_effects_count = IntegerField(default=0)
    era_ids = TextField(default="")
    detail = TextField(default="")
    synced_at = DateTimeField(auto_now_add=True)
