"""Tests for applications/delegation_app.py — entry point for the admin UI."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch


def test_on_open_returns_launch_modal_effect_for_admin_url() -> None:
    mock_effect_instance = MagicMock()
    mock_effect_instance.apply.return_value = "applied-effect"

    with patch("dea_prescriber_filter.applications.delegation_app.LaunchModalEffect") as mock_effect:
        mock_effect.return_value = mock_effect_instance
        mock_effect.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"

        from dea_prescriber_filter.applications.delegation_app import PrescriberDelegationApp

        app = PrescriberDelegationApp.__new__(PrescriberDelegationApp)
        result = app.on_open()

    assert result == "applied-effect"
    assert len(mock_effect.mock_calls) == 2
    # First call: the constructor
    constructor_call = mock_effect.mock_calls[0]
    _, args, kwargs = constructor_call
    assert kwargs["target"] == "DEFAULT_MODAL"
    assert kwargs["title"] == "Prescriber Assist"
    assert kwargs["url"].startswith("/plugin-io/api/dea_prescriber_filter/app/delegation-admin?v=")
    # Second call: .apply()
    assert mock_effect_instance.mock_calls == [call.apply()]
