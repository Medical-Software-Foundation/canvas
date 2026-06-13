"""Tests for PrescriptionProcessingWebApp."""

from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

from prescription_processing_dashboard.handlers.prescription_processing_web_app import (
    PrescriptionProcessingWebApp,
)


class TestPrescriptionProcessingWebAppAuthentication:
    """Tests for authentication functionality."""

    def test_authenticate_with_logged_in_user_returns_true(
        self, mock_simple_api_event, mock_session_credentials
    ):
        """Test that authentication passes when user is logged in."""
        handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)

        result = handler.authenticate(mock_session_credentials)

        # Verify mock_session_credentials - logged_in_user attribute is accessed
        # The 'is not None' comparison doesn't generate mock calls when the value is set
        assert mock_session_credentials.mock_calls == []

        # Verify result
        assert result is True

    def test_authenticate_without_logged_in_user_returns_false(self, mock_simple_api_event):
        """Test that authentication fails when no user is logged in."""
        credentials = MagicMock()
        credentials.logged_in_user = None

        handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)

        result = handler.authenticate(credentials)

        # Verify credentials - logged_in_user is set to None, so 'is not None' returns False
        # The 'is not None' comparison doesn't generate mock calls when the value is set
        assert credentials.mock_calls == []

        # Verify result
        assert result is False


