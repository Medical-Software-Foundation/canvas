"""Tests for visit_type_room_event.py."""

from unittest.mock import patch

from scheduling_with_rooms.models.visit_type_room_event import (
    get_room_event_code_for,
    replace_room_event_codes,
)


def test_get_room_event_code_for_empty_returns_empty():
    assert get_room_event_code_for("") == ""


def test_get_room_event_code_for_returns_configured_value():
    with patch(
        "scheduling_with_rooms.models.visit_type_room_event.VisitTypeRoomEvent.objects"
    ) as mock_objects:
        mock_objects.filter.return_value.values_list.return_value.first.return_value = "room"
        result = get_room_event_code_for("VISIT")
        assert result == "room"


def test_get_room_event_code_for_no_row_returns_empty():
    with patch(
        "scheduling_with_rooms.models.visit_type_room_event.VisitTypeRoomEvent.objects"
    ) as mock_objects:
        mock_objects.filter.return_value.values_list.return_value.first.return_value = None
        result = get_room_event_code_for("VISIT")
        assert result == ""


def test_replace_room_event_codes_empty_no_op():
    with patch(
        "scheduling_with_rooms.models.visit_type_room_event.VisitTypeRoomEvent"
    ) as mock_cls:
        replace_room_event_codes({})
        assert mock_cls.objects.mock_calls == []


def test_replace_room_event_codes_creates_rows():
    with patch(
        "scheduling_with_rooms.models.visit_type_room_event.VisitTypeRoomEvent"
    ) as mock_cls:
        replace_room_event_codes({"VISIT": "room", "OTHER": "exam"})
        bulk_calls = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        assert len(bulk_calls) == 1


def test_replace_room_event_codes_skips_blank_event_codes():
    with patch(
        "scheduling_with_rooms.models.visit_type_room_event.VisitTypeRoomEvent"
    ) as mock_cls:
        # Empty event_code clears (no row created); empty visit-code skipped too.
        replace_room_event_codes({"": "room", "VISIT": "", "OTHER": "exam"})
        bulk_calls = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        # Only OTHER is valid.
        assert len(bulk_calls) == 1


def test_replace_room_event_codes_no_valid_rows():
    with patch(
        "scheduling_with_rooms.models.visit_type_room_event.VisitTypeRoomEvent"
    ) as mock_cls:
        replace_room_event_codes({"VISIT": ""})
        bulk_calls = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        assert len(bulk_calls) == 0
