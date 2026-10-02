"""Tests for ClinicalFavoritesChartApp."""

from unittest.mock import MagicMock, patch

from clinical_favorites.applications.clinical_favorites_chart_app import (
    ClinicalFavoritesChartApp,
)


class TestClinicalFavoritesChartApp:
    """Tests for the patient chart insertion application."""

    @patch("clinical_favorites.applications.clinical_favorites_chart_app.render_to_string")
    @patch("clinical_favorites.applications.clinical_favorites_chart_app.LaunchModalEffect")
    def test_on_open_pins_patient_from_context_into_view(
        self,
        mock_launch_modal: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        mock_event = MagicMock()
        mock_event.context = {
            "patient": {"id": "patient-uuid-9"},
            "user": {"id": "staff-uuid-1"},
        }
        app = ClinicalFavoritesChartApp(mock_event)

        mock_render.return_value = "<html/>"
        mock_effect = MagicMock()
        mock_effect.apply.return_value = "applied_effect"
        mock_launch_modal.return_value = mock_effect

        result = app.on_open()

        assert result == "applied_effect"

        render_calls = mock_render.mock_calls
        assert len(render_calls) == 1
        assert render_calls[0].args[0] == "templates/favorites_chart_template.html"
        context = render_calls[0].args[1]
        assert context["patient_id"] == "patient-uuid-9"
        assert context["staff_id"] == "staff-uuid-1"

        constructor_call = mock_launch_modal.mock_calls[0]
        assert constructor_call.kwargs["content"] == "<html/>"
        assert constructor_call.kwargs["title"] == "Insert Favorites"
        assert (
            constructor_call.kwargs["target"]
            is mock_launch_modal.TargetType.RIGHT_CHART_PANE_LARGE
        )

    @patch("clinical_favorites.applications.clinical_favorites_chart_app.render_to_string")
    @patch("clinical_favorites.applications.clinical_favorites_chart_app.LaunchModalEffect")
    def test_on_open_handles_missing_patient_context(
        self,
        mock_launch_modal: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        mock_event = MagicMock()
        mock_event.context = {}
        app = ClinicalFavoritesChartApp(mock_event)

        mock_render.return_value = "<html/>"
        mock_effect = MagicMock()
        mock_effect.apply.return_value = "applied_effect"
        mock_launch_modal.return_value = mock_effect

        result = app.on_open()

        assert result == "applied_effect"
        context = mock_render.mock_calls[0].args[1]
        assert context["patient_id"] == ""
        assert context["staff_id"] == ""

    def test_chart_template_boots_chart_surface_with_pinned_patient(self) -> None:
        import pathlib

        template_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "clinical_favorites"
            / "templates"
            / "favorites_chart_template.html"
        )
        content = template_path.read_text()
        # The chart surface pins the patient from context and boots the shared
        # module as the chart surface, with the insert markers present and the
        # patient search picker gone.
        assert 'patientId: "{{ patient_id }}"' in content
        assert 'surface: "chart"' in content
        assert 'id="note-picker"' in content
        assert 'id="type-tabs-insert"' in content
        assert 'id="patient-picker"' not in content
        assert "/routes/static/favorites.js" in content

    def test_shared_module_reads_pinned_patient_from_boot(self) -> None:
        import pathlib

        js_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "clinical_favorites"
            / "static"
            / "favorites.js"
        )
        content = js_path.read_text()
        assert "window.FAVORITES_BOOT" in content
        assert "FAVORITES_BOOT.patientId" in content
        assert "const FAVORITES_SURFACE" in content
