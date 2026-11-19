"""ReportBuilderApp.on_open emits a LaunchModalEffect pointing at /app."""

import json
from unittest.mock import MagicMock

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.effects.launch_modal import LaunchModalEffect

from report_builder.handlers.application import ReportBuilderApp


def _open_app() -> Effect:
    event = MagicMock()
    event.context = {}
    return ReportBuilderApp(event=event).on_open()


def test_on_open_returns_launch_modal_effect() -> None:
    effect = _open_app()
    assert effect.type == EffectType.LAUNCH_MODAL


def test_on_open_targets_page_and_carries_cache_bust() -> None:
    effect = _open_app()
    data = json.loads(effect.payload)["data"]
    assert data["target"] == LaunchModalEffect.TargetType.PAGE.value
    assert data["url"].startswith("/plugin-io/api/report_builder/app")
    assert "?v=" in data["url"]
    assert data["title"] == "Report Builder"
