"""Clinical Favorites provider menu application."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ClinicalFavoritesApp(Application):
    """Provider menu application for clinical favorites."""

    def on_open(self) -> Effect:
        staff_id = self.event.context.get("user", {}).get("id", "")
        html = render_to_string(
            "templates/favorites_template.html",
            {"staff_id": staff_id, "cache_bust": _CACHE_BUST},
        )
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Clinical Favorites",
        ).apply()
