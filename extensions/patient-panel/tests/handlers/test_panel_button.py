"""Tests for PanelButton ActionButton handler.

No canvas_sdk mocking — real LaunchModalEffect is invoked and its payload
inspected.
"""

import json

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton


class TestPanelButton:
    def test_inherits_action_button(self) -> None:
        from patient_panel.handlers.panel_button import PanelButton
        assert issubclass(PanelButton, ActionButton)

    def test_button_title(self) -> None:
        from patient_panel.handlers.panel_button import PanelButton
        assert PanelButton.BUTTON_TITLE == "Patient Panel"

    def test_button_key(self) -> None:
        from patient_panel.handlers.panel_button import PanelButton
        assert PanelButton.BUTTON_KEY == "OPEN_PATIENT_PANEL"

    def test_button_location(self) -> None:
        from patient_panel.handlers.panel_button import PanelButton
        assert PanelButton.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_HEADER

    def test_handle_returns_launch_modal_with_correct_url_and_target(self) -> None:
        from patient_panel.handlers.panel_button import PanelButton

        handler = PanelButton.__new__(PanelButton)
        effects = handler.handle()
        assert len(effects) == 1

        payload = effects[0].payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        # LaunchModalEffect.apply() returns an Effect carrying the modal
        # config. The exact key for the URL has evolved; check both common
        # shapes and assert the panel URL is present.
        serialized = json.dumps(payload)
        assert "/plugin-io/api/patient_panel/app/" in serialized
        # Target is PAGE — the enum value (string) should appear in payload
        target_value = LaunchModalEffect.TargetType.PAGE.value
        assert target_value in serialized
