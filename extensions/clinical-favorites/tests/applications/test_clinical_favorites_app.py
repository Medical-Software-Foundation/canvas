"""Tests for ClinicalFavoritesApp."""

from unittest.mock import MagicMock, patch

from clinical_favorites.applications.clinical_favorites_app import ClinicalFavoritesApp


class TestClinicalFavoritesApp:
    """Tests for the ClinicalFavoritesApp provider menu application."""

    @patch("clinical_favorites.applications.clinical_favorites_app.render_to_string")
    @patch("clinical_favorites.applications.clinical_favorites_app.LaunchModalEffect")
    def test_on_open_renders_favorites_template_with_page_target(
        self,
        mock_launch_modal: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        mock_event = MagicMock()
        mock_event.context = {"user": {"id": "staff-uuid-1"}}
        app = ClinicalFavoritesApp(mock_event)

        rendered = (
            "<html><body>"
            "<button class='type-chip'></button>"
            "<select id='note-picker'></select>"
            "<script>fetch('/plugin-io/api/clinical_favorites/routes/insert')</script>"
            "</body></html>"
        )
        mock_render.return_value = rendered
        mock_effect = MagicMock()
        mock_effect.apply.return_value = "applied_effect"
        mock_launch_modal.return_value = mock_effect

        result = app.on_open()

        assert result == "applied_effect"

        render_calls = mock_render.mock_calls
        assert len(render_calls) == 1
        assert render_calls[0].args[0] == "templates/favorites_template.html"
        context = render_calls[0].args[1]
        assert context["staff_id"] == "staff-uuid-1"

        constructor_call = mock_launch_modal.mock_calls[0]
        assert constructor_call.kwargs["content"] == rendered
        assert constructor_call.kwargs["title"] == "Clinical Favorites"
        assert constructor_call.kwargs["target"] is mock_launch_modal.TargetType.PAGE

    def test_management_template_is_management_only(self) -> None:
        import pathlib

        template_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "clinical_favorites"
            / "templates"
            / "favorites_template.html"
        )
        content = template_path.read_text()
        # The management surface keeps its own type tabs, add, and bulk import.
        assert 'id="type-tabs-manage"' in content
        assert 'id="add-favorite-btn"' in content
        assert 'id="bulk-import-btn"' in content
        # It boots the shared module as the management surface.
        assert 'surface: "manage"' in content
        assert "/routes/static/favorites.js" in content
        # Insertion lives on the chart surface only, so none of its markers
        # leak into the management page.
        assert 'id="type-tabs-insert"' not in content
        assert 'id="note-picker"' not in content
        assert 'id="patient-picker"' not in content

    @patch("clinical_favorites.applications.clinical_favorites_app.render_to_string")
    @patch("clinical_favorites.applications.clinical_favorites_app.LaunchModalEffect")
    def test_on_open_handles_missing_user_context(
        self,
        mock_launch_modal: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        mock_event = MagicMock()
        mock_event.context = {}
        app = ClinicalFavoritesApp(mock_event)

        mock_render.return_value = "<html/>"
        mock_effect = MagicMock()
        mock_effect.apply.return_value = "applied_effect"
        mock_launch_modal.return_value = mock_effect

        result = app.on_open()

        assert result == "applied_effect"
        context = mock_render.mock_calls[0].args[1]
        assert context["staff_id"] == ""
