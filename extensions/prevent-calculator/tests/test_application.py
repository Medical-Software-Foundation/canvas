"""Tests for the chart-tab Application entry point."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, PropertyMock, patch

from prevent_calculator.applications.prevent_app import PreventCalculatorApp


def test_on_open_emits_launch_modal_with_patient_id() -> None:
    app = PreventCalculatorApp(event=MagicMock())
    with patch.object(
        type(app),
        "context",
        new_callable=PropertyMock,
        return_value={"patient": {"id": "patient-app-99"}},
    ):
        effect = app.on_open()

    payload = json.loads(effect.payload)
    assert "patient-app-99" in payload["data"]["url"]
    assert "/plugin-io/api/prevent_calculator/calculator" in payload["data"]["url"]
    assert payload["data"]["target"] == "right_chart_pane_large"
    assert payload["data"]["title"] == "PREVENT CVD Risk Calculator"
