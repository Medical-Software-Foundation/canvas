"""Tests for the visits content type module."""

import pytest
from http import HTTPStatus
from unittest.mock import call, patch, MagicMock

from portal_content.content_types import visits


class TestServePortalPage:
    """Tests for serve_portal_page function."""

    def test_returns_html_response(self):
        """Test that portal page returns HTML response."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"

        with patch("portal_content.content_types.visits.log"):
            result = visits.serve_portal_page(api)

        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert b"My Visit Notes" in response.content


class TestHandleNotesRequest:
    """Tests for handle_notes_request function."""

    def test_list_action_calls_handle_list(self):
        """Test that list action routes to _handle_list."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "list"}

        with patch("portal_content.content_types.visits._handle_list") as mock_handle:
            with patch("portal_content.content_types.visits.log"):
                mock_handle.return_value = [MagicMock()]
                result = visits.handle_notes_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "list"})

    def test_detail_action_calls_handle_detail(self):
        """Test that detail action routes to _handle_detail."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "detail", "note_id": "note-123"}

        with patch("portal_content.content_types.visits._handle_detail") as mock_handle:
            with patch("portal_content.content_types.visits.log"):
                mock_handle.return_value = [MagicMock()]
                result = visits.handle_notes_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "detail", "note_id": "note-123"})

    def test_unknown_action_returns_bad_request(self):
        """Test that unknown action returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "invalid"}

        with patch("portal_content.content_types.visits.log"):
            result = visits.handle_notes_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_exception_returns_internal_error(self):
        """Test that exceptions return INTERNAL_SERVER_ERROR."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.side_effect = Exception("Parse error")

        with patch("portal_content.content_types.visits.log"):
            result = visits.handle_notes_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestProxyPdf:
    """Tests for proxy_pdf function."""

    def test_missing_document_id_returns_bad_request(self):
        """Test that missing document_id returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = None

        result = visits.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.visits.log"):
            result = visits.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_document_not_found_returns_404(self):
        """Test that document not found returns NOT_FOUND."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.visits.requests.get") as mock_get:
            with patch("portal_content.content_types.visits.log"):
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                result = visits.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    def test_access_denied_for_other_patient_document(self):
        """Test that accessing another patient's document returns FORBIDDEN."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.visits.requests.get") as mock_get:
            with patch("portal_content.content_types.visits.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "subject": {"reference": "Patient/other-patient-456"}
                }
                mock_get.return_value = mock_response

                result = visits.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_successful_pdf_proxy(self):
        """Test successful PDF proxy returns PDF content."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.visits.requests.get") as mock_get:
            with patch("portal_content.content_types.visits.log"):
                # First call - verify ownership
                verify_response = MagicMock()
                verify_response.status_code = 200
                verify_response.json.return_value = {
                    "subject": {"reference": "Patient/patient-123"}
                }

                # Second call - fetch PDF
                pdf_response = MagicMock()
                pdf_response.status_code = 200
                pdf_response.content = b"%PDF-1.4 test content"

                mock_get.side_effect = [verify_response, pdf_response]

                result = visits.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK
        assert result[0].content == b"%PDF-1.4 test content"

    def test_pdf_fetch_failure_returns_404(self):
        """Test that PDF fetch failure returns NOT_FOUND."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.visits.requests.get") as mock_get:
            with patch("portal_content.content_types.visits.log"):
                # First call - verify ownership
                verify_response = MagicMock()
                verify_response.status_code = 200
                verify_response.json.return_value = {
                    "subject": {"reference": "Patient/patient-123"}
                }

                # Second call - PDF not found
                pdf_response = MagicMock()
                pdf_response.status_code = 404
                pdf_response.text = "Not found"

                mock_get.side_effect = [verify_response, pdf_response]

                result = visits.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND


class TestGetNoteTypesFilter:
    """Tests for _get_note_types_filter function."""

    def test_empty_config_returns_none(self):
        """Test that empty config returns None."""
        api = MagicMock()
        api.secrets.get.return_value = ""

        result = visits._get_note_types_filter(api)

        assert result is None

    def test_single_note_type(self):
        """Test parsing single note type."""
        api = MagicMock()
        api.secrets.get.return_value = "308335008"

        result = visits._get_note_types_filter(api)

        assert result == ["308335008"]

    def test_multiple_note_types(self):
        """Test parsing multiple note types."""
        api = MagicMock()
        api.secrets.get.return_value = "308335008, 010101, 448337001"

        result = visits._get_note_types_filter(api)

        assert result == ["308335008", "010101", "448337001"]

    def test_whitespace_trimmed(self):
        """Test that whitespace is trimmed."""
        api = MagicMock()
        api.secrets.get.return_value = "  308335008  ,  010101  "

        result = visits._get_note_types_filter(api)

        assert result == ["308335008", "010101"]


