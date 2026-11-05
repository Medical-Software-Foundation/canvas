"""Live updates for open queue screens. Staff sessions only."""

from __future__ import annotations

from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI

from canvas__ondemand_provider_queue.handlers.common import CHANNEL, staff_allowed
from canvas__ondemand_provider_queue.settings import Settings


class QueueWebSocket(WebSocketAPI):
    """Accepts the queue channel for signed-in staff while the queue is on."""

    def authenticate(self) -> bool:
        """Allow staff on the queue channel only. API keys are not accepted here."""
        settings = Settings.from_secrets(self.secrets)
        if not settings.enabled or self.websocket.channel != CHANNEL:
            return False
        user = self.websocket.logged_in_user or {}
        return staff_allowed(settings, user.get("type"), user.get("id"))
