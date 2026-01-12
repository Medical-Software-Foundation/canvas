from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from vitalstream.routes.vitalstream_ui_api import VitalstreamUIAPI


class TestVitalstreamUIAPI:
    """Tests for the VitalstreamUIAPI class."""

    def create_api_instance(
        self,
        path_params: dict = None,
        headers: dict = None,
        json_data: dict = None,
        environment: dict = None,
    ) -> VitalstreamUIAPI:
        """Helper to create a VitalstreamUIAPI instance with mocked request."""
        api = VitalstreamUIAPI.__new__(VitalstreamUIAPI)
        api.request = Mock()
        api.request.path_params = path_params or {}
        api.request.headers = headers or {}
        api.request.json.return_value = json_data or {}
        api.environment = environment or {}
        return api


class TestValidateSession(TestVitalstreamUIAPI):
    """Tests for the validate_session method."""

    @patch("vitalstream.routes.vitalstream_ui_api.get_cache")
    @patch("vitalstream.routes.vitalstream_ui_api.Staff")
    def test_returns_session_when_valid(self, mock_staff, mock_get_cache) -> None:
        """Test that validate_session returns session dict when session exists and staff matches."""
        mock_staff_instance = Mock()
        mock_staff_instance.id = "staff-123"
        mock_staff.objects.get.return_value = mock_staff_instance

        mock_cache = Mock()
        session_data = {"note_id": "note-456", "staff_id": "staff-123"}
        mock_cache.get.return_value = session_data
        mock_get_cache.return_value = mock_cache

        api = self.create_api_instance(
            headers={"canvas-logged-in-user-id": "staff-123"}
        )

        result = api.validate_session("test-session-id")

        assert result == session_data
        mock_cache.get.assert_called_once_with("session_id:test-session-id")

    @patch("vitalstream.routes.vitalstream_ui_api.get_cache")
    @patch("vitalstream.routes.vitalstream_ui_api.Staff")
    def test_returns_none_when_session_not_found(self, mock_staff, mock_get_cache) -> None:
        """Test that validate_session returns None when session doesn't exist."""
        mock_staff_instance = Mock()
        mock_staff_instance.id = "staff-123"
        mock_staff.objects.get.return_value = mock_staff_instance

        mock_cache = Mock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        api = self.create_api_instance(
            headers={"canvas-logged-in-user-id": "staff-123"}
        )

        result = api.validate_session("nonexistent-session")

        assert result is None

    @patch("vitalstream.routes.vitalstream_ui_api.get_cache")
    @patch("vitalstream.routes.vitalstream_ui_api.Staff")
    def test_returns_none_when_staff_id_mismatch(self, mock_staff, mock_get_cache) -> None:
        """Test that validate_session returns None when logged-in staff doesn't match session."""
        mock_staff_instance = Mock()
        mock_staff_instance.id = "staff-123"
        mock_staff.objects.get.return_value = mock_staff_instance

        mock_cache = Mock()
        session_data = {"note_id": "note-456", "staff_id": "different-staff-789"}
        mock_cache.get.return_value = session_data
        mock_get_cache.return_value = mock_cache

        api = self.create_api_instance(
            headers={"canvas-logged-in-user-id": "staff-123"}
        )

        result = api.validate_session("test-session-id")

        assert result is None


class TestIndex(TestVitalstreamUIAPI):
    """Tests for the index method."""

    @patch("vitalstream.routes.vitalstream_ui_api.render_to_string")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_returns_404_when_session_invalid(self, mock_validate, mock_render) -> None:
        """Test that index returns 404 when session is invalid."""
        mock_validate.return_value = None
        mock_render.return_value = "<html>Not Found</html>"

        api = self.create_api_instance(
            path_params={"session_id": "invalid-session"}
        )

        effects = api.index()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.NOT_FOUND
        mock_render.assert_called_once_with("templates/session-not-found.html")

    @patch("vitalstream.routes.vitalstream_ui_api.render_to_string")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_returns_200_with_html_when_session_valid(self, mock_validate, mock_render) -> None:
        """Test that index returns 200 with rendered HTML when session is valid."""
        mock_validate.return_value = {"note_id": "note-123", "staff_id": "staff-456"}
        mock_render.return_value = "<html>VitalStream UI</html>"

        api = self.create_api_instance(
            path_params={"session_id": "valid-session"},
            environment={"CUSTOMER_IDENTIFIER": "testcustomer"},
        )

        effects = api.index()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.OK
        mock_render.assert_called_once_with(
            "templates/vitalstream-ui.html",
            {"session_id": "valid-session", "subdomain": "testcustomer"},
        )


