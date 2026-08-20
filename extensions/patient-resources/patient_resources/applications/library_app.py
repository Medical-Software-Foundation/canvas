"""The global app-drawer entry point for curating the resource library."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from patient_resources.constants import LIBRARY_URL


class PatientResourcesAdminApp(Application):
    """Opens the resource library.

    Global scope, because curating a shared library is a configuration task with
    no patient context -- the repo convention is that admin work lives in a
    global-scope Application rather than a patient-scoped one.

    Launched by ``url`` rather than inline ``content``: the library page issues
    repeated same-origin requests for listing, searching and saving, which needs
    a real document origin so the staff session travels with each one.

    Note that there is no way to hide this icon from non-admin staff. The
    applications manifest schema has no role field and ``Application`` has no
    ``visible()`` hook, so every staff member sees it. The page it opens
    therefore renders read-only for anyone who may not curate, and says so --
    a blank modal or a bare 403 would read as breakage.
    """

    def on_open(self) -> Effect:
        """Open the library."""
        return LaunchModalEffect(
            url=LIBRARY_URL,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Patient Resources",
        ).apply()
