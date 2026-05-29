"""Tests for clinical_pathways.applications.builder_app."""

from __future__ import annotations

from clinical_pathways.applications.builder_app import PathwayBuilderApp


class TestPathwayBuilderApp:
    def test_on_open_returns_launch_modal_effect(self, stub_effect_type: type) -> None:
        app = PathwayBuilderApp()
        effect = app.on_open()

        assert isinstance(effect, stub_effect_type)
        assert effect.tag == "LaunchModalEffect"

    def test_on_open_targets_builder_api_url(self, stub_effect_type: type) -> None:
        effect = PathwayBuilderApp().on_open()
        assert isinstance(effect, stub_effect_type)
        assert "/plugin-io/api/clinical_pathways/builder/" in effect.payload["url"]
        assert "?v=" in effect.payload["url"]

    def test_on_open_uses_page_target(self) -> None:
        effect = PathwayBuilderApp().on_open()
        assert effect.payload["target"] == "PAGE"

    def test_on_open_sets_modal_title(self) -> None:
        effect = PathwayBuilderApp().on_open()
        assert effect.payload["title"] == "Pathway Builder"
