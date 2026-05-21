"""Tests for provider_availability.api.ui_api."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.api.ui_api import ACCESS_DENIED_HTML, UIApi

UI_MODULE = "provider_availability.api.ui_api"


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_ui_handler(staff_id: str = "staff-1") -> UIApi:
    """Create a UIApi handler with a mocked request."""
    mock_event = MagicMock()
    handler = UIApi(mock_event)
    handler.request = MagicMock()
    handler.request.staff_id = staff_id
    return handler


# ── get_admin_ui ─────────────────────────────────────────────────────────


class TestGetAdminUI:
    @patch(f"{UI_MODULE}.render_admin_page", return_value="<html>Admin Page</html>")
    @patch(f"{UI_MODULE}.get_allowed_staff", return_value=[])
    def test_no_access_restriction_allowed_empty(self, mock_allowed, mock_render):
        """When allowed_staff list is empty, everyone is allowed (bootstrap mode)."""
        handler = _make_ui_handler(staff_id="anyone")
        result = handler.get_admin_ui()

        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        content = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
        assert "Admin Page" in content
        assert mock_allowed.mock_calls == [call()]
        assert mock_render.mock_calls == [call()]

    @patch(f"{UI_MODULE}.get_allowed_staff", return_value=["staff-1", "staff-2"])
    def test_access_denied_unauthorized_staff(self, mock_allowed):
        """Staff not on the allowed list gets 403 Forbidden."""
        handler = _make_ui_handler(staff_id="staff-999")
        result = handler.get_admin_ui()

        resp = result[0]
        assert resp.status_code == HTTPStatus.FORBIDDEN
        content = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
        assert "Access Denied" in content
        assert mock_allowed.mock_calls == [call()]

    @patch(f"{UI_MODULE}.render_admin_page", return_value="<html>Admin Page</html>")
    @patch(f"{UI_MODULE}.get_allowed_staff", return_value=["staff-1", "staff-2"])
    def test_access_granted_authorized_staff(self, mock_allowed, mock_render):
        """Staff on the allowed list gets the admin UI page."""
        handler = _make_ui_handler(staff_id="staff-1")
        result = handler.get_admin_ui()

        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        content = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
        assert "Admin Page" in content
        assert mock_allowed.mock_calls == [call()]
        assert mock_render.mock_calls == [call()]

    @patch(f"{UI_MODULE}.get_allowed_staff", return_value=["staff-1"])
    def test_empty_staff_id_denied(self, mock_allowed):
        """Empty string staff_id is denied when access list is non-empty."""
        handler = _make_ui_handler(staff_id="")
        result = handler.get_admin_ui()

        resp = result[0]
        assert resp.status_code == HTTPStatus.FORBIDDEN
        assert mock_allowed.mock_calls == [call()]

    @patch(f"{UI_MODULE}.get_allowed_staff", return_value=["staff-1"])
    def test_none_staff_id_denied(self, mock_allowed):
        """None staff_id attribute is denied when access list is non-empty."""
        handler = _make_ui_handler()
        handler.request.staff_id = None
        result = handler.get_admin_ui()

        resp = result[0]
        assert resp.status_code == HTTPStatus.FORBIDDEN
        assert mock_allowed.mock_calls == [call()]


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
