"""Tests for applications/delegation_app.py — entry point for the admin UI."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import call, patch


def test_on_open__returns_launch_modal_effect_for_admin_url() -> None:
    """on_open returns a LaunchModalEffect with the admin UI URL and modal config."""
    with (
        patch("dea_prescriber_filter.applications.delegation_app._CACHE_BUST", "12345"),
        patch("dea_prescriber_filter.applications.delegation_app.LaunchModalEffect") as mock_effect,
    ):
        mock_effect.return_value = SimpleNamespace(apply=lambda: "applied-effect")
        mock_effect.TargetType = SimpleNamespace(DEFAULT_MODAL="DEFAULT_MODAL")

        from dea_prescriber_filter.applications.delegation_app import PrescriberDelegationApp

        tested = PrescriberDelegationApp.__new__(PrescriberDelegationApp)
        result = tested.on_open()

    expected = "applied-effect"
    assert result == expected

    exp_calls = [
        call(
            url="/plugin-io/api/dea_prescriber_filter/app/delegation-admin?v=12345",
            target="DEFAULT_MODAL",
            title="Prescriber Assist",
        ),
    ]
    assert mock_effect.mock_calls == exp_calls
