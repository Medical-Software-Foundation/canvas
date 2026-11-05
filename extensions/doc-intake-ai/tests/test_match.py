"""Tests for patient and reviewer matching."""

import pytest
from unittest.mock import MagicMock, patch

from doc_intake_ai.match import _parse_name, _resolve_default_reviewer, find_patient, find_reviewer
from doc_intake_ai.models import DocumentExtraction


def make_queryset_mock(items: list) -> MagicMock:
    """Create a mock that behaves like a Django QuerySet."""
    mock = MagicMock()
    mock.__iter__ = lambda self: iter(items)
    mock.__len__ = lambda self: len(items)
    mock.first.return_value = items[0] if items else None
    return mock


class TestParseName:
    """Test name parsing helper."""

    def test_both_provided(self) -> None:
        first, last = _parse_name("John", "Doe", None)
        assert first == "John"
        assert last == "Doe"

    def test_from_full_name(self) -> None:
        first, last = _parse_name(None, None, "John Doe")
        assert first == "John"
        assert last == "Doe"

    def test_full_name_with_middle(self) -> None:
        first, last = _parse_name(None, None, "John Michael Doe")
        assert first == "John"
        assert last == "Doe"

    def test_partial_override(self) -> None:
        first, last = _parse_name("Jane", None, "John Doe")
        assert first == "Jane"
        assert last == "Doe"

    def test_single_name(self) -> None:
        first, last = _parse_name(None, None, "John")
        assert first == "John"
        assert last is None

    def test_all_none(self) -> None:
        first, last = _parse_name(None, None, None)
        assert first is None
        assert last is None


