"""Tests for the configuration and component enabling logic."""

import pytest
from unittest.mock import call, patch, MagicMock

from portal_content.shared.config import (
    get_enabled_components,
    is_component_enabled,
    validate_configuration,
    ConfigurationError,
    VALID_COMPONENTS,
    DEFAULT_ENABLED,
    FHIR_REQUIRED_COMPONENTS,
)


class TestGetEnabledComponents:
    """Tests for get_enabled_components function."""

    def test_empty_secret_enables_all(self):
        """Test that empty ENABLED_COMPONENTS secret enables all components."""
        secrets = {"ENABLED_COMPONENTS": ""}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == DEFAULT_ENABLED
            assert mock_log.mock_calls == [call.info("ENABLED_COMPONENTS not configured - all components enabled")]

    def test_missing_secret_enables_all(self):
        """Test that missing ENABLED_COMPONENTS secret enables all components."""
        secrets = {}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == DEFAULT_ENABLED
            assert mock_log.mock_calls == [call.info("ENABLED_COMPONENTS not configured - all components enabled")]

    def test_whitespace_only_enables_all(self):
        """Test that whitespace-only value enables all components."""
        secrets = {"ENABLED_COMPONENTS": "   "}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == DEFAULT_ENABLED
            assert mock_log.mock_calls == [call.info("ENABLED_COMPONENTS not configured - all components enabled")]

    def test_single_component(self):
        """Test enabling a single component."""
        secrets = {"ENABLED_COMPONENTS": "education"}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == {"education"}
            assert mock_log.mock_calls == [call.info("Enabled components: {'education'}")]

    def test_multiple_components(self):
        """Test enabling multiple components."""
        secrets = {"ENABLED_COMPONENTS": "education,labs,imaging"}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == {"education", "labs", "imaging"}
            # Log message will contain the set in some order
            assert len(mock_log.mock_calls) == 1
            assert mock_log.mock_calls[0][0] == "info"

    def test_all_components(self):
        """Test enabling all four components explicitly."""
        secrets = {"ENABLED_COMPONENTS": "education,imaging,labs,visits"}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == VALID_COMPONENTS
            assert len(mock_log.mock_calls) == 1

    def test_whitespace_trimming(self):
        """Test that whitespace around component names is trimmed."""
        secrets = {"ENABLED_COMPONENTS": " education , labs , imaging "}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == {"education", "labs", "imaging"}
            assert len(mock_log.mock_calls) == 1

    def test_case_insensitive(self):
        """Test that component names are case-insensitive."""
        secrets = {"ENABLED_COMPONENTS": "EDUCATION,Labs,IMAGING"}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == {"education", "labs", "imaging"}
            assert len(mock_log.mock_calls) == 1

    def test_invalid_component_ignored(self):
        """Test that invalid component names are ignored."""
        secrets = {"ENABLED_COMPONENTS": "education,invalid,labs"}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == {"education", "labs"}
            # Should have warning for invalid component plus info for enabled
            assert len(mock_log.mock_calls) == 2
            assert mock_log.mock_calls[0] == call.warning("Unknown component 'invalid' in ENABLED_COMPONENTS - ignoring")

    def test_all_invalid_enables_all(self):
        """Test that all invalid components defaults to all enabled."""
        secrets = {"ENABLED_COMPONENTS": "foo,bar,baz"}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == DEFAULT_ENABLED
            # Should have 3 warnings plus 1 warning about enabling all
            assert len(mock_log.mock_calls) == 4
            assert mock_log.mock_calls[3] == call.warning("No valid components in ENABLED_COMPONENTS - enabling all")

    def test_duplicate_components(self):
        """Test that duplicate component names result in single entry."""
        secrets = {"ENABLED_COMPONENTS": "education,education,labs"}

        with patch("portal_content.shared.config.log") as mock_log:
            result = get_enabled_components(secrets)

            assert result == {"education", "labs"}
            assert len(mock_log.mock_calls) == 1


class TestIsComponentEnabled:
    """Tests for is_component_enabled function."""

    def test_component_enabled_when_in_list(self):
        """Test component is enabled when in ENABLED_COMPONENTS."""
        secrets = {"ENABLED_COMPONENTS": "education,labs"}

        with patch("portal_content.shared.config.log"):
            assert is_component_enabled("education", secrets) is True
            assert is_component_enabled("labs", secrets) is True

    def test_component_disabled_when_not_in_list(self):
        """Test component is disabled when not in ENABLED_COMPONENTS."""
        secrets = {"ENABLED_COMPONENTS": "education,labs"}

        with patch("portal_content.shared.config.log"):
            assert is_component_enabled("imaging", secrets) is False
            assert is_component_enabled("visits", secrets) is False

    def test_all_enabled_by_default(self):
        """Test all components enabled when secret is empty."""
        secrets = {}

        with patch("portal_content.shared.config.log"):
            assert is_component_enabled("education", secrets) is True
            assert is_component_enabled("imaging", secrets) is True
            assert is_component_enabled("labs", secrets) is True
            assert is_component_enabled("visits", secrets) is True

    def test_invalid_component_never_enabled(self):
        """Test that invalid component names are never enabled."""
        secrets = {"ENABLED_COMPONENTS": ""}  # All valid enabled

        with patch("portal_content.shared.config.log"):
            assert is_component_enabled("invalid", secrets) is False

    def test_only_visits_enabled(self):
        """Test scenario where only visits is enabled."""
        secrets = {"ENABLED_COMPONENTS": "visits"}

        with patch("portal_content.shared.config.log"):
            assert is_component_enabled("visits", secrets) is True
            assert is_component_enabled("education", secrets) is False
            assert is_component_enabled("imaging", secrets) is False
            assert is_component_enabled("labs", secrets) is False


