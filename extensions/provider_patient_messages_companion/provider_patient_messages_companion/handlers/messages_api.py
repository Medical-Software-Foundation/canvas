from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from django.db.models import Case, Count, F, Q, When

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.message import Message as MessageEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus
from canvas_sdk.v1.data.message import Message

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

PLUGIN_NAME = "provider_patient_messages_companion"
DEFAULT_CONVERSATION_LIMIT = 100
MAX_CONVERSATION_LIMIT = 200


def _panel_patients(staff_uuid: str) -> dict:
    """Map of {patient_uuid_str: Patient} for active care-team memberships."""
    memberships = (
        CareTeamMembership.objects.filter(
            staff__id=staff_uuid,
            status=CareTeamMembershipStatus.ACTIVE,
        )
        .select_related("patient")
        .order_by("patient__last_name", "patient__first_name")
    )
    panel: dict = {}
    for membership in memberships:
        patient = membership.patient
        if patient is None:
            continue
        panel.setdefault(str(patient.id), patient)
    return panel


def _latest_message_per_thread(staff_uuid: str, patient_uuids: list[str]) -> list:
    """One Message per patient on panel, the most recent on either side."""
    if not patient_uuids:
        return []
    return list(
        Message.objects.filter(
            Q(sender__patient__id__in=patient_uuids, recipient__staff__id=staff_uuid)
            | Q(sender__staff__id=staff_uuid, recipient__patient__id__in=patient_uuids)
        )
        .annotate(
            thread_patient_id=Case(
                When(sender__staff__id=staff_uuid, then=F("recipient__patient__id")),
                default=F("sender__patient__id"),
            ),
        )
        .order_by("thread_patient_id", "-created")
        .distinct("thread_patient_id")
    )


def _unread_counts(staff_uuid: str, patient_uuids: list[str]) -> dict:
    """Unread inbound counts keyed by patient UUID string."""
    if not patient_uuids:
        return {}
    rows = (
        Message.objects.filter(
            sender__patient__id__in=patient_uuids,
            recipient__staff__id=staff_uuid,
            read__isnull=True,
        )
        .values_list("sender__patient__id")
        .annotate(Count("id"))
    )
    return {str(patient_id): count for patient_id, count in rows}


def _serialize_thread(patient: Any, last_message: Any | None, unread: int) -> dict:
    last_serialized = None
    if last_message is not None:
        last_serialized = {
            "id": str(last_message.id),
            "content": last_message.content or "",
            "created": (
                last_message.created.isoformat() if last_message.created else None
            ),
            "sent_by_me": _sender_is_this_staff(last_message),
        }
    return {
        "patient_id": str(patient.id),
        "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
        "last_message": last_serialized,
        "unread_count": unread,
    }


def _sender_is_this_staff(message: Any) -> bool:
    """Heuristic used only in thread-list serialization.

    The caller has already filtered to messages where one side is the
    logged-in staff, so `sender.is_staff` is an accurate discriminator.
    """
    sender = message.sender
    if sender is None:
        return False
    return bool(getattr(sender, "is_staff", False))


def _serialize_message(message: Any, staff_uuid: str) -> dict:
    sender = message.sender
    sent_by_me = False
    if sender is not None and sender.is_staff:
        staff_side = sender.person_subclass
        if staff_side is not None and str(staff_side.id) == staff_uuid:
            sent_by_me = True
    return {
        "id": str(message.id),
        "content": message.content or "",
        "created": message.created.isoformat() if message.created else None,
        "sent_by_me": sent_by_me,
        "read": message.read.isoformat() if message.read else None,
    }


