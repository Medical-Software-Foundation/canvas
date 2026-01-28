"""Comprehensive tests for provider_scheduling utilization_web_app."""

from http import HTTPStatus
from unittest.mock import Mock, patch

from provider_scheduling.handlers.utilization_web_app import UtilizationWebApp


class DummyRequest:
    """A dummy request object for testing UtilizationWebApp."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


class DummyEvent:
    """A dummy event object for testing API handlers."""

    def __init__(self, context: dict[str, object] | None = None) -> None:
        self.context = context or {}


def test_web_app_prefix_configuration() -> None:
    """Test that the web app has correct prefix configuration."""
    assert UtilizationWebApp.PREFIX == "/app"


def test_index_returns_html_response() -> None:
    """Test index endpoint returns HTML response with correct status code."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization-dashboard"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    app.request = DummyRequest()

    # Mock database queries
    mock_providers: list = []

    with (
        patch("provider_scheduling.handlers.utilization_web_app.Staff") as mock_staff_class,
        patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render,
    ):
        # Mock querysets
        mock_filter_result = Mock()
        mock_filter_result.distinct.return_value = mock_providers
        mock_staff_class.objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>Test HTML</html>"

        result = app.index()

        # Verify response
        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert b"<html>Test HTML</html>" in response.content


def test_index_queries_active_clinical_providers() -> None:
    """Test index endpoint queries for active providers with clinical roles."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization-dashboard"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    app.request = DummyRequest()

    with (
        patch("provider_scheduling.handlers.utilization_web_app.Staff") as mock_staff_class,
        patch("provider_scheduling.handlers.utilization_web_app.StaffRole") as mock_staff_role,
        patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render,
    ):
        mock_filter_result = Mock()
        mock_filter_result.distinct.return_value = []
        mock_staff_class.objects.filter.return_value = mock_filter_result
        mock_staff_role.RoleDomain.clinical_domains.return_value = ["clinical", "hybrid"]
        mock_render.return_value = "<html>Test</html>"

        app.index()

        # Verify Staff.objects.filter was called with active=True and clinical roles
        mock_staff_class.objects.filter.assert_called_once_with(
            active=True,
            roles__domain__in=["clinical", "hybrid"]
        )


def test_index_builds_providers_context() -> None:
    """Test index endpoint builds providers context with correct data."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization-dashboard"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    app.request = DummyRequest()

    # Create mock providers
    mock_provider1 = Mock()
    mock_provider1.id = "provider-1"
    mock_provider1.credentialed_name = "Dr. Smith, MD"
    mock_provider1.full_name = "Dr. John Smith"

    mock_provider2 = Mock()
    mock_provider2.id = "provider-2"
    mock_provider2.credentialed_name = "Dr. Jones, DO"
    mock_provider2.full_name = "Dr. Jane Jones"

    mock_providers = [mock_provider1, mock_provider2]

    with (
        patch("provider_scheduling.handlers.utilization_web_app.Staff") as mock_staff_class,
        patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render,
    ):
        mock_filter_result = Mock()
        mock_filter_result.distinct.return_value = mock_providers
        mock_staff_class.objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>Test</html>"

        app.index()

        # Verify render_to_string was called with correct context
        call_args = mock_render.call_args
        context = call_args[0][1]

        assert len(context["providers"]) == 2
        assert context["providers"][0]["id"] == "provider-1"
        assert context["providers"][0]["name"] == "Dr. Smith, MD"
        assert context["providers"][0]["full_name"] == "Dr. John Smith"
        assert context["providers"][1]["id"] == "provider-2"
        assert context["providers"][1]["name"] == "Dr. Jones, DO"
        assert context["providers"][1]["full_name"] == "Dr. Jane Jones"


