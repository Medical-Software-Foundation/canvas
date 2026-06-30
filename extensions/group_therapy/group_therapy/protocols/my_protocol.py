import time

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Generated once at module load - changes on every deploy/restart so the modal
# page is never served from a stale iframe/browser cache after an update.
_CACHE_BUST = str(int(time.time()))


class GroupTherapyApplication(Application):
    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/group_therapy/ui?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()


class GroupTherapyAdminApplication(Application):
    """Admin app: build/edit the group therapy templates (form-based, no JSON)."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/group_therapy/admin/ui?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
