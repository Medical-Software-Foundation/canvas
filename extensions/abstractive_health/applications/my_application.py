import json

from base64 import b64encode
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

SMART_LAUNCH_URL = "https://app.abstractive.ai/launch"

class MyApplication(Application):
    def on_open(self) -> Effect:
        launch_context = {"patient": self.context["patient"]["id"]}
        encoded_launch = b64encode(json.dumps(launch_context).encode()).decode()

        launch_params = {
            "iss": f"https://fumage-{self.environment['CUSTOMER_IDENTIFIER']}.canvasmedical.com",
            "launch": encoded_launch
        }
        params = urlencode(launch_params)

        return LaunchModalEffect(
            url=f"{SMART_LAUNCH_URL}?{params}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL, # or RIGHT_CHART_PANE_LARGE / NEW_WINDOW
        ).apply()
