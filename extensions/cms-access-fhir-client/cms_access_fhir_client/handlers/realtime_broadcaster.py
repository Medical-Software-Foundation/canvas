"""Per-patient WebSocket broadcaster for ACCESS alignment state changes.

NOTE: The Canvas SDK (as of v0.1.4) does not expose a PLUGIN_CUSTOM_DATA_MODEL_CHANGED
event type. Broadcasts are therefore emitted inline from the handlers that mutate
ACCESSAlignment rows (AccessOperationsApi, AccessWebhookApi, SubmissionStatusPoller)
using the _broadcast_alignment_update() utility below.

When/if the SDK exposes such an event in a future version, this module can be refactored
to use a dedicated BaseHandler subscriber.

Channel name format (patient-scoped, required to prevent cross-chart leakage):
    access-cms_access_fhir_client-{patient_id}
"""
from canvas_sdk.effects.simple_api import Broadcast


def broadcast_alignment_update(patient_id: str, model_name: str = "ACCESSAlignment") -> Broadcast:
    """Return a Broadcast effect that signals chart summary iframes to reload.

    Must be returned alongside other effects from the handler's compute/execute method
    to take effect.
    """
    channel = f"access-cms_access_fhir_client-{patient_id}"
    return Broadcast(
        message={"event": "access_data_changed", "model": model_name},
        channel=channel,
    ).apply()
