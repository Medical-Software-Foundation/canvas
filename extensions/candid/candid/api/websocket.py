"""WebSocket handler for real-time claim timeline updates.

Clients connect to ``ws://<instance>/plugin-io/ws/candid/claim-<claim_id>/``
and receive a message whenever Candid activity occurs on that claim (sync,
submission, patient payment). The message is a simple ``{"refresh": true}``
signal — the client then fetches updated data via the ``/claim-detail`` REST
endpoint.
"""

from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI


class CandidTimelineWebSocket(WebSocketAPI):
    """Accept WebSocket connections for claim timeline updates."""

    def authenticate(self) -> bool:
        user = self.websocket.logged_in_user
        return bool(user and user.get("type") == "Staff")
