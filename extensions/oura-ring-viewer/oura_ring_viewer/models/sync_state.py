"""Per-patient connection status: last fetch, last error, pending link."""

# mypy: disable-error-code="var-annotated"

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import BooleanField, CharField, DateTimeField, UniqueConstraint


class OuraSyncState(CustomModel):
    """One row per patient. Holds connection status, never Oura data.

    ``last_synced_at`` is the time of the last successful fetch from Oura.
    """

    patient_id = CharField(max_length=64)
    last_synced_at = DateTimeField(null=True, blank=True)
    last_error = CharField(max_length=512, blank=True, default="")
    last_error_at = DateTimeField(null=True, blank=True)
    last_link_sent_at = DateTimeField(null=True, blank=True)
    last_link_nonce = CharField(max_length=64, blank=True, default="")
    link_pending = BooleanField(default=False)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_id"],
                name="ourasyncstate_unique_patient",
            ),
        ]
