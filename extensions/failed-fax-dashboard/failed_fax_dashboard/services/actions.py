"""Row actions: resend a note fax, dismiss a row, reassign a task, comment on a task."""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from uuid import UUID

from canvas_sdk.effects import Effect
from canvas_sdk.effects.fax import FaxNoteEffect
from canvas_sdk.effects.task import AddTaskComment, UpdateTask
from canvas_sdk.v1.data import Fax, FaxDirection, Staff, Team

from failed_fax_dashboard.models import FaxAlert, FaxDismissal, FaxResend
from failed_fax_dashboard.services.history import FAXED
from failed_fax_dashboard.services.sources import RECEIVED_TYPE, SOURCES_BY_KEY, TYPE_LABELS
from failed_fax_dashboard.services.util import (
    STAFF_PREFIX,
    TEAM_PREFIX,
    normalize_number,
    person_name,
    to_e164,
)

MAX_COMMENT = 5000


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


def build_resend(payload: dict[str, Any], staff_id: str, now: datetime | None = None) -> Effect:
    """Remember who clicked Resend and build the FaxNoteEffect that sends the note again."""
    event = _failed_note_event(payload.get("event_id"))
    recipient_name = _text(payload, "recipient_name")
    recipient_number = _text(payload, "recipient_fax_number")
    if not recipient_name:
        raise ActionError("Recipient name is required")
    if not normalize_number(recipient_number):
        raise ActionError("A valid fax number is required")
    staff = Staff.objects.filter(id=staff_id).first()
    if staff is None:
        raise ActionError("Staff member not found", HTTPStatus.FORBIDDEN)
    failed_number = to_e164(event.fax.to_fax_number if event.fax is not None else "")
    later = [
        other
        for other in SOURCES_BY_KEY["note"].model.objects.filter(
            note_id=event.note_id, event_type=FAXED, created__gt=event.created
        ).select_related("fax")
        if other.fax is not None and to_e164(other.fax.to_fax_number) == failed_number
    ]
    if later:
        raise ActionError("This fax was already sent again", HTTPStatus.CONFLICT)
    FaxResend.objects.create(
        note_id=event.note_id,
        staff_id=staff.dbid,
        fax_number=to_e164(recipient_number),
        resent_at=now or datetime.now(timezone.utc),
    )
    return FaxNoteEffect(
        note_id=str(event.note.id),
        recipient_name=recipient_name,
        recipient_fax_number=recipient_number,
    ).apply()


def build_resend_takeover(payload: dict[str, Any], staff_id: str) -> list[Effect]:
    """Move the row's task to whoever clicked Resend, since they've taken the fax on.

    Nothing to do when the row has no task yet, the task is closed, or it's already theirs.
    """
    event = _failed_note_event(payload.get("event_id"))
    actor = _actor(staff_id)
    failed_number = to_e164(event.fax.to_fax_number if event.fax is not None else "")
    alert: FaxAlert | None = FaxAlert.objects.filter(
        source_type="note", item_id=str(event.note.id), fax_number=failed_number, closed=False
    ).first()
    mine = f"{STAFF_PREFIX}{actor.id}"
    if alert is None or alert.assignee == mine:
        return []
    alert.assignee = mine
    alert.save()
    name = person_name(actor)
    return [
        UpdateTask(id=alert.task_id, assignee_id=actor.id, team_id=None).apply(),
        AddTaskComment(
            task_id=alert.task_id,
            body=f"{name} resent the fax and took over this task.",
            author_id=actor.id,
        ).apply(),
    ]


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


def _alert_for_task(task_id: str) -> FaxAlert:
    """The alert behind a task. Only tasks this plugin made can be changed from the dashboard."""
    alert: FaxAlert | None = FaxAlert.objects.filter(
        task_id=str(_parse_uuid(task_id, "task id"))
    ).first()
    if alert is None:
        raise ActionError("Task not found", HTTPStatus.NOT_FOUND)
    return alert


def _actor(staff_id: str) -> Staff:
    staff = Staff.objects.filter(id=staff_id).first()
    if staff is None:
        raise ActionError("Staff member not found", HTTPStatus.FORBIDDEN)
    return staff


def build_reassign(payload: dict[str, Any], staff_id: str) -> list[Effect]:
    """Move a task to a person or team and leave a comment saying who did it."""
    actor = _actor(staff_id)
    alert = _alert_for_task(_text(payload, "task_id"))
    choice = _text(payload, "assignee")
    if choice.startswith(STAFF_PREFIX):
        target = Staff.objects.filter(id=choice[len(STAFF_PREFIX) :], active=True).first()
        if target is None:
            raise ActionError("Assignee not found", HTTPStatus.NOT_FOUND)
        name = person_name(target)
        update = UpdateTask(id=alert.task_id, assignee_id=target.id, team_id=None)
    elif choice.startswith(TEAM_PREFIX):
        team = Team.objects.filter(id=_parse_uuid(choice[len(TEAM_PREFIX) :], "team id")).first()
        if team is None:
            raise ActionError("Assignee not found", HTTPStatus.NOT_FOUND)
        name = team.name
        update = UpdateTask(id=alert.task_id, assignee_id=None, team_id=str(team.id))
    else:
        raise ActionError("Choose a person or a team")
    alert.assignee = choice
    alert.save()
    comment = AddTaskComment(
        task_id=alert.task_id,
        body=f"Reassigned to {name} by {person_name(actor)}.",
        author_id=actor.id,
    )
    return [update.apply(), comment.apply()]


def build_comment(payload: dict[str, Any], staff_id: str) -> Effect:
    """A reply on a task, written under the logged-in staff member's name."""
    actor = _actor(staff_id)
    alert = _alert_for_task(_text(payload, "task_id"))
    body = _text(payload, "body")
    if not body:
        raise ActionError("Write a comment first")
    if len(body) > MAX_COMMENT:
        raise ActionError("That comment is too long")
    return AddTaskComment(task_id=alert.task_id, body=body, author_id=actor.id).apply()
