"""DexcomChartApp: ``on_open`` returns a properly-targeted modal effect."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, PropertyMock, patch

from dexcom_cgm_viewer.applications.dexcom_chart_app import DexcomChartApp


def test_on_open_emits_launch_modal_with_patient_id() -> None:
    app = DexcomChartApp(event=MagicMock())
    with patch.object(
        type(app),
        "context",
        new_callable=PropertyMock,
        return_value={"patient": {"id": "patient-cgm-1"}},
    ):
        effect = app.on_open()

    payload = json.loads(effect.payload)
    assert "patient-cgm-1" in payload["data"]["url"]
    assert "/plugin-io/api/dexcom_cgm_viewer/" in payload["data"]["url"]
    assert payload["data"]["target"] == "right_chart_pane_large"
    assert payload["data"]["title"] == "Dexcom CGM"
