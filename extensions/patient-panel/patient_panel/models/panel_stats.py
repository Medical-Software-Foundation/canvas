"""Per-patient denormalized sort/filter accelerator for the panel table.

Only STABLE derived keys live here as typed, indexed columns. Config-driven
values (metadata) are intentionally excluded — CustomModel DDL is append-only
(columns can never be altered/dropped), so config-dependent columns are unsafe.
"""

from canvas_sdk.v1.data import ModelExtension, Patient
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    Index,
    IntegerField,
    OneToOneField,
    TextField,
)


class CustomPatient(Patient, ModelExtension):
    """Proxy of the SDK Patient — creates no table; gives a clean reverse name."""

    pass


class PatientPanelStats(CustomModel):
    """One row per patient. All columns are nullable at the DB level regardless
    of declaration (Canvas creates custom columns nullable). Do NOT add
    null=/blank=/max_length=/db_index= — declare indexes in Meta only."""

    patient: OneToOneField = OneToOneField(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="panel_stats",
    )
    last_visit_dt: DateTimeField = DateTimeField()
    next_visit_dt: DateTimeField = DateTimeField()
    room_number: TextField = TextField(default="")
    tasks_open_count: IntegerField = IntegerField(default=0)
    gaps_due_count: IntegerField = IntegerField(default=0)
    updated: DateTimeField = DateTimeField()

    class Meta:
        indexes = [
            Index(fields=["last_visit_dt"]),
            Index(fields=["next_visit_dt"]),
            Index(fields=["room_number"]),
            Index(fields=["tasks_open_count"]),
            Index(fields=["gaps_due_count"]),
        ]
