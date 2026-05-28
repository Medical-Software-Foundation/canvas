"""`create_appointment` chat tool (mutation): schedule a new appointment."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import Appointment as AppointmentEffect
from canvas_sdk.v1.data.note import NoteType, NoteTypeCategories
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff


class CreateAppointmentArgs(BaseModel):
    """Arguments for the `create_appointment` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., description="Required.")
    start_time: datetime = Field(
        ...,
        description="ISO datetime, e.g. 2026-05-25T09:00:00. Required.",
    )
    duration_minutes: int = Field(
        30,
        ge=5,
        le=480,
        description="Length in minutes. Defaults to 30.",
    )
    provider_id: str | None = Field(
        None,
        description="Staff id of the clinician. Defaults to the requesting staff_id.",
    )


def create_appointment(
    instance: Any, args: CreateAppointmentArgs, staff_id: str | None
) -> tuple[dict, list[Effect]]:
    """Handler for the `create_appointment` mutation."""
    try:
        patient = Patient.objects.get(id=args.patient_id)
    except Patient.DoesNotExist:
        return {"error": f"patient {args.patient_id!r} not found"}, []

    provider_id = args.provider_id or staff_id
    if not provider_id:
        return {"error": "provider_id required (no staff_id in context)"}, []

    # Default location: patient's default, else the first available practice location.
    location_id = getattr(patient, "default_location_id", None)
    if not location_id:
        location_id = PracticeLocation.objects.values_list("id", flat=True).first()
        if not location_id:
            return {"error": "no practice location configured"}, []

    # Pick a scheduleable encounter note type.
    note_type = (
        NoteType.objects.filter(
            category=NoteTypeCategories.ENCOUNTER,
            is_scheduleable=True,
            is_active=True,
            is_visible=True,
        )
        .values("id", "name")
        .first()
    )
    if not note_type:
        return {"error": "no scheduleable encounter note type configured"}, []

    provider = (
        Staff.objects.filter(id=provider_id).values("first_name", "last_name").first()
    )
    provider_name = (
        f"{provider['first_name']} {provider['last_name']}".strip() if provider else None
    )
    patient_name = f"{patient.first_name} {patient.last_name}".strip()

    effect = AppointmentEffect(
        appointment_note_type_id=note_type["id"],
        patient_id=args.patient_id,
        practice_location_id=str(location_id),
        provider_id=provider_id,
        start_time=args.start_time,
        duration_minutes=args.duration_minutes,
    ).create()

    return (
        {
            "scheduled": True,
            "patient_id": args.patient_id,
            "patient_name": patient_name or None,
            "provider_id": provider_id,
            "provider_name": provider_name or None,
            "start_time": args.start_time.isoformat(),
            "duration_minutes": args.duration_minutes,
            "note_type": note_type["name"],
            "note": "Appointment creation queued; will appear in Canvas momentarily.",
        },
        [effect],
    )

TOOL_SPEC = {
    "name": "create_appointment",
    "description": "Schedule a new appointment in Canvas. Mutating tool — the user "
    "must approve before it actually runs. Defaults provider to the "
    "requesting clinician (the staff_id in the user-message framing); "
    "location and appointment type default to sensible options (the "
    "patient's primary location, a standard encounter note type) so "
    "you do not need to supply them.",
    "args_model": CreateAppointmentArgs,
    "handler": create_appointment,
    "mutates": True,
}
