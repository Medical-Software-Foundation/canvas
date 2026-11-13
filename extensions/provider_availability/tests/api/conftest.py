"""Shared fixtures for the API tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def stub_buffer_reconcile():
    """Stub the buffer reconcile that rule changes run.

    It reads calendars and appointments, and is covered directly in
    tests/protocols/test_appointment_buffer.py. API tests that care whether it
    ran take this fixture by name and assert on the mock.
    """
    with (
        patch(
            "provider_availability.api.availability_api.reconcile_buffers_for_provider",
            return_value=[],
        ) as mock,
        patch(
            "provider_availability.api.csv_import_api.reconcile_buffers_for_provider",
            new=mock,
        ),
    ):
        yield mock
