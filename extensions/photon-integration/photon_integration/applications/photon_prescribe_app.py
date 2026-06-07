"""Patient-chart application that launches the Photon prescribe modal.

Photon requires an authenticated provider (user-access token) to write
prescriptions, which the backend M2M token cannot do. This app opens a modal
that embeds Photon Elements, where the provider authenticates via SSO and
prescribes for the (already-synced) patient.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

MODAL_PATH = "/plugin-io/api/photon_integration/photon/"


class PhotonPrescribeApp(Application):
    """Patient-scope app: opens the Photon Elements prescribe modal."""

    def on_open(self) -> Effect:
        patient_id = (self.event.context.get("patient") or {}).get("id", "")
        return LaunchModalEffect(
            url=f"{MODAL_PATH}?patient_id={patient_id}",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
        ).apply()
