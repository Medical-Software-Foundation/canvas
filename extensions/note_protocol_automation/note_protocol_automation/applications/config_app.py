"""Admin menu item that opens the Note Protocols config UI as a full page.

This Application registers a GLOBAL admin launch surface (manifest scope
``global``). When an admin opens it, ``on_open`` returns a ``LaunchModalEffect``
targeting this plugin's own SimpleAPI static URL, opened as a full PAGE
(``TargetType.PAGE``) — the rule-authoring admin surface.

This is a GLOBAL admin page: it takes NO patient parameter. The rule-authoring
UI operates on the instance's note types and the plugin's own ``Rule``
custom_data table, neither of which is patient-scoped.

Sandbox constraints honored: NO @dataclass, NO pathlib, NO lazy/local imports —
all top-level.
"""

from typing import Final

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Static entry document served by ConfigAPI.serve_index under this plugin's
# SimpleAPI prefix. The slug MUST match the manifest ``name``.
_CONFIG_URL: Final[str] = (
    "/plugin-io/api/note_protocol_automation/static/index.html"
)


class NoteProtocolsConfigApp(Application):
    """Global admin menu item that launches the rule-authoring UI."""

    def on_open(self) -> Effect:
        """Open the Note Protocols config UI as a full page.

        No patient context is read or forwarded — this is a global admin
        surface. The SimpleAPI it launches is StaffSessionAuthMixin-gated and
        further restricted (fail-closed) to the staff ids in the ADMIN_STAFF_IDS
        secret: a non-admin who opens this page loads the shell but gets 403 on
        every rules/note-types request, so they can neither read nor edit rules.
        """
        return LaunchModalEffect(
            url=_CONFIG_URL,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Note Protocols",
        ).apply()
