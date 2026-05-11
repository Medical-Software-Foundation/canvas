"""Broadcast helper for notifying the claim timeline app of updates."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast


def notify_claim_updated(canvas_claim_id: str) -> Effect:
    """Broadcast a refresh signal to the claim's WebSocket channel."""
    return Broadcast(
        message={"refresh": True},
        channel=f"claim-{canvas_claim_id}",
    ).apply()
