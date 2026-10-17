from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


def test_on_open_returns_launch_modal_effect() -> None:
    from scheduling_modal_with_recurring_support.applications.scheduling_app import (
        API_PREFIX,
        PLUGIN_NAME,
        SchedulingApp,
        _CACHE_BUST,
    )

    mock_effect = MagicMock()
    mock_launch = MagicMock()
    mock_launch.apply.return_value = mock_effect

    app = MagicMock(spec=SchedulingApp)
    app.context = {"patient": {"id": "patient-xyz"}}

    with patch(
        "scheduling_modal_with_recurring_support.applications.scheduling_app.LaunchModalEffect",
        return_value=mock_launch,
    ) as mock_lme:
        result = SchedulingApp.on_open(app)

    expected_url = (
        f"/plugin-io/api/{PLUGIN_NAME}/{API_PREFIX}/ui"
        f"?patient_id=patient-xyz&v={_CACHE_BUST}"
    )

    assert mock_lme.mock_calls == [
        call(
            url=expected_url,
            target=mock_lme.call_args[1]["target"],
        )
    ]
    assert mock_launch.mock_calls == [call.apply()]
    assert result is mock_effect


def test_on_open_uses_default_modal() -> None:
    from canvas_sdk.effects.launch_modal import LaunchModalEffect as RealLME

    from scheduling_modal_with_recurring_support.applications.scheduling_app import SchedulingApp

    app = MagicMock(spec=SchedulingApp)
    app.context = {"patient": {"id": "p1"}}

    with patch(
        "scheduling_modal_with_recurring_support.applications.scheduling_app.LaunchModalEffect"
    ) as mock_lme:
        mock_lme.TargetType = RealLME.TargetType
        mock_lme.return_value.apply.return_value = MagicMock()
        SchedulingApp.on_open(app)

    called_target = mock_lme.call_args[1]["target"]
    assert called_target == RealLME.TargetType.DEFAULT_MODAL


def test_on_open_missing_patient_context() -> None:
    from scheduling_modal_with_recurring_support.applications.scheduling_app import SchedulingApp

    app = MagicMock(spec=SchedulingApp)
    app.context = {}

    with patch(
        "scheduling_modal_with_recurring_support.applications.scheduling_app.LaunchModalEffect"
    ) as mock_lme:
        mock_lme.return_value.apply.return_value = MagicMock()
        SchedulingApp.on_open(app)

    called_url: str = mock_lme.call_args[1]["url"]
    assert "patient_id=" in called_url


# ---- GlobalSchedulingApp ----


def test_global_app_on_open_returns_effect() -> None:
    from scheduling_modal_with_recurring_support.applications.scheduling_app import (
        API_PREFIX,
        PLUGIN_NAME,
        GlobalSchedulingApp,
        _CACHE_BUST,
    )

    mock_effect = MagicMock()
    mock_launch = MagicMock()
    mock_launch.apply.return_value = mock_effect

    app = MagicMock(spec=GlobalSchedulingApp)

    with patch(
        "scheduling_modal_with_recurring_support.applications.scheduling_app.LaunchModalEffect",
        return_value=mock_launch,
    ) as mock_lme:
        result = GlobalSchedulingApp.on_open(app)

    expected_url = (
        f"/plugin-io/api/{PLUGIN_NAME}/{API_PREFIX}/ui"
        f"?v={_CACHE_BUST}"
    )

    assert mock_lme.call_args[1]["url"] == expected_url
    assert mock_launch.mock_calls == [call.apply()]
    assert result is mock_effect


def test_global_app_url_has_no_patient_id() -> None:
    from scheduling_modal_with_recurring_support.applications.scheduling_app import GlobalSchedulingApp

    app = MagicMock(spec=GlobalSchedulingApp)

    with patch(
        "scheduling_modal_with_recurring_support.applications.scheduling_app.LaunchModalEffect"
    ) as mock_lme:
        mock_lme.return_value.apply.return_value = MagicMock()
        GlobalSchedulingApp.on_open(app)

    called_url: str = mock_lme.call_args[1]["url"]
    assert "patient_id" not in called_url


def test_global_app_uses_default_modal() -> None:
    from canvas_sdk.effects.launch_modal import LaunchModalEffect as RealLME

    from scheduling_modal_with_recurring_support.applications.scheduling_app import GlobalSchedulingApp

    app = MagicMock(spec=GlobalSchedulingApp)

    with patch(
        "scheduling_modal_with_recurring_support.applications.scheduling_app.LaunchModalEffect"
    ) as mock_lme:
        mock_lme.TargetType = RealLME.TargetType
        mock_lme.return_value.apply.return_value = MagicMock()
        GlobalSchedulingApp.on_open(app)

    called_target = mock_lme.call_args[1]["target"]
    assert called_target == RealLME.TargetType.DEFAULT_MODAL
