"""Tests for helper module functions."""

import pytest
from unittest.mock import MagicMock, patch

from high_risk_medications.helper import (
    get_high_risk_meds,
    parse_patterns,
)


class TestParsePatterns:
    """Test suite for parse_patterns function."""

    def test_parses_json_array(self):
        """Test parsing a JSON array of patterns."""
        result = parse_patterns('["warfarin", "insulin"]')
        assert result == ["warfarin", "insulin"]

    def test_parses_comma_separated_string(self):
        """Test parsing a comma-separated string of patterns."""
        result = parse_patterns("warfarin, insulin, digoxin")
        assert result == ["warfarin", "insulin", "digoxin"]

    def test_strips_whitespace_from_comma_separated(self):
        """Test that whitespace is stripped from comma-separated values."""
        result = parse_patterns("  warfarin  ,  insulin  ")
        assert result == ["warfarin", "insulin"]

    def test_lowercases_comma_separated_patterns(self):
        """Test that comma-separated patterns are lowercased."""
        result = parse_patterns("WARFARIN, Insulin")
        assert result == ["warfarin", "insulin"]

    def test_raises_for_empty_string(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError):
            parse_patterns("")

    def test_raises_for_none(self):
        """Test that None raises ValueError."""
        with pytest.raises(ValueError):
            parse_patterns(None)

    def test_filters_empty_values_from_comma_separated(self):
        """Test that empty values are filtered from comma-separated input."""
        result = parse_patterns("warfarin,,insulin,")
        assert result == ["warfarin", "insulin"]


class TestGetHighRiskMeds:
    """Test suite for get_high_risk_meds function."""

    def test_returns_empty_list_when_no_medications(self):
        """Test that empty list is returned when patient has no medications."""
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = []

            result = get_high_risk_meds("patient-123", "warfarin,insulin")

        assert result == []
        mock_objects.filter.assert_called_once_with(
            patient__id="patient-123", status="active"
        )

    def test_uses_custom_json_patterns(self):
        """Test that custom JSON patterns are used when provided."""
        mock_med = MagicMock()
        mock_med.id = "med-123"
        mock_coding = MagicMock()
        mock_coding.display = "Custom Drug 5mg"
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-456", '["custom"]')

        assert len(result) == 1
        assert result[0]["name"] == "Custom Drug 5mg"

    def test_uses_custom_comma_separated_patterns(self):
        """Test that custom comma-separated patterns are used when provided."""
        mock_med = MagicMock()
        mock_med.id = "med-123"
        mock_coding = MagicMock()
        mock_coding.display = "Another Drug 10mg"
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-456", "another, something")

        assert len(result) == 1
        assert result[0]["name"] == "Another Drug 10mg"

    def test_returns_warfarin_medication(self):
        """Test that warfarin is identified as high-risk."""
        mock_med = MagicMock()
        mock_med.id = "med-123"
        mock_coding = MagicMock()
        mock_coding.display = "Warfarin 5mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-456", "warfarin")

        assert len(result) == 1
        assert result[0]["name"] == "Warfarin 5mg Tablet"
        assert result[0]["id"] == "med-123"

    def test_returns_insulin_medication(self):
        """Test that insulin is identified as high-risk."""
        mock_med = MagicMock()
        mock_med.id = "med-456"
        mock_coding = MagicMock()
        mock_coding.display = "Insulin Glargine 100 units/mL"
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-789", "insulin")

        assert len(result) == 1
        assert result[0]["name"] == "Insulin Glargine 100 units/mL"
        assert result[0]["id"] == "med-456"

    def test_filters_out_non_high_risk_medications(self):
        """Test that non-high-risk medications are excluded."""
        mock_med = MagicMock()
        mock_med.id = "med-999"
        mock_coding = MagicMock()
        mock_coding.display = "Acetaminophen 500mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-303", "warfarin,insulin")

        assert result == []

    def test_returns_multiple_high_risk_medications(self):
        """Test that multiple high-risk medications are all returned."""
        mock_med1 = MagicMock()
        mock_med1.id = "med-111"
        mock_coding1 = MagicMock()
        mock_coding1.display = "Warfarin 5mg Tablet"
        mock_med1.codings.first.return_value = mock_coding1

        mock_med2 = MagicMock()
        mock_med2.id = "med-222"
        mock_coding2 = MagicMock()
        mock_coding2.display = "Insulin Glargine 100 units/mL"
        mock_med2.codings.first.return_value = mock_coding2

        mock_med3 = MagicMock()
        mock_med3.id = "med-333"
        mock_coding3 = MagicMock()
        mock_coding3.display = "Acetaminophen 500mg Tablet"
        mock_med3.codings.first.return_value = mock_coding3

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med1, mock_med2, mock_med3]

            result = get_high_risk_meds("patient-404", "warfarin,insulin")

        assert len(result) == 2
        assert result[0]["name"] == "Warfarin 5mg Tablet"
        assert result[1]["name"] == "Insulin Glargine 100 units/mL"

    def test_case_insensitive_matching(self):
        """Test that pattern matching is case-insensitive."""
        mock_med = MagicMock()
        mock_med.id = "med-555"
        mock_coding = MagicMock()
        mock_coding.display = "WARFARIN SODIUM 5 MG"
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-505", "warfarin")

        assert len(result) == 1
        assert result[0]["name"] == "WARFARIN SODIUM 5 MG"

    def test_handles_null_display_name(self):
        """Test that medication with null display name is handled gracefully."""
        mock_med = MagicMock()
        mock_med.id = "med-666"
        mock_coding = MagicMock()
        mock_coding.display = None
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-606", "warfarin")

        assert result == []

    def test_filters_only_active_medications(self):
        """Test that only active medications are queried."""
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = []

            get_high_risk_meds("patient-808", "warfarin")

        mock_objects.filter.assert_called_once_with(
            patient__id="patient-808", status="active"
        )
