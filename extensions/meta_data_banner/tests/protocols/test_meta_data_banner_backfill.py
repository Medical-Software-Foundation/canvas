"""Tests for the MetaDataBannerBackfill cron task."""
from unittest.mock import MagicMock, patch
import pytest

from meta_data_banner.protocols.meta_data_banner_backfill import (
    MetaDataBannerBackfill,
    CURSOR_KEY,
    CURSOR_DONE,
    TEMPLATE_KEY,
    PAGE_SIZE,
)
from tests.conftest import make_metadata_entry

TEMPLATE = "Status: {ccm_diagnosis}"


class FakeCache:
    """Minimal stateful stand-in for the plugin cache."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value, timeout_seconds=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def task():
    t = MetaDataBannerBackfill.__new__(MetaDataBannerBackfill)
    t.secrets = {"BANNER_TEMPLATE": TEMPLATE}
    return t


def make_patient(dbid):
    p = MagicMock()
    p.id = f"patient-{dbid}"
    p.dbid = dbid
    p.metadata.all.return_value = [make_metadata_entry("ccm_diagnosis", "Active")]
    return p


def wire_queryset(mock_patient_cls, patients):
    """Wire filter().order_by().prefetch_related()[:PAGE_SIZE] to return patients."""
    qs = MagicMock()
    qs.__getitem__.return_value = patients
    (
        mock_patient_cls.objects.filter.return_value.order_by.return_value.prefetch_related.return_value
    ) = qs


def filter_kwargs(mock_patient_cls):
    _, kwargs = mock_patient_cls.objects.filter.call_args
    return kwargs


class TestExecute:
    def test_no_template_returns_empty(self, task):
        task.secrets = {}
        assert task.execute() == []

    @patch("meta_data_banner.protocols.meta_data_banner_backfill.get_cache")
    @patch("meta_data_banner.protocols.meta_data_banner_backfill.Patient")
    def test_first_run_starts_sweep_from_zero(self, mock_patient_cls, mock_get_cache, task):
        cache = FakeCache()  # empty: never swept before
        mock_get_cache.return_value = cache
        wire_queryset(mock_patient_cls, [make_patient(i) for i in range(1, PAGE_SIZE + 1)])

        result = task.execute()

        assert filter_kwargs(mock_patient_cls) == {"active": True, "dbid__gt": 0}
        assert cache.get(TEMPLATE_KEY) == TEMPLATE
        assert cache.get(CURSOR_KEY) == PAGE_SIZE  # full page advances the cursor
        assert len(result) == PAGE_SIZE

    @patch("meta_data_banner.protocols.meta_data_banner_backfill.get_cache")
    @patch("meta_data_banner.protocols.meta_data_banner_backfill.Patient")
    def test_full_page_advances_cursor(self, mock_patient_cls, mock_get_cache, task):
        cache = FakeCache({TEMPLATE_KEY: TEMPLATE, CURSOR_KEY: 100})
        mock_get_cache.return_value = cache
        wire_queryset(mock_patient_cls, [make_patient(i) for i in range(101, 101 + PAGE_SIZE)])

        result = task.execute()

        assert filter_kwargs(mock_patient_cls) == {"active": True, "dbid__gt": 100}
        assert cache.get(CURSOR_KEY) == 100 + PAGE_SIZE
        assert len(result) == PAGE_SIZE

    @patch("meta_data_banner.protocols.meta_data_banner_backfill.get_cache")
    @patch("meta_data_banner.protocols.meta_data_banner_backfill.Patient")
    def test_partial_page_goes_dormant(self, mock_patient_cls, mock_get_cache, task):
        cache = FakeCache({TEMPLATE_KEY: TEMPLATE, CURSOR_KEY: 100})
        mock_get_cache.return_value = cache
        wire_queryset(mock_patient_cls, [make_patient(101), make_patient(102)])

        result = task.execute()

        assert cache.get(CURSOR_KEY) == CURSOR_DONE
        assert len(result) == 2

    @patch("meta_data_banner.protocols.meta_data_banner_backfill.get_cache")
    @patch("meta_data_banner.protocols.meta_data_banner_backfill.Patient")
    def test_empty_page_goes_dormant(self, mock_patient_cls, mock_get_cache, task):
        cache = FakeCache({TEMPLATE_KEY: TEMPLATE, CURSOR_KEY: 5000})
        mock_get_cache.return_value = cache
        wire_queryset(mock_patient_cls, [])

        result = task.execute()

        assert cache.get(CURSOR_KEY) == CURSOR_DONE
        assert result == []

    @patch("meta_data_banner.protocols.meta_data_banner_backfill.get_cache")
    @patch("meta_data_banner.protocols.meta_data_banner_backfill.Patient")
    def test_dormant_returns_empty_without_querying(self, mock_patient_cls, mock_get_cache, task):
        cache = FakeCache({TEMPLATE_KEY: TEMPLATE, CURSOR_KEY: CURSOR_DONE})
        mock_get_cache.return_value = cache

        result = task.execute()

        assert result == []
        # Dormant tick must not scan patients...
        mock_patient_cls.objects.filter.assert_not_called()
        # ...but refreshes the template key so dormancy doesn't expire.
        assert cache.get(TEMPLATE_KEY) == TEMPLATE

    @patch("meta_data_banner.protocols.meta_data_banner_backfill.get_cache")
    @patch("meta_data_banner.protocols.meta_data_banner_backfill.Patient")
    def test_template_change_restarts_sweep(self, mock_patient_cls, mock_get_cache, task):
        # Previously dormant on an older template.
        cache = FakeCache({TEMPLATE_KEY: "Old: {foo}", CURSOR_KEY: CURSOR_DONE})
        mock_get_cache.return_value = cache
        wire_queryset(mock_patient_cls, [make_patient(i) for i in range(1, PAGE_SIZE + 1)])

        result = task.execute()

        # Detected the change, restarted from the beginning, stored new template.
        assert filter_kwargs(mock_patient_cls) == {"active": True, "dbid__gt": 0}
        assert cache.get(TEMPLATE_KEY) == TEMPLATE
        assert cache.get(CURSOR_KEY) == PAGE_SIZE
        assert len(result) == PAGE_SIZE
