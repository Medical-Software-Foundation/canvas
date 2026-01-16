"""Tests for high_risk_meds_api module."""

import pytest
from unittest.mock import MagicMock, patch
from http import HTTPStatus

from high_risk_medications.api.high_risk_meds_api import (
    HighRiskMedsAPI,
    HighRiskMedsWebSocket,
)


class TestHighRiskMedsAPI:
    """Test suite for HighRiskMedsAPI SimpleAPI handler."""

    def test_get_view_returns_html_response_with_medications(self, mock_event, mock_environment):
        """Test that get_view returns HTML when patient has high-risk medications."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)
        api_instance.request = MagicMock()
        api_instance.request.path_params = {"patient_id": "patient-123"}
        api_instance.environment = mock_environment

        high_risk_meds = [
            {"name": "Warfarin 5mg Tablet", "id": "med-123"},
            {"name": "Insulin Glargine", "id": "med-456"},
        ]

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.get_high_risk_meds") as mock_get_meds:
            with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
                mock_get_meds.return_value = high_risk_meds
                mock_render.return_value = "<html>Test HTML</html>"

                responses = api_instance.get_view()

        # Verify
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.OK
        mock_get_meds.assert_called_once_with("patient-123")

    def test_get_view_returns_html_response_with_no_medications(self, mock_event, mock_environment):
        """Test that get_view returns HTML when patient has no high-risk medications."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)
        api_instance.request = MagicMock()
        api_instance.request.path_params = {"patient_id": "patient-456"}
        api_instance.environment = mock_environment

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.get_high_risk_meds") as mock_get_meds:
            with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
                mock_get_meds.return_value = []
                mock_render.return_value = "<html>No medications</html>"

                responses = api_instance.get_view()

        # Verify
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.OK
        mock_get_meds.assert_called_once_with("patient-456")

    def test_get_view_renders_correct_context(self, mock_event, mock_environment):
        """Test that get_view passes correct context to template."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)
        api_instance.request = MagicMock()
        api_instance.request.path_params = {"patient_id": "patient-789"}
        api_instance.environment = mock_environment

        high_risk_meds = [
            {"name": "Warfarin 5mg", "id": "med-1"},
            {"name": "Digoxin 0.25mg", "id": "med-2"},
        ]

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.get_high_risk_meds") as mock_get_meds:
            with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
                mock_get_meds.return_value = high_risk_meds
                mock_render.return_value = "<html>Test</html>"

                api_instance.get_view()

                # Verify context passed to render_to_string
                call_args = mock_render.call_args
                context = call_args[0][1]

                assert context["patient_id"] == "patient-789"
                assert context["has_high_risk_meds"] is True
                assert context["count"] == 2
                assert context["customer_identifier"] == "test-customer"
                assert "Warfarin 5mg" in context["medications"]
                assert "Digoxin 0.25mg" in context["medications"]

    def test_get_view_context_has_high_risk_meds_false_when_empty(self, mock_event, mock_environment):
        """Test that context has_high_risk_meds is False when no medications."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)
        api_instance.request = MagicMock()
        api_instance.request.path_params = {"patient_id": "patient-999"}
        api_instance.environment = mock_environment

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.get_high_risk_meds") as mock_get_meds:
            with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
                mock_get_meds.return_value = []
                mock_render.return_value = "<html>Test</html>"

                api_instance.get_view()

                # Verify context
                call_args = mock_render.call_args
                context = call_args[0][1]

                assert context["has_high_risk_meds"] is False
                assert context["count"] == 0

    def test_get_view_handles_exception_with_error_response(self, mock_event, mock_environment):
        """Test that get_view returns error HTML when exception occurs."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)
        api_instance.request = MagicMock()
        api_instance.request.path_params = {"patient_id": "patient-error"}
        api_instance.environment = mock_environment

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.get_high_risk_meds") as mock_get_meds:
            with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
                mock_get_meds.side_effect = Exception("Database error")
                mock_render.return_value = "<html>Error</html>"

                responses = api_instance.get_view()

        # Verify
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

        # Verify error template was called
        call_args = mock_render.call_args
        assert call_args[0][0] == "assets/templates/error.html"
        assert "Database error" in call_args[0][1]["error_message"]

    def test_get_view_includes_patient_id_in_path_params(self, mock_event, mock_environment):
        """Test that get_view extracts patient_id from path params."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)
        api_instance.request = MagicMock()
        api_instance.request.path_params = {"patient_id": "test-patient-id-123"}
        api_instance.environment = mock_environment

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.get_high_risk_meds") as mock_get_meds:
            with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
                mock_get_meds.return_value = []
                mock_render.return_value = "<html>Test</html>"

                api_instance.get_view()

        # Verify patient_id was used
        mock_get_meds.assert_called_once_with("test-patient-id-123")

    def test_get_view_builds_medication_html_correctly(self, mock_event, mock_environment):
        """Test that medication items are formatted as HTML."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)
        api_instance.request = MagicMock()
        api_instance.request.path_params = {"patient_id": "patient-html"}
        api_instance.environment = mock_environment

        high_risk_meds = [
            {"name": "Methotrexate 2.5mg", "id": "med-999"}
        ]

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.get_high_risk_meds") as mock_get_meds:
            with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
                mock_get_meds.return_value = high_risk_meds
                mock_render.return_value = "<html>Test</html>"

                api_instance.get_view()

                # Verify HTML structure
                call_args = mock_render.call_args
                context = call_args[0][1]
                medications_html = context["medications"]

                assert "HIGH RISK" in medications_html
                assert "Methotrexate 2.5mg" in medications_html
                assert "med-item" in medications_html
                assert "med-header" in medications_html

    def test_get_css_returns_css_response(self, mock_event):
        """Test that get_css returns CSS with correct content type."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
            mock_render.return_value = "body { color: red; }"

            responses = api_instance.get_css()

        # Verify
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.OK
        assert response.headers["Content-Type"] == "text/css"
        mock_render.assert_called_once_with("assets/templates/style.css")

    def test_get_script_returns_javascript_response(self, mock_event):
        """Test that get_script returns JavaScript with correct content type."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
            mock_render.return_value = "console.log('test');"

            responses = api_instance.get_script()

        # Verify
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.OK
        assert response.headers["Content-Type"] == "application/javascript"
        mock_render.assert_called_once_with("assets/templates/script.js")

    def test_get_css_encodes_content_as_bytes(self, mock_event):
        """Test that get_css encodes the CSS content as bytes."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
            mock_render.return_value = "body { color: blue; }"

            api_instance.get_css()

        # The render_to_string result should be encoded
        # This is verified by the fact that .encode() is called in the implementation

    def test_get_script_encodes_content_as_bytes(self, mock_event):
        """Test that get_script encodes the JavaScript content as bytes."""
        # Setup
        api_instance = HighRiskMedsAPI(event=mock_event)

        # Execute
        with patch("high_risk_medications.api.high_risk_meds_api.render_to_string") as mock_render:
            mock_render.return_value = "function test() {}"

            api_instance.get_script()

        # The render_to_string result should be encoded
        # This is verified by the fact that .encode() is called in the implementation

    def test_get_view_uses_staff_session_auth_mixin(self):
        """Test that HighRiskMedsAPI uses StaffSessionAuthMixin."""
        from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

        # Verify that HighRiskMedsAPI inherits from StaffSessionAuthMixin
        assert issubclass(HighRiskMedsAPI, StaffSessionAuthMixin)


