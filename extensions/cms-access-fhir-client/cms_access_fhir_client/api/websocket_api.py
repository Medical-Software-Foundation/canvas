"""WebSocket API for the ACCESS chart summary real-time channel.

Channel format: access-cms_access_fhir_client-{patient_id}
Access: staff session only (chart is staff-facing).
"""
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI
from logger import log


class AccessChartSummaryWebSocket(WebSocketAPI):
    """Authenticate WebSocket connections for the ACCESS chart summary section."""

    def authenticate(self) -> bool:
        logged_in_user = self.websocket.logged_in_user
        if not logged_in_user:
            log.warning("[cms-access] WebSocket connection rejected: no logged-in user")
            return False

        if logged_in_user.get("type") != "Staff":
            log.warning(
                f"[cms-access] WebSocket rejected: user type "
                f"'{logged_in_user.get('type')}' is not Staff"
            )
            return False

        channel = self.websocket.channel
        if not channel.startswith("access-cms_access_fhir_client-"):
            log.warning(
                f"[cms-access] WebSocket rejected: unexpected channel name '{channel}'"
            )
            return False

        return True
