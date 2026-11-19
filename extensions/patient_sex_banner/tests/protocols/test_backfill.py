"""Tests for the BackfillBanners cron task."""
from unittest.mock import MagicMock, patch

import pytest

from patient_sex_banner.protocols.backfill import (
    CURSOR_DONE,
    CURSOR_KEY,
    PAGE_SIZE,
    BackfillBanners,
)

MODULE = "patient_sex_banner.protocols.backfill"


class FakeCache:
    """Minimal stateful stand-in for the plugin cache."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value, timeout_seconds=None):
        self.store[key] = value


@pytest.fixture
def task():
    return BackfillBanners.__new__(BackfillBanners)


def _patient(dbid):
    p = MagicMock()
    p.id = f"patient-{dbid}"
    p.dbid = dbid
    p.sex_at_birth = "O"
    return p


def _wire_queryset(mock_patient_cls, patients):
    """Wire filter().exclude().order_by()[:PAGE_SIZE] to return patients."""
    qs = MagicMock()
    qs.__getitem__.return_value = patients
    mock_patient_cls.objects.filter.return_value.exclude.return_value.order_by.return_value = qs


def _filter_kwargs(mock_patient_cls):
    return mock_patient_cls.objects.filter.call_args.kwargs


@patch(f"{MODULE}.get_cache")
@patch(f"{MODULE}.Patient")
def test_first_run_sweeps_from_zero(mock_patient_cls, mock_get_cache, task):
    cache = FakeCache()  # never swept before
    mock_get_cache.return_value = cache
    _wire_queryset(mock_patient_cls, [_patient(i) for i in range(1, PAGE_SIZE + 1)])

    result = task.execute()

    assert _filter_kwargs(mock_patient_cls) == {"active": True, "dbid__gt": 0}
    assert cache.get(CURSOR_KEY) == PAGE_SIZE  # full page advances the cursor
    assert len(result) == PAGE_SIZE


@patch(f"{MODULE}.get_cache")
@patch(f"{MODULE}.Patient")
def test_full_page_advances_cursor(mock_patient_cls, mock_get_cache, task):
    cache = FakeCache({CURSOR_KEY: 100})
    mock_get_cache.return_value = cache
    _wire_queryset(mock_patient_cls, [_patient(i) for i in range(101, 101 + PAGE_SIZE)])

    result = task.execute()

    assert _filter_kwargs(mock_patient_cls) == {"active": True, "dbid__gt": 100}
    assert cache.get(CURSOR_KEY) == 100 + PAGE_SIZE
    assert len(result) == PAGE_SIZE


@patch(f"{MODULE}.get_cache")
@patch(f"{MODULE}.Patient")
def test_partial_page_goes_dormant(mock_patient_cls, mock_get_cache, task):
    cache = FakeCache({CURSOR_KEY: 100})
    mock_get_cache.return_value = cache
    _wire_queryset(mock_patient_cls, [_patient(101), _patient(102)])

    result = task.execute()

    assert cache.get(CURSOR_KEY) == CURSOR_DONE
    assert len(result) == 2


@patch(f"{MODULE}.get_cache")
@patch(f"{MODULE}.Patient")
def test_empty_page_goes_dormant(mock_patient_cls, mock_get_cache, task):
    cache = FakeCache({CURSOR_KEY: 5000})
    mock_get_cache.return_value = cache
    _wire_queryset(mock_patient_cls, [])

    result = task.execute()

    assert cache.get(CURSOR_KEY) == CURSOR_DONE
    assert result == []


@patch(f"{MODULE}.get_cache")
@patch(f"{MODULE}.Patient")
def test_dormant_returns_empty_without_querying(mock_patient_cls, mock_get_cache, task):
    cache = FakeCache({CURSOR_KEY: CURSOR_DONE})
    mock_get_cache.return_value = cache

    result = task.execute()

    assert result == []
    mock_patient_cls.objects.filter.assert_not_called()  # dormant tick must not scan
    assert cache.get(CURSOR_KEY) == CURSOR_DONE  # marker refreshed so dormancy persists
