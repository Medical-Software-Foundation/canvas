"""Tests for the app-drawer entry point."""

from unittest.mock import MagicMock, call, patch

from canvas_theme_kit.applications.admin_app import ThemeEditorApp

APP = "canvas_theme_kit.applications.admin_app"


class TestThemeEditorApp:
    def test_renders_the_editor_into_a_modal(self) -> None:
        app = ThemeEditorApp.__new__(ThemeEditorApp)

        with patch(f"{APP}.render_to_string") as mock_render, \
             patch(f"{APP}.LaunchModalEffect") as mock_modal:
            mock_render.return_value = "<html></html>"
            mock_modal.return_value.apply.return_value = MagicMock()

            app.on_open()

        assert mock_render.mock_calls == [call("templates/admin.html")]
        assert mock_modal.call_args.kwargs["content"] == "<html></html>"
        assert mock_modal.call_args.kwargs["title"] == "Theme Kit"

    def test_returns_the_applied_effect(self) -> None:
        app = ThemeEditorApp.__new__(ThemeEditorApp)
        effect = MagicMock()

        with patch(f"{APP}.render_to_string", return_value=""), \
             patch(f"{APP}.LaunchModalEffect") as mock_modal:
            mock_modal.return_value.apply.return_value = effect

            assert app.on_open() is effect

    def test_rendering_the_shell_grants_no_privileges(self) -> None:
        """Opening the app must not itself be an authorization decision.

        The modal is rendered for any staff member who can see the app drawer.
        Every read and write it performs goes back through ThemeAdminAPI, which
        re-checks the session and the role allowlist per request — so an
        unauthorized user gets an explanatory error from the API rather than an
        editor that looks functional until they try to save.
        """
        app = ThemeEditorApp.__new__(ThemeEditorApp)

        with patch(f"{APP}.render_to_string", return_value="<html></html>") as render, \
             patch(f"{APP}.LaunchModalEffect"):
            app.on_open()

        # No authorization call is made here, by design.
        assert render.mock_calls == [call("templates/admin.html")]


class TestThemeEditorMenuItem:
    """The provider-menu entry is the same editor at a second scope."""

    def test_inherits_the_editor_behavior(self) -> None:
        from canvas_theme_kit.applications.admin_app import ThemeEditorMenuItem

        app = ThemeEditorMenuItem.__new__(ThemeEditorMenuItem)

        with patch(f"{APP}.render_to_string") as mock_render, \
             patch(f"{APP}.LaunchModalEffect") as mock_modal:
            mock_render.return_value = "<html>editor</html>"
            app.on_open()

        assert mock_render.mock_calls == [call("templates/admin.html")]
        assert mock_modal.call_args.kwargs["title"] == "Theme Kit"

    def test_is_a_distinct_class_so_it_can_hold_its_own_scope(self) -> None:
        # Scope lives in the manifest, keyed by class path, so a second surface
        # needs a second class rather than a second entry for the same one.
        from canvas_theme_kit.applications.admin_app import (
            ThemeEditorApp,
            ThemeEditorMenuItem,
        )

        assert issubclass(ThemeEditorMenuItem, ThemeEditorApp)
        assert ThemeEditorMenuItem is not ThemeEditorApp
