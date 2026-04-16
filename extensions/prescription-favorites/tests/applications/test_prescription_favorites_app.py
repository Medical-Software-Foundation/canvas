"""Tests for PrescriptionFavoritesApp and PrescribeFavoritesAPI."""

from unittest.mock import MagicMock, call, patch

import pytest

from prescription_favorites.applications.prescription_favorites_app import (
    PrescriptionFavoritesApp,
)
from prescription_favorites.protocols.prescription_api import PrescribeFavoritesAPI
from prescription_favorites.medications import FAVORITE_MEDICATIONS


class TestPrescriptionFavoritesApp:
    """Tests for PrescriptionFavoritesApp Application handler."""

    @patch("prescription_favorites.applications.prescription_favorites_app.FavoritesService")
    @patch("prescription_favorites.applications.prescription_favorites_app.Patient.objects")
    @patch("prescription_favorites.applications.prescription_favorites_app.CurrentNoteStateEvent.objects")
    @patch("prescription_favorites.applications.prescription_favorites_app.Note.objects")
    @patch("prescription_favorites.applications.prescription_favorites_app.render_to_string")
    @patch("prescription_favorites.applications.prescription_favorites_app.LaunchModalEffect")
    def test_on_open_with_open_notes(
        self,
        mock_launch_modal: MagicMock,
        mock_render: MagicMock,
        mock_note_objects: MagicMock,
        mock_note_state_objects: MagicMock,
        mock_patient_objects: MagicMock,
        mock_favorites_service: MagicMock,
        mock_patient: MagicMock,
        mock_note: MagicMock,
    ) -> None:
        """Test on_open when patient has open notes."""
        # Setup
        mock_event = MagicMock()
        mock_event.context = {"patient": {"id": "test-patient-123"}}
        app = PrescriptionFavoritesApp(mock_event)

        mock_patient_objects.get.return_value = mock_patient

        # Mock FavoritesService
        mock_service_instance = MagicMock()
        mock_service_instance.get_all_favorites.return_value = list(FAVORITE_MEDICATIONS.values())
        mock_favorites_service.return_value = mock_service_instance

        # Mock note state query
        mock_note_ids_queryset = MagicMock()
        mock_note_ids_queryset.values_list.return_value = ["note-id-1", "note-id-2"]
        mock_note_state_objects.filter.return_value = mock_note_ids_queryset

        # Mock notes queryset with proper chaining
        mock_notes_queryset = MagicMock()
        mock_notes_queryset.__iter__ = MagicMock(return_value=iter([mock_note]))
        mock_notes_queryset.exists.return_value = True
        mock_notes_queryset.first.return_value = mock_note
        mock_notes_queryset.count.return_value = 2

        # Mock the filter().order_by() chain
        mock_filter_result = MagicMock()
        mock_filter_result.order_by.return_value = mock_notes_queryset
        mock_note_objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>Mock HTML</html>"
        mock_effect = MagicMock()
        mock_effect.apply.return_value = "applied_effect"
        mock_launch_modal.return_value = mock_effect

        # Execute
        result = app.on_open()

        # Verify Patient.objects.get was called with correct ID
        assert mock_patient_objects.mock_calls == [call.get(id="test-patient-123")]

        # Verify FavoritesService was used
        mock_favorites_service.assert_called_once()
        mock_service_instance.get_all_favorites.assert_called_once()

        # Verify render_to_string was called with correct context
        render_calls = mock_render.mock_calls
        assert len(render_calls) == 1
        assert render_calls[0].args[0] == "templates/favorites_template.html"
        context = render_calls[0].args[1]
        assert context["has_open_notes"] is True
        assert context["patient_id"] == "test-patient-123"
        assert list(context["medications"]) == list(FAVORITE_MEDICATIONS.values())

        # Verify LaunchModalEffect was created and applied
        assert len(mock_launch_modal.mock_calls) >= 2
        constructor_call = mock_launch_modal.mock_calls[0]
        assert constructor_call.kwargs["content"] == "<html>Mock HTML</html>"
        assert constructor_call.kwargs["title"] == "Prescribing"

        # Verify result
        assert result == "applied_effect"

    @patch("prescription_favorites.applications.prescription_favorites_app.FavoritesService")
    @patch("prescription_favorites.applications.prescription_favorites_app.Patient.objects")
    @patch("prescription_favorites.applications.prescription_favorites_app.CurrentNoteStateEvent.objects")
    @patch("prescription_favorites.applications.prescription_favorites_app.Note.objects")
    @patch("prescription_favorites.applications.prescription_favorites_app.render_to_string")
    @patch("prescription_favorites.applications.prescription_favorites_app.LaunchModalEffect")
    def test_on_open_without_open_notes(
        self,
        mock_launch_modal: MagicMock,
        mock_render: MagicMock,
        mock_note_objects: MagicMock,
        mock_note_state_objects: MagicMock,
        mock_patient_objects: MagicMock,
        mock_favorites_service: MagicMock,
        mock_patient: MagicMock,
    ) -> None:
        """Test on_open when patient has no open notes."""
        # Setup
        mock_event = MagicMock()
        mock_event.context = {"patient": {"id": "test-patient-456"}}
        app = PrescriptionFavoritesApp(mock_event)

        mock_patient_objects.get.return_value = mock_patient

        # Mock FavoritesService
        mock_service_instance = MagicMock()
        mock_service_instance.get_all_favorites.return_value = list(FAVORITE_MEDICATIONS.values())
        mock_favorites_service.return_value = mock_service_instance

        # Mock note state query
        mock_note_ids_queryset = MagicMock()
        mock_note_ids_queryset.values_list.return_value = []
        mock_note_state_objects.filter.return_value = mock_note_ids_queryset

        # Mock notes queryset (empty) with proper chaining
        mock_notes_queryset = MagicMock()
        mock_notes_queryset.exists.return_value = False
        mock_notes_queryset.first.return_value = None
        mock_notes_queryset.count.return_value = 0

        # Mock the filter().order_by() chain
        mock_filter_result = MagicMock()
        mock_filter_result.order_by.return_value = mock_notes_queryset
        mock_note_objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>No notes HTML</html>"
        mock_effect = MagicMock()
        mock_effect.apply.return_value = "applied_effect"
        mock_launch_modal.return_value = mock_effect

        # Execute
        result = app.on_open()

        # Verify Patient.objects.get was called
        assert mock_patient_objects.mock_calls == [call.get(id="test-patient-456")]

        # Verify render context has has_open_notes=False
        render_calls = mock_render.mock_calls
        assert len(render_calls) == 1
        context = render_calls[0].args[1]
        assert context["has_open_notes"] is False
        assert "patient_id" in context

        # Verify result
        assert result == "applied_effect"


