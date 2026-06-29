"""Tests for patient_panel.services.formatting.

compare_threshold is pure; the patient-shaped helpers (coverage, address, flag)
use real ORM records via factories.
"""

__is_plugin__ = True

import arrow
import pytest

from canvas_sdk.test_utils.factories import (
    CoverageFactory,
    PatientAddressFactory,
    PatientFactory,
)
from canvas_sdk.v1.data.patient import PatientMetadata as PatientMetadataRecord

from patient_panel.services.formatting import (
    compare_threshold,
    format_local,
    format_primary_address,
    get_coverage,
    get_flag_color,
    is_patient_flagged,
)

# Default highlight thresholds (mirrors PatientPanelAPI defaults).
THRESHOLDS = {"highlight_green": 1, "highlight_yellow": 3, "highlight_red": 7}


class TestFormatLocal:
    def test_formats_in_given_tz(self) -> None:
        dt = arrow.get("2026-01-15T12:00:00+00:00")
        assert format_local(dt, "YYYY-MM-DD", "UTC") == "2026-01-15"

    def test_converts_to_tz(self) -> None:
        dt = arrow.get("2026-01-15T02:00:00+00:00")
        # New York is UTC-5 in January → previous calendar day
        assert format_local(dt, "YYYY-MM-DD", "America/New_York") == "2026-01-14"


class TestCompareThreshold:
    def test_green_for_recent(self) -> None:
        assert compare_threshold(arrow.utcnow().shift(hours=-1), THRESHOLDS) == "green"

    def test_yellow_for_moderate(self) -> None:
        assert compare_threshold(arrow.utcnow().shift(days=-2), THRESHOLDS) == "yellow"

    def test_red_for_old(self) -> None:
        assert compare_threshold(arrow.utcnow().shift(days=-5), THRESHOLDS) == "red"

    def test_red_for_very_old(self) -> None:
        assert compare_threshold(arrow.utcnow().shift(days=-30), THRESHOLDS) == "red"


pytestmark = pytest.mark.django_db


class TestGetCoverage:
    def test_returns_issuer_name(self) -> None:
        from canvas_sdk.v1.data.coverage import CoverageStack

        patient = PatientFactory.create()
        coverage = CoverageFactory.create(patient=patient, stack=CoverageStack.IN_USE)
        result = get_coverage(patient)
        assert result == coverage.issuer.name if coverage.issuer else result is None

    def test_none_when_no_coverage(self) -> None:
        patient = PatientFactory.create()
        assert get_coverage(patient) is None


class TestFormatPrimaryAddress:
    def test_empty_when_no_addresses(self) -> None:
        patient = PatientFactory.create()
        patient.addresses.all().delete()
        assert format_primary_address(patient) == ""

    def test_renders_full_address(self) -> None:
        patient = PatientFactory.create()
        patient.addresses.all().delete()
        PatientAddressFactory.create(
            patient=patient,
            line1="123 Main St",
            line2="Apt 4B",
            city="Springfield",
            state_code="IL",
            postal_code="62701",
            use="home",
            state="active",
        )
        result = format_primary_address(patient)
        assert "123 Main St" in result
        assert "Springfield" in result
        assert "IL" in result
        assert "62701" in result


class TestGetFlagColor:
    def test_returns_color_from_metadata(self) -> None:
        patient = PatientFactory.create()
        today = arrow.now().format("YYYY-MM-DD")
        PatientMetadataRecord.objects.create(patient=patient, key="daily_flag", value=f"{today}:red")
        assert get_flag_color(patient) == "red"

    def test_none_for_stale_flag(self) -> None:
        patient = PatientFactory.create()
        PatientMetadataRecord.objects.create(patient=patient, key="daily_flag", value="2020-01-01:red")
        assert get_flag_color(patient) is None

    def test_none_when_no_metadata(self) -> None:
        patient = PatientFactory.create()
        assert get_flag_color(patient) is None


class TestIsPatientFlagged:
    def test_true_when_color_set_today(self) -> None:
        patient = PatientFactory.create()
        today = arrow.now().format("YYYY-MM-DD")
        PatientMetadataRecord.objects.create(patient=patient, key="daily_flag", value=f"{today}:yellow")
        assert is_patient_flagged(patient) is True

    def test_false_when_no_flag(self) -> None:
        patient = PatientFactory.create()
        assert is_patient_flagged(patient) is False
