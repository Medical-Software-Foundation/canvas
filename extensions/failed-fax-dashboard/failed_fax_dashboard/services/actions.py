"""Row actions: resend a note fax, create a follow-up task, dismiss a row."""

from __future__ import annotations

from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any
from uuid import UUID

from canvas_sdk.effects import Effect
from canvas_sdk.effects.fax import FaxNoteEffect
from canvas_sdk.effects.task import AddTask, TaskPriority
from canvas_sdk.v1.data import Fax, FaxDirection, ServiceProvider, Staff, Team

from failed_fax_dashboard.models import FaxDismissal
from failed_fax_dashboard.services.failures import normalize_number, person_name
from failed_fax_dashboard.services.sources import (
    RECEIVED_TYPE,
    SOURCES_BY_KEY,
    TYPE_LABELS,
    walk,
)

ASSIGNEE_TYPES = ("staff", "team")


class ActionError(Exception):
    """A request the dashboard cannot honor, with the HTTP status to return."""

    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _parse_uuid(value: Any, what: str) -> UUID:
    """Parse a UUID from request input."""
    try:
        return UUID(str(value))
    except ValueError as error:
        raise ActionError(f"Invalid {what}") from error


def _text(payload: dict[str, Any], key: str) -> str:
    """A stripped string field from a JSON body ('' when absent or not text)."""
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def load_sent_event(source_type: str, source_id: Any) -> tuple[Any, Any]:
    """Load one failed-send action event with the related rows the actions need."""
    spec = SOURCES_BY_KEY.get(source_type)
    if spec is None:
        raise ActionError("Unknown item type")
    event = (
        spec.model.objects.filter(id=_parse_uuid(source_id, "id"))
        .select_related("fax", *spec.select_related)
        .first()
    )
    if event is None:
        raise ActionError("Fax record not found", HTTPStatus.NOT_FOUND)
    return spec, event


def load_received_fax(source_id: Any) -> Any:
    """Load one inbound fax."""
    fax = Fax.objects.filter(
        id=_parse_uuid(source_id, "id"), direction=FaxDirection.INBOUND
    ).first()
    if fax is None:
        raise ActionError("Fax record not found", HTTPStatus.NOT_FOUND)
    return fax


def _failed_note_event(event_id: Any) -> Any:
    """Load a failed note fax, the only kind that can be resent."""
    _, event = load_sent_event("note", event_id)
    if event.delivered_by_fax is not False:
        raise ActionError("Only a fax that was not delivered can be resent")
    return event


def resend_prefill(event_id: Any) -> dict[str, str]:
    """Number and suggested recipient name for the resend form.

    The recipient name is filled in only when exactly one active contact in the
    directory has this fax number.
    """
    event = _failed_note_event(event_id)
    number = event.fax.to_fax_number if event.fax is not None else ""
    return {"fax_number": number, "recipient_name": _directory_name(number)}


def _directory_name(number: str) -> str:
    """Name of the single directory contact with this fax number, else ''."""
    digits = normalize_number(number)[-10:]
    if len(digits) < 7:
        return ""
    pattern = r"\D*".join(digits) + r"\D*$"
    matches = list(
        ServiceProvider.objects.filter(is_active=True, business_fax__regex=pattern)[:2]
    )
    if len(matches) != 1:
        return ""
    return person_name(matches[0])


def build_resend(payload: dict[str, Any]) -> Effect:
    """Build the FaxNoteEffect that resends a failed note fax."""
    event = _failed_note_event(payload.get("event_id"))
    recipient_name = _text(payload, "recipient_name")
    recipient_number = _text(payload, "recipient_fax_number")
    if not recipient_name:
        raise ActionError("Recipient name is required")
    if not normalize_number(recipient_number):
        raise ActionError("A valid fax number is required")
    return FaxNoteEffect(
        note_id=str(event.note.id),
        recipient_name=recipient_name,
        recipient_fax_number=recipient_number,
    ).apply()


def task_options() -> dict[str, list[dict[str, str]]]:
    """Staff and teams that a follow-up task can be assigned to."""
    staff = Staff.objects.filter(active=True).order_by("last_name", "first_name")
    teams = Team.objects.order_by("name")
    return {
        "staff": [{"id": member.id, "name": person_name(member)} for member in staff],
        "teams": [{"id": str(team.id), "name": team.name} for team in teams],
    }


def _parse_due(raw: str) -> datetime | None:
    """Turn a YYYY-MM-DD date into noon UTC so the calendar day holds in any US timezone."""
    if not raw:
        return None
    try:
        day = date.fromisoformat(raw)
    except ValueError as error:
        raise ActionError("Due date must be YYYY-MM-DD") from error
    return datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)


def build_task(payload: dict[str, Any], author_id: str) -> Effect:
    """Build the AddTask effect for a failed-fax row, authored by the clicking staff member."""
    source_type = _text(payload, "source_type")
    if source_type not in TYPE_LABELS:
        raise ActionError("Unknown item type")

    title = _text(payload, "title")
    if not title:
        raise ActionError("Title is required")

    assignee_type = _text(payload, "assignee_type")
    assignee_id = _text(payload, "assignee_id")
    if assignee_type not in ASSIGNEE_TYPES or not assignee_id:
        raise ActionError("Choose a staff member or a team to assign the task to")

    priority_raw = _text(payload, "priority")
    try:
        priority = TaskPriority(priority_raw) if priority_raw else None
    except ValueError as error:
        raise ActionError("Unknown priority") from error
    due = _parse_due(_text(payload, "due"))

    fields: dict[str, Any] = {
        "title": title,
        "due": due,
        "priority": priority,
        "author_id": author_id,
    }
    if assignee_type == "staff":
        if not Staff.objects.filter(id=assignee_id, active=True).exists():
            raise ActionError("Assignee not found", HTTPStatus.NOT_FOUND)
        fields["assignee_id"] = assignee_id
    else:
        if not Team.objects.filter(id=_parse_uuid(assignee_id, "team id")).exists():
            raise ActionError("Team not found", HTTPStatus.NOT_FOUND)
        fields["team_id"] = assignee_id

    if source_type != RECEIVED_TYPE:
        spec, event = load_sent_event(source_type, payload.get("source_id"))
        patient = walk(event, spec.patient_path)
        if patient is not None:
            fields["patient_id"] = patient.id
        linked = walk(event, spec.link_path)
        if linked is not None and spec.link_type is not None:
            fields["linked_object_id"] = str(linked.id)
            fields["linked_object_type"] = spec.link_type
    else:
        load_received_fax(payload.get("source_id"))

    return AddTask(**fields).apply()


def dismiss_row(payload: dict[str, Any], staff_id: str) -> None:
    """Record that staff dismissed a row. Dismissing twice is harmless."""
    source_type = _text(payload, "source_type")
    if source_type not in TYPE_LABELS:
        raise ActionError("Unknown item type")
    if source_type == RECEIVED_TYPE:
        record_id = load_received_fax(payload.get("source_id")).id
    else:
        record_id = load_sent_event(source_type, payload.get("source_id"))[1].id
    FaxDismissal.objects.get_or_create(
        source_type=source_type,
        source_id=str(record_id),
        defaults={"dismissed_by": staff_id, "dismissed_at": datetime.now(timezone.utc)},
    )
