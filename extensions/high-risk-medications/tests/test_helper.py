"""Tests for helper module functions."""

import pytest
from unittest.mock import MagicMock, patch

from high_risk_medications.helper import (
    get_high_risk_meds,
    HIGH_RISK_PATTERNS,
)


class TestHighRiskPatterns:
    """Test suite for HIGH_RISK_PATTERNS constant."""

    def test_high_risk_patterns_contains_warfarin(self):
        """Test that warfarin is in HIGH_RISK_PATTERNS."""
        assert "warfarin" in HIGH_RISK_PATTERNS

    def test_high_risk_patterns_contains_insulin(self):
        """Test that insulin is in HIGH_RISK_PATTERNS."""
        assert "insulin" in HIGH_RISK_PATTERNS

    def test_high_risk_patterns_contains_digoxin(self):
        """Test that digoxin is in HIGH_RISK_PATTERNS."""
        assert "digoxin" in HIGH_RISK_PATTERNS

    def test_high_risk_patterns_contains_methotrexate(self):
        """Test that methotrexate is in HIGH_RISK_PATTERNS."""
        assert "methotrexate" in HIGH_RISK_PATTERNS

    def test_high_risk_patterns_has_four_medications(self):
        """Test that HIGH_RISK_PATTERNS contains exactly 4 medications."""
        assert len(HIGH_RISK_PATTERNS) == 4


class TestGetHighRiskMeds:
    """Test suite for get_high_risk_meds function."""

    def test_returns_empty_list_when_no_medications(self):
        """Test that empty list is returned when patient has no medications."""
        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = []

            result = get_high_risk_meds("patient-123")

        # Verify
        assert result == []
        mock_objects.filter.assert_called_once_with(
            patient__id="patient-123", status="active"
        )

    def test_returns_warfarin_medication(self):
        """Test that warfarin is identified as high-risk."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-123"
        mock_coding = MagicMock()
        mock_coding.display = "Warfarin 5mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-456")

        # Verify
        assert len(result) == 1
        assert result[0]["name"] == "Warfarin 5mg Tablet"
        assert result[0]["id"] == "med-123"

    def test_returns_insulin_medication(self):
        """Test that insulin is identified as high-risk."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-456"
        mock_coding = MagicMock()
        mock_coding.display = "Insulin Glargine 100 units/mL"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-789")

        # Verify
        assert len(result) == 1
        assert result[0]["name"] == "Insulin Glargine 100 units/mL"
        assert result[0]["id"] == "med-456"

    def test_returns_digoxin_medication(self):
        """Test that digoxin is identified as high-risk."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-789"
        mock_coding = MagicMock()
        mock_coding.display = "Digoxin 0.25mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-101")

        # Verify
        assert len(result) == 1
        assert result[0]["name"] == "Digoxin 0.25mg Tablet"
        assert result[0]["id"] == "med-789"

    def test_returns_methotrexate_medication(self):
        """Test that methotrexate is identified as high-risk."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-101"
        mock_coding = MagicMock()
        mock_coding.display = "Methotrexate 2.5mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-202")

        # Verify
        assert len(result) == 1
        assert result[0]["name"] == "Methotrexate 2.5mg Tablet"
        assert result[0]["id"] == "med-101"

    def test_filters_out_non_high_risk_medications(self):
        """Test that non-high-risk medications are excluded."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-999"
        mock_coding = MagicMock()
        mock_coding.display = "Acetaminophen 500mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-303")

        # Verify
        assert result == []

    def test_returns_multiple_high_risk_medications(self):
        """Test that multiple high-risk medications are all returned."""
        # Setup
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

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med1, mock_med2, mock_med3]

            result = get_high_risk_meds("patient-404")

        # Verify - should only return the 2 high-risk medications
        assert len(result) == 2
        assert result[0]["name"] == "Warfarin 5mg Tablet"
        assert result[0]["id"] == "med-111"
        assert result[1]["name"] == "Insulin Glargine 100 units/mL"
        assert result[1]["id"] == "med-222"

    def test_case_insensitive_matching(self):
        """Test that pattern matching is case-insensitive."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-555"
        mock_coding = MagicMock()
        mock_coding.display = "WARFARIN SODIUM 5 MG"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-505")

        # Verify
        assert len(result) == 1
        assert result[0]["name"] == "WARFARIN SODIUM 5 MG"
        assert result[0]["id"] == "med-555"

    def test_handles_null_display_name(self):
        """Test that medication with null display name is handled gracefully."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-666"
        mock_coding = MagicMock()
        mock_coding.display = None
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-606")

        # Verify - should not crash and should return empty list
        assert result == []

    def test_handles_empty_display_name(self):
        """Test that medication with empty display name is handled gracefully."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-777"
        mock_coding = MagicMock()
        mock_coding.display = ""
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-707")

        # Verify - should not crash and should return empty list
        assert result == []

    def test_filters_only_active_medications(self):
        """Test that only active medications are queried."""
        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = []

            get_high_risk_meds("patient-808")

        # Verify status="active" filter was used
        mock_objects.filter.assert_called_once_with(
            patient__id="patient-808", status="active"
        )

    def test_partial_name_matching(self):
        """Test that partial pattern matching works correctly."""
        # Setup - "warfarin" should match "Warfarin Sodium"
        mock_med = MagicMock()
        mock_med.id = "med-888"
        mock_coding = MagicMock()
        mock_coding.display = "Warfarin Sodium Oral Solution"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-909")

        # Verify
        assert len(result) == 1
        assert result[0]["name"] == "Warfarin Sodium Oral Solution"

    def test_mixed_case_in_medication_name(self):
        """Test handling of mixed case in medication names."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-999"
        mock_coding = MagicMock()
        mock_coding.display = "InSuLiN LiSpRo"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-1010")

        # Verify
        assert len(result) == 1
        assert result[0]["name"] == "InSuLiN LiSpRo"
        assert result[0]["id"] == "med-999"

    def test_returns_correct_structure(self):
        """Test that returned dictionaries have correct keys."""
        # Setup
        mock_med = MagicMock()
        mock_med.id = "med-1111"
        mock_coding = MagicMock()
        mock_coding.display = "Digoxin 0.125mg"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            result = get_high_risk_meds("patient-1111")

        # Verify structure
        assert len(result) == 1
        assert "name" in result[0]
        assert "id" in result[0]
        assert len(result[0]) == 2  # Ensure no extra keys

    def test_all_high_risk_patterns_together(self):
        """Test all four high-risk medication types in one patient."""
        # Setup
        mock_meds = []
        medications = [
            ("med-1", "Warfarin 5mg"),
            ("med-2", "Insulin Glargine"),
            ("med-3", "Digoxin 0.25mg"),
            ("med-4", "Methotrexate 2.5mg"),
        ]

        for med_id, display in medications:
            mock_med = MagicMock()
            mock_med.id = med_id
            mock_coding = MagicMock()
            mock_coding.display = display
            mock_med.codings.first.return_value = mock_coding
            mock_meds.append(mock_med)

        # Execute
        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = mock_meds

            result = get_high_risk_meds("patient-1212")

        # Verify
        assert len(result) == 4
        assert result[0]["name"] == "Warfarin 5mg"
        assert result[1]["name"] == "Insulin Glargine"
        assert result[2]["name"] == "Digoxin 0.25mg"
        assert result[3]["name"] == "Methotrexate 2.5mg"
