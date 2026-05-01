"""Top-level Canvas application for staff to view all memberships.

Registered under ``components.applications`` in ``CANVAS_MANIFEST.json``;
appears in the provider menu. Opening it launches the admin page in a new
browser window so staff can keep the rest of Canvas open alongside it.
"""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

ADMIN_PAGE_PATH = "/plugin-io/api/portal_membership/admin/page"


class MembershipAdminApp(Application):
    """Staff-facing read-only directory of all memberships."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=ADMIN_PAGE_PATH,
            target=LaunchModalEffect.TargetType.NEW_WINDOW,
            title="Memberships",
        ).apply()