class TestValidateConfiguration:
    """Tests for validate_configuration function."""

    def test_valid_config_all_components(self):
        """Test validation passes with all components enabled and configured."""
        secrets = {
            "ENABLED_COMPONENTS": "education,imaging,labs,visits",
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
            "NOTE_TYPES": "office-visit,telemedicine",
        }

        with patch("portal_content.shared.config.log") as mock_log:
            # Should not raise
            validate_configuration(secrets)
            # Should log success
            info_calls = [c for c in mock_log.mock_calls if c[0] == "info"]
            assert any("validation passed" in str(c) for c in info_calls)

    def test_valid_config_no_visits(self):
        """Test validation passes when visits disabled (no NOTE_TYPES needed)."""
        secrets = {
            "ENABLED_COMPONENTS": "education,imaging,labs",
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
        }

        with patch("portal_content.shared.config.log"):
            # Should not raise - visits not enabled, so NOTE_TYPES not required
            validate_configuration(secrets)

    def test_visits_enabled_without_note_types_raises(self):
        """Test validation fails when visits enabled but NOTE_TYPES missing."""
        secrets = {
            "ENABLED_COMPONENTS": "visits",
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            assert "visits component is enabled" in str(exc_info.value)
            assert "NOTE_TYPES" in str(exc_info.value)

    def test_visits_enabled_with_empty_note_types_raises(self):
        """Test validation fails when visits enabled but NOTE_TYPES empty."""
        secrets = {
            "ENABLED_COMPONENTS": "visits",
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
            "NOTE_TYPES": "",
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            assert "NOTE_TYPES" in str(exc_info.value)

    def test_visits_enabled_with_whitespace_note_types_raises(self):
        """Test validation fails when visits enabled but NOTE_TYPES is whitespace."""
        secrets = {
            "ENABLED_COMPONENTS": "visits",
            "CLIENT_ID": "test-client-id",
            "CLIENT_SECRET": "test-client-secret",
            "NOTE_TYPES": "   ",
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            assert "NOTE_TYPES" in str(exc_info.value)

    def test_fhir_component_without_client_id_raises(self):
        """Test validation fails when FHIR component enabled but CLIENT_ID missing."""
        secrets = {
            "ENABLED_COMPONENTS": "education",
            "CLIENT_SECRET": "test-client-secret",
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            assert "CLIENT_ID" in str(exc_info.value)
            assert "FHIR API access" in str(exc_info.value)

    def test_fhir_component_without_client_secret_raises(self):
        """Test validation fails when FHIR component enabled but CLIENT_SECRET missing."""
        secrets = {
            "ENABLED_COMPONENTS": "labs",
            "CLIENT_ID": "test-client-id",
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            assert "CLIENT_SECRET" in str(exc_info.value)
            assert "FHIR API access" in str(exc_info.value)

    def test_fhir_component_without_both_credentials_raises(self):
        """Test validation fails when FHIR component enabled but both credentials missing."""
        secrets = {
            "ENABLED_COMPONENTS": "imaging",
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            assert "CLIENT_ID" in str(exc_info.value)
            assert "CLIENT_SECRET" in str(exc_info.value)

    def test_fhir_component_with_empty_credentials_raises(self):
        """Test validation fails when FHIR credentials are empty strings."""
        secrets = {
            "ENABLED_COMPONENTS": "education",
            "CLIENT_ID": "",
            "CLIENT_SECRET": "",
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            assert "CLIENT_ID" in str(exc_info.value)

    def test_default_all_enabled_requires_all_config(self):
        """Test that default (all enabled) requires both FHIR creds and NOTE_TYPES."""
        secrets = {}  # All components enabled by default

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            # Should fail on visits NOTE_TYPES or FHIR creds
            error_msg = str(exc_info.value)
            assert "NOTE_TYPES" in error_msg or "CLIENT_ID" in error_msg

    def test_multiple_fhir_components_same_error(self):
        """Test that multiple FHIR components report together in error."""
        secrets = {
            "ENABLED_COMPONENTS": "education,imaging,labs",
            # Missing both CLIENT_ID and CLIENT_SECRET
        }

        with patch("portal_content.shared.config.log"):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(secrets)

            # Error should mention the FHIR components
            error_msg = str(exc_info.value)
            assert "FHIR API access" in error_msg
