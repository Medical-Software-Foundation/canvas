"""Shared fixtures for vanta_lab_orders tests."""

from __future__ import annotations

import json
from typing import Any

import pytest


# These UUIDs are valid and are used in both test fixtures and the secrets map.
LOCATION_UUID_1 = "11111111-1111-1111-1111-111111111111"
LOCATION_UUID_2 = "22222222-2222-2222-2222-222222222222"


@pytest.fixture()
def secrets() -> dict[str, Any]:
    """Default plugin secrets for testing."""
    return {
        "LKCAREEVOLVE_BASE_URL": "https://lkcareevolve.example.com",
        "LKCAREEVOLVE_API_KEY": "test-api-key-abc123",
        "VANTA_LAB_PARTNER_NAME": "Vanta Diagnostics",
        "LOCATION_TO_ACCOUNT_MAP_JSON": json.dumps(
            {
                LOCATION_UUID_1: "ACCT-001",
                LOCATION_UUID_2: "ACCT-002",
            }
        ),
        "SENDING_FACILITY_NAME": "Example Facility",
    }
