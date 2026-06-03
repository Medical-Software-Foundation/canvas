from unittest.mock import MagicMock, patch

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.v1.data.staff import Staff

from open_availability.applications.provision_availability import (
    ACCESS_DENIED_HTML,
    API_KEY_PLACEHOLDER,
    PROVISION_HTML_TEMPLATE,
    ProvisionAvailabilityApp,
    get_admin_users,
    is_user_authorized,
)


class TestGetAdminUsers:
    """Tests for the get_admin_users helper."""

    def test_parses_comma_separated_names(self) -> None:
        secrets = {"ADMIN_USERS": "Jane Smith, John Doe"}
        result = get_admin_users(secrets)
        assert result == {"jane smith", "john doe"}

    def test_lowercases_and_strips(self) -> None:
        secrets = {"ADMIN_USERS": "  JANE SMITH , John DOE  "}
        result = get_admin_users(secrets)
        assert result == {"jane smith", "john doe"}

    def test_empty_string_returns_empty_set(self) -> None:
        secrets = {"ADMIN_USERS": ""}
        result = get_admin_users(secrets)
        assert result == set()

    def test_missing_key_returns_empty_set(self) -> None:
        secrets: dict[str, str] = {}
        result = get_admin_users(secrets)
        assert result == set()

    def test_single_name(self) -> None:
        secrets = {"ADMIN_USERS": "Jane Smith"}
        result = get_admin_users(secrets)
        assert result == {"jane smith"}


class TestIsUserAuthorized:
    """Tests for the is_user_authorized helper."""

    def test_authorized_when_name_matches(self) -> None:
        mock_staff = MagicMock()
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Smith"

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.return_value = mock_staff
            result = is_user_authorized("user-123", {"jane smith"})
            assert result is True

    def test_not_authorized_when_name_not_in_set(self) -> None:
        mock_staff = MagicMock()
        mock_staff.first_name = "Bob"
        mock_staff.last_name = "Jones"

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.return_value = mock_staff
            result = is_user_authorized("user-123", {"jane smith"})
            assert result is False

    def test_case_insensitive_matching(self) -> None:
        mock_staff = MagicMock()
        mock_staff.first_name = "JANE"
        mock_staff.last_name = "SMITH"

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.return_value = mock_staff
            result = is_user_authorized("user-123", {"jane smith"})
            assert result is True

    def test_staff_not_found_returns_false(self) -> None:
        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.side_effect = Staff.DoesNotExist
            result = is_user_authorized("user-123", {"jane smith"})
            assert result is False


