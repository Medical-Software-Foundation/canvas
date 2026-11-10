"""Per-patient connection status: last fetch, last error, pending link."""

# mypy: disable-error-code="var-annotated"

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    BooleanField,
    CharField,
    DateTimeField,
    OneToOneField,
)

from oura_ring_viewer.models.proxy import PatientProxy


class OuraSyncState(CustomModel):
    """One row per patient. Holds connection status, never Oura data.

    ``last_synced_at`` is the time of the last successful fetch from Oura.
    """

    patient = OneToOneField(
        PatientProxy, to_field="dbid", on_delete=DO_NOTHING, related_name="oura_sync_state"
    )
    last_synced_at = DateTimeField()
    last_error = CharField(default="")
    last_error_at = DateTimeField()
    last_link_sent_at = DateTimeField()
    last_link_nonce = CharField(default="")
    link_pending = BooleanField(default=False)
