"""Tests for the plugin secrets parser."""

from __future__ import annotations

import json

import pytest

from salesforce_to_canvas_integration.services.config import (
    DEFAULT_FIELD_MAPPING,
    ConfigError,
    load_config,
)


def base_secrets() -> dict[str, str]:
    return {
        "SF_CLIENT_ID": "cid",
        "SF_CLIENT_SECRET": "csecret",
        "SF_LOGIN_URL": "https://login.salesforce.com/",
        "SF_WEBHOOK_SECRET": "shhh",
        "SF_ADMIN_STAFF_IDS": "staff-1, staff-2",
    }


def test_load_config_uses_defaults() -> None:
    config = load_config(base_secrets())

    assert config.client_id == "cid"
    assert config.login_url == "https://login.salesforce.com"  # trailing slash stripped
    assert config.admin_staff_ids == {"staff-1", "staff-2"}
    assert config.source_sobject == "Contact"
    assert config.field_mapping == DEFAULT_FIELD_MAPPING


def test_load_config_parses_custom_mapping() -> None:
    custom_map = {
        "FirstName": {"target": "first_name"},
        "Health_Cloud_MRN__c": {"target": "metadata.mrn"},
    }
    secrets = base_secrets() | {"SF_FIELD_MAPPING_JSON": json.dumps(custom_map)}

    config = load_config(secrets)

    assert config.field_mapping["FirstName"]["target"] == "first_name"
    assert config.field_mapping["Health_Cloud_MRN__c"]["target"] == "metadata.mrn"


def test_load_config_rejects_malformed_mapping() -> None:
    secrets = base_secrets() | {"SF_FIELD_MAPPING_JSON": json.dumps({"FirstName": "first_name"})}
    with pytest.raises(ConfigError):
        load_config(secrets)


@pytest.mark.parametrize("missing", ["SF_CLIENT_ID", "SF_WEBHOOK_SECRET", "SF_ADMIN_STAFF_IDS"])
def test_load_config_fails_closed_on_missing_required(missing: str) -> None:
    secrets = base_secrets()
    secrets[missing] = ""
    with pytest.raises(ConfigError):
        load_config(secrets)


def test_canvas_instance_url_defaults_to_empty_when_unset() -> None:
    config = load_config(base_secrets())
    assert config.canvas_instance_url == ""


def test_canvas_instance_url_is_stripped_and_trailing_slash_removed() -> None:
    # The token host override is normalized the same way as the other urls. See
    # journal cnv-928/002.
    secrets = base_secrets() | {"CANVAS_INSTANCE_URL": "  http://localhost:8000/  "}
    config = load_config(secrets)
    assert config.canvas_instance_url == "http://localhost:8000"
