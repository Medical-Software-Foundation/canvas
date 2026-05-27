from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
)

from canvas_sdk.v1.data.base import CustomModel

from vitalstream.models.session import VitalstreamSession


class VitalstreamReading(CustomModel):
    """A single device reading persisted as it arrives.

    One row per measurement timestamp the device pushes. Rows accumulate while
    a session is open and are read back at end-of-session to compute the mean
    Observations. Readings also let a staff member close and reopen the chart
    pane without losing data.
    """

    session = ForeignKey(
        VitalstreamSession,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="readings",
    )
    reading_time = DateTimeField()
    received_at = DateTimeField(auto_now_add=True)
    hr = IntegerField(null=True, blank=True)
    sys = IntegerField(null=True, blank=True)
    dia = IntegerField(null=True, blank=True)
    resp = IntegerField(null=True, blank=True)
    spo2 = IntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            Index(fields=["session", "reading_time"]),
        ]
