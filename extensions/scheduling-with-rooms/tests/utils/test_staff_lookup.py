"""Tests for staff_lookup.py."""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.utils.staff_lookup import (
    get_room_staff,
    get_schedulable_staff,
    parse_schedulable_roles,
)


def test_parse_schedulable_roles_empty():
    assert parse_schedulable_roles("") == []
    assert parse_schedulable_roles(None) == []
    assert parse_schedulable_roles("   ") == []


def test_parse_schedulable_roles_json_array():
    assert parse_schedulable_roles('["MD","NP"]') == ["MD", "NP"]


def test_parse_schedulable_roles_csv():
    assert parse_schedulable_roles("MD,NP") == ["MD", "NP"]


def test_parse_schedulable_roles_csv_with_spaces():
    assert parse_schedulable_roles("MD, NP, PA") == ["MD", "NP", "PA"]


def test_parse_schedulable_roles_malformed_json_falls_back_to_csv():
    # Bracket-only is invalid JSON — should drop bracket chars in fallback.
    assert parse_schedulable_roles("[MD,NP]") == ["MD", "NP"]


def test_parse_schedulable_roles_json_non_list():
    # Non-list JSON falls through to CSV path.
    assert parse_schedulable_roles('"MD"') == ["MD"]


def test_parse_schedulable_roles_strips_quotes():
    assert parse_schedulable_roles('"MD","NP"') == ["MD", "NP"]


def test_get_schedulable_staff_no_roles():
    assert get_schedulable_staff([]) == []
    assert get_schedulable_staff([""]) == []


def test_get_schedulable_staff_returns_dicts():
    staff1 = MagicMock()
    staff1.id = "id-1"
    staff1.full_name = "Bob"
    staff2 = MagicMock()
    staff2.id = "id-2"
    staff2.full_name = "Alice"

    with patch("scheduling_with_rooms.utils.staff_lookup.Staff") as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.exclude.return_value.distinct.return_value.order_by.return_value = [
            staff1,
            staff2,
        ]
        result = get_schedulable_staff(["MD"])
        assert result == [
            {"id": "id-1", "name": "Bob"},
            {"id": "id-2", "name": "Alice"},
        ]


def test_get_room_staff_returns_active_rr():
    rr1 = MagicMock()
    rr1.id = "room-1"
    rr1.full_name = "Exam 1"

    with patch("scheduling_with_rooms.utils.staff_lookup.Staff") as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.distinct.return_value.order_by.return_value = [
            rr1
        ]
        result = get_room_staff()
        assert result == [{"id": "room-1", "name": "Exam 1"}]
