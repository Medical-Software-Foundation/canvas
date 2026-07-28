import json
from unittest.mock import MagicMock


class TestBulkSurescriptsApp:
    @staticmethod
    def _payload():
        from surescripts_med_history.applications.bulk_requests import (
            BulkSurescriptsApp,
        )

        app = BulkSurescriptsApp.__new__(BulkSurescriptsApp)
        app.event = MagicMock()
        return json.loads(app.on_open().payload)["data"]

    def test_opens_the_bulk_page(self):
        """The URL is the only link between the menu item and the API, and a
        typo here fails silently at click time."""
        url = self._payload()["url"]
        assert url.startswith("/plugin-io/api/surescripts_med_history/bulk/page")

    def test_url_is_cache_busted(self):
        from surescripts_med_history.applications import bulk_requests

        assert self._payload()["url"].endswith("?v=%s" % bulk_requests._CACHE_BUST)
        assert bulk_requests._CACHE_BUST.isdigit()

    def test_opens_as_a_full_page(self):
        assert self._payload()["target"] == "page"
