"""Shared fixtures for provider-availability tests."""

import datetime as dt
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from provider_availability.engine.models import (
    AdminBlock,
    AvailableSlot,
    BookingInterval,
    BufferTime,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)


PROVIDER_ID = "provider-uuid-123"
LOCATION_ID = "location-uuid-456"
VISIT_TYPE_ID = "visit-type-uuid-789"


@pytest.fixture
def mock_cache():
    """A mock plugin cache that behaves like a dict."""
    store: dict[str, object] = {}

    cache = MagicMock()
    cache.get.side_effect = lambda key, default=None: store.get(key, default)
    cache.set.side_effect = lambda key, value, timeout_seconds=None: store.__setitem__(key, value)
    cache.delete.side_effect = lambda key: store.pop(key, None)

    def get_many(keys):
        return {k: store[k] for k in keys if k in store}

    cache.get_many.side_effect = get_many
    cache._store = store
    return cache


@pytest.fixture
def patch_cache(mock_cache):
    """Patch storage._get_cache to return mock_cache."""
    with patch("provider_availability.engine.storage._get_cache", return_value=mock_cache):
        yield mock_cache


@pytest.fixture
def sample_time_window():
    """A 9:00-12:00 time window."""
    return TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))


@pytest.fixture
def sample_rule():
    """A basic availability rule for testing."""
    return ProviderAvailabilityRule(
        id="rule-uuid-001",
        provider_id=PROVIDER_ID,
        location_ids=[LOCATION_ID],
        visit_types=[VISIT_TYPE_ID],
        weekly_schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            "wednesday": [TimeWindow(start=dt.time(13, 0), end=dt.time(17, 0))],
        },
        buffer_minutes=BufferTime(pre=0, post=15),
        booking_interval=BookingInterval(min_lead_hours=24, slot_granularity_minutes=15),
        is_active=True,
    )


@pytest.fixture
def sample_block():
    """A basic admin block for testing."""
    return AdminBlock(
        id="block-uuid-001",
        provider_id=PROVIDER_ID,
        start=datetime(2026, 3, 10, 9, 0),
        end=datetime(2026, 3, 10, 12, 0),
        reason="PTO",
    )


@pytest.fixture
def sample_recurring_block():
    """A basic recurring block for testing."""
    return RecurringBlock(
        id="recurring-block-001",
        provider_id=PROVIDER_ID,
        weekly_schedule={
            "friday": [TimeWindow(start=dt.time(12, 0), end=dt.time(13, 0))],
        },
        reason="Lunch",
        is_active=True,
    )


@pytest.fixture
def mock_event():
    """A mock Canvas SDK event."""
    event = MagicMock()
    event.target.id = "target-uuid-123"
    return event
