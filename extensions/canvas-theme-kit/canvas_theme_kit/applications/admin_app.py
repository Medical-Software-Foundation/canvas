"""App-drawer entry point for the theme editor.

The modal is rendered inline rather than iframing a URL, so there is no second
authenticated surface to secure. The editor page itself carries no privileges:
every read and write it performs goes through `ThemeAdminAPI`, which re-checks
the staff session and the role allowlist on each request. Rendering the editor
is not an authorization decision.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string


class ThemeEditorApp(Application):
    """Opens the Canvas Theme Kit editor from the app drawer."""

    def on_open(self) -> Effect:
        """Render the editor shell.

        The shell loads themes over the admin API on open, so an unauthorized
        staff member gets an explanatory error from the API rather than an empty
        editor that appears to work until they try to save.
        """
        return LaunchModalEffect(
            content=render_to_string("templates/admin.html"),
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Theme Kit",
        ).apply()


class ThemeEditorMenuItem(ThemeEditorApp):
    """The same editor, surfaced in the provider (hamburger) menu.

    Registered as a second application because scope is set per manifest entry,
    not in code. A `global` application only appears in the app drawer outside a
    patient chart, which is easy to miss; the provider menu is a stable, obvious
    place to find it and is independent of the menu allow-list.

    Behavior is inherited wholesale — this exists purely to occupy a second
    scope.
    """
