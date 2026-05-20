"""Tests for ProfileApplication."""

import json
from unittest.mock import MagicMock

from canvas_sdk.effects import EffectType
from canvas_sdk.effects.launch_modal import LaunchModalEffect

from patient_portal_profile.applications.profile_application import ProfileApplication


def test_on_open_returns_launch_modal_effect_for_page() -> None:
    """on_open returns a LaunchModalEffect with PAGE target pointed at the SimpleAPI URL."""
    app = ProfileApplication(event=MagicMock())

    effect = app.on_open()

    assert effect.type == EffectType.LAUNCH_MODAL
    data = json.loads(effect.payload)["data"]
    assert data["url"] == "/plugin-io/api/patient_portal_profile/app/profile"
    assert data["target"] == LaunchModalEffect.TargetType.PAGE.value
