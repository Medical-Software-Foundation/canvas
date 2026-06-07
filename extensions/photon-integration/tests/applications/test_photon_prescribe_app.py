"""Tests for the Photon prescribe Application launcher."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from photon_integration.applications.photon_prescribe_app import PhotonPrescribeApp

MODULE = "photon_integration.applications.photon_prescribe_app"


def _app(context):
    app = PhotonPrescribeApp.__new__(PhotonPrescribeApp)
    app.event = SimpleNamespace(context=context)
    return app


def test_on_open_launches_modal_with_patient():
    app = _app({"patient": {"id": "pat-123"}})
    with patch(f"{MODULE}.LaunchModalEffect") as modal:
        modal.return_value.apply.return_value = "MODAL_EFFECT"
        result = app.on_open()

    assert result == "MODAL_EFFECT"
    kwargs = modal.call_args.kwargs
    assert kwargs["url"] == (
        "/plugin-io/api/photon_integration/photon/?patient_id=pat-123"
    )
    assert kwargs["target"] == modal.TargetType.RIGHT_CHART_PANE_LARGE


def test_on_open_handles_missing_patient():
    app = _app({})
    with patch(f"{MODULE}.LaunchModalEffect") as modal:
        modal.return_value.apply.return_value = "MODAL_EFFECT"
        app.on_open()
    assert modal.call_args.kwargs["url"].endswith("patient_id=")
