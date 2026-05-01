"""Protocol-test-only fixtures.

The handlers (membership_api, billing_cron) call ``append_charge`` — which
reaches into the ``ChargeRecord`` ORM to insert a row. Without a real test
DB, those inserts hit UUID validation and fail.

For protocol tests we stub the ORM-backing layer so handler logic can be
exercised without needing Django's migration machinery. Dedicated ORM tests
live in ``tests/utils/`` and target the real model calls (mocked there too,
matching the vida_sticky_note pattern).
"""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_charge_record() -> MagicMock:
    """Prevent ``append_charge`` from hitting the ORM during protocol tests."""
    with patch(
        "portal_membership.utils.charge_history.ChargeRecord"
    ) as mock:
        yield mock
