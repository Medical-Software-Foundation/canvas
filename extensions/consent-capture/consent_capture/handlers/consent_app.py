"""Consents — the always-available patient-chart app-drawer launcher.

Registered as a ``patient_specific`` Application so it is present in the chart's
application drawer at all times, even when no consent is currently due. It opens
the same patient-facing picker modal as the red ``ConsentButton`` (which only
appears when a consent is still needed), giving staff a way to view completed
consents, record an ad-hoc/optional consent, or reach Settings any time.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.application import Application

from consent_capture.picker_modal import build_picker_modal


class ConsentApp(Application):
    """App-drawer entry that opens the consent picker for the charted patient."""

    def _patient_id(self):
        try:
            return (self.context.get("patient", {}) or {}).get("id", "")
        except Exception:  # noqa: BLE001 - context shape varies; treat as unknown
            return ""

    def _staff_id(self):
        try:
            return (self.context.get("user", {}) or {}).get("id", "")
        except Exception:  # noqa: BLE001 - context shape varies; treat as unknown user
            return ""

    def on_open(self) -> Effect:
        secrets = getattr(self, "secrets", None) or {}
        return build_picker_modal(self._patient_id(), self._staff_id(), secrets).apply()
