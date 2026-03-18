"""Tests for patient matching service."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from extend_lab_intake.services.patient_matcher import (
    ExtractedDemographics,
    PatientMatcher,
    PatientMatchResult,
)


class TestExtractedDemographics:
    """Tests for ExtractedDemographics parsing."""

    def test_from_extend_output_basic(self) -> None:
        """Test parsing basic demographics from Extend output."""
        output = {
            "patient": {
                "first_name": "John",
                "last_name": "Doe",
                "date_of_birth": "1990-05-15",
            }
        }

        demographics = ExtractedDemographics.from_extend_output(output)

        assert demographics.first_name == "John"
        assert demographics.last_name == "Doe"
        assert demographics.date_of_birth == date(1990, 5, 15)

    def test_from_extend_output_alternative_field_names(self) -> None:
        """Test parsing demographics with alternative field names."""
        output = {
            "firstName": "Jane",
            "lastName": "Smith",
            "dob": "03/20/1985",
        }

        demographics = ExtractedDemographics.from_extend_output(output)

        assert demographics.first_name == "Jane"
        assert demographics.last_name == "Smith"
        assert demographics.date_of_birth == date(1985, 3, 20)

    def test_from_extend_output_missing_fields(self) -> None:
        """Test parsing with missing fields returns None."""
        output = {}

        demographics = ExtractedDemographics.from_extend_output(output)

        assert demographics.first_name is None
        assert demographics.last_name is None
        assert demographics.date_of_birth is None


class TestPatientMatcher:
    """Tests for PatientMatcher service."""

    @pytest.fixture
    def mock_llm_client(self) -> MagicMock:
        """Create a mock LLM client."""
        return MagicMock()

    @pytest.fixture
    def matcher(self, mock_llm_client: MagicMock) -> PatientMatcher:
        """Create a PatientMatcher instance."""
        return PatientMatcher(llm_client=mock_llm_client)

    def test_match_no_candidates_returns_none(
        self, matcher: PatientMatcher
    ) -> None:
        """Test that no candidates returns none confidence."""
        demographics = ExtractedDemographics(
            first_name="Unknown",
            last_name="Person",
            date_of_birth=date(2000, 1, 1),
        )

        with patch.object(matcher, "_find_candidates", return_value=[]):
            result = matcher.match_patient(demographics)

        assert result.patient_id is None
        assert result.confidence == "none"
        assert result.candidates_considered == 0

    def test_confidence_calculation_high(self, matcher: PatientMatcher) -> None:
        """Test high confidence calculation for exact match."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient = MagicMock()
        mock_patient.first_name = "John"
        mock_patient.last_name = "Doe"
        mock_patient.birth_date = date(1990, 5, 15)

        confidence = matcher._calculate_confidence(demographics, mock_patient)

        assert confidence == "high"

    def test_confidence_calculation_medium(self, matcher: PatientMatcher) -> None:
        """Test medium confidence for partial match."""
        demographics = ExtractedDemographics(
            first_name="Johnny",  # Slightly different
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient = MagicMock()
        mock_patient.first_name = "John"
        mock_patient.last_name = "Doe"
        mock_patient.birth_date = date(1990, 5, 15)

        confidence = matcher._calculate_confidence(demographics, mock_patient)

        # DOB + last name exact = 70, first name partial ~15 = 85
        assert confidence in ("high", "medium")

    def test_confidence_calculation_low(self, matcher: PatientMatcher) -> None:
        """Test low confidence for weak match."""
        demographics = ExtractedDemographics(
            first_name="Jonathan",
            last_name="D",  # Partial last name
            date_of_birth=None,  # No DOB
        )

        mock_patient = MagicMock()
        mock_patient.first_name = "John"
        mock_patient.last_name = "Doe"
        mock_patient.birth_date = date(1990, 5, 15)

        confidence = matcher._calculate_confidence(demographics, mock_patient)

        assert confidence in ("low", "none")

    def test_from_extend_output_with_value_wrapper(self) -> None:
        """Test parsing demographics wrapped in 'value' key."""
        output = {
            "value": {
                "patient_name": "John Doe",
                "date_of_birth": "1990-05-15",
            }
        }

        demographics = ExtractedDemographics.from_extend_output(output)

        assert demographics.first_name == "John"
        assert demographics.last_name == "Doe"

    def test_from_extend_output_combined_name(self) -> None:
        """Test parsing combined patient name."""
        output = {
            "patient_name": "Jane Marie Smith",
        }

        demographics = ExtractedDemographics.from_extend_output(output)

        assert demographics.first_name == "Jane"
        assert demographics.last_name == "Marie Smith"

    def test_from_extend_output_single_name(self) -> None:
        """Test parsing single-word name."""
        output = {
            "name": "Madonna",
        }

        demographics = ExtractedDemographics.from_extend_output(output)

        assert demographics.first_name is None
        assert demographics.last_name == "Madonna"

    def test_from_extend_output_various_dob_formats(self) -> None:
        """Test parsing various DOB formats."""
        formats_and_expected = [
            ("2024-01-15", date(2024, 1, 15)),
            ("01/15/2024", date(2024, 1, 15)),
            ("01-15-2024", date(2024, 1, 15)),
        ]

        for dob_str, expected in formats_and_expected:
            output = {"dob": dob_str}
            demographics = ExtractedDemographics.from_extend_output(output)
            assert demographics.date_of_birth == expected, f"Failed for {dob_str}"

    def test_match_patient_with_mrn(self, matcher: PatientMatcher) -> None:
        """Test matching by MRN."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
            mrn="MRN12345",
        )

        mock_patient = MagicMock()
        mock_patient.id = "patient-123"

        with patch.object(matcher, "_match_by_mrn", return_value=mock_patient):
            result = matcher.match_patient(demographics)

        assert result.patient_id == "patient-123"
        assert result.confidence == "high"
        assert "MRN" in result.match_details

    def test_match_patient_single_candidate(self, matcher: PatientMatcher) -> None:
        """Test matching with single candidate."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient = MagicMock()
        mock_patient.id = "patient-123"
        mock_patient.first_name = "John"
        mock_patient.last_name = "Doe"
        mock_patient.birth_date = date(1990, 5, 15)

        with patch.object(matcher, "_find_candidates", return_value=[mock_patient]):
            result = matcher.match_patient(demographics)

        assert result.patient_id == "patient-123"
        assert result.candidates_considered == 1

    def test_match_patient_multiple_candidates_llm(
        self, matcher: PatientMatcher, mock_llm_client: MagicMock
    ) -> None:
        """Test matching with multiple candidates uses LLM."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient1 = MagicMock()
        mock_patient1.id = "patient-123"
        mock_patient1.first_name = "John"
        mock_patient1.last_name = "Doe"
        mock_patient1.birth_date = date(1990, 5, 15)

        mock_patient2 = MagicMock()
        mock_patient2.id = "patient-456"
        mock_patient2.first_name = "Johnny"
        mock_patient2.last_name = "Doe"
        mock_patient2.birth_date = date(1990, 5, 15)

        mock_llm_client.chat_with_json.return_value = {
            "success": True,
            "data": {
                "matched_patient_id": "patient-123",
                "confidence": "high",
                "reasoning": "Exact name match",
            },
        }

        with patch.object(
            matcher, "_find_candidates", return_value=[mock_patient1, mock_patient2]
        ):
            result = matcher.match_patient(demographics)

        assert result.patient_id == "patient-123"
        assert result.confidence == "high"
        mock_llm_client.chat_with_json.assert_called_once()

    def test_match_patient_llm_failure(
        self, matcher: PatientMatcher, mock_llm_client: MagicMock
    ) -> None:
        """Test matching when LLM fails."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient1 = MagicMock()
        mock_patient1.id = "patient-123"
        mock_patient1.first_name = "John"
        mock_patient1.last_name = "Doe"
        mock_patient1.birth_date = date(1990, 5, 15)

        mock_patient2 = MagicMock()
        mock_patient2.id = "patient-456"
        mock_patient2.first_name = "Johnny"
        mock_patient2.last_name = "Doe"
        mock_patient2.birth_date = date(1990, 5, 15)

        mock_llm_client.chat_with_json.return_value = {
            "success": False,
            "error": "API error",
        }

        with patch.object(
            matcher, "_find_candidates", return_value=[mock_patient1, mock_patient2]
        ):
            result = matcher.match_patient(demographics)

        assert result.patient_id is None
        assert result.confidence == "none"
        assert "failed" in result.match_details.lower()

    @patch("canvas_sdk.v1.data.patient.Patient.objects")
    def test_match_by_mrn_success(
        self, mock_patient_objects: MagicMock, matcher: PatientMatcher
    ) -> None:
        """Test MRN lookup success."""
        mock_patient = MagicMock()
        mock_patient.id = "patient-123"
        mock_patient_objects.filter.return_value.all.return_value = [mock_patient]

        result = matcher._match_by_mrn("MRN12345")

        assert result == mock_patient

    @patch("canvas_sdk.v1.data.patient.Patient.objects")
    def test_match_by_mrn_not_found(
        self, mock_patient_objects: MagicMock, matcher: PatientMatcher
    ) -> None:
        """Test MRN lookup when not found."""
        mock_patient_objects.filter.return_value.all.return_value = []

        result = matcher._match_by_mrn("MRN99999")

        assert result is None

    @patch("canvas_sdk.v1.data.patient.Patient.objects")
    def test_match_by_mrn_exception(
        self, mock_patient_objects: MagicMock, matcher: PatientMatcher
    ) -> None:
        """Test MRN lookup handles exception."""
        mock_patient_objects.filter.side_effect = Exception("Database error")

        result = matcher._match_by_mrn("MRN12345")

        assert result is None

    @patch("canvas_sdk.v1.data.patient.Patient.objects")
    def test_find_candidates_with_dob(
        self, mock_patient_objects: MagicMock, matcher: PatientMatcher
    ) -> None:
        """Test finding candidates with DOB filter."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient = MagicMock()
        mock_patient.first_name = "John"
        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.__getitem__ = MagicMock(return_value=[mock_patient])
        mock_patient_objects.all.return_value = mock_queryset

        result = matcher._find_candidates(demographics)

        # Verify DOB filter was applied
        mock_queryset.filter.assert_called()

    @patch("canvas_sdk.v1.data.patient.Patient.objects")
    def test_find_candidates_exception(
        self, mock_patient_objects: MagicMock, matcher: PatientMatcher
    ) -> None:
        """Test finding candidates handles exception."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient_objects.all.side_effect = Exception("Database error")

        result = matcher._find_candidates(demographics)

        assert result == []

    def test_confidence_none_when_no_match(self, matcher: PatientMatcher) -> None:
        """Test confidence is 'none' when no significant match."""
        demographics = ExtractedDemographics(
            first_name=None,
            last_name=None,
            date_of_birth=None,
        )

        mock_patient = MagicMock()
        mock_patient.first_name = "John"
        mock_patient.last_name = "Doe"
        mock_patient.birth_date = date(1990, 5, 15)

        confidence = matcher._calculate_confidence(demographics, mock_patient)

        assert confidence == "none"

    def test_confidence_partial_last_name(self, matcher: PatientMatcher) -> None:
        """Test confidence with partial last name match."""
        demographics = ExtractedDemographics(
            first_name="John",
            last_name="Doeherty",  # Contains "Doe"
            date_of_birth=date(1990, 5, 15),
        )

        mock_patient = MagicMock()
        mock_patient.first_name = "John"
        mock_patient.last_name = "Doe"
        mock_patient.birth_date = date(1990, 5, 15)

        confidence = matcher._calculate_confidence(demographics, mock_patient)

        # Should have DOB match (40) + partial last name (15) + first name (30) = 85
        assert confidence in ("high", "medium")
