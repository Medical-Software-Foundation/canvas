"""Tests for VaccineCardApplication."""

import json
from unittest.mock import MagicMock

from canvas_sdk.effects import EffectType
from canvas_sdk.effects.launch_modal import LaunchModalEffect

from portal_vaccine_card.applications.vaccine_card_application import (
    VaccineCardApplication,
)


def test_on_open_returns_launch_modal_effect_for_page() -> None:
    """on_open returns a LaunchModalEffect with PAGE target pointed at the SimpleAPI URL."""
    app = VaccineCardApplication(event=MagicMock())

    effect = app.on_open()

    assert effect.type == EffectType.LAUNCH_MODAL
    data = json.loads(effect.payload)["data"]
    assert data["url"].startswith("/plugin-io/api/portal_vaccine_card/app/card?v=")
    assert data["target"] == LaunchModalEffect.TargetType.PAGE.value
