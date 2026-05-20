"""Tests for the OrderSetsApp launcher."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from order_sets.applications.order_sets_app import OrderSetsApp


def _make_app(patient_id: str) -> OrderSetsApp:
    app = object.__new__(OrderSetsApp)
    app.event = SimpleNamespace(context={"patient": {"id": patient_id}})
    app.secrets = {}
    app.environment = {}
    return app


def test_on_open_returns_an_applied_launch_modal_effect(mocker: MagicMock) -> None:
    """on_open should build a LaunchModalEffect and return its .apply() result."""
    fake_apply = mocker.patch(
        "order_sets.applications.order_sets_app.LaunchModalEffect.__init__",
        return_value=None,
    )
    apply_mock = mocker.patch(
        "order_sets.applications.order_sets_app.LaunchModalEffect.apply",
        return_value="APPLIED",
    )

    app = _make_app("patient-123")
    result = app.on_open()

    assert result == "APPLIED"
    apply_mock.assert_called_once()
    # The first __init__ call should have received the loader HTML and target.
    _, kwargs = fake_apply.call_args
    assert "patient_id=patient-123" in kwargs["content"]
    # Target is RIGHT_CHART_PANE for patient_specific apps.
    from canvas_sdk.effects.launch_modal import LaunchModalEffect

    assert kwargs["target"] == LaunchModalEffect.TargetType.RIGHT_CHART_PANE


def test_on_open_handles_missing_patient_id(mocker: MagicMock) -> None:
    """If event context has no patient.id, the URL still renders (empty id)."""
    fake_init = mocker.patch(
        "order_sets.applications.order_sets_app.LaunchModalEffect.__init__",
        return_value=None,
    )
    mocker.patch(
        "order_sets.applications.order_sets_app.LaunchModalEffect.apply",
        return_value="APPLIED",
    )

    app = object.__new__(OrderSetsApp)
    app.event = SimpleNamespace(context={})  # no patient at all
    app.secrets = {}
    app.environment = {}

    result = app.on_open()
    assert result == "APPLIED"
    _, kwargs = fake_init.call_args
    assert "patient_id=" in kwargs["content"]
    # spinner / loader is included so user sees feedback while fetching
    assert "Loading Order Sets" in kwargs["content"]
