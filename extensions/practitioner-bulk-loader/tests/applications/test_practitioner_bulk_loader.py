"""Tests for practitioner_bulk_loader.applications.practitioner_bulk_loader."""

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from practitioner_bulk_loader.applications.practitioner_bulk_loader import (
    PractitionerBulkLoaderApp,
    _APP_HTML,
)


class TestPractitionerBulkLoaderApp:
    def _make_app(self):
        app = PractitionerBulkLoaderApp.__new__(PractitionerBulkLoaderApp)
        return app

    def test_on_open_returns_launch_modal_effect(self):
        app = self._make_app()
        result = app.on_open()
        # The effect is a protobuf Effect — verify it stringifies as a LAUNCH_MODAL
        result_str = str(result)
        assert "LAUNCH_MODAL" in result_str

    def test_html_contains_api_base(self):
        assert "/plugin-io/api/practitioner_bulk_loader/bulk-upload" in _APP_HTML

    def test_html_contains_all_three_states(self):
        assert "state-upload" in _APP_HTML
        assert "state-preview" in _APP_HTML
        assert "state-results" in _APP_HTML

    def test_html_contains_drop_zone(self):
        assert "drop-zone" in _APP_HTML

    def test_html_contains_copy_staff_keys(self):
        assert "copyStaffKeys" in _APP_HTML

    def test_html_contains_download_results_csv(self):
        assert "downloadResultsCsv" in _APP_HTML
