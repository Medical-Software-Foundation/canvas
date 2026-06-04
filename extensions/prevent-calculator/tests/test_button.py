"""Tests for the PREVENT calculator action button."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from canvas_sdk.handlers.action_button import ActionButton

from prevent_calculator.protocols.button import PreventCalculatorButton


def test_button_configuration() -> None:
    assert PreventCalculatorButton.BUTTON_TITLE == "PREVENT CVD Score"
    assert PreventCalculatorButton.BUTTON_KEY == "prevent_calculator_open"
    assert (
        PreventCalculatorButton.BUTTON_LOCATION
        == ActionButton.ButtonLocation.CHART_SUMMARY_CONDITIONS_SECTION
    )


def test_handle_emits_launch_modal_effect_with_patient_id() -> None:
    event = MagicMock()
    event.target = SimpleNamespace(id="patient-abc-123")
    button = PreventCalculatorButton(event=event)

    effects = button.handle()

    assert len(effects) == 1
    effect = effects[0]
    payload = effect.payload
    assert "patient-abc-123" in payload
    assert "/plugin-io/api/prevent_calculator/calculator" in payload
    assert "right_chart_pane_large" in payload
    assert "PREVENT CVD Risk Calculator" in payload
