from unittest.mock import MagicMock, patch


class TestBulkSurescriptsApp:
    def test_on_open_returns_page_launch_modal(self):
        """on_open should return a single PAGE target LaunchModalEffect pointing at the bulk page route with a cache bust query."""
        from rx_history.applications import bulk_requests as app_module
        from rx_history.applications.bulk_requests import BulkSurescriptsApp

        with patch(
            "rx_history.applications.bulk_requests.LaunchModalEffect"
        ) as mock_modal_cls:
            mock_effect = MagicMock()
            mock_modal_instance = MagicMock()
            mock_modal_instance.apply.return_value = mock_effect
            mock_modal_cls.return_value = mock_modal_instance
            mock_modal_cls.TargetType.PAGE = "page"

            app = BulkSurescriptsApp(event=MagicMock())
            result = app.on_open()

            assert result is mock_effect
            mock_modal_cls.assert_called_once_with(
                url=f"/plugin-io/api/rx_history/bulk/page?v={app_module._CACHE_BUST}",
                target="page",
                title="Surescripts Requests",
            )
            mock_modal_instance.apply.assert_called_once_with()
