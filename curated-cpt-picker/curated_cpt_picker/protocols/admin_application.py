from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class CuratedCptAdminApp(Application):
    """Admin app for managing the curated CPT picker list.

    Clicking the app drawer icon opens the admin UI as a centered modal.
    The UI itself is served by `admin_api.AdminAPI.GET /admin`, which
    does the auth check against ADMIN_STAFF_IDS.
    """

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/curated_cpt_picker/admin",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
