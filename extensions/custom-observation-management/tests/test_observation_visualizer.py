"""Tests for the Observation Visualizer Application and API."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest

from custom_observation_management.applications.observation_visualizer import (
    ObservationVisualizerApp,
)
from custom_observation_management.protocols.observation_visualizer import (
    ObservationVisualizerAPI,
)


class TestObservationVisualizerApp:
    """Tests for the ObservationVisualizerApp Application handler."""

    def create_app_instance(self, context: dict) -> ObservationVisualizerApp:
        """Helper to create an ObservationVisualizerApp instance with mocked event."""
        app = ObservationVisualizerApp.__new__(ObservationVisualizerApp)
        app.event = Mock()
        app.event.context = context
        return app

    def test_on_open_launches_modal_with_patient_id(self) -> None:
        """Test that on_open launches a modal with the patient ID from context."""
        with patch.object(
            ObservationVisualizerApp, "context", new_callable=PropertyMock
        ) as mock_context:
            mock_context.return_value = {"patient": {"id": "patient-uuid-123"}}
            app = self.create_app_instance({"patient": {"id": "patient-uuid-123"}})

            result = app.on_open()

            assert len(result) == 1
            effect = result[0]
            payload = json.loads(effect.payload)["data"]
            assert "patient_id=patient-uuid-123" in payload.get("url", "")

    def test_on_open_handles_missing_patient(self) -> None:
        """Test that on_open handles missing patient context gracefully."""
        with patch.object(
            ObservationVisualizerApp, "context", new_callable=PropertyMock
        ) as mock_context:
            mock_context.return_value = {}
            app = self.create_app_instance({})

            result = app.on_open()

            assert len(result) == 1
            effect = result[0]
            payload = json.loads(effect.payload)["data"]
            assert "patient_id=None" in payload.get("url", "")


class TestObservationVisualizerAPI:
    """Tests for the ObservationVisualizerAPI SimpleAPI handler."""

    @pytest.fixture
    def mock_event(self) -> MagicMock:
        """Create a mock event object for handler initialization."""
        event = MagicMock()
        event.context = {"method": "GET", "path": "/visualizer"}
        event.target = MagicMock()
        return event

    @pytest.fixture
    def mock_request(self) -> MagicMock:
        """Create a mock HTTP request object."""
        request = MagicMock()
        request.headers = {"Host": "localhost", "X-Forwarded-Proto": "https"}
        request.query_params = {}
        request.path_params = {}
        return request

    def test_uses_staff_session_auth_mixin(self) -> None:
        """Test that the API uses StaffSessionAuthMixin for authentication."""
        from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

        assert issubclass(ObservationVisualizerAPI, StaffSessionAuthMixin)

    def test_index_returns_html_response(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that index returns an HTML response with patient ID embedded."""
        mock_request.query_params = {"patient_id": "patient-uuid-123"}

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request

        with patch(
            "custom_observation_management.protocols.observation_visualizer.render_to_string"
        ) as mock_render:
            mock_render.return_value = "<html>Test</html>"

            result = handler.index()

            # Verify render_to_string was called with correct template and context
            mock_render.assert_called_once()
            call_args = mock_render.call_args
            assert call_args[0][0] == "templates/observation_visualizer.html"
            assert call_args[1]["context"]["patient_id"] == "patient-uuid-123"

            # Verify response
            assert len(result) == 1
            response = result[0]
            assert response.status_code == HTTPStatus.OK

    def test_index_handles_missing_patient_id(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that index handles missing patient_id gracefully."""
        mock_request.query_params = {}

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request

        with patch(
            "custom_observation_management.protocols.observation_visualizer.render_to_string"
        ) as mock_render:
            mock_render.return_value = "<html>Test</html>"

            result = handler.index()

            # Verify render_to_string was called with empty patient_id
            call_args = mock_render.call_args
            assert call_args[1]["context"]["patient_id"] == ""

            # Should still return OK response
            assert len(result) == 1
            assert result[0].status_code == HTTPStatus.OK

    def test_get_css_returns_css_response(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that get_css returns CSS content with correct content type."""
        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request

        with patch(
            "custom_observation_management.protocols.observation_visualizer.render_to_string"
        ) as mock_render:
            mock_render.return_value = "body { margin: 0; }"

            result = handler.get_css()

            # Verify render_to_string was called with CSS template
            mock_render.assert_called_once_with("templates/observation_visualizer.css")

            # Verify response
            assert len(result) == 1
            response = result[0]
            assert response.status_code == HTTPStatus.OK

    def test_get_js_returns_javascript_response(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that get_js returns JavaScript content with correct content type."""
        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request

        with patch(
            "custom_observation_management.protocols.observation_visualizer.render_to_string"
        ) as mock_render:
            mock_render.return_value = "console.log('test');"

            result = handler.get_js()

            # Verify render_to_string was called with JS template
            mock_render.assert_called_once_with("templates/observation_visualizer.js")

            # Verify response
            assert len(result) == 1
            response = result[0]
            assert response.status_code == HTTPStatus.OK

    def test_get_observations_raises_error_when_api_key_missing(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that get_observations raises KeyError when API key is not configured."""
        mock_request.query_params = {"patient_id": "patient-uuid-123"}

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = {}

        with pytest.raises(KeyError):
            handler.get_observations()

    def test_get_observations_proxies_to_observation_api(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that get_observations proxies request to ObservationAPI with API key."""
        mock_request.query_params = {"patient_id": "patient-uuid-123"}

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = {"simpleapi-api-key": "test-api-key"}

        with patch(
            "custom_observation_management.protocols.observation_visualizer.requests.get"
        ) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "observations": [{"id": "obs-1", "name": "Test"}],
                "pagination": {
                    "current_page": 1,
                    "total_pages": 1,
                    "total_count": 1,
                    "page_size": 25,
                    "has_previous": False,
                    "has_next": False
                }
            }
            mock_get.return_value = mock_response

            result = handler.get_observations()

            # Verify request was made with correct params and auth header
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "patient_id" in call_args.kwargs["params"]
            assert call_args.kwargs["headers"]["Authorization"] == "test-api-key"

            # Verify response
            assert len(result) == 1
            assert result[0].status_code == HTTPStatus.OK

    def test_get_observations_forwards_all_query_params(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that get_observations forwards all filter query parameters including pagination and sorting."""
        mock_request.query_params = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "category": "vital-signs",
            "effective_datetime_start": "2024-01-01T00:00:00Z",
            "effective_datetime_end": "2024-12-31T23:59:59Z",
            "sort_by": "name",
            "sort_order": "asc",
            "page": "2",
            "page_size": "50",
        }

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = {"simpleapi-api-key": "test-api-key"}

        with patch(
            "custom_observation_management.protocols.observation_visualizer.requests.get"
        ) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "observations": [],
                "pagination": {
                    "current_page": 2,
                    "total_pages": 1,
                    "total_count": 0,
                    "page_size": 50,
                    "has_previous": True,
                    "has_next": False
                }
            }
            mock_get.return_value = mock_response

            handler.get_observations()

            # Verify all params were forwarded
            call_args = mock_get.call_args
            params = call_args.kwargs["params"]
            assert params["patient_id"] == "patient-uuid-123"
            assert params["name"] == "Blood Pressure"
            assert params["category"] == "vital-signs"
            assert params["effective_datetime_start"] == "2024-01-01T00:00:00Z"
            assert params["effective_datetime_end"] == "2024-12-31T23:59:59Z"
            assert params["sort_by"] == "name"
            assert params["sort_order"] == "asc"
            assert params["page"] == "2"
            assert params["page_size"] == "50"

    def test_get_observation_filters_proxies_to_observation_api(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test that get_observation_filters proxies request to ObservationAPI."""
        mock_request.query_params = {"patient_id": "patient-uuid-123"}

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = {"simpleapi-api-key": "test-api-key"}

        with patch(
            "custom_observation_management.protocols.observation_visualizer.requests.get"
        ) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "names": ["Blood Pressure", "Heart Rate"],
                "categories": ["vital-signs", "laboratory"]
            }
            mock_get.return_value = mock_response

            result = handler.get_observation_filters()

            # Verify request was made
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "observation-filters" in call_args.args[0]
            assert "patient_id" in call_args.kwargs["params"]

            # Verify response
            assert len(result) == 1
            assert result[0].status_code == HTTPStatus.OK


class TestCreateChartReview:
    """Tests for the create_chart_review endpoint."""

    @pytest.fixture
    def mock_event(self) -> MagicMock:
        """Create a mock event object for handler initialization."""
        event = MagicMock()
        event.context = {"method": "POST", "path": "/visualizer/create-chart-review"}
        event.target = MagicMock()
        return event

    @pytest.fixture
    def mock_request(self) -> MagicMock:
        """Create a mock HTTP request object."""
        request = MagicMock()
        request.headers = {"Host": "localhost", "X-Forwarded-Proto": "https"}
        request.query_params = {}
        request.path_params = {}
        return request

    @pytest.fixture
    def mock_note_type(self) -> MagicMock:
        """Create a mock NoteType object."""
        note_type = MagicMock()
        note_type.id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        return note_type

    @pytest.fixture
    def mock_practice_location(self) -> MagicMock:
        """Create a mock PracticeLocation object."""
        location = MagicMock()
        location.id = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
        return location

    def test_create_chart_review_success(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_note_type: MagicMock,
        mock_practice_location: MagicMock,
    ) -> None:
        """Test successful creation of a Chart Review note."""
        mock_request.json.return_value = {
            "patient_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
            "staff_id": "d4e5f6a7-b8c9-0123-def1-234567890123",
            "summary_text": "<table>Summary HTML</table>",
            "comment": "Test comment",
        }

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request

        with patch(
            "custom_observation_management.protocols.observation_visualizer.NoteType"
        ) as MockNoteType, patch(
            "custom_observation_management.protocols.observation_visualizer.PracticeLocation"
        ) as MockPracticeLocation, patch(
            "custom_observation_management.protocols.observation_visualizer.Note"
        ) as MockNote, patch(
            "custom_observation_management.protocols.observation_visualizer.CustomCommand"
        ) as MockCustomCommand:
            MockNoteType.objects.filter.return_value.first.return_value = mock_note_type
            MockPracticeLocation.objects.first.return_value = mock_practice_location

            # Mock Note effect to return a mock effect on create()
            mock_note_effect = MagicMock()
            mock_note_effect.create.return_value = MagicMock()
            MockNote.return_value = mock_note_effect

            # Mock CustomCommand to return a mock effect on originate()
            mock_command = MagicMock()
            mock_command.originate.return_value = MagicMock()
            MockCustomCommand.return_value = mock_command

            result = handler.create_chart_review()

            # Should return 3 items: note effect, command effect, and JSON response
            assert len(result) == 3
            # Last item should be the JSON response with CREATED status
            assert result[2].status_code == HTTPStatus.CREATED

    def test_create_chart_review_without_comment(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_note_type: MagicMock,
        mock_practice_location: MagicMock,
    ) -> None:
        """Test creation of Chart Review note without optional comment."""
        mock_request.json.return_value = {
            "patient_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
            "staff_id": "d4e5f6a7-b8c9-0123-def1-234567890123",
            "summary_text": "<table>Summary HTML</table>",
        }

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request

        with patch(
            "custom_observation_management.protocols.observation_visualizer.NoteType"
        ) as MockNoteType, patch(
            "custom_observation_management.protocols.observation_visualizer.PracticeLocation"
        ) as MockPracticeLocation, patch(
            "custom_observation_management.protocols.observation_visualizer.Note"
        ) as MockNote, patch(
            "custom_observation_management.protocols.observation_visualizer.CustomCommand"
        ) as MockCustomCommand:
            MockNoteType.objects.filter.return_value.first.return_value = mock_note_type
            MockPracticeLocation.objects.first.return_value = mock_practice_location

            mock_note_effect = MagicMock()
            mock_note_effect.create.return_value = MagicMock()
            MockNote.return_value = mock_note_effect

            mock_command = MagicMock()
            mock_command.originate.return_value = MagicMock()
            MockCustomCommand.return_value = mock_command

            result = handler.create_chart_review()

            assert len(result) == 3
            assert result[2].status_code == HTTPStatus.CREATED

    def test_create_chart_review_with_empty_comment(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_note_type: MagicMock,
        mock_practice_location: MagicMock,
    ) -> None:
        """Test creation of Chart Review note with empty comment string."""
        mock_request.json.return_value = {
            "patient_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
            "staff_id": "d4e5f6a7-b8c9-0123-def1-234567890123",
            "summary_text": "<table>Summary HTML</table>",
            "comment": "",
        }

        handler = ObservationVisualizerAPI(event=mock_event)
        handler.request = mock_request

        with patch(
            "custom_observation_management.protocols.observation_visualizer.NoteType"
        ) as MockNoteType, patch(
            "custom_observation_management.protocols.observation_visualizer.PracticeLocation"
        ) as MockPracticeLocation, patch(
            "custom_observation_management.protocols.observation_visualizer.Note"
        ) as MockNote, patch(
            "custom_observation_management.protocols.observation_visualizer.CustomCommand"
        ) as MockCustomCommand:
            MockNoteType.objects.filter.return_value.first.return_value = mock_note_type
            MockPracticeLocation.objects.first.return_value = mock_practice_location

            mock_note_effect = MagicMock()
            mock_note_effect.create.return_value = MagicMock()
            MockNote.return_value = mock_note_effect

            mock_command = MagicMock()
            mock_command.originate.return_value = MagicMock()
            MockCustomCommand.return_value = mock_command

            result = handler.create_chart_review()

            assert len(result) == 3
            assert result[2].status_code == HTTPStatus.CREATED
