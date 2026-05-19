from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel
from cms_access_fhir_client.models.access_alignment import CustomPatient


class ACCESSWebhookEvent(CustomModel):
    """Audit log of every CMS subscription notification received."""

    event_type = TextField(default="")
    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="access_webhook_events",
    )
    alignment_id = TextField(default="")
    raw_payload = JSONField(default=dict)
    received_at = DateTimeField(auto_now_add=True)
    processed_at = DateTimeField(default=None)
    processing_status = TextField(default="pending")
    processing_error = TextField(default="")

    class Meta:
        indexes = [
            Index(fields=["event_type"]),
            Index(fields=["processing_status"]),
            Index(fields=["-received_at"]),
        ]

    # Event type constants matching CMS subscription event types
    EVENT_LOCK_IN_ENDING = "provider-lock-in-period-ending"
    EVENT_REPORTING_DUE_BASELINE = "data-reporting-due-baseline"
    EVENT_REPORTING_DUE_QUARTERLY = "data-reporting-due-quarterly"
    EVENT_REPORTING_DUE_END_OF_PERIOD = "data-reporting-due-end-of-period"
    EVENT_RENEWAL_DUE = "alignment-renewal-due"
    EVENT_UNALIGNMENT_CMS = "unalignment-cms-initiated"
    EVENT_UNALIGNMENT_PARTICIPANT = "unalignment-participant-initiated"

    ALL_EVENT_TYPES = [
        EVENT_LOCK_IN_ENDING,
        EVENT_REPORTING_DUE_BASELINE,
        EVENT_REPORTING_DUE_QUARTERLY,
        EVENT_REPORTING_DUE_END_OF_PERIOD,
        EVENT_RENEWAL_DUE,
        EVENT_UNALIGNMENT_CMS,
        EVENT_UNALIGNMENT_PARTICIPANT,
    ]

    # Processing status choices
    STATUS_PENDING = "pending"
    STATUS_OK = "ok"
    STATUS_ERROR = "error"
