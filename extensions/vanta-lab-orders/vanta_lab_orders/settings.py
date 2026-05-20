"""Secret accessors and configuration helpers for vanta_lab_orders.

All accessors raise loudly on missing or malformed values — no defaults.
"""

from __future__ import annotations

import json
from typing import Any


def lkcareevolve_base_url(secrets: dict[str, Any]) -> str:
    """Return the LKCareEvolve base URL (e.g. 'https://api.lkcareevolve.ellkay.com').

    Refuses to return a non-https URL so a misconfigured secret can't cause
    the bearer token to traverse the network in cleartext.
    """
    value: str = secrets["LKCAREEVOLVE_BASE_URL"]
    if not value:
        raise ValueError("Secret LKCAREEVOLVE_BASE_URL is empty")
    if not value.startswith("https://"):
        raise ValueError(
            "LKCAREEVOLVE_BASE_URL must use https:// — the bearer token "
            "must not be sent over an unencrypted connection."
        )
    return value.rstrip("/")


def lkcareevolve_api_key(secrets: dict[str, Any]) -> str:
    """Return the bearer token issued by ELLKAY."""
    value: str = secrets["LKCAREEVOLVE_API_KEY"]
    if not value:
        raise ValueError("Secret LKCAREEVOLVE_API_KEY is empty")
    return value


def vanta_lab_partner_name(secrets: dict[str, Any]) -> str:
    """Return the exact LabPartner.name string for the Vanta/Vanta partner."""
    value: str = secrets["VANTA_LAB_PARTNER_NAME"]
    if not value:
        raise ValueError("Secret VANTA_LAB_PARTNER_NAME is empty")
    return value


def location_to_account_map(secrets: dict[str, Any]) -> dict[str, str]:
    """Parse and return the location-UUID → LKCareEvolve-account-number mapping.

    Expects a JSON string like: {"<location_uuid>": "<account_number>"}
    Raises ValueError on parse failure or empty map.
    """
    raw: str = secrets["LOCATION_TO_ACCOUNT_MAP_JSON"]
    if not raw:
        raise ValueError("Secret LOCATION_TO_ACCOUNT_MAP_JSON is empty")
    try:
        mapping: dict[str, str] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LOCATION_TO_ACCOUNT_MAP_JSON is not valid JSON: {exc}"
        ) from exc
    if not isinstance(mapping, dict):
        raise ValueError("LOCATION_TO_ACCOUNT_MAP_JSON must be a JSON object")
    return mapping


def sending_facility_name(secrets: dict[str, Any]) -> str:
    """Return the friendly facility name for MessageHeader.SendingFacilityName."""
    value: str = secrets["SENDING_FACILITY_NAME"]
    if not value:
        raise ValueError("Secret SENDING_FACILITY_NAME is empty")
    return value


def account_number_for_location(
    location_id: str,
    secrets: dict[str, Any],
) -> str:
    """Look up the LKCareEvolve account number for a given practice-location UUID.

    Raises KeyError if the location is not in the mapping — fail loud.
    """
    mapping = location_to_account_map(secrets)
    if location_id not in mapping:
        raise KeyError(
            f"No LKCareEvolve account number configured for location '{location_id}'. "
            f"Add it to LOCATION_TO_ACCOUNT_MAP_JSON."
        )
    return mapping[location_id]
