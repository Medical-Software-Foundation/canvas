from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI


class ChartSubscriptionAuth(WebSocketAPI):
    """Authenticates WebSocket subscribers for the clinical-summary patient channel."""

    def authenticate(self) -> bool:
        user = self.websocket.logged_in_user
        if not user:
            return False
        return user.get("type") == "Staff"