class TestPrescriptionProcessingWebAppDashboard:
    """Tests for the dashboard endpoint."""

    def test_index_returns_html_response(self, mock_simple_api_event, mock_staff, mock_request):
        """Test that index returns an HTML response with rendered template."""
        with patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Staff"
        ) as mock_staff_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Command"
        ) as mock_command_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.render_to_string"
        ) as mock_render, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.HTMLResponse"
        ) as mock_html_response:
            # Setup mocks
            mock_staff_class.objects.get.return_value = mock_staff
            mock_queryset = MagicMock()
            mock_queryset.__iter__ = MagicMock(return_value=iter([]))
            mock_command_class.objects.filter.return_value.exclude.return_value.select_related.return_value = (
                mock_queryset
            )
            mock_render.return_value = "<html>Dashboard</html>"
            mock_response = MagicMock()
            mock_html_response.return_value = mock_response

            handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)
            handler.request = mock_request

            result = handler.index()

            # Verify mock_staff_class
            assert mock_staff_class.mock_calls == [call.objects.get(id="staff-123")]

            # Verify mock_command_class - includes __iter__ call when iterating over queryset
            assert mock_command_class.mock_calls == [
                call.objects.filter(
                    schema_key="prescribe",
                    committer__isnull=True,
                    entered_in_error__isnull=True,
                    data__prescribe__isnull=False,
                    data__prescriber__isnull=False,
                    data__pharmacy__isnull=False,
                    data__days_supply__isnull=False,
                    note__current_state__state__in=[
                        mock_command_class.mock_calls[0][2]["note__current_state__state__in"][0],
                        mock_command_class.mock_calls[0][2]["note__current_state__state__in"][1],
                        mock_command_class.mock_calls[0][2]["note__current_state__state__in"][2],
                        mock_command_class.mock_calls[0][2]["note__current_state__state__in"][3],
                        mock_command_class.mock_calls[0][2]["note__current_state__state__in"][4],
                        mock_command_class.mock_calls[0][2]["note__current_state__state__in"][5],
                    ],
                ),
                call.objects.filter().exclude(data__sig=""),
                call.objects.filter().exclude().select_related("patient", "note", "originator__staff"),
                call.objects.filter().exclude().select_related().__iter__(),
            ]

            # Verify mock_render
            assert mock_render.mock_calls == [
                call(
                    "static/index.html",
                    {
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "pending_prescriptions": mock_queryset,
                        "prescribers": [],
                        "selected_prescriber": None,
                    },
                )
            ]

            # Verify mock_html_response
            assert mock_html_response.mock_calls == [
                call("<html>Dashboard</html>", status_code=HTTPStatus.OK)
            ]

            # Verify mock_request - used as data container, access via dict-like headers
            # and query_params doesn't generate mock_calls since they're pre-set attributes
            assert mock_request.mock_calls == []

            # Verify mock_staff - used for first_name/last_name attributes (pre-set)
            assert mock_staff.mock_calls == []

            # Verify mock_queryset
            assert mock_queryset.mock_calls == [call.__iter__()]

            # Verify result
            assert result == [mock_response]

    def test_index_with_prescriptions_extracts_prescribers(
        self, mock_simple_api_event, mock_staff, mock_request
    ):
        """Test that index extracts unique prescribers from prescriptions."""
        with patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Staff"
        ) as mock_staff_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Command"
        ) as mock_command_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.render_to_string"
        ) as mock_render, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.HTMLResponse"
        ) as mock_html_response:
            # Setup mocks
            mock_staff_class.objects.get.return_value = mock_staff

            # Create prescription with prescriber data
            mock_prescription1 = MagicMock()
            mock_prescription1.data = {"prescriber": {"text": "Dr. Smith", "value": 123}}
            mock_prescription2 = MagicMock()
            mock_prescription2.data = {"prescriber": {"text": "Dr. Jones", "value": 456}}
            mock_prescription3 = MagicMock()
            mock_prescription3.data = {"prescriber": {"text": "Dr. Smith", "value": 123}}  # Duplicate

            mock_queryset = MagicMock()
            mock_queryset.__iter__ = MagicMock(
                return_value=iter([mock_prescription1, mock_prescription2, mock_prescription3])
            )
            mock_command_class.objects.filter.return_value.exclude.return_value.select_related.return_value = (
                mock_queryset
            )
            mock_render.return_value = "<html>Dashboard</html>"
            mock_response = MagicMock()
            mock_html_response.return_value = mock_response

            handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)
            handler.request = mock_request

            handler.index()

            # Verify render was called with sorted unique prescribers
            render_call = mock_render.mock_calls[0]
            context = render_call[1][1]
            assert context["prescribers"] == [("456", "Dr. Jones"), ("123", "Dr. Smith")]

            # Verify mock_simple_api_event (not accessed during index)
            assert mock_simple_api_event.mock_calls == []

    def test_index_with_prescriber_filter(self, mock_simple_api_event, mock_staff, mock_request):
        """Test that index filters prescriptions by selected prescriber."""
        mock_request.query_params = {"prescriber": "123"}

        with patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Staff"
        ) as mock_staff_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Command"
        ) as mock_command_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.render_to_string"
        ) as mock_render, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.HTMLResponse"
        ) as mock_html_response:
            # Setup mocks
            mock_staff_class.objects.get.return_value = mock_staff

            mock_prescription = MagicMock()
            mock_prescription.data = {"prescriber": {"text": "Dr. Smith", "value": 123}}

            mock_queryset = MagicMock()
            mock_queryset.__iter__ = MagicMock(return_value=iter([mock_prescription]))
            mock_filtered_queryset = MagicMock()
            mock_queryset.filter.return_value = mock_filtered_queryset
            mock_command_class.objects.filter.return_value.exclude.return_value.select_related.return_value = (
                mock_queryset
            )
            mock_render.return_value = "<html>Dashboard</html>"
            mock_response = MagicMock()
            mock_html_response.return_value = mock_response

            handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)
            handler.request = mock_request

            handler.index()

            # Verify queryset.filter was called with prescriber filter
            assert mock_queryset.mock_calls == [
                call.__iter__(),
                call.filter(data__prescriber__value=123),
            ]

            # Verify render was called with selected_prescriber
            render_call = mock_render.mock_calls[0]
            context = render_call[1][1]
            assert context["selected_prescriber"] == "123"
            assert context["pending_prescriptions"] == mock_filtered_queryset

            # Verify mock_simple_api_event (not accessed during index)
            assert mock_simple_api_event.mock_calls == []

    def test_index_handles_prescription_without_prescriber_text(
        self, mock_simple_api_event, mock_staff, mock_request
    ):
        """Test that index handles prescriptions with missing prescriber text."""
        with patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Staff"
        ) as mock_staff_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Command"
        ) as mock_command_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.render_to_string"
        ) as mock_render, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.HTMLResponse"
        ) as mock_html_response:
            # Setup mocks
            mock_staff_class.objects.get.return_value = mock_staff

            # Prescription with empty prescriber text
            mock_prescription = MagicMock()
            mock_prescription.data = {"prescriber": {"text": "", "value": 123}}

            mock_queryset = MagicMock()
            mock_queryset.__iter__ = MagicMock(return_value=iter([mock_prescription]))
            mock_command_class.objects.filter.return_value.exclude.return_value.select_related.return_value = (
                mock_queryset
            )
            mock_render.return_value = "<html>Dashboard</html>"
            mock_response = MagicMock()
            mock_html_response.return_value = mock_response

            handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)
            handler.request = mock_request

            handler.index()

            # Verify render was called with empty prescribers list (filtered out empty text)
            render_call = mock_render.mock_calls[0]
            context = render_call[1][1]
            assert context["prescribers"] == []

            # Verify mock_simple_api_event (not accessed during index)
            assert mock_simple_api_event.mock_calls == []

    def test_index_handles_prescription_without_prescriber_key(
        self, mock_simple_api_event, mock_staff, mock_request
    ):
        """Test that index handles prescriptions with missing prescriber key."""
        with patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Staff"
        ) as mock_staff_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Command"
        ) as mock_command_class, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.render_to_string"
        ) as mock_render, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.HTMLResponse"
        ) as mock_html_response:
            # Setup mocks
            mock_staff_class.objects.get.return_value = mock_staff

            # Prescription without prescriber key
            mock_prescription = MagicMock()
            mock_prescription.data = {}

            mock_queryset = MagicMock()
            mock_queryset.__iter__ = MagicMock(return_value=iter([mock_prescription]))
            mock_command_class.objects.filter.return_value.exclude.return_value.select_related.return_value = (
                mock_queryset
            )
            mock_render.return_value = "<html>Dashboard</html>"
            mock_response = MagicMock()
            mock_html_response.return_value = mock_response

            handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)
            handler.request = mock_request

            handler.index()

            # Verify render was called with empty prescribers list
            render_call = mock_render.mock_calls[0]
            context = render_call[1][1]
            assert context["prescribers"] == []

            # Verify mock_simple_api_event (not accessed during index)
            assert mock_simple_api_event.mock_calls == []


