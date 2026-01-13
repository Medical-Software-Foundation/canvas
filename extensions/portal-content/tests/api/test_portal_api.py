"""Tests for the combined portal content API handler."""

import pytest
from http import HTTPStatus
from unittest.mock import call, patch, MagicMock

from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from portal_content.api.portal_api import PortalContentAPI
from portal_content.shared.fhir_client import FHIRClient
from portal_content.shared.config import ConfigurationError


# Helper to create valid secrets for tests
def valid_secrets(overrides=None):
    """Create valid secrets dict with optional overrides."""
    secrets = {
        "ENABLED_COMPONENTS": "education",  # Single non-visits component
        "CLIENT_ID": "test-client-id",
        "CLIENT_SECRET": "test-client-secret",
    }
    if overrides:
        secrets.update(overrides)
    return secrets


class TestPatientSessionAuthMixin:
    """Tests verifying PatientSessionAuthMixin behavior."""

    def test_authenticate_succeeds_for_patient_user(self):
        """Test authentication succeeds for patient users via mixin."""
        mock_self = MagicMock()
        mock_self.secrets = valid_secrets()

        credentials = MagicMock()
        credentials.logged_in_user = {"id": "patient-123", "type": "Patient"}

        # The mixin's authenticate returns True for patients
        result = PortalContentAPI.authenticate(mock_self, credentials)
        assert result is True

    def test_authenticate_raises_for_staff_user(self):
        """Test authentication raises InvalidCredentialsError for staff users."""
        mock_self = MagicMock()
        mock_self.secrets = valid_secrets()

        credentials = MagicMock()
        credentials.logged_in_user = {"id": "staff-456", "type": "Staff"}

        # The mixin raises InvalidCredentialsError for non-patients
        with pytest.raises(InvalidCredentialsError):
            PortalContentAPI.authenticate(mock_self, credentials)

    def test_authenticate_raises_for_no_user(self):
        """Test authentication raises when no user is logged in."""
        mock_self = MagicMock()
        mock_self.secrets = valid_secrets()

        credentials = MagicMock()
        credentials.logged_in_user = None

        # The mixin raises for missing user
        with pytest.raises((InvalidCredentialsError, TypeError, KeyError)):
            PortalContentAPI.authenticate(mock_self, credentials)


