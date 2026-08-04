"""Tests for staff_lookup.py."""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.utils.staff_lookup import (
    get_schedulable_staff_and_rooms,
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


def _rows(*rows):
    """Patch Staff so .filter().order_by().values() yields the given rows.

    One row per (staff, role) pair — the join fan-out the new query relies on.
    """
    patcher = patch("scheduling_with_rooms.utils.staff_lookup.Staff")
    mock = patcher.start()
    mock.objects.filter.return_value.order_by.return_value.values.return_value = list(rows)
    return patcher, mock


def _row(staff_id, first, last, role):
    return {
        "id": staff_id,
        "first_name": first,
        "last_name": last,
        "roles__internal_code": role,
    }


def test_partitions_providers_and_rooms_from_one_query():
    patcher, mock = _rows(
        _row("id-1", "Alice", "Adams", "MD"),
        _row("id-2", "Exam", "One", "RR"),
    )
    try:
        providers, rooms = get_schedulable_staff_and_rooms(["MD"])

        assert providers == [{"id": "id-1", "name": "Alice Adams"}]
        assert rooms == [{"id": "id-2", "name": "Exam One"}]
        # The whole point: a single query, not one per group.
        assert mock.objects.filter.call_count == 1
    finally:
        patcher.stop()


def test_query_asks_for_only_the_fields_used():
    patcher, mock = _rows()
    try:
        get_schedulable_staff_and_rooms(["MD"])

        values_call = mock.objects.filter.return_value.order_by.return_value.values
        assert values_call.call_args.args == (
            "id",
            "first_name",
            "last_name",
            "roles__internal_code",
        )
    finally:
        patcher.stop()


def test_room_role_is_always_queried_even_when_not_configured():
    """Rooms are configured independently of SCHEDULABLE_STAFF_ROLES."""
    patcher, mock = _rows()
    try:
        get_schedulable_staff_and_rooms(["MD"])

        assert mock.objects.filter.call_args.kwargs["roles__internal_code__in"] == [
            "MD",
            "RR",
        ]
    finally:
        patcher.stop()


def test_multi_role_staff_is_returned_once():
    """Selecting the role code fans the join out; folding it back replaces .distinct()."""
    patcher, _ = _rows(
        _row("id-1", "Alice", "Adams", "MD"),
        _row("id-1", "Alice", "Adams", "NP"),
    )
    try:
        providers, rooms = get_schedulable_staff_and_rooms(["MD", "NP"])

        assert providers == [{"id": "id-1", "name": "Alice Adams"}]
        assert rooms == []
    finally:
        patcher.stop()


def test_staff_holding_both_a_clinical_role_and_rr_counts_as_a_room():
    """Matches the old .exclude(roles__internal_code="RR") on the provider query."""
    patcher, _ = _rows(
        _row("id-1", "Dual", "Purpose", "MD"),
        _row("id-1", "Dual", "Purpose", "RR"),
    )
    try:
        providers, rooms = get_schedulable_staff_and_rooms(["MD"])

        assert providers == []
        assert rooms == [{"id": "id-1", "name": "Dual Purpose"}]
    finally:
        patcher.stop()


def test_staff_without_a_wanted_role_is_dropped():
    patcher, _ = _rows(_row("id-9", "Admin", "Person", "AD"))
    try:
        providers, rooms = get_schedulable_staff_and_rooms(["MD"])

        assert providers == []
        assert rooms == []
    finally:
        patcher.stop()


def test_no_roles_still_returns_rooms():
    patcher, mock = _rows(_row("id-2", "Exam", "One", "RR"))
    try:
        providers, rooms = get_schedulable_staff_and_rooms([])

        assert providers == []
        assert rooms == [{"id": "id-2", "name": "Exam One"}]
        assert mock.objects.filter.call_args.kwargs["roles__internal_code__in"] == ["RR"]
    finally:
        patcher.stop()


def test_ordering_follows_the_query():
    patcher, _ = _rows(
        _row("id-2", "Alice", "Adams", "MD"),
        _row("id-1", "Bob", "Brown", "MD"),
    )
    try:
        providers, _rooms = get_schedulable_staff_and_rooms(["MD"])

        assert [p["name"] for p in providers] == ["Alice Adams", "Bob Brown"]
    finally:
        patcher.stop()


def test_null_role_code_is_ignored():
    patcher, _ = _rows(_row("id-1", "Alice", "Adams", None))
    try:
        providers, rooms = get_schedulable_staff_and_rooms(["MD"])

        assert providers == []
        assert rooms == []
    finally:
        patcher.stop()
