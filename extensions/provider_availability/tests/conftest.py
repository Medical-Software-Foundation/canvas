"""Shared fixtures for provider-availability tests."""

import datetime as dt
from pathlib import Path
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


_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "provider_availability"


def _render_plugin_template(template_name, context=None, **kwargs):
    """Stand-in for the SDK's render_to_string, which needs a running plugin.

    Renders the plugin's real file with a plain Django engine, so the tests
    exercise the same template the plugin serves.
    """
    from django.template.engine import Engine

    engine = Engine(dirs=[str(_PLUGIN_DIR)])
    return engine.render_to_string(str(_PLUGIN_DIR / template_name.lstrip("/")), context=context)


@pytest.fixture(autouse=True)
def _admin_page_renders_from_file():
    with patch("provider_availability.templates.admin_ui.render_to_string", side_effect=_render_plugin_template):
        yield


@pytest.fixture(autouse=True)
def _no_stored_recurring_blocks():
    """Recurring-block resyncs redraw the provider's other blocks from storage,
    which needs a running plugin. Default to none stored; tests that care patch it."""
    with patch("provider_availability.engine.event_sync.get_recurring_blocks_for_provider", return_value=[]):
        yield


class QS(list):
    """A list that answers the queryset calls the plugin makes on query results.

    Tests stub ``Model.objects.filter`` with a plain list; code that asks for
    ``.values_list("id", flat=True)`` needs this instead.
    """

    def values_list(self, *fields, flat=False):
        if flat:
            return [getattr(o, fields[0]) for o in self]
        return [tuple(getattr(o, f) for f in fields) for o in self]

    def order_by(self, *fields):
        return self


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
