"""Clinical Favorites patient chart application.

Launches the favorites surface inside the patient chart, with the patient
pinned from the chart context rather than chosen through a search picker. This
is the insertion entry point. The provider menu application stays management
only.
"""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ClinicalFavoritesChartApp(Application):
    """Patient chart application for inserting clinical favorites into a note."""

    def on_open(self) -> Effect:
        patient_id = self.event.context.get("patient", {}).get("id", "")
        staff_id = self.event.context.get("user", {}).get("id", "")
        html = render_to_string(
            "templates/favorites_chart_template.html",
            {
                "staff_id": staff_id,
                "patient_id": patient_id,
                "cache_bust": _CACHE_BUST,
            },
        )
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
            title="Insert Favorites",
        ).apply()