class TestPostMeasurements(TestVitalstreamUIAPI):
    """Tests for the post_measurements method."""

    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_returns_404_when_session_invalid(self, mock_validate) -> None:
        """Test that post_measurements returns 404 when session is invalid."""
        mock_validate.return_value = None

        api = self.create_api_instance(
            path_params={"session_id": "invalid-session"}
        )

        effects = api.post_measurements()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.NOT_FOUND
        assert effects[0].headers["Content-Type"] == "application/json"

    @patch("vitalstream.routes.vitalstream_ui_api.Observation")
    @patch("vitalstream.routes.vitalstream_ui_api.Note")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_creates_observation_for_heart_rate(self, mock_validate, mock_note, mock_observation) -> None:
        """Test that post_measurements creates an observation for heart rate."""
        mock_validate.return_value = {"note_id": "note-123", "staff_id": "staff-456"}

        mock_note_instance = Mock()
        mock_note_instance.patient.id = "patient-789"
        mock_note_instance.dbid = 123
        mock_note.objects.get.return_value = mock_note_instance

        mock_obs_instance = Mock()
        mock_obs_instance.create.return_value = Mock()
        mock_observation.return_value = mock_obs_instance

        api = self.create_api_instance(
            path_params={"session_id": "valid-session"},
            json_data={
                "timestamp": "2026-01-07T08:50:14+00:00",
                "hr": 72,
            },
        )

        effects = api.post_measurements()

        # Should have 1 observation effect + 1 response
        assert len(effects) == 2
        assert effects[-1].status_code == HTTPStatus.OK

        mock_observation.assert_called_once()
        call_kwargs = mock_observation.call_args.kwargs
        assert call_kwargs["patient_id"] == "patient-789"
        assert call_kwargs["note_id"] == 123
        assert call_kwargs["category"] == "vital-signs"
        assert call_kwargs["name"] == "Mean heart rate"
        assert call_kwargs["value"] == "72"
        assert call_kwargs["units"] == "{beats}/min"
        assert call_kwargs["codings"][0].code == "103205-1"

    @patch("vitalstream.routes.vitalstream_ui_api.Observation")
    @patch("vitalstream.routes.vitalstream_ui_api.Note")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_creates_bp_panel_when_systolic_present(self, mock_validate, mock_note, mock_observation) -> None:
        """Test that post_measurements creates a BP panel when only systolic is present."""
        mock_validate.return_value = {"note_id": "note-123", "staff_id": "staff-456"}

        mock_note_instance = Mock()
        mock_note_instance.patient.id = "patient-789"
        mock_note_instance.dbid = 123
        mock_note.objects.get.return_value = mock_note_instance

        mock_obs_instance = Mock()
        mock_obs_instance.create.return_value = Mock()
        mock_observation.return_value = mock_obs_instance

        api = self.create_api_instance(
            path_params={"session_id": "valid-session"},
            json_data={
                "timestamp": "2026-01-07T08:50:14+00:00",
                "sys": 120,
            },
        )

        effects = api.post_measurements()

        # Should have 1 BP panel observation + 1 response
        assert len(effects) == 2

        mock_observation.assert_called_once()
        call_kwargs = mock_observation.call_args.kwargs
        assert call_kwargs["category"] == "vital-signs"
        assert call_kwargs["name"] == "Blood pressure panel mean systolic and mean diastolic"
        assert call_kwargs["codings"][0].code == "96607-7"
        assert len(call_kwargs["components"]) == 1
        assert call_kwargs["components"][0].value_quantity == "120"
        assert call_kwargs["components"][0].codings[0].code == "96608-5"

    @patch("vitalstream.routes.vitalstream_ui_api.Observation")
    @patch("vitalstream.routes.vitalstream_ui_api.Note")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_creates_bp_panel_when_diastolic_present(self, mock_validate, mock_note, mock_observation) -> None:
        """Test that post_measurements creates a BP panel when only diastolic is present."""
        mock_validate.return_value = {"note_id": "note-123", "staff_id": "staff-456"}

        mock_note_instance = Mock()
        mock_note_instance.patient.id = "patient-789"
        mock_note_instance.dbid = 123
        mock_note.objects.get.return_value = mock_note_instance

        mock_obs_instance = Mock()
        mock_obs_instance.create.return_value = Mock()
        mock_observation.return_value = mock_obs_instance

        api = self.create_api_instance(
            path_params={"session_id": "valid-session"},
            json_data={
                "timestamp": "2026-01-07T08:50:14+00:00",
                "dia": 80,
            },
        )

        effects = api.post_measurements()

        # Should have 1 BP panel observation + 1 response
        assert len(effects) == 2

        mock_observation.assert_called_once()
        call_kwargs = mock_observation.call_args.kwargs
        assert call_kwargs["category"] == "vital-signs"
        assert call_kwargs["name"] == "Blood pressure panel mean systolic and mean diastolic"
        assert call_kwargs["codings"][0].code == "96607-7"
        assert len(call_kwargs["components"]) == 1
        assert call_kwargs["components"][0].value_quantity == "80"
        assert call_kwargs["components"][0].codings[0].code == "96609-3"

    @patch("vitalstream.routes.vitalstream_ui_api.Observation")
    @patch("vitalstream.routes.vitalstream_ui_api.Note")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_creates_bp_panel_with_both_components(self, mock_validate, mock_note, mock_observation) -> None:
        """Test that post_measurements creates a BP panel with both sys and dia."""
        mock_validate.return_value = {"note_id": "note-123", "staff_id": "staff-456"}

        mock_note_instance = Mock()
        mock_note_instance.patient.id = "patient-789"
        mock_note_instance.dbid = 123
        mock_note.objects.get.return_value = mock_note_instance

        mock_obs_instance = Mock()
        mock_obs_instance.create.return_value = Mock()
        mock_observation.return_value = mock_obs_instance

        api = self.create_api_instance(
            path_params={"session_id": "valid-session"},
            json_data={
                "timestamp": "2026-01-07T08:50:14+00:00",
                "sys": 120,
                "dia": 80,
            },
        )

        effects = api.post_measurements()

        mock_observation.assert_called_once()
        call_kwargs = mock_observation.call_args.kwargs
        assert len(call_kwargs["components"]) == 2

    @patch("vitalstream.routes.vitalstream_ui_api.Observation")
    @patch("vitalstream.routes.vitalstream_ui_api.Note")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_creates_multiple_observations_for_all_vitals(self, mock_validate, mock_note, mock_observation) -> None:
        """Test that post_measurements creates observations for all provided vitals."""
        mock_validate.return_value = {"note_id": "note-123", "staff_id": "staff-456"}

        mock_note_instance = Mock()
        mock_note_instance.patient.id = "patient-789"
        mock_note_instance.dbid = 123
        mock_note.objects.get.return_value = mock_note_instance

        mock_obs_instance = Mock()
        mock_obs_instance.create.return_value = Mock()
        mock_observation.return_value = mock_obs_instance

        api = self.create_api_instance(
            path_params={"session_id": "valid-session"},
            json_data={
                "timestamp": "2026-01-07T08:50:14+00:00",
                "hr": 72,
                "sys": 120,
                "dia": 80,
                "resp": 16,
                "spo2": 98,
            },
        )

        effects = api.post_measurements()

        # 3 individual observations (hr, resp, spo2) + 1 BP panel + 1 response = 5
        assert len(effects) == 5
        assert mock_observation.call_count == 4  # 3 individual + 1 BP panel

    @patch("vitalstream.routes.vitalstream_ui_api.Observation")
    @patch("vitalstream.routes.vitalstream_ui_api.Note")
    @patch.object(VitalstreamUIAPI, "validate_session")
    def test_skips_missing_vitals(self, mock_validate, mock_note, mock_observation) -> None:
        """Test that post_measurements skips vitals that are not in the data."""
        mock_validate.return_value = {"note_id": "note-123", "staff_id": "staff-456"}

        mock_note_instance = Mock()
        mock_note_instance.patient.id = "patient-789"
        mock_note_instance.dbid = 123
        mock_note.objects.get.return_value = mock_note_instance

        mock_obs_instance = Mock()
        mock_obs_instance.create.return_value = Mock()
        mock_observation.return_value = mock_obs_instance

        api = self.create_api_instance(
            path_params={"session_id": "valid-session"},
            json_data={
                "timestamp": "2026-01-07T08:50:14+00:00",
                # No vitals provided
            },
        )

        effects = api.post_measurements()

        # Only the response, no observations
        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.OK
        mock_observation.assert_not_called()


class TestGetMainJs(TestVitalstreamUIAPI):
    """Tests for the get_main_js method."""

    @patch("vitalstream.routes.vitalstream_ui_api.render_to_string")
    def test_returns_javascript_file(self, mock_render) -> None:
        """Test that get_main_js returns JavaScript with correct content type."""
        mock_render.return_value = "console.log('test');"

        api = self.create_api_instance()

        effects = api.get_main_js()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.OK
        assert effects[0].headers["Content-Type"] == "text/javascript"
        assert effects[0].content == b"console.log('test');"
        mock_render.assert_called_once_with("static/main.js")


class TestGetCss(TestVitalstreamUIAPI):
    """Tests for the get_css method."""

    @patch("vitalstream.routes.vitalstream_ui_api.render_to_string")
    def test_returns_css_file(self, mock_render) -> None:
        """Test that get_css returns CSS with correct content type."""
        mock_render.return_value = "body { color: red; }"

        api = self.create_api_instance()

        effects = api.get_css()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.OK
        assert effects[0].headers["Content-Type"] == "text/css"
        assert effects[0].content == b"body { color: red; }"
        mock_render.assert_called_once_with("static/styles.css")