class TestHandleList:
    """Tests for _handle_list function."""

    def test_successful_list_returns_notes(self):
        """Test successful note listing."""
        api = MagicMock()
        api.secrets.get.return_value = ""

        # Create mock notes
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.note_type_version.name = "Office visit"
        mock_note.provider.full_name = "Dr. Smith"
        mock_note.chief_complaint = "Headache"
        mock_note.current_state.state = "SGN"

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_queryset = MagicMock()
                mock_queryset.filter.return_value = mock_queryset
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.order_by.return_value = mock_queryset
                mock_queryset.__iter__ = lambda self: iter([mock_note])
                mock_note_class.objects = mock_queryset

                result = visits._handle_list(api, "patient-123", {"limit": 20, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_empty_results_returns_empty_list(self):
        """Test empty results returns empty summaries."""
        api = MagicMock()
        api.secrets.get.return_value = ""

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_queryset = MagicMock()
                mock_queryset.filter.return_value = mock_queryset
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.order_by.return_value = mock_queryset
                mock_queryset.__iter__ = lambda self: iter([])
                mock_note_class.objects = mock_queryset

                result = visits._handle_list(api, "patient-123", {"limit": 20, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_limit_capped_at_50(self):
        """Test that limit is capped at 50."""
        api = MagicMock()
        api.secrets.get.return_value = ""

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_queryset = MagicMock()
                mock_queryset.filter.return_value = mock_queryset
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.order_by.return_value = mock_queryset
                mock_queryset.__iter__ = lambda self: iter([])
                mock_note_class.objects = mock_queryset

                result = visits._handle_list(api, "patient-123", {"limit": 100, "offset": 0})

        assert len(result) == 1
        response_data = result[0].content
        # The limit should be capped internally


class TestHandleDetail:
    """Tests for _handle_detail function."""

    def test_missing_note_id_returns_bad_request(self):
        """Test that missing note_id returns BAD_REQUEST."""
        api = MagicMock()

        result = visits._handle_detail(api, "patient-123", {})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_note_not_found_returns_404(self):
        """Test that note not found returns NOT_FOUND."""
        api = MagicMock()

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            mock_note_class.DoesNotExist = Exception
            mock_queryset = MagicMock()
            mock_queryset.select_related.return_value = mock_queryset
            mock_queryset.get.side_effect = mock_note_class.DoesNotExist
            mock_note_class.objects = mock_queryset

            result = visits._handle_detail(api, "patient-123", {"note_id": "nonexistent"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    def test_access_denied_for_other_patient_note(self):
        """Test that accessing another patient's note returns FORBIDDEN."""
        api = MagicMock()

        mock_note = MagicMock()
        mock_note.patient.id = "other-patient-456"

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_note_class.DoesNotExist = Exception
                mock_queryset = MagicMock()
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.get.return_value = mock_note
                mock_note_class.objects = mock_queryset

                result = visits._handle_detail(api, "patient-123", {"note_id": "note-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_note_not_finalized_returns_forbidden(self):
        """Test that non-finalized note returns FORBIDDEN."""
        api = MagicMock()

        mock_note = MagicMock()
        mock_note.patient.id = "patient-123"
        mock_note.current_state.state = "DRF"  # Draft, not finalized

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_note_class.DoesNotExist = Exception
                mock_queryset = MagicMock()
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.get.return_value = mock_note
                mock_note_class.objects = mock_queryset

                result = visits._handle_detail(api, "patient-123", {"note_id": "note-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_note_no_current_state_returns_forbidden(self):
        """Test that note with no current state returns FORBIDDEN."""
        api = MagicMock()

        mock_note = MagicMock()
        mock_note.patient.id = "patient-123"
        mock_note.current_state = None

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_note_class.DoesNotExist = Exception
                mock_queryset = MagicMock()
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.get.return_value = mock_note
                mock_note_class.objects = mock_queryset

                result = visits._handle_detail(api, "patient-123", {"note_id": "note-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_successful_detail_with_fhir_document(self):
        """Test successful detail with FHIR document reference."""
        api = MagicMock()

        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.patient.id = "patient-123"
        mock_note.current_state.state = "SGN"
        mock_note.encounter.id = "enc-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.provider.full_name = "Dr. Smith"

        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {
            "entry": [
                {
                    "resource": {
                        "id": "doc-123",
                        "context": {
                            "encounter": [{"reference": "Encounter/enc-123"}]
                        }
                    }
                }
            ]
        }
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_note_class.DoesNotExist = Exception
                mock_queryset = MagicMock()
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.get.return_value = mock_note
                mock_note_class.objects = mock_queryset

                result = visits._handle_detail(api, "patient-123", {"note_id": "note-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_fallback_to_command_extraction_when_no_fhir(self):
        """Test fallback to command extraction when FHIR unavailable."""
        api = MagicMock()
        api._get_fhir_client.return_value = None

        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.patient.id = "patient-123"
        mock_note.current_state.state = "SGN"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.provider.full_name = "Dr. Smith"
        mock_note.commands.all.return_value = []

        with patch("portal_content.content_types.visits.Note") as mock_note_class:
            with patch("portal_content.content_types.visits.log"):
                mock_note_class.DoesNotExist = Exception
                mock_queryset = MagicMock()
                mock_queryset.select_related.return_value = mock_queryset
                mock_queryset.get.return_value = mock_note
                mock_note_class.objects = mock_queryset

                result = visits._handle_detail(api, "patient-123", {"note_id": "note-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK


class TestExtractNoteListInfo:
    """Tests for _extract_note_list_info function."""

    def test_extracts_all_fields(self):
        """Test that all fields are extracted."""
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.note_type_version.name = "Office visit"
        mock_note.provider.full_name = "Dr. Smith"
        mock_note.chief_complaint = "Headache"

        result = visits._extract_note_list_info(mock_note)

        assert result["note_id"] == "note-123"
        assert result["visit_date"] == "2024-01-15T10:00:00"
        assert result["visit_type"] == "Office visit"
        assert result["provider_name"] == "Dr. Smith"
        assert result["chief_concern"] == "Headache"

    def test_handles_missing_note_type_version(self):
        """Test handling of missing note_type_version."""
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.note_type_version = None
        mock_note.provider.full_name = "Dr. Smith"
        mock_note.chief_complaint = ""

        result = visits._extract_note_list_info(mock_note)

        assert result["visit_type"] is None


class TestExtractProviderName:
    """Tests for _extract_provider_name function."""

    def test_extracts_full_name(self):
        """Test extracting provider full name."""
        mock_note = MagicMock()
        mock_note.provider.full_name = "Dr. John Smith"

        result = visits._extract_provider_name(mock_note)

        assert result == "Dr. John Smith"

    def test_uses_first_last_when_no_full_name(self):
        """Test using first/last name when full_name not available."""
        mock_note = MagicMock()
        mock_note.provider = MagicMock(spec=["first_name", "last_name"])
        mock_note.provider.first_name = "John"
        mock_note.provider.last_name = "Smith"

        result = visits._extract_provider_name(mock_note)

        assert result == "Dr. John Smith"

    def test_returns_unknown_when_no_provider(self):
        """Test returning 'Unknown Provider' when provider is None."""
        mock_note = MagicMock()
        mock_note.provider = None

        result = visits._extract_provider_name(mock_note)

        assert result == "Unknown Provider"


class TestExtractChiefConcern:
    """Tests for _extract_chief_concern function."""

    def test_extracts_chief_complaint(self):
        """Test extracting chief complaint."""
        mock_note = MagicMock()
        mock_note.chief_complaint = "Headache"

        result = visits._extract_chief_concern(mock_note)

        assert result == "Headache"

    def test_returns_empty_when_no_chief_complaint(self):
        """Test returning empty string when no chief complaint."""
        mock_note = MagicMock()
        mock_note.chief_complaint = None

        result = visits._extract_chief_concern(mock_note)

        assert result == ""


class TestExtractNoteSummary:
    """Tests for _extract_note_summary function."""

    def test_extracts_basic_info(self):
        """Test extracting basic note info."""
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.provider.full_name = "Dr. Smith"
        mock_note.commands.all.return_value = []

        result = visits._extract_note_summary(mock_note)

        assert result["note_id"] == "note-123"
        assert result["visit_date"] == "2024-01-15T10:00:00"
        assert result["provider_name"] == "Dr. Smith"

    def test_extracts_chief_concern_from_commands(self):
        """Test extracting chief concern from commands."""
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.provider.full_name = "Dr. Smith"

        mock_cmd = MagicMock()
        mock_cmd.data = {"comment": "Patient reports headache"}
        mock_note.commands.all.return_value = [mock_cmd]

        result = visits._extract_note_summary(mock_note)

        assert result["chief_concern"] == "Patient reports headache"

    def test_extracts_diagnoses(self):
        """Test extracting diagnoses from commands."""
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.provider.full_name = "Dr. Smith"

        mock_cmd = MagicMock()
        mock_cmd.data = {"diagnose": {"text": "Migraine"}, "background": "Chronic"}
        mock_note.commands.all.return_value = [mock_cmd]

        result = visits._extract_note_summary(mock_note)

        assert "Migraine" in result["assessment_and_plan"]
        assert "Chronic" in result["assessment_and_plan"]

    def test_extracts_prescriptions(self):
        """Test extracting prescriptions from commands."""
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.provider.full_name = "Dr. Smith"

        mock_cmd = MagicMock()
        mock_cmd.data = {"prescribe": {"text": "Ibuprofen 400mg"}, "sig": "Take twice daily"}
        mock_note.commands.all.return_value = [mock_cmd]

        result = visits._extract_note_summary(mock_note)

        assert "Ibuprofen 400mg" in result["assessment_and_plan"]

    def test_extracts_follow_up(self):
        """Test extracting follow-up from commands."""
        mock_note = MagicMock()
        mock_note.id = "note-123"
        mock_note.created.isoformat.return_value = "2024-01-15T10:00:00"
        mock_note.provider.full_name = "Dr. Smith"

        mock_cmd = MagicMock()
        mock_cmd.data = {
            "requested_date": {"date": "2024-02-15"},
            "note_type": {"text": "Follow-up visit"}
        }
        mock_note.commands.all.return_value = [mock_cmd]

        result = visits._extract_note_summary(mock_note)

        assert "Follow-up" in result["follow_up"]
        assert "2024-02-15" in result["follow_up"]
