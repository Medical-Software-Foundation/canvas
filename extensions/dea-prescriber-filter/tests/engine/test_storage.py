"""Tests for engine/storage.py — cache-based delegation storage."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


@pytest.fixture
def mock_cache():
    """Shared mock cache for patching get_cache()."""
    return MagicMock()


def test_get_all_delegations_returns_empty_when_no_index(mock_cache) -> None:
    mock_cache.get.return_value = None
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache) as mock_get_cache:
        from dea_prescriber_filter.engine.storage import get_all_delegations

        result = get_all_delegations()

        assert mock_get_cache.mock_calls == [call()]
        assert mock_cache.mock_calls == [call.get("dea:delegations:index")]
    assert result == {}


def test_get_all_delegations_returns_empty_when_index_empty_list(mock_cache) -> None:
    mock_cache.get.return_value = []
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import get_all_delegations

        result = get_all_delegations()

    assert result == {}
    assert mock_cache.mock_calls == [call.get("dea:delegations:index")]


def test_get_all_delegations_returns_all_valid_delegations(mock_cache) -> None:
    mock_cache.get.side_effect = [
        ["prov1", "prov2"],
        ["staff1", "staff2"],
        ["staff3"],
    ]
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import get_all_delegations

        result = get_all_delegations()

    assert result == {"prov1": ["staff1", "staff2"], "prov2": ["staff3"]}
    assert mock_cache.mock_calls == [
        call.get("dea:delegations:index"),
        call.get("dea:delegation:prov1"),
        call.get("dea:delegation:prov2"),
    ]


def test_get_all_delegations_skips_missing_provider_entries(mock_cache) -> None:
    mock_cache.get.side_effect = [
        ["prov1", "prov2"],
        None,
        ["staff3"],
    ]
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import get_all_delegations

        result = get_all_delegations()

    assert result == {"prov2": ["staff3"]}
    assert mock_cache.mock_calls == [
        call.get("dea:delegations:index"),
        call.get("dea:delegation:prov1"),
        call.get("dea:delegation:prov2"),
    ]


def test_get_all_delegations_skips_non_list_values(mock_cache) -> None:
    mock_cache.get.side_effect = [
        ["prov1", "prov2"],
        "not-a-list",
        ["staff3"],
    ]
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import get_all_delegations

        result = get_all_delegations()

    assert result == {"prov2": ["staff3"]}


def test_set_delegation_with_staff_adds_to_index(mock_cache) -> None:
    mock_cache.get.return_value = []
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import CACHE_TTL_SECONDS, set_delegation

        set_delegation("prov1", ["staff1", "staff2"])

    assert mock_cache.mock_calls == [
        call.set("dea:delegation:prov1", ["staff1", "staff2"], timeout_seconds=CACHE_TTL_SECONDS),
        call.get("dea:delegations:index"),
        call.set("dea:delegations:index", ["prov1"], timeout_seconds=CACHE_TTL_SECONDS),
    ]


def test_set_delegation_does_not_duplicate_in_index_and_refreshes_ttl(mock_cache) -> None:
    mock_cache.get.return_value = ["prov1"]
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import CACHE_TTL_SECONDS, set_delegation

        set_delegation("prov1", ["staff1"])

    # Index is not duplicated (still ["prov1"]), but cache.set is called to
    # refresh its TTL so the index can't expire before the per-provider entries.
    assert mock_cache.mock_calls == [
        call.set("dea:delegation:prov1", ["staff1"], timeout_seconds=CACHE_TTL_SECONDS),
        call.get("dea:delegations:index"),
        call.set("dea:delegations:index", ["prov1"], timeout_seconds=CACHE_TTL_SECONDS),
    ]


def test_set_delegation_with_empty_list_removes_delegation(mock_cache) -> None:
    mock_cache.get.return_value = ["prov1"]
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import CACHE_TTL_SECONDS, set_delegation

        set_delegation("prov1", [])

    assert mock_cache.mock_calls == [
        call.delete("dea:delegation:prov1"),
        call.get("dea:delegations:index"),
        call.set("dea:delegations:index", [], timeout_seconds=CACHE_TTL_SECONDS),
    ]


def test_remove_delegation_removes_from_index(mock_cache) -> None:
    mock_cache.get.return_value = ["prov1", "prov2"]
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import CACHE_TTL_SECONDS, remove_delegation

        remove_delegation("prov1")

    assert mock_cache.mock_calls == [
        call.delete("dea:delegation:prov1"),
        call.get("dea:delegations:index"),
        call.set("dea:delegations:index", ["prov2"], timeout_seconds=CACHE_TTL_SECONDS),
    ]


def test_remove_delegation_when_not_in_index(mock_cache) -> None:
    mock_cache.get.return_value = ["prov2"]
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import remove_delegation

        remove_delegation("prov1")

    assert mock_cache.mock_calls == [
        call.delete("dea:delegation:prov1"),
        call.get("dea:delegations:index"),
    ]


def test_remove_delegation_when_index_empty(mock_cache) -> None:
    mock_cache.get.return_value = None
    with patch("dea_prescriber_filter.engine.storage.get_cache", return_value=mock_cache):
        from dea_prescriber_filter.engine.storage import remove_delegation

        remove_delegation("prov1")

    assert mock_cache.mock_calls == [
        call.delete("dea:delegation:prov1"),
        call.get("dea:delegations:index"),
    ]
