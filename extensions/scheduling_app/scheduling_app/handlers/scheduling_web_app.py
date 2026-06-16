"""SimpleAPI handler serving the scheduling UI and its data/booking endpoints.

The UI is a React (Vite) app. Its built bundle is base64-embedded into
``_assets.py`` at build time and served here as raw bytes — NOT via
``render_to_string``, whose Django template engine would corrupt a minified
bundle containing ``{{`` / ``{%``. Reference data is read through the ORM, and
bookings are written through appointment effects (see booking.py). See the
README for the v1 limitations (no availability grid, no "scheduled together"
linking, etc.).
"""

from __future__ import annotations

import datetime
from base64 import b64decode
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data.appointment import Appointment, AppointmentLabel
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import NoteType, NoteTypeCategories
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.reason_for_visit import ReasonForVisitSettingCoding
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import TaskLabel, TaskLabelModule
from logger import log

# Import the asset names directly: the sandbox's _safe_getattr blocks reaching
# attributes off a module object (e.g. ``_assets.BUILT`` -> AttributeError).
from scheduling_app._assets import ASSETS, BUILT
from scheduling_app.booking import build_booking_effects

# Offered when no structured reason-for-visit durations apply. The per-visit-type
# duration list the built-in modal uses isn't exposed to the SDK (see README).
DEFAULT_DURATIONS = [15, 20, 30, 45, 60]

# The built-in modal renders a *coded* reason-for-visit dropdown when the
# `STRUCTURED_REASON_FOR_VISIT_ENABLED` constance flag is on, and a free-text
# field when it's off (the shipped default is False). That flag isn't exposed to
# plugins through any SDK data model or database view, so we can't read it at
# runtime — mirror your instance's setting here and the UI renders accordingly.
STRUCTURED_REASON_FOR_VISIT = False

# Content types for the built assets served by /app/assets/<filename>.
CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "js": "text/javascript",
    "css": "text/css",
    "svg": "image/svg+xml",
    "png": "image/png",
    "ico": "image/x-icon",
    "woff": "font/woff",
    "woff2": "font/woff2",
}

# Shown until the frontend has been built (``yarn build`` in ./frontend).
NOT_BUILT_HTML = (
    "<!doctype html><html><body style='font-family:sans-serif;padding:24px'>"
    "<h2>Scheduling UI not built</h2>"
    "<p>Run <code>yarn build</code> in <code>scheduling_app/frontend</code> "
    "to generate the bundle.</p></body></html>"
)


