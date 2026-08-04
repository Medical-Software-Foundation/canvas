"""Tests for api/scheduling_admin_api.py."""

import json
from unittest.mock import MagicMock, patch

from scheduling_with_rooms.api.scheduling_admin_api import SchedulingAdminAPI


def _handler(body=None, secrets=None):
    h = SchedulingAdminAPI.__new__(SchedulingAdminAPI)
    request = MagicMock()
    request.json.return_value = body if body is not None else {}
    h.request = request
    h.secrets = secrets or {"SCHEDULABLE_STAFF_ROLES": "MD,NP"}
    return h


def test_admin_page_returns_html():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.render_to_string",
        return_value="<html>",
    ):
        result = h.admin_page()
        assert len(result) == 1


def test_admin_data_full_payload():
    h = _handler()

    visit_type = {"id": "nt-1", "name": "Visit", "code": "VISIT"}

    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ) as mock_mapping, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomEvent"
    ) as mock_event_cfg, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeDuration"
    ) as mock_duration, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.StaffSlotConfig"
    ) as mock_slot, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.get_schedulable_staff_and_rooms",
        return_value=([{"id": "p1", "name": "Bob"}], [{"id": "room-1", "name": "Exam 1"}]),
    ):
        # encounter visit types — match returned shape used by .values()
        mock_nt.objects.filter.return_value.values.return_value.order_by.return_value = [
            visit_type,
            {"id": "nt-2", "name": "Other", "code": ""},  # filtered out
        ]
        mock_mapping.objects.values.return_value = [
            {"note_type_code": "VISIT", "room_staff_key": "room-1"},
        ]
        # schedule_event note types
        # Same .filter().values().order_by() pattern
        mock_nt.objects.filter.side_effect = [
            MagicMock(
                **{
                    "values.return_value.order_by.return_value": [
                        visit_type,
                        {"id": "nt-2", "name": "Other", "code": ""},
                    ]
                }
            ),
            MagicMock(
                **{
                    "values.return_value.order_by.return_value": [
                        {"name": "Room booked", "code": "room"},
                        {"name": "No code", "code": ""},
                    ]
                }
            ),
        ]
        mock_event_cfg.objects.values.return_value = [
            {"note_type_code": "VISIT", "room_event_note_type_code": "room"},
        ]
        mock_duration.objects.values.return_value = [
            {"note_type_code": "VISIT", "duration_minutes": 30},
            {"note_type_code": "VISIT", "duration_minutes": 60},
        ]
        mock_slot.objects.values.return_value = [
            {"staff_key": "p1", "concurrent_limit": 2},
        ]

        result = h.admin_data()
        assert len(result) == 1


def test_save_mappings_invalid_mappings_type():
    h = _handler({"mappings": "not-a-dict"})
    result = h.save_mappings()
    assert len(result) == 1


def test_save_mappings_invalid_mapping_value():
    h = _handler({"mappings": {"VISIT": "not-a-list"}})
    result = h.save_mappings()
    assert len(result) == 1


def test_save_mappings_invalid_room_event_codes_type():
    h = _handler({"mappings": {}, "room_event_codes": "not-a-dict"})
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_invalid_room_event_value():
    h = _handler({"mappings": {}, "room_event_codes": {"VISIT": 123}})
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_invalid_durations_type():
    h = _handler({"mappings": {}, "durations": "not-a-dict"})
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_room_event_codes"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_invalid_duration_value():
    h = _handler({"mappings": {}, "durations": {"VISIT": "not-a-list"}})
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_room_event_codes"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_invalid_concurrent_limits_type():
    h = _handler({"mappings": {}, "concurrent_limits": "x"})
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_room_event_codes"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_durations"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_invalid_concurrent_limits_key():
    h = _handler({"mappings": {}, "concurrent_limits": {123: 2}})
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_room_event_codes"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_durations"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_full_save():
    h = _handler({
        "mappings": {"VISIT": ["room-1", "room-1"]},  # dup key gets deduped
        "room_event_codes": {"VISIT": " room "},
        "durations": {"VISIT": [30, "60", "abc", -1, 45]},
        "concurrent_limits": {"p1": 2, "p2": "abc", "p3": 0, "p4": "5"},
    })
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_room_event_codes"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_durations"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_concurrent_limits"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_empty_payload():
    h = _handler({})
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_room_event_codes"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_durations"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_concurrent_limits"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_save_mappings_none_payload_falls_back_to_empty():
    h = _handler(None)
    h.request.json.return_value = None
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_room_event_codes"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_durations"
    ), patch(
        "scheduling_with_rooms.api.scheduling_admin_api.replace_concurrent_limits"
    ):
        result = h.save_mappings()
        assert len(result) == 1


def test_admin_data_tags_providers_and_rooms():
    """Each entry carries its role so the admin matrix can group them.

    The two lists arrive already disjoint from
    ``get_schedulable_staff_and_rooms`` — a staff member holding both a
    clinical role and RR is classified there, not deduped here. See
    ``test_staff_lookup.test_staff_holding_both_a_clinical_role_and_rr_counts_as_a_room``.
    """
    h = _handler()

    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomMapping"
    ) as mock_mapping, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeRoomEvent"
    ) as mock_event_cfg, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.VisitTypeDuration"
    ) as mock_duration, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.StaffSlotConfig"
    ) as mock_slot, patch(
        "scheduling_with_rooms.api.scheduling_admin_api.get_schedulable_staff_and_rooms",
        return_value=([{"id": "p1", "name": "Bob"}], [{"id": "r1", "name": "Exam 1"}]),
    ):
        mock_nt.objects.filter.return_value.values.return_value.order_by.return_value = []
        mock_mapping.objects.values.return_value = []
        mock_event_cfg.objects.values.return_value = []
        mock_duration.objects.values.return_value = []
        mock_slot.objects.values.return_value = []

        body = json.loads(h.admin_data()[0].content)

        assert body["schedulable_staff"] == [
            {"id": "p1", "name": "Bob", "role": "provider"},
            {"id": "r1", "name": "Exam 1", "role": "room"},
        ]


def test_admin_css_is_served_as_a_stylesheet():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_admin_api.render_to_string",
        return_value=":root { color: red; }",
    ) as mock_render:
        result = h.admin_css()

        assert len(result) == 1
        assert result[0].headers["Content-Type"] == "text/css"
        mock_render.assert_called_once_with("static/scheduling_admin.css")


def test_admin_css_contains_no_hardcoded_colors():
    import pathlib
    import re

    css = (
        pathlib.Path(__file__).parents[2]
        / "scheduling_with_rooms"
        / "static"
        / "scheduling_admin.css"
    ).read_text()
    hexes = re.findall(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", css)

    assert hexes == [], f"hardcoded colors leaked back in: {sorted(set(hexes))}"
