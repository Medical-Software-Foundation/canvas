try:
    from canvas_sdk.v1.data.base import CustomModel

    _HAS_CUSTOM_MODEL = True
except ImportError:
    from django.db.models import Model as CustomModel

    _HAS_CUSTOM_MODEL = False

from django.db.models import (
    BooleanField,
    DateTimeField,
    DecimalField,
    Index,
    TextField,
)


VITAL_TYPES = (
    "bp_systolic",
    "bp_diastolic",
    "heart_rate",
    "weight_current",
    "weight_dry",
    "urine_output",
    "oxygen_saturation",
    "respiration_rate",
    "temperature",
    "pain_score",
    "edema",
)

POSITIONS = ("laying", "sitting", "standing")

CUFF_LOCATIONS = (
    "right_arm",
    "left_arm",
    "right_thigh",
    "left_thigh",
    "right_wrist",
    "left_wrist",
)


class VitalsSession(CustomModel):
    """One charting session for a patient — groups related measurements."""

    patient_key = TextField()
    note_id = TextField(blank=True, default="")
    entered_by_staff_key = TextField()
    provider_of_record_key = TextField(blank=True, default="")
    session_datetime = DateTimeField()
    note_stale = BooleanField(default=False)
    observations_synced = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        if not _HAS_CUSTOM_MODEL:
            app_label = "vitals_dashboard"
        indexes = [
            Index(fields=["patient_key"]),
            Index(fields=["session_datetime"]),
            Index(fields=["note_id"]),
        ]


class VitalsMeasurement(CustomModel):
    """A single measurement within a VitalsSession."""

    session_id = TextField()
    patient_key = TextField()
    vital_type = TextField()
    position = TextField(blank=True, default="")
    cuff_location = TextField(blank=True, default="")
    value_numeric = DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    value_text = TextField(blank=True, default="")
    unit = TextField(blank=True, default="")
    recorded_at = DateTimeField()
    entered_by_staff_key = TextField()
    is_deleted = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        if not _HAS_CUSTOM_MODEL:
            app_label = "vitals_dashboard"
        indexes = [
            Index(fields=["session_id"]),
            Index(fields=["patient_key", "vital_type"]),
            Index(fields=["patient_key", "recorded_at"]),
            Index(fields=["is_deleted"]),
        ]
