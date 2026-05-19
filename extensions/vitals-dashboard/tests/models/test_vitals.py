"""Tests for vitals_dashboard/models/vitals.py."""

from vitals_dashboard.models import vitals as vitals_module
from vitals_dashboard.models.vitals import (
    CUFF_LOCATIONS,
    POSITIONS,
    VITAL_TYPES,
    VitalsMeasurement,
    VitalsSession,
)


class TestConstants:
    def test_vital_types_includes_expected(self):
        assert "bp_systolic" in VITAL_TYPES
        assert "bp_diastolic" in VITAL_TYPES
        assert "heart_rate" in VITAL_TYPES
        assert "weight_current" in VITAL_TYPES
        assert "weight_dry" in VITAL_TYPES
        assert "urine_output" in VITAL_TYPES
        assert "oxygen_saturation" in VITAL_TYPES
        assert "respiration_rate" in VITAL_TYPES
        assert "temperature" in VITAL_TYPES
        assert "pain_score" in VITAL_TYPES
        assert "edema" in VITAL_TYPES
        assert len(VITAL_TYPES) == 11

    def test_positions(self):
        assert POSITIONS == ("laying", "sitting", "standing")

    def test_cuff_locations(self):
        assert set(CUFF_LOCATIONS) == {
            "right_arm", "left_arm",
            "right_thigh", "left_thigh",
            "right_wrist", "left_wrist",
        }


class TestVitalsSession:
    def test_fields_exist(self):
        fields = {f.name for f in VitalsSession._meta.get_fields()}
        expected = {
            "patient_key", "note_id", "entered_by_staff_key",
            "provider_of_record_key", "session_datetime",
            "note_stale", "observations_synced",
            "created_at", "updated_at",
        }
        assert expected.issubset(fields)

    def test_has_expected_indexes(self):
        idx_fields = [tuple(i.fields) for i in VitalsSession._meta.indexes]
        assert ("patient_key",) in idx_fields
        assert ("session_datetime",) in idx_fields
        assert ("note_id",) in idx_fields


class TestVitalsMeasurement:
    def test_fields_exist(self):
        fields = {f.name for f in VitalsMeasurement._meta.get_fields()}
        expected = {
            "session_id", "patient_key", "vital_type",
            "position", "cuff_location",
            "value_numeric", "value_text", "unit",
            "recorded_at", "entered_by_staff_key", "is_deleted",
            "created_at", "updated_at",
        }
        assert expected.issubset(fields)

    def test_has_expected_indexes(self):
        idx_fields = [tuple(i.fields) for i in VitalsMeasurement._meta.indexes]
        assert ("session_id",) in idx_fields
        assert ("patient_key", "vital_type") in idx_fields
        assert ("patient_key", "recorded_at") in idx_fields
        assert ("is_deleted",) in idx_fields


class TestCustomModelImport:
    def test_custom_model_flag_defined(self):
        assert isinstance(vitals_module._HAS_CUSTOM_MODEL, bool)