class TestPrescriptionProcessingWebAppStaticFiles:
    """Tests for static file serving endpoints."""

    def test_get_main_js_returns_javascript(self, mock_simple_api_event):
        """Test that get_main_js returns JavaScript content."""
        with patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.render_to_string"
        ) as mock_render, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Response"
        ) as mock_response:
            mock_render.return_value = "console.log('test');"
            mock_response_obj = MagicMock()
            mock_response.return_value = mock_response_obj

            handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)
            result = handler.get_main_js()

            # Verify mock_render
            assert mock_render.mock_calls == [call("static/main.js")]

            # Verify mock_response
            assert mock_response.mock_calls == [
                call(
                    b"console.log('test');",
                    status_code=HTTPStatus.OK,
                    content_type="text/javascript",
                )
            ]

            # Verify mock_simple_api_event (not accessed during get_main_js)
            assert mock_simple_api_event.mock_calls == []

            # Verify result
            assert result == [mock_response_obj]

    def test_get_css_returns_stylesheet(self, mock_simple_api_event):
        """Test that get_css returns CSS content."""
        with patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.render_to_string"
        ) as mock_render, patch(
            "prescription_processing_dashboard.handlers.prescription_processing_web_app.Response"
        ) as mock_response:
            mock_render.return_value = "body { color: red; }"
            mock_response_obj = MagicMock()
            mock_response.return_value = mock_response_obj

            handler = PrescriptionProcessingWebApp(event=mock_simple_api_event)
            result = handler.get_css()

            # Verify mock_render
            assert mock_render.mock_calls == [call("static/styles.css")]

            # Verify mock_response
            assert mock_response.mock_calls == [
                call(
                    b"body { color: red; }",
                    status_code=HTTPStatus.OK,
                    content_type="text/css",
                )
            ]

            # Verify mock_simple_api_event (not accessed during get_css)
            assert mock_simple_api_event.mock_calls == []

            # Verify result
            assert result == [mock_response_obj]


class TestPrescriptionProcessingWebAppConfiguration:
    """Tests for handler configuration."""

    def test_prefix_is_app(self):
        """Test that the handler prefix is /app."""
        assert PrescriptionProcessingWebApp.PREFIX == "/app"
