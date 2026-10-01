"""Daily aggregate row computed from DexcomEgv readings."""

# mypy: disable-error-code="var-annotated"

from django.db.models import (
    CharField,
    DateField,
    FloatField,
    IntegerField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel


class DexcomSummary(CustomModel):
    """One row per (patient, local-date). Retained indefinitely."""

    patient_id = CharField(max_length=64, db_index=True)
    date = DateField()
    avg_glucose_mgdl = FloatField()
    gmi_percent = FloatField()
    tir_low_pct = FloatField()
    tir_target_pct = FloatField()
    tir_high_pct = FloatField()
    hypo_events = IntegerField(default=0)
    hyper_events = IntegerField(default=0)
    reading_count = IntegerField(default=0)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_id", "date"],
                name="dexcomsummary_unique_patient_date",
            ),
        ]