def _durations_to_minutes(durations: list[datetime.timedelta]) -> list[int]:
    """Convert an RFV setting's duration list (timedeltas) to whole minutes."""
    return [int(duration.total_seconds() // 60) for duration in durations]


def _patient_summary(patient: Patient) -> dict[str, Any]:
    """Patient fields the UI's selected-patient card shows (name + demographics).

    Age is intentionally computed client-side from ``birthDate`` so this stays a
    pure data read (no server-side "now").
    """
    phone = patient.primary_phone_number
    return {
        "id": patient.id,
        "name": f"{patient.first_name} {patient.last_name}".strip(),
        "birthDate": patient.birth_date.isoformat() if patient.birth_date else None,
        "sex": patient.sex_at_birth or None,
        "phone": phone.value if phone else None,
    }


def _reference_data(category: str) -> dict[str, Any]:
    """Gather the dropdown data for the form, all via the SDK ORM."""
    note_type_category = (
        NoteTypeCategories.SCHEDULE_EVENT
        if category == "schedule_event"
        else NoteTypeCategories.ENCOUNTER
    )
    visit_types = NoteType.objects.filter(
        is_active=True, is_scheduleable=True, category=note_type_category
    ).order_by("name")

    # Only user-selected codings, matching the built-in modal (which filters
    # `coding__user_selected=True`); this drops inactive/unconfigured codes.
    rfv_settings = ReasonForVisitSettingCoding.objects.filter(user_selected=True).order_by(
        "display"
    )

    # Appointment-applicable labels: the modal shows active labels whose modules
    # include 'appointments' (or that are unscoped), ordered by their configured
    # position (matching the built-in: Emergent, Urgent, Routine, Chart, …).
    labels = [
        {"id": str(label.id), "name": label.name, "color": label.color}
        for label in TaskLabel.objects.filter(active=True).order_by("position", "name")
        if not label.modules or TaskLabelModule.APPOINTMENTS in label.modules
    ]

    return {
        "providers": [
            {"id": staff.id, "name": staff.full_name}
            for staff in Staff.objects.filter(active=True).order_by("last_name", "first_name")
        ],
        "locations": [
            {"id": str(location.id), "name": location.full_name}
            for location in PracticeLocation.objects.filter(active=True).order_by("full_name")
        ],
        "visitTypes": [
            {
                "id": str(visit_type.id),
                "name": visit_type.name,
                "isTelehealth": visit_type.is_telehealth,
                "isDefault": visit_type.is_default_appointment_type,
                "allowCustomTitle": visit_type.allow_custom_title,
                "isPatientRequired": visit_type.is_patient_required,
            }
            for visit_type in visit_types
        ],
        "reasonsForVisit": [
            {
                # `id` (the coding's external id) is what a structured RFV command
                # references; `code`/`display` are for showing the option.
                "id": str(rfv.id),
                "code": rfv.code,
                "display": rfv.display,
                "durations": _durations_to_minutes(rfv.duration),
            }
            for rfv in rfv_settings
        ],
        "defaultDurations": DEFAULT_DURATIONS,
        "labels": labels,
        "structuredReasonForVisit": STRUCTURED_REASON_FOR_VISIT,
    }


# A reason-for-visit is persisted as a command of this schema on the note.
RFV_SCHEMA_KEY = "reasonForVisit"


def _appointment_labels(appointment: Appointment) -> list[str]:
    """Label names on the appointment (shown read-only on the reschedule form)."""
    return [
        link.task_label.name
        for link in AppointmentLabel.objects.filter(appointment=appointment).select_related(
            "task_label"
        )
        if link.task_label
    ]


def _appointment_rfv(appointment: Appointment) -> dict[str, Any]:
    """The note's current reason-for-visit, mapped to the form's fields.

    home-app stores a coded reason as the coding *code*, not the external id the
    form's dropdown uses, so a coded reason is reverse-mapped back to that id. A
    free-text reason round-trips through the command's comment.
    """
    empty: dict[str, Any] = {"rfvCode": None, "rfvText": None, "comment": None}
    note = appointment.note
    if note is None:
        return empty
    command = (
        Command.objects.filter(note=note, schema_key=RFV_SCHEMA_KEY)
        .exclude(state="entered_in_error")
        .order_by("-dbid")
        .first()
    )
    if command is None:
        return empty
    data = command.data or {}
    comment = data.get("comment") or None
    coding_code = data.get("coding")
    if coding_code:
        rfv_id = (
            ReasonForVisitSettingCoding.objects.filter(code=coding_code)
            .values_list("id", flat=True)
            .first()
        )
        return {"rfvCode": str(rfv_id) if rfv_id else None, "rfvText": None, "comment": comment}
    return {"rfvCode": None, "rfvText": comment, "comment": None}


def _appointment_summary(appointment: Appointment) -> dict[str, Any]:
    """Existing appointment details used to prefill the reschedule form."""
    return {
        "id": str(appointment.id),
        "providerId": appointment.provider.id if appointment.provider else None,
        "locationId": str(appointment.location.id) if appointment.location else None,
        "visitTypeId": str(appointment.note_type.id) if appointment.note_type else None,
        "startTime": appointment.start_time.isoformat() if appointment.start_time else None,
        "durationMinutes": appointment.duration_minutes,
        "patientId": appointment.patient.id if appointment.patient else None,
        "labels": _appointment_labels(appointment),
        **_appointment_rfv(appointment),
    }


def _reschedule_rfv_context(appointment_id: str | None) -> dict[str, str | None]:
    """Resolve the surviving note + existing reason-for-visit command for a reschedule.

    Looked up fresh server-side (never trusted from the client) so booking.py can
    edit or originate the reason-for-visit while staying a pure payload-to-effects
    function. Returns an empty dict when there's nothing to resolve.
    """
    if not appointment_id:
        return {}
    appointment = Appointment.objects.select_related("note").filter(id=appointment_id).first()
    if appointment is None or appointment.note is None:
        return {}
    command_id = (
        Command.objects.filter(note=appointment.note, schema_key=RFV_SCHEMA_KEY)
        .exclude(state="entered_in_error")
        .order_by("-dbid")
        .values_list("id", flat=True)
        .first()
    )
    return {
        "note_id": str(appointment.note.id),
        "rfv_command_id": str(command_id) if command_id else None,
    }


class SchedulingWebApp(StaffSessionAuthMixin, SimpleAPI):
    """Serves the scheduling iframe app, its reference data, and booking."""

    PREFIX = "/app"

    @api.get("/modal")
    def modal(self) -> list[Response | Effect]:
        """Serve the React app's HTML shell (it reads context from the URL)."""
        if not BUILT or "index.html" not in ASSETS:
            return [HTMLResponse(NOT_BUILT_HTML, status_code=HTTPStatus.OK)]
        return [
            Response(
                b64decode(ASSETS["index.html"]),
                status_code=HTTPStatus.OK,
                content_type=CONTENT_TYPES["html"],
            )
        ]

    @api.get("/assets/<filename>")
    def asset(self) -> list[Response | Effect]:
        """Serve a built asset (app.js, app.css, ...) as raw bytes."""
        filename = self.request.path_params["filename"]
        encoded = ASSETS.get(filename)
        if encoded is None:
            return [Response(b"Not found", status_code=HTTPStatus.NOT_FOUND)]
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return [
            Response(
                b64decode(encoded),
                status_code=HTTPStatus.OK,
                content_type=CONTENT_TYPES.get(extension, "application/octet-stream"),
            )
        ]

    @api.get("/patients")
    def patients(self) -> list[Response | Effect]:
        """Search patients by name, or look one up by id (for context prefill)."""
        patient_id = self.request.query_params.get("id")
        query = (self.request.query_params.get("q") or "").strip()

        found: dict[str, Patient] = {}
        if patient_id:
            patient = Patient.objects.filter(id=patient_id).first()
            if patient:
                found[patient.id] = patient
        elif len(query) >= 2:
            # `django.db.models.Q` isn't available in the sandbox, so OR across
            # first/last name with two queries and de-dupe.
            for lookup in ("first_name__icontains", "last_name__icontains"):
                for patient in Patient.objects.filter(**{lookup: query})[:10]:
                    found[patient.id] = patient

        results = [_patient_summary(patient) for patient in list(found.values())[:10]]
        return [JSONResponse({"patients": results})]

    @api.get("/reference")
    def reference(self) -> list[Response | Effect]:
        """Return the form's dropdown data for the requested category."""
        category = self.request.query_params.get("category", "appointment")
        return [JSONResponse(_reference_data(category))]

    @api.get("/appointment")
    def appointment(self) -> list[Response | Effect]:
        """Return an existing appointment's details to prefill the reschedule form."""
        appointment_id = self.request.query_params.get("id")
        appointment = (
            Appointment.objects.select_related("provider", "location", "note_type", "note", "patient")
            .filter(id=appointment_id)
            .first()
        )
        if not appointment:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]

        return [JSONResponse(_appointment_summary(appointment))]

    @api.post("/book")
    def book(self) -> list[Response | Effect]:
        """Book (or reschedule) from the submitted form, returning the effect(s)."""
        payload = self.request.json()
        # Resolve the surviving note + existing RFV command server-side so the
        # reschedule can edit/originate the reason-for-visit (booking.py stays pure).
        if payload.get("mode") == "reschedule":
            payload.update(_reschedule_rfv_context(payload.get("appointment_id")))
        try:
            effects = build_booking_effects(payload)
        except (KeyError, ValueError) as error:
            return [JSONResponse({"error": str(error)}, status_code=HTTPStatus.BAD_REQUEST)]
        except Exception as error:
            # Surface the cause (e.g. a pydantic ValidationError from .create())
            # rather than letting it become an opaque 500.
            log.exception("Failed to build booking effects")
            return [JSONResponse({"error": str(error)}, status_code=HTTPStatus.BAD_REQUEST)]

        return [JSONResponse({"booked": True}), *effects]