class TestProvisionAvailabilityApp:
    """Tests for the admin provisioning application."""

    def _make_app(
        self,
        secrets: dict[str, str],
        user_id: str = "user-123",
    ) -> ProvisionAvailabilityApp:
        mock_event = MagicMock()
        mock_event.type = "APPLICATION__ON_OPEN"
        mock_event.context = {"user": {"id": user_id}}
        app = ProvisionAvailabilityApp(event=mock_event)
        app.secrets = secrets
        return app

    def test_access_denied_when_admin_users_empty(self) -> None:
        """Empty ADMIN_USERS secret should deny all access."""
        app = self._make_app(secrets={"ADMIN_USERS": "", "simpleapi-api-key": "key"})

        with patch.object(LaunchModalEffect, "__init__", return_value=None) as mock_init:
            with patch.object(LaunchModalEffect, "apply", return_value=MagicMock()):
                app.on_open()
                html_content = mock_init.call_args.kwargs["content"]
                assert "Access Denied" in html_content

    def test_access_denied_when_admin_users_missing(self) -> None:
        """Missing ADMIN_USERS secret should deny all access."""
        app = self._make_app(secrets={"simpleapi-api-key": "key"})

        with patch.object(LaunchModalEffect, "__init__", return_value=None) as mock_init:
            with patch.object(LaunchModalEffect, "apply", return_value=MagicMock()):
                app.on_open()
                html_content = mock_init.call_args.kwargs["content"]
                assert "Access Denied" in html_content

    def test_access_denied_when_user_not_in_admin_users(self) -> None:
        """User not in ADMIN_USERS should see access denied."""
        app = self._make_app(
            secrets={"ADMIN_USERS": "Jane Smith", "simpleapi-api-key": "key"},
            user_id="user-456",
        )

        mock_staff = MagicMock()
        mock_staff.first_name = "Bob"
        mock_staff.last_name = "Jones"

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.return_value = mock_staff
            with patch.object(LaunchModalEffect, "__init__", return_value=None) as mock_init:
                with patch.object(LaunchModalEffect, "apply", return_value=MagicMock()):
                    app.on_open()
                    html_content = mock_init.call_args.kwargs["content"]
                    assert "Access Denied" in html_content

    def test_access_denied_when_staff_not_found(self) -> None:
        """Staff not found should return access denied."""
        app = self._make_app(
            secrets={"ADMIN_USERS": "Jane Smith", "simpleapi-api-key": "key"},
            user_id="nonexistent-user",
        )

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.side_effect = Staff.DoesNotExist
            with patch.object(LaunchModalEffect, "__init__", return_value=None) as mock_init:
                with patch.object(LaunchModalEffect, "apply", return_value=MagicMock()):
                    app.on_open()
                    html_content = mock_init.call_args.kwargs["content"]
                    assert "Access Denied" in html_content

    def test_access_granted_when_user_in_admin_users(self) -> None:
        """Authorized user should see the provisioning UI."""
        app = self._make_app(
            secrets={"ADMIN_USERS": "Jane Smith", "simpleapi-api-key": "test-key-123"},
            user_id="user-123",
        )

        mock_staff = MagicMock()
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Smith"

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.return_value = mock_staff
            with patch.object(LaunchModalEffect, "__init__", return_value=None) as mock_init:
                with patch.object(LaunchModalEffect, "apply", return_value=MagicMock()):
                    app.on_open()
                    html_content = mock_init.call_args.kwargs["content"]
                    assert "Run Provisioning" in html_content
                    assert "test-key-123" in html_content
                    assert API_KEY_PLACEHOLDER not in html_content

    def test_access_granted_case_insensitive(self) -> None:
        """Name matching should be case-insensitive."""
        app = self._make_app(
            secrets={"ADMIN_USERS": "jane smith", "simpleapi-api-key": "key"},
            user_id="user-123",
        )

        mock_staff = MagicMock()
        mock_staff.first_name = "JANE"
        mock_staff.last_name = "SMITH"

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.return_value = mock_staff
            with patch.object(LaunchModalEffect, "__init__", return_value=None) as mock_init:
                with patch.object(LaunchModalEffect, "apply", return_value=MagicMock()):
                    app.on_open()
                    html_content = mock_init.call_args.kwargs["content"]
                    assert "Run Provisioning" in html_content

    def test_on_open_returns_effect(self) -> None:
        """Verify on_open returns an effect for authorized users."""
        app = self._make_app(
            secrets={"ADMIN_USERS": "Jane Smith", "simpleapi-api-key": "test-key-123"},
            user_id="user-123",
        )

        mock_staff = MagicMock()
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Smith"

        with patch(
            "open_availability.applications.provision_availability.Staff.objects"
        ) as mock_objects:
            mock_objects.get.return_value = mock_staff
            result = app.on_open()
            assert result is not None

    def test_provision_html_template_contains_run_button(self) -> None:
        """Verify the HTML template contains the provisioning button."""
        assert "Run Provisioning" in PROVISION_HTML_TEMPLATE
        assert "runProvisioning" in PROVISION_HTML_TEMPLATE

    def test_provision_html_template_calls_correct_api_endpoint(self) -> None:
        """Verify the HTML calls the correct SimpleAPI endpoint."""
        assert "/plugin-io/api/open_availability/provision-availability/" in PROVISION_HTML_TEMPLATE

    def test_provision_html_template_sends_authorization_header(self) -> None:
        """Verify the HTML includes the Authorization header in the fetch call."""
        assert "'Authorization'" in PROVISION_HTML_TEMPLATE

    def test_access_denied_html_contains_message(self) -> None:
        """Verify the access denied HTML has the expected content."""
        assert "Access Denied" in ACCESS_DENIED_HTML
        assert "not authorized" in ACCESS_DENIED_HTML
