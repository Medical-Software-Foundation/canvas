"""Tests for AvailabilitySlotFilter."""

import datetime
import json
from unittest.mock import MagicMock, patch

import pytest

from provider_availability_manager.protocols import availability_slot_filter
from provider_availability_manager.protocols.availability_slot_filter import (
    AvailabilitySlotFilter,
    _filter_one_provider_slots,
    _parse_slot_dt,
    _provider_id_from_entry,
    _resolve_location_name,
    _to_naive_local,
)


class TestResolveLocationName:
    def test_dict_with_name(self):
        assert _resolve_location_name({"location": {"name": "Main Clinic"}}) == "Main Clinic"

    def test_dict_with_label(self):
        assert _resolve_location_name({"location": {"label": "North Office"}}) == "North Office"

    def test_string_location_falls_back_to_value(self):
        with patch.object(
            availability_slot_filter, "PracticeLocation"
        ) as practice_loc:
            practice_loc.objects.filter.return_value.first.return_value = None
            assert _resolve_location_name({"location": "raw-string"}) == "raw-string"

    def test_non_uuid_string_location_falls_through_without_crashing(self):
        """Regression: PracticeLocation.id is a UUIDField; Django raises
        ValidationError when ``.filter(id=<non-uuid>)`` is constructed.

        Letting that propagate out of ``_resolve_location_name`` would crash
        ``compute()``, no APPOINTMENT__SLOTS__POST_SEARCH_RESULTS effect would
        be emitted, and Canvas would silently show the original unfiltered
        slot list — converting the README's fail-closed guarantee into
        fail-OPEN. The lookup must be wrapped so we fall through to the
        ``.strip()`` fallback instead.
        """
        from django.core.exceptions import ValidationError

        with patch.object(
            availability_slot_filter, "PracticeLocation"
        ) as practice_loc:
            practice_loc.objects.filter.side_effect = ValidationError(
                "Main Clinic is not a valid UUID."
            )
            # Must not raise; must return the stripped fallback.
            assert _resolve_location_name({"location": "Main Clinic"}) == "Main Clinic"

    def test_non_uuid_dict_id_falls_through_without_crashing(self):
        """Same regression on the dict-shape branch when only id/value is
        present and the string isn't a UUID. The function must return ""
        (the dict-branch's fall-through), not raise."""
        from django.core.exceptions import ValidationError

        with patch.object(
            availability_slot_filter, "PracticeLocation"
        ) as practice_loc:
            practice_loc.objects.filter.side_effect = ValidationError(
                "main-clinic-slug is not a valid UUID."
            )
            assert _resolve_location_name(
                {"location": {"id": "main-clinic-slug"}}
            ) == ""

    def test_value_error_from_filter_also_caught(self):
        """Older Django versions raised ValueError instead of ValidationError
        from UUIDField.to_python. The except clause catches both so we
        survive the SDK upgrading Django under our feet."""
        with patch.object(
            availability_slot_filter, "PracticeLocation"
        ) as practice_loc:
            practice_loc.objects.filter.side_effect = ValueError("bad uuid")
            assert _resolve_location_name({"location": "Main Clinic"}) == "Main Clinic"

    def test_missing_location_returns_empty(self):
        assert _resolve_location_name({}) == ""

    def test_non_dict_returns_empty(self):
        assert _resolve_location_name(None) == ""


