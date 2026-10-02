"""Shared fixtures for availability API tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _stub_buffer_reconcile():
    """Stub buffer reconciliation for the rule-CRUD API tests.

    The rule create/update/delete handlers reconcile a provider's Buffer holds by
    calling ``reconcile_buffers_for_provider`` (covered directly in
    tests/protocols/test_appointment_buffer.py). These API tests assert only the
    availability-sync effects, so stub the buffer pass to a no-op to keep them
    isolated from calendar/DB access.
    """
    with patch(
        "provider_availability.api.availability_api.reconcile_buffers_for_provider",
        return_value=[],
    ):
        yield
