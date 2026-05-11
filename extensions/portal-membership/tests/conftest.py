"""Shared pytest fixtures for portal-membership tests."""
import json
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_event() -> MagicMock:
    """A minimal Canvas event mock with patient session context."""
    event = MagicMock()
    event.context = {
        "user": {"id": "patient-abc-123", "type": "Patient"}
    }
    return event


@pytest.fixture
def patient_id() -> str:
    return "patient-abc-123"


@pytest.fixture
def membership_plans() -> list[dict[str, Any]]:
    return [
        {"name": "Basic", "key": "basic", "price_cents": 4900},
        {"name": "Gold", "key": "gold", "price_cents": 9900},
    ]


@pytest.fixture
def discount_codes() -> list[dict[str, Any]]:
    return [
        {"code": "WELCOME10", "type": "percent", "value": 10, "months": 3},
        {"code": "SAVE20", "type": "fixed", "value": 2000, "months": 1},
        {"code": "FREEMONTH", "type": "percent", "value": 100, "months": 1},
    ]


@pytest.fixture
def secrets(
    membership_plans: list[dict[str, Any]],
    discount_codes: list[dict[str, Any]],
) -> dict[str, str]:
    return {
        "STRIPE_SECRET_KEY": "sk_test_fake",
        "MEMBERSHIP_PLANS": json.dumps(membership_plans),
        "DISCOUNT_CODES": json.dumps(discount_codes),
        "STAFF_OFFBOARDING_TEAM_ID": "team-uuid-999",
        "BILLING_CURRENCY": "usd",
    }


@pytest.fixture
def active_record() -> dict[str, Any]:
    return {
        "plan": "gold",
        "plan_name": "Gold",
        "status": "active",
        "stripe_customer_id": "cus_test123",
        "payment_method_id": "pm_test456",
        "cadence": "monthly",
        "next_billing_date": "2026-04-11",
        "billing_day": 11,
        "amount_cents": 9900,
        "currency": "usd",
        "consecutive_failures": 0,
    }


@pytest.fixture
def cancelled_record(active_record: dict[str, Any]) -> dict[str, Any]:
    r = dict(active_record)
    r["status"] = "cancelled"
    return r
