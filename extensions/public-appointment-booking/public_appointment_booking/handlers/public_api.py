"""Public (unauthenticated) booking endpoints.

    GET  /plugin-io/api/public_appointment_booking/public/book   booking page (HTML)
    GET  /plugin-io/api/public_appointment_booking/public/slots  open slots (JSON)
    POST /plugin-io/api/public_appointment_booking/public/book   booking request (JSON)

Security model, in order, for every request:
  1. Off unless PUBLIC_BOOKING_ENABLED=true. When off, every route answers 404.
  2. Per-client and instance-wide rate limits (plugin cache, fixed window).
  3. POST only: JSON content type + Origin/Referer host check (CSRF), body size cap,
     strict field validation, per-email rate limit.
  4. Responses carry no PHI. The booking response is the same whether or not the
     details match an existing patient, and the slot is held in both cases, so
     neither the response nor the slot list reveals whether a patient exists.
"""

import datetime
import json
import uuid
from datetime import UTC
from http import HTTPStatus
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import Appointment as AppointmentEffect
from canvas_sdk.effects.note.base import AppointmentIdentifier
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from logger import log

from public_appointment_booking import booking, guards

EXTERNAL_ID_SYSTEM = "public-appointment-booking"
TASK_LABEL = "public-booking"

RECEIVED_BODY = {
    "status": "received",
    "message": (
        "Thanks. Your request has been received. "
        "The practice will contact you to confirm your appointment."
    ),
}

HTML_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; form-action 'none'; frame-ancestors 'self'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}
JSON_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _json(body: dict, status: HTTPStatus = HTTPStatus.OK) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=JSON_HEADERS)


def _error(code: str, status: HTTPStatus, **extra: Any) -> JSONResponse:
    return _json({"error": code, **extra}, status)


NOT_FOUND = ("not_found", HTTPStatus.NOT_FOUND)
RATE_LIMITED = ("rate_limited", HTTPStatus.TOO_MANY_REQUESTS)
UNAVAILABLE = ("unavailable", HTTPStatus.SERVICE_UNAVAILABLE)


