"""
Medication Change Broadcast Protocol

This protocol broadcasts WebSocket notifications when medications are added/changed/removed
so the high-risk medications view can refresh in real-time.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from logger import log


class MedicationChangeBroadcast(BaseProtocol):
    """
    Broadcasts WebSocket notifications when medications change.
    """

    # Listen for medication command events
    RESPONDS_TO = [
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_ENTER_IN_ERROR),
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_ENTER_IN_ERROR),
        EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_COMMIT),
        EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_ENTER_IN_ERROR),
        EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_COMMIT),
        EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_ENTER_IN_ERROR),
    ]

    def compute(self) -> list[Effect]:
        """
        Broadcast a WebSocket message when a medication is added/changed/removed.
        """
        log.info(f"MedicationChangeBroadcast triggered: event={self.event.type}")

        # Get patient ID from context
        patient_id = self.context.get("patient", {}).get("id")

        if not patient_id:
            log.warning(f"No patient context. Context keys: {list(self.context.keys())}")
            return []

        # The channel must match the WebSocket path pattern
        # WebSocket URL: /plugin-io/ws/high_risk_medications/{patient_id}/
        # Channel names must be alphanumeric with underscores only (no dashes)
        # Replace dashes with underscores to meet validation requirements
        channel_name = patient_id.replace("-", "_")
        log.info(f"Broadcasting to channel: {channel_name} (patient: {patient_id})")

        broadcast_effect = Broadcast(
            message={"event": "medication_changed"},
            channel=channel_name
        )

        log.info(f"Broadcast effect: {broadcast_effect}")

        return [broadcast_effect.apply()]
