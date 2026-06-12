"""Per-patient sync watermark, error state, and pending-link tracking."""

# mypy: disable-error-code="var-annotated"

from django.db.models import (
    BooleanField,
    CharField,
    DateTimeField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel


class DexcomSyncState(CustomModel):
    """One row per patient. Tracks sync watermark + transient connect-link state."""

    patient_id = CharField(max_length=64)
    last_synced_at = DateTimeField(null=True, blank=True)
    last_egv_system_time = DateTimeField(null=True, blank=True)
    last_error = CharField(max_length=512, blank=True, default="")
    last_error_at = DateTimeField(null=True, blank=True)
    last_link_sent_at = DateTimeField(null=True, blank=True)
    last_link_nonce = CharField(max_length=64, blank=True, default="")
    link_pending = BooleanField(default=False)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_id"],
                name="dexcomsyncstate_unique_patient",
            ),
        ]
