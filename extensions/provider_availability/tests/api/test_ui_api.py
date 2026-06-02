"""Tests for provider_availability.api.ui_api."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.api.ui_api import ACCESS_DENIED_HTML, UIApi

UI_MODULE = "provider_availability.api.ui_api"


# ── Helpers ──────────────────────────────────────────────────────────────


_STAFF_HEX = "5e4fb0011234567890abcdef01234567"  # undashed (Staff.id form)
_STAFF_DASHED = "5e4fb001-1234-5678-90ab-cdef01234567"  # same UUID, dashed
_OTHER_HEX = "aa11bb22cc33dd44ee55ff6677889900"


def _make_ui_handler(staff_id: str | None = _STAFF_HEX, secrets: dict | None = None) -> UIApi:
    """Create a UIApi handler with a header-based request mock."""
    mock_event = MagicMock()
    handler = UIApi(mock_event)
    handler.request = MagicMock()
    handler.request.headers = (
        {"canvas-logged-in-user-id": staff_id} if staff_id is not None else {}
    )
    handler.secrets = secrets or {}
    return handler


# ── get_admin_ui ─────────────────────────────────────────────────────────


class TestGetAdminUI:
    @patch(f"{UI_MODULE}.render_admin_page", return_value="<html>Admin Page</html>")
    def test_empty_secret_allows_any_staff(self, mock_render):
        """Unset/empty allowed-staff-keys → any logged-in staff is allowed."""
        handler = _make_ui_handler(staff_id=_STAFF_HEX, secrets={})
        result = handler.get_admin_ui()
        assert result[0].status_code == HTTPStatus.OK
        assert "Admin Page" in result[0].content.decode()
        assert mock_render.mock_calls == [call()]

    @patch(f"{UI_MODULE}.render_admin_page", return_value="<html>Admin Page</html>")
    def test_access_granted_listed_staff_undashed(self, mock_render):
        """Caller staff_id (undashed) matches an undashed entry in the secret."""
        handler = _make_ui_handler(
            staff_id=_STAFF_HEX,
            secrets={"allowed-staff-keys": _STAFF_HEX},
        )
        result = handler.get_admin_ui()
        assert result[0].status_code == HTTPStatus.OK
        assert "Admin Page" in result[0].content.decode()
        assert mock_render.mock_calls == [call()]

    @patch(f"{UI_MODULE}.render_admin_page", return_value="<html>Admin Page</html>")
    def test_dashed_secret_matches_undashed_header(self, mock_render):
        """Regression for PR #339-comment: dashed UUID in secret + undashed header → allowed."""
        handler = _make_ui_handler(
            staff_id=_STAFF_HEX,
            secrets={"allowed-staff-keys": _STAFF_DASHED},
        )
        result = handler.get_admin_ui()
        assert result[0].status_code == HTTPStatus.OK
        assert "Admin Page" in result[0].content.decode()
        assert mock_render.mock_calls == [call()]

    def test_access_denied_unlisted_staff(self):
        handler = _make_ui_handler(
            staff_id=_OTHER_HEX,
            secrets={"allowed-staff-keys": _STAFF_HEX},
        )
        result = handler.get_admin_ui()
        assert result[0].status_code == HTTPStatus.FORBIDDEN
        assert "Access Denied" in result[0].content.decode()

    def test_missing_header_denied_when_secret_set(self):
        handler = _make_ui_handler(
            staff_id=None,
            secrets={"allowed-staff-keys": _STAFF_HEX},
        )
        result = handler.get_admin_ui()
        assert result[0].status_code == HTTPStatus.FORBIDDEN


# ── get_admin_css ────────────────────────────────────────────────────────


class TestGetAdminCSS:
    @patch(f"{UI_MODULE}.render_to_string", return_value="body { color: red; }")
    def test_returns_css_content(self, mock_render):
        """Returns the CSS file content with 200 status."""
        handler = _make_ui_handler()
        result = handler.get_admin_css()

        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        content = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
        assert "color: red" in content
        assert mock_render.mock_calls == [call("static/css/admin.css")]

    @patch(f"{UI_MODULE}.render_to_string", return_value="body { color: red; }")
    def test_content_type_is_css(self, mock_render):
        """Content-Type header is set to text/css."""
        handler = _make_ui_handler()
        result = handler.get_admin_css()

        resp = result[0]
        assert resp.headers.get("Content-Type") == "text/css"
        assert mock_render.mock_calls == [call("static/css/admin.css")]

    @patch(f"{UI_MODULE}.render_to_string", return_value="body { color: red; }")
    def test_cache_control_no_cache(self, mock_render):
        """Cache-Control header is set to no-cache."""
        handler = _make_ui_handler()
        result = handler.get_admin_css()

        resp = result[0]
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert mock_render.mock_calls == [call("static/css/admin.css")]


# ── get_admin_js ─────────────────────────────────────────────────────────


class TestGetAdminJS:
    @patch(f"{UI_MODULE}.render_to_string", return_value="console.log('hello');")
    def test_returns_js_content(self, mock_render):
        """Returns the JS file content with 200 status."""
        handler = _make_ui_handler()
        result = handler.get_admin_js()

        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        content = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
        assert "console.log" in content
        assert mock_render.mock_calls == [call("static/js/admin.js")]

    @patch(f"{UI_MODULE}.render_to_string", return_value="console.log('hello');")
    def test_content_type_is_javascript(self, mock_render):
        """Content-Type header is set to application/javascript."""
        handler = _make_ui_handler()
        result = handler.get_admin_js()

        resp = result[0]
        assert resp.headers.get("Content-Type") == "application/javascript"
        assert mock_render.mock_calls == [call("static/js/admin.js")]

    @patch(f"{UI_MODULE}.render_to_string", return_value="console.log('hello');")
    def test_cache_control_no_cache(self, mock_render):
        """Cache-Control header is set to no-cache."""
        handler = _make_ui_handler()
        result = handler.get_admin_js()

        resp = result[0]
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert mock_render.mock_calls == [call("static/js/admin.js")]
