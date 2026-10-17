"""The provider-menu entry point for curating the resource library."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from patient_resources.constants import LIBRARY_URL


class PatientResourcesAdminApp(Application):
    """Opens the resource library.

    Declared ``provider_menu_item`` rather than ``global``. Curating a shared
    library is configuration: it is not something a user opens against the
    patient or note in front of them, which is what the app drawer is for. Every
    other admin surface in this repo that lives behind the provider menu makes
    the same declaration.

    Launched by ``url`` rather than inline ``content``: the library page issues
    repeated same-origin requests for listing, searching, paging and saving,
    which needs a real document origin so the staff session travels with each
    one.

    ``PAGE`` rather than ``DEFAULT_MODAL``, because a menu entry has no modal
    host to draw an iframe in -- no menu-item application in this repo launches
    the default modal. The page keeps its modal plumbing anyway: it resizes and
    closes correctly if it is ever hosted in one again, and it reveals its close
    control only when a host actually offers the port to close through.

    Note that there is no way to hide this entry from non-admin staff. The
    applications manifest schema has no role field and ``Application`` has no
    ``visible()`` hook, so every staff member sees it. The page it opens
    therefore renders read-only for anyone who may not curate, and says so --
    a blank page or a bare 403 would read as breakage.
    """

    def on_open(self) -> Effect:
        """Open the library."""
        return LaunchModalEffect(
            url=LIBRARY_URL,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Patient Resources",
        ).apply()
