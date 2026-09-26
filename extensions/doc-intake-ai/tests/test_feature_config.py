"""Tests for _is_enabled helper and FeatureConfig.from_secrets."""

import pytest

from doc_intake_ai.models import FeatureConfig, _is_enabled


class TestIsEnabled:
    """_is_enabled returns True only for the string 'true' (case-insensitive)."""

    def test_true_lowercase(self) -> None:
        assert _is_enabled("true") is True

    def test_true_uppercase(self) -> None:
        assert _is_enabled("TRUE") is True

    def test_true_mixed_case(self) -> None:
        assert _is_enabled("True") is True
        assert _is_enabled("tRuE") is True

    def test_true_with_whitespace(self) -> None:
        assert _is_enabled("  true  ") is True

    def test_false_string(self) -> None:
        assert _is_enabled("false") is False

    def test_empty_string(self) -> None:
        assert _is_enabled("") is False

    def test_none_value(self) -> None:
        assert _is_enabled(None) is False

    def test_whitespace_only(self) -> None:
        assert _is_enabled("   ") is False

    def test_arbitrary_strings(self) -> None:
        assert _is_enabled("yes") is False
        assert _is_enabled("1") is False
        assert _is_enabled("on") is False
        assert _is_enabled("enabled") is False


class TestFeatureConfigDefaults:
    """Capability fields default to False, fax channel defaults to True."""

    def test_capability_defaults_false(self) -> None:
        config = FeatureConfig()
        assert config.classify is False
        assert config.match_patient is False
        assert config.assign_reviewer is False
        assert config.prefill_templates is False

    def test_channel_fax_defaults_true(self) -> None:
        config = FeatureConfig()
        assert config.channel_fax is True

    def test_non_fax_channels_default_false(self) -> None:
        config = FeatureConfig()
        assert config.channel_document_upload is False
        assert config.channel_integration_engine is False
        assert config.channel_patient_portal is False


