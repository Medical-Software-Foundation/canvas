"""Tests for staff_slot_config.py."""

from unittest.mock import MagicMock, patch, call

from scheduling_with_rooms.models.staff_slot_config import (
    get_concurrent_limit,
    replace_concurrent_limits,
)


def test_get_concurrent_limit_empty_key_returns_default():
    result = get_concurrent_limit("")
    assert result == 1


def test_get_concurrent_limit_empty_key_with_custom_default():
    result = get_concurrent_limit("", default=5)
    assert result == 5


def test_get_concurrent_limit_no_row_returns_default():
    with patch(
        "scheduling_with_rooms.models.staff_slot_config.StaffSlotConfig.objects"
    ) as mock_objects:
        mock_qs = MagicMock()
        mock_objects.filter.return_value = mock_qs
        mock_qs.values_list.return_value.first.return_value = None

        result = get_concurrent_limit("staff-1")

        assert mock_objects.mock_calls == [
            call.filter(staff_key="staff-1"),
            call.filter().values_list("concurrent_limit", flat=True),
            call.filter().values_list().first(),
        ]
        assert result == 1


def test_get_concurrent_limit_below_one_returns_default():
    with patch(
        "scheduling_with_rooms.models.staff_slot_config.StaffSlotConfig.objects"
    ) as mock_objects:
        mock_objects.filter.return_value.values_list.return_value.first.return_value = 0

        result = get_concurrent_limit("staff-1", default=2)

        assert result == 2


def test_get_concurrent_limit_returns_configured_value():
    with patch(
        "scheduling_with_rooms.models.staff_slot_config.StaffSlotConfig.objects"
    ) as mock_objects:
        mock_objects.filter.return_value.values_list.return_value.first.return_value = 3

        result = get_concurrent_limit("staff-1")

        assert result == 3


def test_replace_concurrent_limits_empty_dict_no_op():
    with patch(
        "scheduling_with_rooms.models.staff_slot_config.StaffSlotConfig.objects"
    ) as mock_objects:
        replace_concurrent_limits({})
        assert mock_objects.mock_calls == []


def test_replace_concurrent_limits_creates_valid_rows():
    with patch(
        "scheduling_with_rooms.models.staff_slot_config.StaffSlotConfig"
    ) as mock_cls:
        replace_concurrent_limits({"staff-1": 2, "staff-2": 1})

        # Verify delete and bulk_create happened
        delete_calls = [c for c in mock_cls.objects.mock_calls if "delete" in str(c)]
        assert len(delete_calls) >= 1
        bulk_create_calls = [
            c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)
        ]
        assert len(bulk_create_calls) == 1


def test_replace_concurrent_limits_skips_invalid_keys():
    with patch(
        "scheduling_with_rooms.models.staff_slot_config.StaffSlotConfig"
    ) as mock_cls:
        replace_concurrent_limits({"": 2, "staff-1": "abc", "staff-2": 0, "staff-3": 4})
        # Only staff-3 should pass validation (staff-1 has bad int, staff-2 has 0).
        bulk_call = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        assert len(bulk_call) == 1


def test_replace_concurrent_limits_no_valid_rows_no_bulk_create():
    with patch(
        "scheduling_with_rooms.models.staff_slot_config.StaffSlotConfig"
    ) as mock_cls:
        replace_concurrent_limits({"": 2, "staff-1": 0})
        bulk_call = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        assert len(bulk_call) == 0
