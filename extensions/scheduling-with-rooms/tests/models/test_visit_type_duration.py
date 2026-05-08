"""Tests for visit_type_duration.py."""

from unittest.mock import patch

from scheduling_with_rooms.models.visit_type_duration import (
    get_durations_for,
    replace_durations,
)


def test_get_durations_for_empty_returns_empty_list():
    assert get_durations_for("") == []


def test_get_durations_for_returns_sorted():
    with patch(
        "scheduling_with_rooms.models.visit_type_duration.VisitTypeDuration.objects"
    ) as mock_objects:
        mock_objects.filter.return_value.values_list.return_value = [60, 30, 15]

        result = get_durations_for("VISIT")

        assert result == [15, 30, 60]


def test_replace_durations_empty_dict_no_op():
    with patch(
        "scheduling_with_rooms.models.visit_type_duration.VisitTypeDuration"
    ) as mock_cls:
        replace_durations({})
        assert mock_cls.objects.mock_calls == []


def test_replace_durations_creates_unique_valid_rows():
    with patch(
        "scheduling_with_rooms.models.visit_type_duration.VisitTypeDuration"
    ) as mock_cls:
        replace_durations({"VISIT": [30, 60, 60, 30], "OTHER": [15]})
        bulk_calls = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        assert len(bulk_calls) == 1


def test_replace_durations_skips_invalid_codes():
    with patch(
        "scheduling_with_rooms.models.visit_type_duration.VisitTypeDuration"
    ) as mock_cls:
        # Empty string code, non-int duration, zero/negative duration all skipped.
        replace_durations({"": [30], "VISIT": [0, -5, "abc", 30.5, 45]})
        bulk_calls = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        # Only 45 is valid for VISIT.
        assert len(bulk_calls) == 1


def test_replace_durations_no_valid_rows_no_bulk_create():
    with patch(
        "scheduling_with_rooms.models.visit_type_duration.VisitTypeDuration"
    ) as mock_cls:
        replace_durations({"VISIT": [0, -1]})
        bulk_calls = [c for c in mock_cls.objects.mock_calls if "bulk_create" in str(c)]
        assert len(bulk_calls) == 0