class TestFeatureConfigFromSecrets:
    """from_secrets builds config from individual ENABLE_* secret values."""

    def test_all_enabled(self) -> None:
        secrets: dict[str, str | None] = {
            "ENABLE_CLASSIFY": "true",
            "ENABLE_MATCH_PATIENT": "true",
            "ENABLE_ASSIGN_REVIEWER": "true",
            "ENABLE_PREFILL_TEMPLATES": "true",
            "ENABLE_CHANNEL_FAX": "true",
            "ENABLE_CHANNEL_DOCUMENT_UPLOAD": "true",
            "ENABLE_CHANNEL_INTEGRATION_ENGINE": "true",
            "ENABLE_CHANNEL_PATIENT_PORTAL": "true",
        }
        config = FeatureConfig.from_secrets(secrets)
        assert config.classify is True
        assert config.match_patient is True
        assert config.assign_reviewer is True
        assert config.prefill_templates is True
        assert config.channel_fax is True
        assert config.channel_document_upload is True
        assert config.channel_integration_engine is True
        assert config.channel_patient_portal is True

    def test_all_disabled_empty_dict(self) -> None:
        config = FeatureConfig.from_secrets({})
        assert config.classify is False
        assert config.match_patient is False
        assert config.assign_reviewer is False
        assert config.prefill_templates is False
        assert config.channel_fax is True
        assert config.channel_document_upload is False
        assert config.channel_integration_engine is False
        assert config.channel_patient_portal is False

    def test_all_disabled_missing_keys(self) -> None:
        secrets: dict[str, str | None] = {"EXTEND_API_KEY": "test-key"}
        config = FeatureConfig.from_secrets(secrets)
        assert config.classify is False
        assert config.match_patient is False
        assert config.assign_reviewer is False
        assert config.prefill_templates is False
        assert config.channel_fax is True
        assert config.channel_document_upload is False
        assert config.channel_integration_engine is False
        assert config.channel_patient_portal is False

    def test_single_toggle_enabled(self) -> None:
        secrets: dict[str, str | None] = {"ENABLE_CLASSIFY": "true"}
        config = FeatureConfig.from_secrets(secrets)
        assert config.classify is True
        assert config.match_patient is False
        assert config.assign_reviewer is False
        assert config.prefill_templates is False

    def test_mixed_values(self) -> None:
        secrets: dict[str, str | None] = {
            "ENABLE_CLASSIFY": "false",
            "ENABLE_MATCH_PATIENT": "true",
            "ENABLE_ASSIGN_REVIEWER": "",
            "ENABLE_PREFILL_TEMPLATES": "true",
        }
        config = FeatureConfig.from_secrets(secrets)
        assert config.classify is False
        assert config.match_patient is True
        assert config.assign_reviewer is False
        assert config.prefill_templates is True

    def test_case_insensitivity_across_fields(self) -> None:
        secrets: dict[str, str | None] = {
            "ENABLE_CLASSIFY": "TRUE",
            "ENABLE_MATCH_PATIENT": "True",
            "ENABLE_ASSIGN_REVIEWER": "true",
            "ENABLE_PREFILL_TEMPLATES": "tRuE",
        }
        config = FeatureConfig.from_secrets(secrets)
        assert config.classify is True
        assert config.match_patient is True
        assert config.assign_reviewer is True
        assert config.prefill_templates is True

    def test_brigade_customer_config(self) -> None:
        """Patient matching only, as discussed in the source meeting."""
        secrets: dict[str, str | None] = {"ENABLE_MATCH_PATIENT": "true"}
        config = FeatureConfig.from_secrets(secrets)
        assert config.classify is False
        assert config.match_patient is True
        assert config.assign_reviewer is False
        assert config.prefill_templates is False

    def test_single_channel_enabled(self) -> None:
        secrets: dict[str, str | None] = {"ENABLE_CHANNEL_DOCUMENT_UPLOAD": "true"}
        config = FeatureConfig.from_secrets(secrets)
        assert config.channel_document_upload is True
        assert config.channel_integration_engine is False
        assert config.channel_patient_portal is False
        assert config.channel_fax is True

    def test_fax_default_true_when_secret_empty(self) -> None:
        """Canvas creates all manifest secrets as empty strings on install."""
        secrets: dict[str, str | None] = {"ENABLE_CHANNEL_FAX": ""}
        config = FeatureConfig.from_secrets(secrets)
        assert config.channel_fax is True

    def test_fax_default_true_when_secret_missing(self) -> None:
        config = FeatureConfig.from_secrets({})
        assert config.channel_fax is True

    def test_fax_explicitly_disabled(self) -> None:
        secrets: dict[str, str | None] = {"ENABLE_CHANNEL_FAX": "false"}
        config = FeatureConfig.from_secrets(secrets)
        assert config.channel_fax is False

    def test_fax_explicitly_enabled(self) -> None:
        secrets: dict[str, str | None] = {"ENABLE_CHANNEL_FAX": "true"}
        config = FeatureConfig.from_secrets(secrets)
        assert config.channel_fax is True

    def test_all_channels_and_capabilities_enabled(self) -> None:
        secrets: dict[str, str | None] = {
            "ENABLE_CLASSIFY": "true",
            "ENABLE_MATCH_PATIENT": "true",
            "ENABLE_ASSIGN_REVIEWER": "true",
            "ENABLE_PREFILL_TEMPLATES": "true",
            "ENABLE_CHANNEL_FAX": "true",
            "ENABLE_CHANNEL_DOCUMENT_UPLOAD": "true",
            "ENABLE_CHANNEL_INTEGRATION_ENGINE": "true",
            "ENABLE_CHANNEL_PATIENT_PORTAL": "true",
        }
        config = FeatureConfig.from_secrets(secrets)
        assert config.channel_fax is True
        assert config.channel_document_upload is True
        assert config.channel_integration_engine is True
        assert config.channel_patient_portal is True


class TestIsChannelEnabled:
    """is_channel_enabled maps raw channel strings to config fields."""

    def test_fax_enabled_by_default(self) -> None:
        config = FeatureConfig()
        assert config.is_channel_enabled("FAX") is True

    def test_document_upload_disabled_by_default(self) -> None:
        config = FeatureConfig()
        assert config.is_channel_enabled("DOCUMENT_UPLOAD") is False

    def test_integration_engine_disabled_by_default(self) -> None:
        config = FeatureConfig()
        assert config.is_channel_enabled("FROM_INTEGRATION_ENGINE") is False

    def test_patient_portal_disabled_by_default(self) -> None:
        config = FeatureConfig()
        assert config.is_channel_enabled("FROM_PATIENT_PORTAL") is False

    def test_unknown_channel_returns_true(self) -> None:
        config = FeatureConfig()
        assert config.is_channel_enabled("SOMETHING_NEW") is True

    def test_empty_channel_returns_true(self) -> None:
        config = FeatureConfig()
        assert config.is_channel_enabled("") is True

    def test_case_insensitive(self) -> None:
        config = FeatureConfig()
        assert config.is_channel_enabled("fax") is True
        assert config.is_channel_enabled("document_upload") is False

    def test_channel_enabled_after_toggle(self) -> None:
        config = FeatureConfig(channel_document_upload=True)
        assert config.is_channel_enabled("DOCUMENT_UPLOAD") is True
