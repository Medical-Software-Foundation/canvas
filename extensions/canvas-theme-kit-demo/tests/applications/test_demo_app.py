"""Tests for the provider-menu entry point."""

from unittest.mock import MagicMock, patch

from canvas_theme_kit_demo.applications.demo_app import DEMO_URL, ThemeKitDemoApp

APP = "canvas_theme_kit_demo.applications.demo_app"


class TestThemeKitDemoApp:
    def test_iframes_the_page_rather_than_inlining_it(self) -> None:
        """The demo exists to show the page arriving from the server with its
        token block already in <head>. Passing rendered HTML as `content` would
        skip that request path entirely, so the modal must load it by URL."""
        app = ThemeKitDemoApp.__new__(ThemeKitDemoApp)

        with patch(f"{APP}.LaunchModalEffect") as mock_modal:
            app.on_open()

        kwargs = mock_modal.call_args.kwargs
        assert kwargs["url"] == DEMO_URL
        assert "content" not in kwargs
        assert kwargs["title"] == "Theme Kit Demo"

    def test_url_is_same_origin(self) -> None:
        # A same-origin path needs no url_permissions entry in the manifest.
        assert DEMO_URL.startswith("/plugin-io/api/canvas_theme_kit_demo/")

    def test_returns_the_applied_effect(self) -> None:
        app = ThemeKitDemoApp.__new__(ThemeKitDemoApp)
        effect = MagicMock()

        with patch(f"{APP}.LaunchModalEffect") as mock_modal:
            mock_modal.return_value.apply.return_value = effect

            assert app.on_open() is effect
