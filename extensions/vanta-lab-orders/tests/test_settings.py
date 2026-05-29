"""Tests for vanta_lab_orders.settings accessors."""

from __future__ import annotations

import json

import pytest

from tests.conftest import LOCATION_UUID_1, LOCATION_UUID_2
from vanta_lab_orders import settings as settings_module
from vanta_lab_orders.settings import (
    account_number_for_location,
    lkcareevolve_api_key,
    lkcareevolve_base_url,
    location_to_account_map,
    sending_facility_name,
    vanta_lab_partner_name,
)


@pytest.fixture(autouse=True)
def _disable_secrets_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the local-dev fallback never leaks into these tests.

    A developer may have a real secrets_local.py in their tree; without this,
    the 'missing'/'empty' assertions would pick up those values and fail.
    """
    monkeypatch.setattr(settings_module, "_secrets_local", None)


def test_lkcareevolve_base_url_strips_trailing_slash(secrets: dict) -> None:
    secrets["LKCAREEVOLVE_BASE_URL"] = "https://api.example.com/"
    assert lkcareevolve_base_url(secrets) == "https://api.example.com"


def test_lkcareevolve_base_url_missing_raises() -> None:
    # With the secrets_local fallback, a missing key is treated the same as an
    # empty value: no source supplies it, so it raises ValueError ("is empty").
    with pytest.raises(ValueError, match="LKCAREEVOLVE_BASE_URL is empty"):
        lkcareevolve_base_url({})


def test_lkcareevolve_base_url_empty_raises(secrets: dict) -> None:
    secrets["LKCAREEVOLVE_BASE_URL"] = ""
    with pytest.raises(ValueError, match="LKCAREEVOLVE_BASE_URL is empty"):
        lkcareevolve_base_url(secrets)


def test_lkcareevolve_base_url_rejects_http_scheme(secrets: dict) -> None:
    """Plaintext http:// is rejected so the bearer token can't leak in cleartext."""
    secrets["LKCAREEVOLVE_BASE_URL"] = "http://api.example.com"
    with pytest.raises(ValueError, match="must use https://"):
        lkcareevolve_base_url(secrets)


def test_lkcareevolve_base_url_rejects_bare_hostname(secrets: dict) -> None:
    """A scheme-less hostname is also rejected."""
    secrets["LKCAREEVOLVE_BASE_URL"] = "api.example.com"
    with pytest.raises(ValueError, match="must use https://"):
        lkcareevolve_base_url(secrets)


def test_lkcareevolve_api_key_returns_value(secrets: dict) -> None:
    assert lkcareevolve_api_key(secrets) == "test-api-key-abc123"


def test_lkcareevolve_api_key_empty_raises(secrets: dict) -> None:
    secrets["LKCAREEVOLVE_API_KEY"] = ""
    with pytest.raises(ValueError, match="LKCAREEVOLVE_API_KEY is empty"):
        lkcareevolve_api_key(secrets)


def test_vanta_lab_partner_name_returns_value(secrets: dict) -> None:
    assert vanta_lab_partner_name(secrets) == "Vanta Diagnostics"


def test_vanta_lab_partner_name_empty_raises(secrets: dict) -> None:
    secrets["VANTA_LAB_PARTNER_NAME"] = ""
    with pytest.raises(ValueError, match="VANTA_LAB_PARTNER_NAME is empty"):
        vanta_lab_partner_name(secrets)


def test_sending_facility_name_returns_value(secrets: dict) -> None:
    assert sending_facility_name(secrets) == "Example Facility"


def test_sending_facility_name_empty_raises(secrets: dict) -> None:
    secrets["SENDING_FACILITY_NAME"] = ""
    with pytest.raises(ValueError, match="SENDING_FACILITY_NAME is empty"):
        sending_facility_name(secrets)


def test_location_to_account_map_parses_json(secrets: dict) -> None:
    mapping = location_to_account_map(secrets)
    assert mapping == {LOCATION_UUID_1: "ACCT-001", LOCATION_UUID_2: "ACCT-002"}


def test_location_to_account_map_invalid_json_raises(secrets: dict) -> None:
    secrets["LOCATION_TO_ACCOUNT_MAP_JSON"] = "not-json"
    with pytest.raises(ValueError, match="not valid JSON"):
        location_to_account_map(secrets)


def test_location_to_account_map_non_dict_raises(secrets: dict) -> None:
    secrets["LOCATION_TO_ACCOUNT_MAP_JSON"] = json.dumps([1, 2, 3])
    with pytest.raises(ValueError, match="must be a JSON object"):
        location_to_account_map(secrets)


def test_location_to_account_map_empty_string_raises(secrets: dict) -> None:
    secrets["LOCATION_TO_ACCOUNT_MAP_JSON"] = ""
    with pytest.raises(ValueError, match="LOCATION_TO_ACCOUNT_MAP_JSON is empty"):
        location_to_account_map(secrets)


def test_account_number_for_location_found(secrets: dict) -> None:
    assert account_number_for_location(LOCATION_UUID_1, secrets) == "ACCT-001"


def test_account_number_for_location_missing_raises(secrets: dict) -> None:
    with pytest.raises(KeyError, match="No LKCareEvolve account number configured"):
        account_number_for_location("unknown-loc", secrets)
