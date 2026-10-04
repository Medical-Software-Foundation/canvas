"""Tests for visit_summaries.helpers.config_store."""
from unittest.mock import MagicMock, patch

import pytest

from visit_summaries.helpers.config_store import (
    DEFAULT_CONFIG,
    get_config,
    is_feature_enabled,
    update_config,
)


def _mock_cache():
    """Return a dict-backed mock cache for testing."""
    store = {}
    cache = MagicMock()
    cache.get = lambda key: store.get(key)
    cache.set = lambda key, value: store.__setitem__(key, value)
    return cache


@pytest.fixture(autouse=True)
def mock_plugin_cache():
    """Patch get_cache to use a fresh in-memory dict for each test."""
    cache = _mock_cache()
    with patch("visit_summaries.helpers.config_store._get_cache", return_value=cache):
        yield cache


def test_get_config_returns_defaults():
    config = get_config()
    assert config["enable_previous_visit"] is True
    assert config["enable_since_last_visit"] is True
    assert config["enable_avs"] is True


def test_update_config_persists():
    update_config({"enable_avs": False})
    config = get_config()
    assert config["enable_avs"] is False


def test_update_config_partial_update():
    """Updating one key does not affect other keys."""
    update_config({"enable_previous_visit": False})
    config = get_config()
    assert config["enable_previous_visit"] is False
    assert config["enable_avs"] is True


def test_update_config_returns_merged():
    result = update_config({"enable_previous_visit": False})
    assert result["enable_previous_visit"] is False
    assert "enable_avs" in result


def test_is_feature_enabled_default_true():
    assert is_feature_enabled("enable_previous_visit") is True
    assert is_feature_enabled("enable_since_last_visit") is True
    assert is_feature_enabled("enable_avs") is True


def test_is_feature_enabled_after_disable():
    update_config({"enable_avs": False})
    assert is_feature_enabled("enable_avs") is False


def test_is_feature_enabled_unknown_key_defaults_true():
    """Unknown feature keys fall back to True (permissive default)."""
    assert is_feature_enabled("nonexistent_feature") is True


def test_update_config_multiple_times():
    update_config({"enable_previous_visit": False})
    update_config({"enable_previous_visit": True})
    assert is_feature_enabled("enable_previous_visit") is True


def test_get_config_handles_malformed_cache():
    """When cache contains invalid JSON, fall back to defaults."""
    cache = _mock_cache()
    cache.set("visit_summaries_config", "not valid json{{{")
    with patch("visit_summaries.helpers.config_store._get_cache", return_value=cache):
        config = get_config()
    assert config == DEFAULT_CONFIG


def test_get_config_handles_none_cache():
    """When cache returns None, fall back to defaults."""
    config = get_config()
    assert config == DEFAULT_CONFIG
