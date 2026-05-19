from urllib.parse import quote

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class OrderSetsApp(Application):
    def on_open(self) -> Effect:
        patient_id = self.event.context.get("patient", {}).get("id", "")
        url = f"/plugin-io/api/order_sets/ui?patient_id={quote(patient_id, safe='')}"
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        ).apply()
