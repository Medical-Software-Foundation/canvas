"""Per-reading 5-minute glucose values pulled from Dexcom egvs."""

# mypy: disable-error-code="var-annotated"

from django.db.models import (
    CharField,
    DateTimeField,
    FloatField,
    Index,
    IntegerField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel


class DexcomEgv(CustomModel):
    """One row per 5-minute reading. 90-day rolling retention per patient."""

    patient_id = CharField(max_length=64, db_index=True)
    system_time = DateTimeField(db_index=True)
    display_time = DateTimeField()
    value_mgdl = IntegerField(null=True, blank=True)
    trend = CharField(max_length=32, blank=True, default="")
    trend_rate = FloatField(null=True, blank=True)
    status = CharField(max_length=16, blank=True, default="")
    unit = CharField(max_length=16, default="mg/dL")

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_id", "system_time"],
                name="dexcomegv_unique_patient_systemtime",
            ),
        ]
        # The hot read path (chart /data) and summary recompute both filter
        # and sort on display_time scoped to a patient; a composite index
        # serves both directly.
        indexes = [
            Index(
                fields=["patient_id", "display_time"],
                name="dexcomegv_pid_displaytime_idx",
            ),
        ]