class TestFindPatient:
    """Test patient matching with mocked ORM."""

    @patch("doc_intake_ai.match.Patient")
    def test_match_by_mrn_single(self, mock_patient_cls: MagicMock) -> None:
        mock_patient = MagicMock(id="123")
        mock_patient_cls.objects.filter.return_value = [mock_patient]

        extraction = DocumentExtraction(patient_id="MRN001")
        result = find_patient(extraction)

        assert result.found is True
        assert result.error is None
        mock_patient_cls.objects.filter.assert_called_with(mrn="MRN001")

    @patch("doc_intake_ai.match.Patient")
    def test_match_by_mrn_multiple_returns_error(self, mock_patient_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value = [MagicMock(), MagicMock()]

        extraction = DocumentExtraction(patient_id="MRN001")
        result = find_patient(extraction)

        assert result.found is False
        assert "Multiple" in (result.error or "")

    @patch("doc_intake_ai.match.Patient")
    def test_match_by_mrn_none_found_fallback_to_name(self, mock_patient_cls: MagicMock) -> None:
        mock_patient = MagicMock(id="456")
        mock_patient_cls.objects.filter.side_effect = [
            [],  # MRN lookup
            [mock_patient],  # name+DOB lookup
        ]

        extraction = DocumentExtraction(
            patient_id="MRN001",
            patient_first_name="John",
            patient_last_name="Doe",
            date_of_birth="1990-01-15",
        )
        result = find_patient(extraction)
        assert result.found is True

    @patch("doc_intake_ai.match.Patient")
    def test_match_by_name_and_dob(self, mock_patient_cls: MagicMock) -> None:
        mock_patient = MagicMock(id="456")
        mock_patient_cls.objects.filter.return_value = [mock_patient]

        extraction = DocumentExtraction(
            patient_first_name="John",
            patient_last_name="Doe",
            date_of_birth="1990-01-15",
        )
        result = find_patient(extraction)

        assert result.found is True
        assert result.patient is not None
        assert result.patient.id == "456"

    @patch("doc_intake_ai.match.Patient")
    def test_match_by_name_only(self, mock_patient_cls: MagicMock) -> None:
        mock_patient = MagicMock(id="789")
        mock_patient_cls.objects.filter.return_value = [mock_patient]

        extraction = DocumentExtraction(
            patient_first_name="John",
            patient_last_name="Doe",
        )
        result = find_patient(extraction)
        assert result.found is True

    @patch("doc_intake_ai.match.Patient")
    def test_match_by_full_name(self, mock_patient_cls: MagicMock) -> None:
        mock_patient = MagicMock(id="999")
        mock_patient_cls.objects.filter.return_value = [mock_patient]

        extraction = DocumentExtraction(patient_name="John Doe")
        result = find_patient(extraction)
        assert result.found is True

    @patch("doc_intake_ai.match.Patient")
    def test_no_match_by_name_dob_then_name_only(self, mock_patient_cls: MagicMock) -> None:
        mock_patient = MagicMock(id="789")
        mock_patient_cls.objects.filter.side_effect = [
            [],  # name+DOB fails
            [mock_patient],  # name-only succeeds
        ]

        extraction = DocumentExtraction(
            patient_first_name="John",
            patient_last_name="Doe",
            date_of_birth="1990-01-15",
        )
        result = find_patient(extraction)
        assert result.found is True

    @patch("doc_intake_ai.match.Patient")
    def test_multiple_by_name_returns_error(self, mock_patient_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value = [MagicMock(), MagicMock()]

        extraction = DocumentExtraction(
            patient_first_name="John",
            patient_last_name="Doe",
        )
        result = find_patient(extraction)

        assert result.found is False
        assert "Multiple" in (result.error or "")

    @patch("doc_intake_ai.match.Patient")
    def test_no_extraction_data(self, mock_patient_cls: MagicMock) -> None:
        extraction = DocumentExtraction()
        result = find_patient(extraction)

        assert result.found is False
        assert result.error is None

    @patch("doc_intake_ai.match.Patient")
    def test_only_first_name_no_match(self, mock_patient_cls: MagicMock) -> None:
        extraction = DocumentExtraction(patient_first_name="John")
        result = find_patient(extraction)
        assert result.found is False

    @patch("doc_intake_ai.match.Patient")
    def test_multiple_by_name_and_dob_returns_error(self, mock_patient_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value = [MagicMock(), MagicMock()]

        extraction = DocumentExtraction(
            patient_first_name="John",
            patient_last_name="Doe",
            date_of_birth="1990-01-15",
        )
        result = find_patient(extraction)

        assert result.found is False
        assert "Multiple" in (result.error or "")

    @patch("doc_intake_ai.match.Patient")
    def test_no_match_at_all_returns_empty(self, mock_patient_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value = []

        extraction = DocumentExtraction(
            patient_first_name="John",
            patient_last_name="Doe",
        )
        result = find_patient(extraction)

        assert result.found is False
        assert result.error is None


class TestResolveDefaultReviewer:
    """Test default reviewer resolution."""

    @patch("doc_intake_ai.match.Staff")
    def test_empty_string_returns_none(self, mock_staff_cls: MagicMock) -> None:
        assert _resolve_default_reviewer("  ") is None

    @patch("doc_intake_ai.match.Staff")
    def test_npi_match(self, mock_staff_cls: MagicMock) -> None:
        mock_staff = MagicMock(id="npi-match")
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        result = _resolve_default_reviewer("1234567890")
        assert result == mock_staff

    @patch("doc_intake_ai.match.Staff")
    def test_npi_no_match_falls_through(self, mock_staff_cls: MagicMock) -> None:
        # NPI filter returns queryset with .first() = None
        npi_qs = MagicMock()
        npi_qs.first.return_value = None
        # Name filter returns empty list
        mock_staff_cls.objects.filter.side_effect = [npi_qs, []]

        result = _resolve_default_reviewer("1234567890")
        assert result is None

    @patch("doc_intake_ai.match.Staff")
    def test_multiple_name_matches_returns_none(self, mock_staff_cls: MagicMock) -> None:
        mock_staff_cls.objects.filter.return_value = [MagicMock(), MagicMock()]

        result = _resolve_default_reviewer("Jane Smith")
        assert result is None

    @patch("doc_intake_ai.match.Staff")
    def test_single_word_name_returns_none(self, mock_staff_cls: MagicMock) -> None:
        result = _resolve_default_reviewer("Jane")
        assert result is None


class TestFindReviewer:
    """Test reviewer matching with mocked ORM."""

    @patch("doc_intake_ai.match.Staff")
    def test_match_by_npi(self, mock_staff_cls: MagicMock) -> None:
        mock_reviewer = MagicMock(id="staff-123")
        mock_staff_cls.objects.filter.return_value = [mock_reviewer]

        extraction = DocumentExtraction(practitioner_npi="1234567890")
        result = find_reviewer(extraction)

        assert result.found is True
        assert result.reviewer is not None
        assert result.reviewer.id == "staff-123"
        assert result.auto_assigned is False

    @patch("doc_intake_ai.match.Staff")
    def test_match_by_name(self, mock_staff_cls: MagicMock) -> None:
        mock_reviewer = MagicMock(id="staff-456")
        mock_staff_cls.objects.filter.return_value = [mock_reviewer]

        extraction = DocumentExtraction(
            practitioner_first_name="Jane",
            practitioner_last_name="Smith",
        )
        result = find_reviewer(extraction)

        assert result.found is True
        assert result.auto_assigned is False

    @patch("doc_intake_ai.match.Staff")
    def test_match_by_full_name(self, mock_staff_cls: MagicMock) -> None:
        mock_reviewer = MagicMock(id="staff-789")
        mock_staff_cls.objects.filter.return_value = [mock_reviewer]

        extraction = DocumentExtraction(practitioner_name="Jane Smith")
        result = find_reviewer(extraction)
        assert result.found is True

    @patch("doc_intake_ai.match.Staff")
    def test_default_reviewer_by_name(self, mock_staff_cls: MagicMock) -> None:
        mock_default = MagicMock(id="default-staff")
        # First filter call returns empty (no NPI match — extraction has none)
        # _resolve_default_reviewer tries NPI (digits check fails for "Jane Smith")
        # then name lookup returns match
        mock_staff_cls.objects.filter.return_value = [mock_default]

        extraction = DocumentExtraction()
        result = find_reviewer(extraction, default_reviewer="Jane Smith")

        assert result.found is True
        assert result.auto_assigned is True

    @patch("doc_intake_ai.match.Staff")
    def test_default_reviewer_by_npi(self, mock_staff_cls: MagicMock) -> None:
        mock_default = MagicMock(id="npi-staff")
        mock_staff_cls.objects.filter.return_value = make_queryset_mock([mock_default])

        extraction = DocumentExtraction()
        result = find_reviewer(extraction, default_reviewer="1234567890")

        assert result.found is True
        assert result.auto_assigned is True

    @patch("doc_intake_ai.match.Staff")
    def test_auto_assign_canvas_bot(self, mock_staff_cls: MagicMock) -> None:
        mock_bot = MagicMock(id="canvas-bot")
        filter_mock = make_queryset_mock([mock_bot])
        mock_staff_cls.objects.filter.return_value = filter_mock

        extraction = DocumentExtraction()
        result = find_reviewer(extraction)

        assert result.found is True
        assert result.auto_assigned is True

    @patch("doc_intake_ai.match.Staff")
    def test_auto_assign_fallback_to_first_staff(self, mock_staff_cls: MagicMock) -> None:
        mock_first = MagicMock(id="first-staff")
        filter_mock = make_queryset_mock([])
        mock_staff_cls.objects.filter.return_value = filter_mock
        mock_staff_cls.objects.first.return_value = mock_first

        extraction = DocumentExtraction()
        result = find_reviewer(extraction)

        assert result.found is True
        assert result.auto_assigned is True

    @patch("doc_intake_ai.match.Staff")
    def test_no_staff_available(self, mock_staff_cls: MagicMock) -> None:
        filter_mock = make_queryset_mock([])
        mock_staff_cls.objects.filter.return_value = filter_mock
        mock_staff_cls.objects.first.return_value = None

        extraction = DocumentExtraction()
        result = find_reviewer(extraction)

        assert result.found is False
        assert result.auto_assigned is False

    @patch("doc_intake_ai.match.Staff")
    def test_npi_not_found_fallback_to_name(self, mock_staff_cls: MagicMock) -> None:
        mock_reviewer = MagicMock(id="staff-by-name")
        mock_staff_cls.objects.filter.side_effect = [
            [],  # NPI lookup fails
            [mock_reviewer],  # Name lookup succeeds
        ]

        extraction = DocumentExtraction(
            practitioner_npi="0000000000",
            practitioner_first_name="Jane",
            practitioner_last_name="Smith",
        )
        result = find_reviewer(extraction)

        assert result.found is True
        assert result.auto_assigned is False
