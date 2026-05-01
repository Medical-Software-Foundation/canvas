"""Unit tests for MembershipAdminApp."""
from unittest.mock import MagicMock

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from portal_membership.applications.membership_admin_app import (
    ADMIN_PAGE_PATH,
    MembershipAdminApp,
)


def _make_app() -> MembershipAdminApp:
    event = MagicMock()
    return MembershipAdminApp(event=event)


class TestMembershipAdminAppOnOpen:
    def test_returns_launch_modal_effect(self) -> None:
        from canvas_sdk.effects import Effect

        result = _make_app().on_open()
        assert isinstance(result, Effect)

    def test_targets_new_window_with_admin_page_url(self) -> None:
        # Reconstruct what we expect on_open to emit and apply it the same
        # way the SDK does, so we can compare effect payloads.
        expected = LaunchModalEffect(
            url=ADMIN_PAGE_PATH,
            target=LaunchModalEffect.TargetType.NEW_WINDOW,
            title="Memberships",
        ).apply()

        result = _make_app().on_open()
        assert result.payload == expected.payload
