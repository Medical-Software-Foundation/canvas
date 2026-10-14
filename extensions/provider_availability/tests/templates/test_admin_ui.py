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
        assert "preloaded_script" not in html

    def test_escapes_script_tags(self):
        data = {"payload": "</script><script>alert(1)</script>"}
        html = render_admin_page(data)
        assert "</script><script>" not in html
        assert "\\u003c/script>" in html

    def test_comment_open_in_data_cannot_swallow_the_page_script(self):
        """A reason containing "<!--<script" would otherwise eat the admin.js tag."""
        html = render_admin_page({"reason": "x<!--<script"})
        preload = html[html.index("window.__PRELOADED__="):]
        preload = preload[: preload.index("</script>")]
        assert "<" not in preload

    def test_escaped_data_reads_back_unchanged(self):
        import json

        data = {"reason": "a<b </script> <!--"}
        html = render_admin_page(data)
        preload = html[html.index("window.__PRELOADED__=") + len("window.__PRELOADED__="):]
        assert json.loads(preload[: preload.index(";</script>")]) == data

    def test_preserves_data_integrity(self):
        data = {"key": "value/with/slashes"}
        html = render_admin_page(data)
        assert "value/with/slashes" in html

    def test_bulk_import_is_a_settings_section_not_a_tab(self):
        """Bulk import is a set-once task, so it sits inside Settings."""
        html = render_admin_page(None)
        settings = html[html.index('<canvas-tab-panel id="panel-settings">'):]
        settings = settings[: settings.index("</canvas-tab-panel>")]
        assert 'id="settings-bulk-import"' in settings
        assert 'onclick="bulkUploadValidate()"' in settings
        assert "panel-bulk-import" not in html
        assert html.count("<canvas-tab for=") == 3

    def test_every_placeholder_is_filled(self):
        """The page is a Django template now; no placeholder should reach the browser."""
        html = render_admin_page({"k": "v"})
        assert "{{" not in html
        assert "cache_bust" not in html
        assert "admin.js?v=" in html

    def test_stamp_is_taken_when_the_page_is_built(self):
        """The asset stamp comes from the request, so an update can never leave an old one behind."""
        from unittest.mock import patch
        import datetime as dt

        fixed = dt.datetime(2026, 10, 8, 22, 30, tzinfo=dt.timezone.utc)
        with patch("provider_availability.templates.admin_ui.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            html = render_admin_page(None)
        assert f"admin.js?v={int(fixed.timestamp())}" in html

    def test_expired_banner_and_no_show_all_button(self):
        html = render_admin_page(None)
        assert 'id="expired-banner"' in html
        assert 'id="expired-panel"' in html
        assert 'onclick="removeExpired()"' in html
        assert "showAllProviders" not in html
