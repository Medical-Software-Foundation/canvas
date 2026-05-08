"""Tests for rfv_cache.py."""

import datetime
from unittest.mock import MagicMock, patch

from scheduling_with_rooms.utils import rfv_cache


def test_make_key_naive_datetime():
    dt = datetime.datetime(2026, 5, 7, 14, 30, 0)
    key = rfv_cache.make_key("p1", "prov1", dt)
    assert key == "rc:rfv:p1:prov1:2026-05-07T14:30:00"


def test_make_key_aware_datetime_normalises_to_utc():
    tz = datetime.timezone(datetime.timedelta(hours=-5))
    dt = datetime.datetime(2026, 5, 7, 9, 30, 0, tzinfo=tz)
    key = rfv_cache.make_key("p1", "prov1", dt)
    assert "2026-05-07T14:30:00" in key


def test_stash_empty_text_no_op():
    with patch("scheduling_with_rooms.utils.rfv_cache.get_cache") as mock_cache:
        rfv_cache.stash("p1", "prov1", datetime.datetime(2026, 5, 7), "")
        assert mock_cache.mock_calls == []


def test_stash_writes_to_cache():
    fake_cache = MagicMock()
    with patch(
        "scheduling_with_rooms.utils.rfv_cache.get_cache", return_value=fake_cache
    ):
        rfv_cache.stash("p1", "prov1", datetime.datetime(2026, 5, 7), "fever")
        # Verify set was called
        set_calls = [c for c in fake_cache.mock_calls if "set" in str(c)]
        assert len(set_calls) == 1


def test_pop_missing_returns_empty_string():
    fake_cache = MagicMock()
    fake_cache.get.return_value = None
    with patch(
        "scheduling_with_rooms.utils.rfv_cache.get_cache", return_value=fake_cache
    ):
        result = rfv_cache.pop("p1", "prov1", datetime.datetime(2026, 5, 7))
        assert result == ""


def test_pop_returns_text_and_deletes():
    fake_cache = MagicMock()
    fake_cache.get.return_value = "fever"
    with patch(
        "scheduling_with_rooms.utils.rfv_cache.get_cache", return_value=fake_cache
    ):
        result = rfv_cache.pop("p1", "prov1", datetime.datetime(2026, 5, 7))
        assert result == "fever"
        delete_calls = [c for c in fake_cache.mock_calls if "delete" in str(c)]
        assert len(delete_calls) == 1


def test_pop_non_string_returns_empty_string():
    fake_cache = MagicMock()
    fake_cache.get.return_value = 123  # corrupted cache value
    with patch(
        "scheduling_with_rooms.utils.rfv_cache.get_cache", return_value=fake_cache
    ):
        result = rfv_cache.pop("p1", "prov1", datetime.datetime(2026, 5, 7))
        assert result == ""