def test_index_includes_logged_in_user_id_in_context() -> None:
    """Test index endpoint includes logged in user ID in context."""
    # Create web app instance with logged in user header
    dummy_context = {"method": "GET", "path": "/app/utilization-dashboard"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    app.request = DummyRequest(headers={"canvas-logged-in-user-id": "user-123"})

    with (
        patch("provider_scheduling.handlers.utilization_web_app.Staff") as mock_staff_class,
        patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render,
    ):
        mock_filter_result = Mock()
        mock_filter_result.distinct.return_value = []
        mock_staff_class.objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>Test</html>"

        app.index()

        # Verify context includes logged in user ID
        call_args = mock_render.call_args
        context = call_args[0][1]

        assert context["loggedInUserId"] == "user-123"


def test_index_renders_correct_template() -> None:
    """Test index endpoint renders the correct HTML template."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization-dashboard"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    app.request = DummyRequest()

    with (
        patch("provider_scheduling.handlers.utilization_web_app.Staff") as mock_staff_class,
        patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render,
    ):
        mock_filter_result = Mock()
        mock_filter_result.distinct.return_value = []
        mock_staff_class.objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>Test</html>"

        app.index()

        # Verify render_to_string was called with correct template path
        call_args = mock_render.call_args
        assert call_args[0][0] == "static/utilization/index.html"


def test_get_main_js_returns_javascript() -> None:
    """Test get_main_js endpoint returns JavaScript with correct status code."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization.js"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]

    with patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render:
        mock_render.return_value = "console.log('test');"

        result = app.get_main_js()

        # Verify response
        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"console.log('test');"


def test_get_main_js_renders_correct_template() -> None:
    """Test get_main_js endpoint renders the correct JavaScript template."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization.js"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]

    with patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render:
        mock_render.return_value = "// JavaScript content"

        app.get_main_js()

        # Verify render_to_string was called with correct template
        mock_render.assert_called_once_with("static/utilization/main.js")


def test_get_css_returns_stylesheet() -> None:
    """Test get_css endpoint returns CSS with correct status code."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization.css"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]

    with patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render:
        mock_render.return_value = "body { margin: 0; }"

        result = app.get_css()

        # Verify response
        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"body { margin: 0; }"


def test_get_css_renders_correct_template() -> None:
    """Test get_css endpoint renders the correct CSS template."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization.css"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]

    with patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render:
        mock_render.return_value = "/* CSS content */"

        app.get_css()

        # Verify render_to_string was called with correct template
        mock_render.assert_called_once_with("static/utilization/styles.css")


def test_index_handles_empty_providers() -> None:
    """Test index endpoint handles empty providers list correctly."""
    # Create web app instance
    dummy_context = {"method": "GET", "path": "/app/utilization-dashboard"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    app.request = DummyRequest()

    with (
        patch("provider_scheduling.handlers.utilization_web_app.Staff") as mock_staff_class,
        patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render,
    ):
        mock_filter_result = Mock()
        mock_filter_result.distinct.return_value = []
        mock_staff_class.objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>Test</html>"

        app.index()

        # Verify context includes empty providers list
        call_args = mock_render.call_args
        context = call_args[0][1]

        assert context["providers"] == []


def test_index_handles_missing_logged_in_user_header() -> None:
    """Test index endpoint handles missing logged in user header."""
    # Create web app instance without logged in user header
    dummy_context = {"method": "GET", "path": "/app/utilization-dashboard"}
    app = UtilizationWebApp(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    app.request = DummyRequest(headers={})

    with (
        patch("provider_scheduling.handlers.utilization_web_app.Staff") as mock_staff_class,
        patch("provider_scheduling.handlers.utilization_web_app.render_to_string") as mock_render,
    ):
        mock_filter_result = Mock()
        mock_filter_result.distinct.return_value = []
        mock_staff_class.objects.filter.return_value = mock_filter_result

        mock_render.return_value = "<html>Test</html>"

        app.index()

        # Verify context has None for logged in user ID
        call_args = mock_render.call_args
        context = call_args[0][1]

        assert context["loggedInUserId"] is None
