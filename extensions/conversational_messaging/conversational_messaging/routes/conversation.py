import arrow
from http import HTTPStatus

from django.db.models import Count, Q
from logger import log

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.message import Message
from canvas_sdk.effects.simple_api import Broadcast, HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SimpleAPI,
    SimpleAPIRoute,
    APIKeyAuthMixin,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.message import Message as MessageModel
from canvas_sdk.v1.data.patient import ContactPointSystem, Patient, PatientContactPoint
from canvas_sdk.v1.data.staff import Staff


cache = get_cache()

# Cache key for the staff directory shared between view rendering and mutation endpoints.
STAFF_NAMES_CACHE_KEY = "conversational_messaging:staff_names"


class StaffPatientConversation(StaffSessionAuthMixin, SimpleAPI):
    """SimpleAPI handler backing the messaging conversational view.

    Responsible for rendering the HTML view and posting mutations (send message,
    mark read).
    """

    ATTACHMENT_PLACEHOLDER = (
        "Message contains {count} attachment(s), see timeline to view attachments"
    )
    STAFF_CACHE_TTL_SECONDS = 3600

    def _get_sent_description(self, timestamp):
        """Return a human-friendly string describing when the message was sent."""
        return arrow.get(timestamp).humanize()

    def _get_staff_names(self) -> dict[str, dict[str, str]]:
        """Fetch (and cache) a mapping of staff user IDs to display info."""
        return cache.get_or_set(
            STAFF_NAMES_CACHE_KEY,
            default=lambda: {
                str(staff["user_id"]): {
                    "name": f"{staff['first_name']} {staff['last_name']}",
                    "id": str(staff["id"]),
                }
                for staff in Staff.objects.values("user_id", "first_name", "last_name", "id")
            },
            timeout_seconds=self.STAFF_CACHE_TTL_SECONDS,
        )

    def _get_default_page_limit(self) -> int:
        secret_value = self.secrets.get("MESSAGING_CONVERSATION_PAGE_LIMIT")
        try:
            return max(5, min(int(secret_value), 200))
        except (TypeError, ValueError):
            return 20

    def _get_patient_conversation(
        self,
        patient_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], bool, int]:
        """Build the chat transcript context for the given patient."""
        patient = (
            Patient.objects.filter(id=patient_id)
            .values("user_id", "first_name", "last_name")
            .first()
        )

        if patient is None:
            return [], False, 0

        messages_queryset = (
            MessageModel.objects.filter(
                Q(sender_id=patient["user_id"]) | Q(recipient_id=patient["user_id"])
            )
            .annotate(message_count=Count("message"))
            .order_by("-created")
        )

        total_messages = messages_queryset.count()
        messages = list(messages_queryset[offset : offset + limit])
        unread_message = [msg.id for msg in messages if msg.sender_id == patient["user_id"] and not msg.read]
        has_unread_message = len(unread_message) > 0

        patient_name = f"{patient['first_name']} {patient['last_name']}"
        staff_lookup = self._get_staff_names()

        conversation: list[dict] = []

        for msg in messages:
            sender_details = staff_lookup.get(str(msg.sender_id))
            sender_is_practitioner = sender_details is not None

            conversation.append(
                {
                    "sent": msg.created,
                    "sent_description": self._get_sent_description(msg.created),
                    "type": "Practitioner" if sender_is_practitioner else "Patient",
                    "text": msg.content or "",
                    "unread": msg.id == unread_message[-1] if has_unread_message else False,
                    "attachment_count": msg.message_count,
                    "name": (sender_details["name"]
                        if sender_details
                        else patient_name),
                }
            )

        conversation.sort(key=lambda item: item["sent"])
        return conversation, has_unread_message, total_messages

    @api.get("/conversation/<patient_id>")
    def get(self) -> list[Response | Effect]:
        """Render the conversational view HTML for the given patient."""
        patient_id = self.request.path_params["patient_id"]
        staff_id = self.request.headers["canvas-logged-in-user-id"]

        default_limit = self._get_default_page_limit()

        try:
            limit = int(self.request.query_params.get("limit", default_limit))
        except (TypeError, ValueError):
            limit = default_limit

        if limit <= 0:
            limit = default_limit
        limit = min(limit, default_limit)

        try:
            offset = int(self.request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0

        if offset < 0:
            offset = 0

        consented_contact_points = (
            PatientContactPoint.objects.filter(
                patient__id=patient_id,
                system__in=[
                    ContactPointSystem.PHONE.value,
                    ContactPointSystem.EMAIL.value,
                ],
                has_consent=True,
            ).exists()
        )

        conversation, has_unread_messages, total_messages = self._get_patient_conversation(
            patient_id, limit, offset
        )

        context = {
            "conversation": conversation,
            "patient_id": patient_id,
            "staff_id": staff_id,
            "customer_identifier": self.environment['CUSTOMER_IDENTIFIER'],
            "has_eligible_contact_point": consented_contact_points,
            "has_unread_messages": has_unread_messages,
            "limit": limit,
            "offset": offset,
            "total_messages": total_messages,
        }

        return [
            HTMLResponse(
                render_to_string("templates/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/style.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the compiled stylesheet used by the conversational view."""
        return [
            Response(
                render_to_string("templates/style.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/script.js")
    def get_script(self) -> list[Response | Effect]:
        """Serve the JavaScript helpers used by the conversational view."""
        return [
            Response(
                render_to_string("templates/script.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    def redirect_to_conversation(self, patient_id):
        """Return a simple HTML redirect to reload the conversation."""
        log.info('Reloading conversational view')
        return [
            HTMLResponse(
                content=f"""
                    <html>
                      <head>
                        <script type="text/javascript">
                          window.location.href = '/plugin-io/api/conversational_messaging/conversation/{patient_id}';
                        </script>
                      </head>
                      <body>
                        <p>Redirecting back to conversation...</p>
                      </body>
                    </html>
                """,
                status_code=HTTPStatus.OK,
            )
        ]

    def send_message(self, patient_recipient, staff_sender, message_body):
        """Create a messaging effect that sends the provided text."""
        m2 = Message(
            content=message_body,
            sender_id=staff_sender,
            recipient_id=patient_recipient,
        )
        return([m2.create_and_send()])

    @api.post("/send-sms")
    def send_sms_post(self) -> list[Response | Effect]:
        """Handle form submissions from the conversational view composer to send a message to the Patient."""
        form = self.request.form_data()
        message = form["message"].value
        patient_id = form["patient_id"].value
        staff_id = form["staff_id"].value

        log.info(f"sending message: {message}")
        send_msg_effect = self.send_message(
            patient_recipient=patient_id,
            staff_sender=staff_id,
            message_body=message)

        is_ajax_request = self.request.headers.get("x-requested-with") == "XMLHttpRequest"

        if is_ajax_request:
            return send_msg_effect + [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]

        return send_msg_effect + self.redirect_to_conversation(patient_id)

    @api.post("/mark-all-read/<patient_id>")
    def mark_all_read(self) -> list[Response | Effect]:
        """Mark all unread patient messages as read and refresh the view."""
        patient_id = self.request.path_params["patient_id"]
        now = arrow.now().datetime
        
        # Get patient user_id
        patient = Patient.objects.filter(id=patient_id).values("user_id").first()
        if not patient:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]
        
        # Mark all messages sent by this patient as read
        unread_messages = list(
            MessageModel.objects.filter(
            sender_id=patient["user_id"],
            read__isnull=True
        )
        )

        if not unread_messages:
            return self.redirect_to_conversation(patient_id)

        staff_lookup = self._get_staff_names()

        effects: list[Effect] = []
        for message in unread_messages:
            staff_details = staff_lookup.get(str(message.recipient_id))
            if not staff_details:
                log.warning(
                    "Unable to resolve staff ID for recipient %s when marking messages read",
                    message.recipient_id,
                )
                continue

            effects.append(
                Message(
                    message_id=str(message.id),
                    content=message.content or "--", # need to send something to the message edit effect to avoid errors if there is only an attachment and no message content
                    read=now,
                    sender_id=patient_id,
                    recipient_id=staff_details["id"],
                ).edit()
            )

        log.info(f"Marked all messages as read for patient {patient_id}")

        return effects + self.redirect_to_conversation(patient_id)


class MessageCreationNotification(APIKeyAuthMixin, SimpleAPIRoute):
    """Endpoint invoked (via webhook) to signal new inbound messages."""

    PATH = "/message/received"

    def post(self) -> list[Response | Effect]:
        """Broadcast websocket events so the UI refreshes when new messages arrive."""
        log.info("message received")
        msg_body = self.request.json()
        patient_id = msg_body["patient_id"]

        # broadcast to the websocket so that the frontend knows that we have received a new message;
        broadcast_effect = Broadcast(message={"msg": "received"}, channel=patient_id)

        return [
            broadcast_effect.apply(),
            JSONResponse({"status": "ok"}, status_code=HTTPStatus.ACCEPTED),
        ]


class WebSocketConversation(WebSocketAPI):
    """Authenticate websocket connections for live conversation updates."""

    def authenticate(self) -> bool:
        logged_in_user = self.websocket.logged_in_user
        return logged_in_user.get("type") == "Staff"