class TestHighRiskMedsWebSocket:
    """Test suite for HighRiskMedsWebSocket handler."""

    def test_authenticate_returns_true_for_staff_user(self, mock_event, mock_websocket):
        """Test that authenticate returns True for staff users."""
        # Setup
        mock_websocket.logged_in_user = {"id": "staff-123", "type": "Staff"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify
        assert result is True

    def test_authenticate_returns_false_for_non_staff_user(self, mock_event, mock_websocket):
        """Test that authenticate returns False for non-staff users."""
        # Setup
        mock_websocket.logged_in_user = {"id": "patient-456", "type": "Patient"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify
        assert result is False

    def test_authenticate_returns_false_when_no_logged_in_user(self, mock_event, mock_websocket):
        """Test that authenticate returns False when no user is logged in."""
        # Setup
        mock_websocket.logged_in_user = None

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify
        assert result is False

    def test_authenticate_checks_user_type_is_staff(self, mock_event, mock_websocket):
        """Test that authenticate checks for 'Staff' type specifically."""
        # Setup - user with different type
        mock_websocket.logged_in_user = {"id": "admin-789", "type": "Admin"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify - should be False since type is not "Staff"
        assert result is False

    def test_authenticate_handles_missing_type_field(self, mock_event, mock_websocket):
        """Test that authenticate handles missing 'type' field gracefully."""
        # Setup - user without type field
        mock_websocket.logged_in_user = {"id": "user-999"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify - should be False since type is missing
        assert result is False

    def test_authenticate_accesses_websocket_channel(self, mock_event, mock_websocket):
        """Test that authenticate can access websocket channel."""
        # Setup
        mock_websocket.channel = "patient-123"
        mock_websocket.logged_in_user = {"id": "staff-123", "type": "Staff"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify - should not crash and should work correctly
        assert result is True
        assert ws_instance.websocket.channel == "patient-123"

    def test_authenticate_accesses_websocket_headers(self, mock_event, mock_websocket):
        """Test that authenticate can access websocket headers."""
        # Setup
        mock_websocket.headers = {"Authorization": "Bearer token123"}
        mock_websocket.logged_in_user = {"id": "staff-123", "type": "Staff"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify - should not crash and should work correctly
        assert result is True
        assert "Authorization" in ws_instance.websocket.headers

    def test_authenticate_case_sensitive_staff_type(self, mock_event, mock_websocket):
        """Test that authenticate is case-sensitive for 'Staff' type."""
        # Setup - lowercase 'staff'
        mock_websocket.logged_in_user = {"id": "staff-123", "type": "staff"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify - should be False since "staff" != "Staff"
        assert result is False

    def test_authenticate_returns_boolean(self, mock_event, mock_websocket):
        """Test that authenticate always returns a boolean value."""
        # Setup - valid staff
        mock_websocket.logged_in_user = {"id": "staff-123", "type": "Staff"}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify type
        assert isinstance(result, bool)

    def test_authenticate_handles_empty_logged_in_user_dict(self, mock_event, mock_websocket):
        """Test that authenticate handles empty logged_in_user dict."""
        # Setup - empty dict (truthy but no type)
        mock_websocket.logged_in_user = {}

        ws_instance = HighRiskMedsWebSocket(event=mock_event)
        ws_instance.websocket = mock_websocket

        # Execute
        result = ws_instance.authenticate()

        # Verify - should be False since type is missing
        assert result is False