class TestParseSlotDt:
    def test_iso_string_parsed(self):
        dt = _parse_slot_dt("2026-05-15T09:00:00")
        assert dt == datetime.datetime(2026, 5, 15, 9, 0, 0)

    def test_z_suffix_treated_as_utc(self):
        dt = _parse_slot_dt("2026-05-15T09:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_datetime_passthrough(self):
        original = datetime.datetime(2026, 5, 15, 9)
        assert _parse_slot_dt(original) is original

    def test_invalid_string_returns_none(self):
        assert _parse_slot_dt("not-a-date") is None

    def test_empty_returns_none(self):
        assert _parse_slot_dt("") is None
        assert _parse_slot_dt(None) is None


class TestProviderIdFromEntry:
    def test_provider_dict_with_id(self):
        assert _provider_id_from_entry({"provider": {"id": "abc"}, "slots": []}) == "abc"

    def test_flat_provider_id(self):
        assert _provider_id_from_entry({"provider_id": "abc", "slots": []}) == "abc"

    def test_missing_returns_empty(self):
        assert _provider_id_from_entry({"slots": []}) == ""

    def test_non_dict_returns_empty(self):
        assert _provider_id_from_entry(None) == ""


class TestFilterOneProviderSlots:
    @patch.object(availability_slot_filter, "get_location_timezone", return_value="UTC")
    @patch.object(availability_slot_filter, "get_availability_windows", return_value=[])
    @patch.object(availability_slot_filter, "get_blocking_calendar_events", return_value=[])
    def test_empty_windows_fail_closed(self, _block, _avail, _tz):
        slots = [{"start": "2026-05-15T09:00:00", "end": "2026-05-15T09:30:00"}]
        assert _filter_one_provider_slots("p1", "Main", slots, {}, {}) == []

    @patch.object(availability_slot_filter, "get_location_timezone", return_value="UTC")
    @patch.object(
        availability_slot_filter,
        "get_availability_windows",
        return_value=[
            (datetime.datetime(2026, 5, 15, 9), datetime.datetime(2026, 5, 15, 17))
        ],
    )
    @patch.object(availability_slot_filter, "get_blocking_calendar_events", return_value=[])
    def test_slot_inside_window_kept(self, _block, _avail, _tz):
        slots = [{"start": "2026-05-15T10:00:00", "end": "2026-05-15T10:30:00"}]
        result = _filter_one_provider_slots("p1", "Main", slots, {}, {})
        assert len(result) == 1
        assert result[0]["start"] == "2026-05-15T10:00:00"

    @patch.object(availability_slot_filter, "get_location_timezone", return_value="UTC")
    @patch.object(
        availability_slot_filter,
        "get_availability_windows",
        return_value=[
            (datetime.datetime(2026, 5, 15, 9), datetime.datetime(2026, 5, 15, 12))
        ],
    )
    @patch.object(availability_slot_filter, "get_blocking_calendar_events", return_value=[])
    def test_slot_outside_window_dropped(self, _block, _avail, _tz):
        slots = [{"start": "2026-05-15T13:00:00", "end": "2026-05-15T13:30:00"}]
        assert _filter_one_provider_slots("p1", "Main", slots, {}, {}) == []

    @patch.object(availability_slot_filter, "get_location_timezone", return_value="UTC")
    @patch.object(
        availability_slot_filter,
        "get_availability_windows",
        return_value=[
            (datetime.datetime(2026, 5, 15, 9), datetime.datetime(2026, 5, 15, 17))
        ],
    )
    @patch.object(
        availability_slot_filter,
        "get_blocking_calendar_events",
        return_value=[
            (datetime.datetime(2026, 5, 15, 12), datetime.datetime(2026, 5, 15, 13))
        ],
    )
    def test_slot_overlapping_busy_block_dropped(self, _block, _avail, _tz):
        slots = [
            {"start": "2026-05-15T11:30:00", "end": "2026-05-15T12:30:00"},
            {"start": "2026-05-15T14:00:00", "end": "2026-05-15T14:30:00"},
        ]
        result = _filter_one_provider_slots("p1", "Main", slots, {}, {})
        assert len(result) == 1
        assert result[0]["start"] == "2026-05-15T14:00:00"


class TestAvailabilitySlotFilterCompute:
    def _make_handler(self, context):
        handler = AvailabilitySlotFilter.__new__(AvailabilitySlotFilter)
        handler.event = MagicMock()
        handler.event.context = context
        return handler

    @patch.object(availability_slot_filter, "PracticeLocation")
    def test_no_location_passes_through(self, _practice_loc):
        handler = self._make_handler({
            "slots_by_provider": [{"provider": {"id": "p1"}, "slots": []}],
            "selected_values": {},
        })
        assert handler.compute() == []

    @patch.object(availability_slot_filter, "get_location_timezone", return_value="UTC")
    @patch.object(availability_slot_filter, "get_availability_windows", return_value=[])
    @patch.object(availability_slot_filter, "get_blocking_calendar_events", return_value=[])
    def test_list_payload_fail_closed_drops_slots(self, _b, _a, _tz):
        handler = self._make_handler({
            "slots_by_provider": [
                {
                    "provider": {"id": "p1"},
                    "slots": [{"start": "2026-05-15T09:00:00", "end": "2026-05-15T09:30:00"}],
                }
            ],
            "selected_values": {"location": {"name": "Main"}},
        })
        result = handler.compute()
        assert len(result) == 1
        payload = json.loads(result[0].payload)
        assert payload["slots_by_provider"][0]["slots"] == []

    @patch.object(availability_slot_filter, "get_location_timezone", return_value="UTC")
    @patch.object(
        availability_slot_filter,
        "get_availability_windows",
        return_value=[
            (datetime.datetime(2026, 5, 15, 9), datetime.datetime(2026, 5, 15, 17))
        ],
    )
    @patch.object(availability_slot_filter, "get_blocking_calendar_events", return_value=[])
    def test_list_payload_keeps_valid_slot(self, _b, _a, _tz):
        handler = self._make_handler({
            "slots_by_provider": [
                {
                    "provider": {"id": "p1"},
                    "slots": [{"start": "2026-05-15T10:00:00", "end": "2026-05-15T10:30:00"}],
                }
            ],
            "selected_values": {"location": {"name": "Main"}},
        })
        result = handler.compute()
        payload = json.loads(result[0].payload)
        assert len(payload["slots_by_provider"][0]["slots"]) == 1

    @patch.object(availability_slot_filter, "get_location_timezone", return_value="UTC")
    @patch.object(
        availability_slot_filter,
        "get_availability_windows",
        return_value=[
            (datetime.datetime(2026, 5, 15, 9), datetime.datetime(2026, 5, 15, 17))
        ],
    )
    @patch.object(availability_slot_filter, "get_blocking_calendar_events", return_value=[])
    def test_dict_payload_shape(self, _b, _a, _tz):
        handler = self._make_handler({
            "slots_by_provider": {
                "p1": [{"start": "2026-05-15T10:00:00", "end": "2026-05-15T10:30:00"}],
            },
            "selected_values": {"location": {"name": "Main"}},
        })
        result = handler.compute()
        payload = json.loads(result[0].payload)
        assert "p1" in payload["slots_by_provider"]
        assert len(payload["slots_by_provider"]["p1"]) == 1


class TestToNaiveLocal:
    def test_naive_datetime_passthrough(self):
        from zoneinfo import ZoneInfo

        dt = datetime.datetime(2026, 5, 15, 10)
        assert _to_naive_local(dt, ZoneInfo("UTC")) == dt

    def test_aware_datetime_converted_and_stripped(self):
        from zoneinfo import ZoneInfo

        dt = datetime.datetime(2026, 5, 15, 14, tzinfo=ZoneInfo("UTC"))
        local = _to_naive_local(dt, ZoneInfo("America/New_York"))
        assert local.tzinfo is None
        assert local == datetime.datetime(2026, 5, 15, 10)
