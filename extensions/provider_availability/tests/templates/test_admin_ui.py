"""Tests for provider_availability.templates.admin_ui."""

from __future__ import annotations

from provider_availability.templates.admin_ui import render_admin_page


class TestRenderAdminPage:
    def test_with_preloaded_data(self):
        data = {"providers": [{"name": "Dr. Test"}], "timezone": "US/Eastern"}
        html = render_admin_page(data)
        assert "window.__PRELOADED__=" in html
        assert "Dr. Test" in html

    def test_without_preloaded_data(self):
        html = render_admin_page(None)
        assert "window.__PRELOADED__=" not in html
        assert "{{PRELOADED_SCRIPT}}" not in html

    def test_escapes_script_tags(self):
        data = {"payload": "</script><script>alert(1)</script>"}
        html = render_admin_page(data)
        assert "</script><script>" not in html
        assert "<\\/script>" in html

    def test_preserves_data_integrity(self):
        data = {"key": "value/with/slashes"}
        html = render_admin_page(data)
        assert "value/with/slashes" in html