class PublicBookingAPI(SimpleAPI):
    """Unauthenticated booking API. See the module docstring for the security model."""

    PREFIX = "/public"

    def authenticate(self, credentials: Credentials) -> bool:
        """Public on purpose: these routes serve people who have no Canvas login.

        Access control is the enabled flag, rate limits, origin check and input
        validation applied inside each route. No route returns PHI.
        """
        return True

    # -- shared --------------------------------------------------------------------

    def _secrets(self) -> dict:
        return getattr(self, "secrets", None) or {}

    def _environment(self) -> dict:
        return getattr(self, "environment", None) or {}

    def _note_type(self) -> tuple[Any, str]:
        name = str(self._secrets().get(guards.NOTE_TYPE_SECRET) or "").strip()
        if not name:
            log.error("public booking: PUBLIC_BOOKING_NOTE_TYPE_NAME is not set")
            return None, ""
        return booking.resolve_note_type(name), name

    def _open_slots(self, cache: Any, note_type: Any, name: str) -> list[dict]:
        """Open slots (all fields), cached briefly, minus slots already requested."""
        slots = cache.get(booking.SLOTS_CACHE_KEY)
        if slots is None:
            secrets = self._secrets()
            slots = booking.search_slots(
                note_type=note_type,
                note_type_name=name,
                now=datetime.datetime.now(UTC),
                lead=guards.lead_time_minutes(secrets),
                days=guards.window_days(secrets),
            )
            cache.set(
                booking.SLOTS_CACHE_KEY,
                slots,
                timeout_seconds=booking.SLOTS_CACHE_SECONDS,
            )
        return booking.drop_held(slots, cache)

    # -- routes --------------------------------------------------------------------

    @api.get("/book")
    def page(self) -> list[Response | Effect]:
        """Serves the booking page."""
        if not guards.is_enabled(self._secrets()):
            return [_error(*NOT_FOUND)]
        return [
            HTMLResponse(
                render_to_string("templates/book.html") or "", headers=HTML_HEADERS
            )
        ]

    @api.get("/slots")
    def slots(self) -> list[Response | Effect]:
        """Lists open slots: provider name, time, location name. No patient data."""
        if not guards.is_enabled(self._secrets()):
            return [_error(*NOT_FOUND)]
        cache = get_cache()
        client = guards.client_key(self.request.headers)
        if guards.hit_rate_limit(cache, f"slots:{client}", guards.SLOTS_LIMIT):
            log.info(f"public booking: slots limit hit for {client}")
            return [_error(*RATE_LIMITED)]

        note_type, name = self._note_type()
        if note_type is None:
            return [_error(*UNAVAILABLE)]
        duration = note_type.online_duration
        open_slots = self._open_slots(cache, note_type, name)
        return [
            _json({"slots": [booking.public_slot(s, duration) for s in open_slots]})
        ]

    @api.post("/book")
    def book(self) -> list[Response | Effect]:
        """Accepts a booking request. Same response whether or not the patient exists."""
        secrets = self._secrets()
        if not guards.is_enabled(secrets):
            return [_error(*NOT_FOUND)]

        headers = self.request.headers
        if not guards.is_json_request(headers):
            return [_error("unsupported_media_type", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)]
        hosts = guards.allowed_hosts(secrets, self._environment(), headers)
        if not guards.origin_allowed(headers, hosts):
            log.warning("public booking: rejected cross-origin POST")
            return [_error("forbidden_origin", HTTPStatus.FORBIDDEN)]
        if len(self.request.body or b"") > guards.MAX_BODY_BYTES:
            return [_error("payload_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)]

        cache = get_cache()
        client = guards.client_key(headers)
        if guards.hit_rate_limit(cache, f"book:{client}", guards.BOOK_LIMIT_PER_CLIENT):
            log.info(f"public booking: per-client limit hit for {client}")
            return [_error(*RATE_LIMITED)]

        try:
            payload = json.loads(self.request.body or b"")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return [_error("invalid_json", HTTPStatus.BAD_REQUEST)]
        now = datetime.datetime.now(UTC)
        try:
            data = guards.validate_booking(payload, today=now.date())
        except guards.ValidationError as exc:
            return [_error("invalid_field", HTTPStatus.BAD_REQUEST, field=exc.field)]

        if guards.hit_rate_limit(
            cache, f"book-email:{data['email']}", guards.BOOK_LIMIT_PER_EMAIL
        ):
            return [_error(*RATE_LIMITED)]
        # Charged only for well-formed requests, so junk POSTs can't use up the
        # instance-wide budget and lock out real bookings.
        if guards.hit_rate_limit(cache, "book:global", guards.BOOK_LIMIT_GLOBAL):
            log.warning("public booking: instance-wide booking rate limit reached")
            return [_error(*RATE_LIMITED)]

        note_type, name = self._note_type()
        if note_type is None:
            return [_error(*UNAVAILABLE)]
        location_id, _ = booking.active_location()
        if not location_id:
            log.error("public booking: no active practice location")
            return [_error(*UNAVAILABLE)]

        slot = self._match_slot(cache, note_type, name, data)
        if slot is None:
            return [_error("slot_unavailable", HTTPStatus.CONFLICT)]

        # Claim the slot with an add-if-absent, so two concurrent requests for the
        # same slot can't both book it. The hold applies to both outcomes, so the
        # public slot list looks the same whether or not a patient matched.
        claim = str(uuid.uuid4())
        holder = cache.get_or_set(
            booking.hold_key(data["provider_id"], data["start_time"]),
            claim,
            timeout_seconds=booking.hold_seconds(data["start_time"], now),
        )
        if holder != claim:
            return [_error("slot_unavailable", HTTPStatus.CONFLICT)]
        cache.delete(booking.SLOTS_CACHE_KEY)

        patient = booking.find_matching_patient(
            first_name=data["first_name"],
            last_name=data["last_name"],
            birth_date=data["birth_date"],
            email=data["email"],
            phone=data["phone"],
        )
        effects = self._effects(
            data=data,
            slot=slot,
            note_type=note_type,
            location_id=slot.get("location_id") or location_id,
            patient_id=str(patient.id) if patient else None,
        )
        return [*effects, _json(RECEIVED_BODY, HTTPStatus.ACCEPTED)]

    # -- booking helpers -------------------------------------------------------------

    def _match_slot(
        self, cache: Any, note_type: Any, name: str, data: dict
    ) -> dict | None:
        """The open slot for the requested provider + instant, re-checked server-side."""
        for slot in self._open_slots(cache, note_type, name):
            if (
                slot["provider_id"] == data["provider_id"]
                and datetime.datetime.fromisoformat(slot["start_iso"])
                == data["start_time"]
            ):
                return slot
        return None

    def _effects(
        self,
        *,
        data: dict,
        slot: dict,
        note_type: Any,
        location_id: str,
        patient_id: str | None,
    ) -> list[Effect]:
        """Appointment + confirm task for a matched patient; a review task otherwise."""
        request_id = str(uuid.uuid4())
        when = data["start_time"].isoformat()
        team_id = str(self._secrets().get(guards.TEAM_SECRET) or "").strip()
        task_id = str(uuid.uuid4())
        task_kwargs: dict[str, Any] = {
            "id": task_id,
            "status": TaskStatus.OPEN,
            "due": data["start_time"],
            "labels": [TASK_LABEL],
        }
        if team_id:
            task_kwargs["team_id"] = team_id

        effects: list[Effect] = []
        if patient_id:
            effects.append(
                AppointmentEffect(
                    appointment_note_type_id=str(note_type.id),
                    patient_id=patient_id,
                    provider_id=data["provider_id"],
                    practice_location_id=location_id,
                    start_time=data["start_time"],
                    duration_minutes=note_type.online_duration,
                    status=AppointmentProgressStatus.UNCONFIRMED,
                    external_identifiers=[
                        AppointmentIdentifier(
                            system=EXTERNAL_ID_SYSTEM, value=request_id
                        )
                    ],
                ).create()
            )
            task_kwargs["patient_id"] = patient_id
            task_kwargs["title"] = (
                f"Confirm online booking with {slot['provider_name']} at {when}"
            )
        else:
            task_kwargs["title"] = (
                f"Online booking request (no matching patient) with {slot['provider_name']} "
                f"at {when}: register the patient, then book"
            )
        effects.append(AddTask(**task_kwargs).apply())
        effects.append(
            AddTaskComment(
                task_id=task_id, body=_task_comment(data, request_id)
            ).apply()
        )
        return effects


def _task_comment(data: dict, request_id: str) -> str:
    lines = [
        "Submitted through the public booking page. Details are as entered by the requester",
        "and are not verified.",
        f"Name: {data['first_name']} {data['last_name']}",
        f"Date of birth: {data['birth_date'].isoformat()}",
        f"Email: {data['email']}",
        f"Phone: {data['phone']}",
        f"Requested start: {data['start_time'].isoformat()}",
        f"Request id: {request_id}",
    ]
    if data["reason"]:
        lines.append(f"Reason: {data['reason']}")
    return "\n".join(lines)