class TestPrescribeFavoritesAPI:
    """Tests for PrescribeFavoritesAPI SimpleAPI handler."""

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.Patient.objects")
    @patch("prescription_favorites.protocols.prescription_api.CurrentNoteStateEvent.objects")
    @patch("prescription_favorites.protocols.prescription_api.Note.objects")
    @patch("prescription_favorites.protocols.prescription_api.PrescribeCommand")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_with_valid_request(
        self,
        mock_json_response: MagicMock,
        mock_prescribe_command: MagicMock,
        mock_note_objects: MagicMock,
        mock_note_state_objects: MagicMock,
        mock_patient_objects: MagicMock,
        mock_favorites_service: MagicMock,
        mock_patient: MagicMock,
        mock_note: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST with valid request and medications."""
        # Setup
        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "patient_id": "test-patient-123",
            "selected_medications": ["wegovy_0.25mg", "ondansetron_4mg"],
        }
        # headers.get already returns "test-staff-123" for canvas-logged-in-user-id via conftest

        # Mock FavoritesService with batch method
        wegovy = dict(FAVORITE_MEDICATIONS["wegovy_0.25mg"])
        wegovy["is_custom"] = False
        ondansetron = dict(FAVORITE_MEDICATIONS["ondansetron_4mg"])
        ondansetron["is_custom"] = False
        mock_service_instance = MagicMock()
        mock_service_instance.get_favorites_by_ids.return_value = {
            "wegovy_0.25mg": wegovy,
            "ondansetron_4mg": ondansetron,
        }
        mock_favorites_service.return_value = mock_service_instance

        mock_patient_objects.get.return_value = mock_patient

        # Mock note state query
        mock_note_ids_queryset = MagicMock()
        mock_note_ids_queryset.values_list.return_value = ["note-id-1"]
        mock_note_state_objects.filter.return_value = mock_note_ids_queryset

        # Mock notes queryset
        mock_notes_queryset = MagicMock()
        mock_notes_queryset.exists.return_value = True
        mock_notes_queryset.first.return_value = mock_note
        mock_note_objects.filter.return_value = mock_notes_queryset

        # Mock PrescribeCommand
        mock_effect_1 = MagicMock()
        mock_effect_2 = MagicMock()
        mock_prescribe_instance_1 = MagicMock()
        mock_prescribe_instance_1.originate.return_value = mock_effect_1
        mock_prescribe_instance_2 = MagicMock()
        mock_prescribe_instance_2.originate.return_value = mock_effect_2
        mock_prescribe_command.side_effect = [
            mock_prescribe_instance_1,
            mock_prescribe_instance_2,
        ]

        mock_json_response.return_value = "json_response"

        # Execute
        result = api.post()

        # Verify Patient.objects.get was called with correct ID
        assert mock_patient_objects.mock_calls == [call.get(id="test-patient-123")]

        # Verify batch lookup was called
        mock_service_instance.get_favorites_by_ids.assert_called_once_with(
            ["wegovy_0.25mg", "ondansetron_4mg"], staff_id="test-staff-123"
        )

        # Verify PrescribeCommand was called twice (once per medication)
        assert len(mock_prescribe_command.mock_calls) == 2

        # Verify first PrescribeCommand call
        first_call = mock_prescribe_command.mock_calls[0]
        assert "note_uuid" in first_call.kwargs
        assert first_call.kwargs["fdb_code"] == "606783"  # Wegovy 0.25mg
        assert first_call.kwargs["sig"] == "Inject subcutaneously once weekly"
        assert first_call.kwargs["days_supply"] == 28
        assert first_call.kwargs["prescriber_id"] == "test-staff-123"

        # Verify second PrescribeCommand call
        second_call = mock_prescribe_command.mock_calls[1]
        assert second_call.kwargs["fdb_code"] == "285288"  # Ondansetron 4mg

        # Verify JSONResponse was called with success
        json_response_calls = mock_json_response.mock_calls
        assert len(json_response_calls) == 1
        response_data = json_response_calls[0].args[0]
        assert response_data["success"] is True
        assert response_data["count"] == 2
        assert "2 prescriptions added to note" in response_data["message"]

        # Verify result includes JSONResponse and effects
        assert result == ["json_response", mock_effect_1, mock_effect_2]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_without_patient_id(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test POST without patient_id returns error."""
        # Setup
        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "selected_medications": ["wegovy_0.25mg"],
        }

        mock_json_response.return_value = "error_response"

        # Execute
        result = api.post()

        # Verify JSONResponse was called with error
        json_response_calls = mock_json_response.mock_calls
        assert len(json_response_calls) == 1
        response_data = json_response_calls[0].args[0]
        assert response_data["success"] is False
        assert "Patient ID is required" in response_data["error"]

        # Verify result
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_without_selected_medications(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test POST without selected medications returns error."""
        # Setup
        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "patient_id": "test-patient-123",
            "selected_medications": [],
        }

        mock_json_response.return_value = "error_response"

        # Execute
        result = api.post()

        # Verify JSONResponse was called with error
        json_response_calls = mock_json_response.mock_calls
        assert len(json_response_calls) == 1
        response_data = json_response_calls[0].args[0]
        assert response_data["success"] is False
        assert "No medications selected" in response_data["error"]

        # Verify result
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.Patient.objects")
    @patch("prescription_favorites.protocols.prescription_api.CurrentNoteStateEvent.objects")
    @patch("prescription_favorites.protocols.prescription_api.Note.objects")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_without_open_notes(
        self,
        mock_json_response: MagicMock,
        mock_note_objects: MagicMock,
        mock_note_state_objects: MagicMock,
        mock_patient_objects: MagicMock,
        mock_favorites_service: MagicMock,
        mock_patient: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST when patient has no open notes."""
        # Setup
        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "patient_id": "test-patient-123",
            "selected_medications": ["wegovy_0.25mg"],
        }

        mock_patient_objects.get.return_value = mock_patient

        # Mock note state query
        mock_note_ids_queryset = MagicMock()
        mock_note_ids_queryset.values_list.return_value = []
        mock_note_state_objects.filter.return_value = mock_note_ids_queryset

        # Mock notes queryset (empty) with proper chaining
        mock_notes_queryset = MagicMock()
        mock_notes_queryset.exists.return_value = False

        # Mock the filter().order_by() chain
        mock_filter_result = MagicMock()
        mock_filter_result.order_by.return_value = mock_notes_queryset
        mock_note_objects.filter.return_value = mock_filter_result

        mock_json_response.return_value = "error_response"

        # Execute
        result = api.post()

        # Verify Patient.objects.get was called
        assert mock_patient_objects.mock_calls == [call.get(id="test-patient-123")]

        # Verify JSONResponse was called with error about no open notes
        json_response_calls = mock_json_response.mock_calls
        assert len(json_response_calls) == 1
        response_data = json_response_calls[0].args[0]
        assert response_data["success"] is False
        assert "No open notes found" in response_data["error"]
        assert "Please create a new note" in response_data["error"]

        # Verify result
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.Patient.objects")
    @patch("prescription_favorites.protocols.prescription_api.CurrentNoteStateEvent.objects")
    @patch("prescription_favorites.protocols.prescription_api.Note.objects")
    @patch("prescription_favorites.protocols.prescription_api.PrescribeCommand")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_with_invalid_medication_id(
        self,
        mock_json_response: MagicMock,
        mock_prescribe_command: MagicMock,
        mock_note_objects: MagicMock,
        mock_note_state_objects: MagicMock,
        mock_patient_objects: MagicMock,
        mock_favorites_service: MagicMock,
        mock_patient: MagicMock,
        mock_note: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST with invalid medication ID skips that medication."""
        # Setup
        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "patient_id": "test-patient-123",
            "selected_medications": [
                "wegovy_0.25mg",
                "invalid_med_id",
                "ondansetron_4mg",
            ],
        }
        # headers.get already returns "test-staff-123" for canvas-logged-in-user-id via conftest

        # Mock FavoritesService - batch lookup omits invalid ID
        wegovy = dict(FAVORITE_MEDICATIONS["wegovy_0.25mg"])
        wegovy["is_custom"] = False
        ondansetron = dict(FAVORITE_MEDICATIONS["ondansetron_4mg"])
        ondansetron["is_custom"] = False
        mock_service_instance = MagicMock()
        mock_service_instance.get_favorites_by_ids.return_value = {
            "wegovy_0.25mg": wegovy,
            "ondansetron_4mg": ondansetron,
            # "invalid_med_id" is not in the result - simulates not found
        }
        mock_favorites_service.return_value = mock_service_instance

        mock_patient_objects.get.return_value = mock_patient

        # Mock note state query
        mock_note_ids_queryset = MagicMock()
        mock_note_ids_queryset.values_list.return_value = ["note-id-1"]
        mock_note_state_objects.filter.return_value = mock_note_ids_queryset

        # Mock notes queryset
        mock_notes_queryset = MagicMock()
        mock_notes_queryset.exists.return_value = True
        mock_notes_queryset.first.return_value = mock_note
        mock_note_objects.filter.return_value = mock_notes_queryset

        # Mock PrescribeCommand (only 2 valid meds)
        mock_effect_1 = MagicMock()
        mock_effect_2 = MagicMock()
        mock_prescribe_instance_1 = MagicMock()
        mock_prescribe_instance_1.originate.return_value = mock_effect_1
        mock_prescribe_instance_2 = MagicMock()
        mock_prescribe_instance_2.originate.return_value = mock_effect_2
        mock_prescribe_command.side_effect = [
            mock_prescribe_instance_1,
            mock_prescribe_instance_2,
        ]

        mock_json_response.return_value = "json_response"

        # Execute
        result = api.post()

        # Verify PrescribeCommand was called only twice (invalid ID skipped)
        assert len(mock_prescribe_command.mock_calls) == 2

        # Verify JSONResponse shows count of 2 (not 3)
        json_response_calls = mock_json_response.mock_calls
        response_data = json_response_calls[0].args[0]
        assert response_data["count"] == 2
        assert "2 prescriptions added to note" in response_data["message"]

        # Verify result includes only 2 effects
        assert result == ["json_response", mock_effect_1, mock_effect_2]

    def test_authenticate_returns_true(self) -> None:
        """Test authenticate method returns True for Staff users."""
        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        credentials = MagicMock()
        credentials.logged_in_user = {"type": "Staff"}

        result = api.authenticate(credentials)

        assert result is True
