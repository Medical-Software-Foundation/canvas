"""Tests for practitioner_bulk_loader.applications.practitioner_bulk_loader."""

from unittest.mock import MagicMock

from practitioner_bulk_loader.applications.practitioner_bulk_loader import (
    PractitionerBulkLoaderApp,
    _APP_HTML,
)


class TestPractitionerBulkLoaderApp:
    def _make_app(self, staff_id="a" * 32, allowed="a" * 32):
        app = PractitionerBulkLoaderApp.__new__(PractitionerBulkLoaderApp)
        app.event = MagicMock()
        app.event.context = {"user": {"id": staff_id, "type": "Staff"}}
        app.secrets = {"BULK_LOADER_ALLOWED_STAFF_KEYS": allowed}
        return app

    def test_listed_staff_see_the_app(self):
        assert self._make_app().visible() is True

    def test_unlisted_staff_do_not_see_the_app(self):
        assert self._make_app(staff_id="b" * 32).visible() is False

    def test_nobody_sees_the_app_when_the_list_is_empty(self):
        assert self._make_app(allowed="").visible() is False

    def test_unlisted_staff_opening_directly_get_a_refusal(self):
        result = str(self._make_app(staff_id="b" * 32).on_open())
        assert "LAUNCH_MODAL" in result
        assert "access list" in result
        assert "drop-zone" not in result

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
