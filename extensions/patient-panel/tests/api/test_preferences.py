"""Tests for the per-user column preference ENDPOINTS.

Free-function column logic (get_all_org_columns / get_user_column_prefs /
get_effective_columns) is tested in tests/services/test_columns.py. These
cover the get/save/reset_preferences endpoints on the API class.

No mocking of canvas_sdk. The real plugin cache is used (enabled by
`__is_plugin__ = True` at module level).
"""

__is_plugin__ = True

import json
from http import HTTPStatus

import pytest

from tests._helpers import build_api, cache_delete, cache_get, cache_set


pytestmark = pytest.mark.django_db


def _clear_cache_keys(*keys: str) -> None:
    for key in keys:
        cache_delete(key)


class TestGetPreferencesEndpoint:
    def test_returns_401_when_no_staff_id(self) -> None:
        api = build_api()
        responses = api.get_preferences()
        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_all_columns_with_visibility(self) -> None:
        _clear_cache_keys("column_prefs_pref-1")
        api = build_api(headers={"canvas-logged-in-user-id": "pref-1"})
        responses = api.get_preferences()
        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.OK
        data = json.loads(responses[0].content)
        assert isinstance(data, list)
        keys = [c["key"] for c in data]
        assert "patient" in keys
        for item in data:
            assert "key" in item
            assert "label" in item
            assert "type" in item
            assert "visible" in item

    def test_merges_user_prefs_into_response(self) -> None:
        prefs = {"tasks": False, "next_visit": True}
        cache_key = "column_prefs_pref-2"
        cache_set(cache_key, json.dumps(prefs))
        try:
            api = build_api(headers={"canvas-logged-in-user-id": "pref-2"})
            responses = api.get_preferences()
            data = json.loads(responses[0].content)
            tasks_col = next(c for c in data if c["key"] == "tasks")
            assert tasks_col["visible"] is False
            next_visit_col = next(c for c in data if c["key"] == "next_visit")
            assert next_visit_col["visible"] is True
        finally:
            _clear_cache_keys(cache_key)


class TestSavePreferencesEndpoint:
    def test_returns_401_when_no_staff_id(self) -> None:
        api = build_api()
        responses = api.save_preferences()
        assert responses[0].status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_400_when_no_columns_field(self) -> None:
        api = build_api(headers={"canvas-logged-in-user-id": "save-1"})
        responses = api.save_preferences()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_400_on_invalid_json(self) -> None:
        api = build_api(
            headers={"canvas-logged-in-user-id": "save-2"},
            form_data={"columns": "{bad json"},
        )
        responses = api.save_preferences()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_400_on_invalid_format(self) -> None:
        api = build_api(
            headers={"canvas-logged-in-user-id": "save-3"},
            form_data={"columns": json.dumps({"patient": "not-a-bool"})},
        )
        responses = api.save_preferences()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_saves_valid_preferences(self) -> None:
        prefs = {"patient": True, "tasks": False, "care_team": True}
        cache_key = "column_prefs_save-4"
        _clear_cache_keys(cache_key)
        try:
            api = build_api(
                headers={"canvas-logged-in-user-id": "save-4"},
                form_data={"columns": json.dumps(prefs)},
            )
            responses = api.save_preferences()
            assert responses[0].status_code == HTTPStatus.OK
            cached = cache_get(cache_key)
            assert cached == json.dumps(prefs)
        finally:
            _clear_cache_keys(cache_key)


class TestResetPreferencesEndpoint:
    def test_returns_401_when_no_staff_id(self) -> None:
        api = build_api()
        responses = api.reset_preferences()
        assert responses[0].status_code == HTTPStatus.UNAUTHORIZED

    def test_deletes_cache_entry(self) -> None:
        cache_key = "column_prefs_reset-1"
        cache_set(cache_key, json.dumps({"patient": True}))
        try:
            api = build_api(headers={"canvas-logged-in-user-id": "reset-1"})
            responses = api.reset_preferences()
            assert responses[0].status_code == HTTPStatus.OK
            assert cache_get(cache_key) is None
        finally:
            _clear_cache_keys(cache_key)
