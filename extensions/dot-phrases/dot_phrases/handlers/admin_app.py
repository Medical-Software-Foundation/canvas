from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import PanelApplication

from dot_phrases.library import is_admin


class DotPhrasesAdminApp(PanelApplication):
    """App drawer icon for practice phrases, practice settings, and import.

    Only members of the team named in the ADMIN_TEAM setting see it. When the setting is empty, nobody
    does. Needs Canvas 1.364 or later, which added per-user app drawer icons.
    """

    NAME = "Dot Phrases"
    IDENTIFIER = "dot_phrases__admin"
    ICON_URL = "/plugin-io/api/dot_phrases/icon.svg"

    def _staff_id(self) -> str | None:
        user = self.event.context.get("user") or {}
        return user.get("id")

    def visible(self) -> bool:
        # Hidden inside a patient chart, where Dot Phrases means the chart panel. Admins reach a
        # practice phrase from there with the panel's open-in-admin icon.
        if self.event.context.get("patient"):
            return False
        return is_admin(self._staff_id(), self.secrets)

    def on_open(self) -> Effect | list[Effect]:
        # The admin page checks the signed-in staff member again, so a stale menu entry can't
        # open it for someone removed from the setting.
        return LaunchModalEffect(
            url="/plugin-io/api/dot_phrases/admin/",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Dot Phrases",
        ).apply()