class TestValidateConfig:
    """Tests for _validate_config method."""

    def test_returns_none_for_valid_config(self):
        """Test _validate_config returns None for valid configuration."""
        mock_self = MagicMock()
        mock_self.secrets = valid_secrets()

        with patch("portal_content.api.portal_api.validate_configuration"):
            result = PortalContentAPI._validate_config(mock_self)

        assert result is None

    def test_returns_error_response_for_invalid_config(self):
        """Test _validate_config returns error response for invalid configuration."""
        mock_self = MagicMock()
        mock_self.secrets = {}

        with patch("portal_content.api.portal_api.log"):
            with patch("portal_content.api.portal_api.validate_configuration") as mock_validate:
                mock_validate.side_effect = ConfigurationError("Missing CLIENT_ID")
                result = PortalContentAPI._validate_config(mock_self)

        assert result is not None
        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_returns_error_for_visits_without_note_types(self):
        """Test _validate_config returns error when visits enabled but NOTE_TYPES missing."""
        mock_self = MagicMock()
        mock_self.secrets = {
            "ENABLED_COMPONENTS": "visits",
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
            # NOTE_TYPES missing
        }

        with patch("portal_content.api.portal_api.log"):
            # Let validation run with real implementation
            result = PortalContentAPI._validate_config(mock_self)

        assert result is not None
        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_returns_error_for_fhir_component_without_credentials(self):
        """Test _validate_config returns error when FHIR component enabled without credentials."""
        mock_self = MagicMock()
        mock_self.secrets = {
            "ENABLED_COMPONENTS": "education",
            # CLIENT_ID and CLIENT_SECRET missing
        }

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI._validate_config(mock_self)

        assert result is not None
        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestPortalContentAPIFHIRToken:
    """Tests for _get_fhir_token method."""

    def test_get_fhir_token_success(self):
        """Test successful FHIR token retrieval."""
        mock_self = MagicMock()
        mock_self.secrets = {
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
        }
        mock_self.environment = {"CUSTOMER_IDENTIFIER": "test-sandbox"}

        with patch("portal_content.api.portal_api.requests.post") as mock_post:
            with patch("portal_content.api.portal_api.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"access_token": "test-token-12345"}
                mock_post.return_value = mock_response

                token = PortalContentAPI._get_fhir_token(mock_self, "patient-123")

        assert token == "test-token-12345"
        mock_post.assert_called_once_with(
            "https://test-sandbox.canvasmedical.com/auth/token/",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
                "patient": "patient-123",
                "scope": "patient/DiagnosticReport.read patient/DocumentReference.read",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_get_fhir_token_missing_client_id(self):
        """Test token retrieval fails when CLIENT_ID is missing."""
        mock_self = MagicMock()
        mock_self.secrets = {"CLIENT_SECRET": "test-client-secret"}
        mock_self.environment = {"CUSTOMER_IDENTIFIER": "test-sandbox"}

        with patch("portal_content.api.portal_api.log") as mock_log:
            token = PortalContentAPI._get_fhir_token(mock_self, "patient-123")

        assert token is None
        error_calls = [c for c in mock_log.mock_calls if c[0] == "error"]
        assert len(error_calls) >= 1

    def test_get_fhir_token_missing_client_secret(self):
        """Test token retrieval fails when CLIENT_SECRET is missing."""
        mock_self = MagicMock()
        mock_self.secrets = {"CLIENT_ID": "test-client-id"}
        mock_self.environment = {"CUSTOMER_IDENTIFIER": "test-sandbox"}

        with patch("portal_content.api.portal_api.log"):
            token = PortalContentAPI._get_fhir_token(mock_self, "patient-123")

        assert token is None

    def test_get_fhir_token_api_error(self):
        """Test token retrieval handles API errors."""
        mock_self = MagicMock()
        mock_self.secrets = {
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
        }
        mock_self.environment = {"CUSTOMER_IDENTIFIER": "test-sandbox"}

        with patch("portal_content.api.portal_api.requests.post") as mock_post:
            with patch("portal_content.api.portal_api.log"):
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_response.text = "Unauthorized"
                mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
                mock_post.return_value = mock_response

                token = PortalContentAPI._get_fhir_token(mock_self, "patient-123")

        assert token is None


class TestPortalContentAPIFHIRClient:
    """Tests for _get_fhir_client method."""

    def test_get_fhir_client_success(self):
        """Test successful FHIR client creation."""
        mock_self = MagicMock()
        mock_self.secrets = {
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
        }
        mock_self.environment = {"CUSTOMER_IDENTIFIER": "test-sandbox"}
        # Mock _get_fhir_token on the mock_self instance to return a token
        mock_self._get_fhir_token.return_value = "test-token-12345"

        with patch("portal_content.api.portal_api.log"):
            client = PortalContentAPI._get_fhir_client(mock_self, "patient-123")

        assert client is not None
        assert isinstance(client, FHIRClient)
        assert client.token == "test-token-12345"
        assert "fumage-test-sandbox" in client.base_url

    def test_get_fhir_client_token_failure(self):
        """Test FHIR client creation fails when token retrieval fails."""
        mock_self = MagicMock()
        mock_self.secrets = {}
        mock_self.environment = {"CUSTOMER_IDENTIFIER": "test-sandbox"}
        # Mock _get_fhir_token on the mock_self instance to return None
        mock_self._get_fhir_token.return_value = None

        with patch("portal_content.api.portal_api.log"):
            client = PortalContentAPI._get_fhir_client(mock_self, "patient-123")

        assert client is None


class TestPortalContentAPIComponentEnabling:
    """Tests for component enabling/disabling in endpoint methods."""

    def test_education_endpoint_disabled(self):
        """Test education endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "labs,imaging"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.serve_education_portal(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_imaging_endpoint_disabled(self):
        """Test imaging endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "education,labs"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.serve_imaging_portal(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_labs_endpoint_disabled(self):
        """Test labs endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "education,imaging"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.serve_labs_portal(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_visits_endpoint_disabled(self):
        """Test visits endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "education,imaging,labs"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.serve_visits_portal(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_education_endpoint_enabled(self):
        """Test education endpoint works when enabled."""
        mock_self = MagicMock()
        mock_self.secrets = {}  # All enabled by default
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None

        with patch("portal_content.api.portal_api.education_serve_portal") as mock_serve:
            with patch("portal_content.api.portal_api.log"):
                mock_serve.return_value = [MagicMock()]
                result = PortalContentAPI.serve_education_portal(mock_self)

        mock_serve.assert_called_once_with(mock_self)

    def test_endpoint_returns_config_error(self):
        """Test endpoint returns error when config validation fails."""
        mock_self = MagicMock()
        mock_self.secrets = {}
        error_response = [MagicMock(status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]
        mock_self._validate_config.return_value = error_response

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.serve_education_portal(mock_self)

        assert result == error_response


class TestPortalContentAPIReportsEndpoints:
    """Tests for reports/notes endpoint methods."""

    def test_education_reports_disabled(self):
        """Test education reports endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "labs"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.handle_education_reports(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_education_reports_enabled(self):
        """Test education reports endpoint calls handler when enabled."""
        mock_self = MagicMock()
        mock_self.secrets = {}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None

        with patch("portal_content.api.portal_api.education_handle_reports") as mock_handler:
            with patch("portal_content.api.portal_api.log"):
                mock_handler.return_value = [MagicMock()]
                result = PortalContentAPI.handle_education_reports(mock_self)

        mock_handler.assert_called_once_with(mock_self)

    def test_visits_notes_disabled(self):
        """Test visits notes endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "labs"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.handle_visits_notes(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN


class TestPortalContentAPIPDFEndpoints:
    """Tests for PDF proxy endpoint methods."""

    def test_education_pdf_disabled(self):
        """Test education PDF endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "labs"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.proxy_education_pdf(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_education_pdf_enabled(self):
        """Test education PDF endpoint calls handler when enabled."""
        mock_self = MagicMock()
        mock_self.secrets = {}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None

        with patch("portal_content.api.portal_api.education_proxy_pdf") as mock_handler:
            with patch("portal_content.api.portal_api.log"):
                mock_handler.return_value = [MagicMock()]
                result = PortalContentAPI.proxy_education_pdf(mock_self)

        mock_handler.assert_called_once_with(mock_self)

    def test_imaging_pdf_disabled(self):
        """Test imaging PDF endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "labs"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.proxy_imaging_pdf(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_labs_pdf_disabled(self):
        """Test labs PDF endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "education"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.proxy_labs_pdf(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_visits_pdf_disabled(self):
        """Test visits PDF endpoint returns 403 when disabled."""
        mock_self = MagicMock()
        mock_self.secrets = {"ENABLED_COMPONENTS": "education"}
        mock_self.request.headers.get.return_value = "patient-123"
        mock_self._validate_config.return_value = None
        mock_self._disabled_response = lambda component: PortalContentAPI._disabled_response(mock_self, component)

        with patch("portal_content.api.portal_api.log"):
            result = PortalContentAPI.proxy_visits_pdf(mock_self)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN


class TestDisabledResponse:
    """Tests for _disabled_response method."""

    def test_returns_forbidden_with_message(self):
        """Test that disabled response returns 403 with message."""
        mock_self = MagicMock()

        result = PortalContentAPI._disabled_response(mock_self, "education")

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN
