from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI


class PatientMessagesWebSocket(WebSocketAPI):
    """Accept WebSocket connections on channel `staff-<staff_uuid>`.

    The channel name is chosen by the client via the connection URL
    (`/plugin-io/ws/provider_patient_messages_companion/staff-<uuid>`); we
    verify it matches the session's logged-in staff UUID so a client can
    only subscribe to its own channel.
    """

    def authenticate(self) -> bool:
        logged_in_user = self.websocket.logged_in_user
        if not logged_in_user or logged_in_user.get("type") != "Staff":
            return False
        expected_channel = f"staff-{logged_in_user.get('id', '')}"
        return self.websocket.channel == expected_channel
