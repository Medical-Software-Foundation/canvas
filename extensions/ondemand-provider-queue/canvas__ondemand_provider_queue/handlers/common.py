"""Helpers shared by the queue's API, websocket and note handlers."""

from __future__ import annotations

from datetime import date
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast
from canvas_sdk.v1.data import Patient, Staff

from canvas__ondemand_provider_queue.settings import Settings
from canvas__ondemand_provider_queue.storage.base import QueueEntry

CHANNEL = "queue"


def staff_allowed(settings: Settings, user_type: str | None, user_id: str | None) -> bool:
    """Return True for a logged-in staff member who may use the queue.

    ``QUEUE_STAFF_IDS`` narrows access further; left empty, every active staff
    member signed in to Canvas may use it (the same people who can open the app).
    """
    if user_type != "Staff" or not user_id:
        return False
    return not settings.staff_ids or user_id in settings.staff_ids


def notify(event_type: str, entry: QueueEntry | None = None) -> Effect:
    """Tell open queue screens something changed. Carries ids only, never patient data."""
    message: dict[str, Any] = {"type": event_type}
    if entry is not None:
        message.update(
            entry_id=entry.id,
            status=entry.status,
            provider_id=entry.assigned_provider_id,
        )
    return Broadcast(channel=CHANNEL, message=message).apply()


def staff_name(staff: Staff) -> str:
    """Return a staff member's display name."""
    return f"{staff.first_name} {staff.last_name}".strip()


def age_in_years(birth_date: date | None, today: date) -> int | None:
    """Return whole years between a birth date and today, or None without a birth date."""
    if birth_date is None:
        return None
    before_birthday = (today.month, today.day) < (birth_date.month, birth_date.day)
    return today.year - birth_date.year - int(before_birthday)


def with_patient_details(entries: list[QueueEntry]) -> list[dict[str, Any]]:
    """Add patient name, birth date, age and sex to each entry with one query."""
    ids = {e.patient_id for e in entries}
    patients = {
        p.id: p
        for p in Patient.objects.filter(id__in=ids).only(
            "id", "first_name", "last_name", "birth_date", "sex_at_birth"
        )
    }
    rows = []
    for entry in entries:
        row = entry.to_dict()
        patient = patients.get(entry.patient_id)
        if patient is not None:
            row["patient_name"] = f"{patient.first_name} {patient.last_name}".strip()
            row["patient_dob"] = patient.birth_date.isoformat() if patient.birth_date else None
            row["patient_age"] = age_in_years(patient.birth_date, date.today())
            row["patient_sex"] = patient.sex_at_birth or None
        rows.append(row)
    return rows