class PatientMessagesAPI(StaffSessionAuthMixin, SimpleAPI):
    """HTTP endpoints for the My Messages companion app."""

    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        staff_uuid = self.request.headers["canvas-logged-in-user-id"]
        context = {
            "cache_bust": _CACHE_BUST,
            "ws_url": f"/plugin-io/ws/{PLUGIN_NAME}/staff-{staff_uuid}",
        }
        return [
            HTMLResponse(
                render_to_string("static/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/threads")
    def threads(self) -> list[Response | Effect]:
        staff_uuid = self.request.headers["canvas-logged-in-user-id"]
        panel = _panel_patients(staff_uuid)
        patient_uuids = list(panel.keys())

        latest = _latest_message_per_thread(staff_uuid, patient_uuids)
        unread = _unread_counts(staff_uuid, patient_uuids)

        latest_by_patient: dict = {}
        for message in latest:
            latest_by_patient[str(message.thread_patient_id)] = message

        serialized = [
            _serialize_thread(
                patient,
                latest_by_patient.get(patient_uuid),
                unread.get(patient_uuid, 0),
            )
            for patient_uuid, patient in panel.items()
        ]
        return [JSONResponse({"threads": serialized})]

    @api.get("/threads/<patient_id>/messages")
    def conversation(self) -> list[Response | Effect]:
        staff_uuid = self.request.headers["canvas-logged-in-user-id"]
        patient_uuid = self.request.path_params["patient_id"]

        panel = _panel_patients(staff_uuid)
        if patient_uuid not in panel:
            return [
                JSONResponse(
                    {"error": "Patient is not on your panel"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            limit = min(
                int(self.request.query_params.get("limit", DEFAULT_CONVERSATION_LIMIT)),
                MAX_CONVERSATION_LIMIT,
            )
        except ValueError:
            limit = DEFAULT_CONVERSATION_LIMIT
        if limit < 1:
            limit = DEFAULT_CONVERSATION_LIMIT

        before_raw = self.request.query_params.get("before")
        messages_qs = Message.objects.filter(
            Q(sender__patient__id=patient_uuid, recipient__staff__id=staff_uuid)
            | Q(sender__staff__id=staff_uuid, recipient__patient__id=patient_uuid)
        ).select_related(
            "sender",
            "sender__patient",
            "sender__staff",
            "recipient",
            "recipient__patient",
            "recipient__staff",
        )
        if before_raw:
            try:
                before = datetime.fromisoformat(before_raw.replace("Z", "+00:00"))
            except ValueError:
                return [
                    JSONResponse(
                        {"error": "'before' must be ISO-8601"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            messages_qs = messages_qs.filter(created__lt=before)

        descending = list(messages_qs.order_by("-created")[:limit])
        chronological = list(reversed(descending))
        serialized = [_serialize_message(m, staff_uuid) for m in chronological]

        return [JSONResponse({"messages": serialized})]

    @api.post("/threads/<patient_id>/messages")
    def send(self) -> list[Response | Effect]:
        staff_uuid = self.request.headers["canvas-logged-in-user-id"]
        patient_uuid = self.request.path_params["patient_id"]

        panel = _panel_patients(staff_uuid)
        if patient_uuid not in panel:
            return [
                JSONResponse(
                    {"error": "Patient is not on your panel"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        body = (self.request.json() or {}).get("content", "").strip()
        if not body:
            return [
                JSONResponse(
                    {"error": "content is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Use .create() rather than .create_and_send(): the patient may not have
        # a transmission channel (SMS/email) configured, in which case
        # CREATE_AND_SEND_MESSAGE fails server-side with "Channel not
        # supported". Creating the message stores it in Canvas and the patient
        # sees it on their next portal visit, which is the right behavior for
        # a reference plugin that doesn't assume transmission config.
        effect = MessageEffect(
            sender_id=staff_uuid,
            recipient_id=patient_uuid,
            content=body,
        ).create()
        return [
            effect,
            JSONResponse(
                {"pending": {"content": body, "sent_by_me": True}},
                status_code=HTTPStatus.ACCEPTED,
            ),
        ]

    @api.post("/threads/<patient_id>/mark-read")
    def mark_read(self) -> list[Response | Effect]:
        staff_uuid = self.request.headers["canvas-logged-in-user-id"]
        patient_uuid = self.request.path_params["patient_id"]

        panel = _panel_patients(staff_uuid)
        if patient_uuid not in panel:
            return [
                JSONResponse(
                    {"error": "Patient is not on your panel"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        unread = list(
            Message.objects.filter(
                sender__patient__id=patient_uuid,
                recipient__staff__id=staff_uuid,
                read__isnull=True,
            ).values_list("id", "content")
        )

        if not unread:
            return [JSONResponse({"marked": 0})]

        now = datetime.now(timezone.utc)
        effects: list = []
        for message_id, existing_content in unread:
            effects.append(
                MessageEffect(
                    message_id=str(message_id),
                    sender_id=patient_uuid,
                    recipient_id=staff_uuid,
                    content=existing_content or "",
                    read=now,
                ).edit()
            )
        effects.append(JSONResponse({"marked": len(unread)}))
        return effects

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
