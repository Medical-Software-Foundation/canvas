from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import PanelApplication


class DotPhrasesAdminApp(PanelApplication):
    """App drawer icon for the Dot Phrases app.

    Every staff member sees it: My phrases and a read-only Practice phrases tab for everyone, and
    editable practice phrases and Practice settings for members of the ADMIN_TEAM team. Needs
    Canvas 1.364 or later, which added per-user app drawer icons.
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
        return bool(self._staff_id())

    def on_open(self) -> Effect | list[Effect]:
        # The page and its API check who is signed in on every request, so only admins can change
        # practice phrases or settings, whatever the page shows.
        return LaunchModalEffect(
            url="/plugin-io/api/dot_phrases/admin/",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Dot Phrases",
        ).apply()
