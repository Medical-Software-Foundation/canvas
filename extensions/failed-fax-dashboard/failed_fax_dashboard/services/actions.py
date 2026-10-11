"""Row actions: resend a note fax, dismiss a row, reassign a task, comment on a task."""

from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from uuid import UUID

from canvas_sdk.effects import Effect
from canvas_sdk.effects.fax import FaxNoteEffect
from canvas_sdk.effects.task import AddTaskComment, TaskStatus, UpdateTask
from canvas_sdk.v1.data import Fax, FaxDirection, Staff, Task, Team
from django.db import IntegrityError
from django.db.models import Q
from django.db.transaction import atomic

from failed_fax_dashboard.models import FaxAlert, FaxDismissal, FaxResend
from failed_fax_dashboard.services.alerts import restored_task_effects
from failed_fax_dashboard.services.handoff import to_person, to_team
from failed_fax_dashboard.services.history import Histories, load_attempts
from failed_fax_dashboard.services.sources import RECEIVED_TYPE, SOURCES_BY_KEY, TYPE_LABELS
from failed_fax_dashboard.services.util import (
    STAFF_PREFIX,
    TEAM_PREFIX,
    is_fax_number,
    person_name,
    to_e164,
)

MAX_COMMENT = 5000
# Most rows one bulk dismiss or restore may carry.
MAX_ROWS = 200


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
        .defer(*spec.defer)
        .first()
    )
    if event is None:
        raise ActionError("Fax record not found", HTTPStatus.NOT_FOUND)
    return spec, event


def _failed_note_event(event_id: Any) -> Any:
    """Load a failed note fax, the only kind that can be resent."""
    _, event = load_sent_event("note", event_id)
    if event.delivered_by_fax is not False:
        raise ActionError("Only a fax that was not delivered can be resent")
    return event


def _note_row(event: Any, now: datetime | None = None) -> tuple[str, Histories]:
    """The E.164 number of the row a failed note send belongs to, and the note's attempts.

    A send that was itself a resend to a corrected number belongs to the row it came from.
    """
    histories = load_attempts(SOURCES_BY_KEY["note"], [event.note_id], now=now)
    number = to_e164(event.fax.to_fax_number if event.fax is not None else "")
    return histories.row_number(str(event.id), number), histories


def build_resend(payload: dict[str, Any], staff_id: str, now: datetime | None = None) -> Effect:
    """Remember who clicked Resend and build the FaxNoteEffect that sends the note again.

    Refused when the row already has a later send (to any number) or a Resend click still
    waiting for its send, so two clicks moments apart send the note only once.
    """
    event = _failed_note_event(payload.get("event_id"))
    recipient_name = _text(payload, "recipient_name")
    recipient_number = _text(payload, "recipient_fax_number")
    if not recipient_name:
        raise ActionError("Recipient name is required")
    if not is_fax_number(recipient_number):
        raise ActionError("Enter a 10-digit fax number")
    staff = Staff.objects.filter(id=staff_id).first()
    if staff is None:
        raise ActionError("Staff member not found", HTTPStatus.FORBIDDEN)
    moment = now or datetime.now(timezone.utc)
    row_number, histories = _note_row(event, moment)
    row = (event.note_id, row_number)
    if row in histories.waiting or any(
        attempt.created > event.created for attempt in histories.get(row, [])
    ):
        raise ActionError("This fax was already sent again", HTTPStatus.CONFLICT)
    # Each resend of this failed send takes the next numbered claim. Two clicks at the same
    # instant reach for the same claim, and the database lets only one of them have it.
    earlier = FaxResend.objects.filter(claim__startswith=f"{event.id}:").count()
    try:
        with atomic():
            FaxResend.objects.create(
                note_id=event.note_id,
                staff_id=staff.dbid,
                fax_number=to_e164(recipient_number),
                from_fax_number=row_number,
                resent_at=moment,
                claim=f"{event.id}:{earlier}",
            )
    except IntegrityError as error:
        raise ActionError("This fax was already sent again", HTTPStatus.CONFLICT) from error
    return FaxNoteEffect(
        note_id=str(event.note.id),
        recipient_name=recipient_name,
        recipient_fax_number=recipient_number,
    ).apply()


def build_resend_takeover(payload: dict[str, Any], staff_id: str) -> list[Effect]:
    """Move the row's task to whoever clicked Resend, since they've taken the fax on.

    Nothing to do when the row has no task yet, the task is closed (on the dashboard or
    in Canvas), or it's already theirs.
    """
    event = _failed_note_event(payload.get("event_id"))
    actor = _actor(staff_id)
    row_number, _ = _note_row(event)
    alert: FaxAlert | None = FaxAlert.objects.filter(
        source_type="note", item_id=str(event.note.id), fax_number=row_number, closed=False
    ).first()
    mine = f"{STAFF_PREFIX}{actor.id}"
    if alert is None or alert.assignee == mine:
        return []
    if not Task.objects.filter(id=alert.task_id, status="OPEN").exists():
        return []
    alert.assignee = mine
    alert.save(update_fields=["assignee"])
    name = person_name(actor)
    return [
        to_person(alert.task_id, actor.id).apply(),
        AddTaskComment(
            task_id=alert.task_id,
            body=f"{name} resent the fax and took over this task.",
            author_id=actor.id,
        ).apply(),
    ]


def _row_keys(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    """The rows a dismiss or restore names, as (item type, record id).

    The body carries ``keys``, each the row's key ``"{item type}:{record id}"``.
    """
    keys = payload.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ActionError("Choose at least one row")
    if len(keys) > MAX_ROWS:
        raise ActionError(f"Choose at most {MAX_ROWS} rows at a time")
    parsed: list[tuple[str, Any]] = []
    for key in keys:
        source_type, _, source_id = str(key).partition(":")
        if source_type not in TYPE_LABELS:
            raise ActionError("Unknown item type")
        parsed.append((source_type, source_id))
    return parsed


@dataclass
class _Row:
    """One row named by a dismiss or restore: its failed record and its alert (task)."""

    source_type: str
    record_id: str
    alert: FaxAlert | None


def _load_rows(keys: list[tuple[str, Any]]) -> list[_Row]:
    """The failed record and alert for each named row, in a few queries for all of them.

    Raises when any row's record is missing, so one bad key changes nothing.
    """
    by_type: dict[str, list[UUID]] = {}
    for source_type, source_id in keys:
        by_type.setdefault(source_type, []).append(_parse_uuid(source_id, "id"))
    # (item type, record id) -> (item id, E.164 number of the row)
    records: dict[tuple[str, str], tuple[str, str]] = {}
    for source_type, ids in by_type.items():
        if source_type == RECEIVED_TYPE:
            for fax in Fax.objects.filter(id__in=ids, direction=FaxDirection.INBOUND):
                records[(RECEIVED_TYPE, str(fax.id))] = (str(fax.id), to_e164(fax.from_fax_number))
            continue
        spec = SOURCES_BY_KEY[source_type]
        events = list(
            spec.model.objects.filter(id__in=ids).select_related("fax", *spec.select_related).defer(*spec.defer)
        )
        histories = (
            load_attempts(spec, [event.note_id for event in events]) if spec.type_key == "note" else Histories()
        )
        for event in events:
            number = to_e164(event.fax.to_fax_number if event.fax is not None else "")
            records[(source_type, str(event.id))] = (
                str(getattr(event, spec.item_field).id),
                histories.row_number(str(event.id), number),
            )
    alerts = {
        (alert.source_type, alert.item_id, alert.fax_number): alert
        for alert in FaxAlert.objects.filter(item_id__in=sorted({item for item, _ in records.values()}))
    }
    rows: list[_Row] = []
    for source_type, source_id in keys:
        record_id = str(_parse_uuid(source_id, "id"))
        found = records.get((source_type, record_id))
        if found is None:
            raise ActionError("Fax record not found", HTTPStatus.NOT_FOUND)
        rows.append(_Row(source_type, record_id, alerts.get((source_type, *found))))
    return rows


def dismiss_rows(payload: dict[str, Any], staff_id: str) -> list[Effect]:
    """Dismiss rows and close each one's open task, with a comment naming who dismissed it.

    Dismissing a row twice is harmless and closes nothing the second time.
    """
    keys = _row_keys(payload)
    actor = _actor(staff_id)
    rows = _load_rows(keys)
    alerts = [row.alert for row in rows if row.alert is not None]
    statuses = {
        str(task_id): status
        for task_id, status in Task.objects.filter(
            id__in=[alert.task_id for alert in alerts if alert.task_id]
        ).values_list("id", "status")
    }
    open_ids = {task_id for task_id, status in statuses.items() if status == "OPEN"}
    already = {
        (dismissal.source_type, dismissal.source_id)
        for dismissal in FaxDismissal.objects.filter(source_id__in=[row.record_id for row in rows])
    }
    now = datetime.now(timezone.utc)
    effects: list[Effect] = []
    for row in rows:
        if (row.source_type, row.record_id) in already:
            continue
        already.add((row.source_type, row.record_id))
        alert = row.alert
        closes = alert is not None and alert.task_id in open_ids
        FaxDismissal.objects.create(
            source_type=row.source_type,
            source_id=row.record_id,
            dismissed_by=actor.id,
            dismissed_at=now,
            closed_task_id=alert.task_id if closes and alert is not None else "",
        )
        if alert is not None and not closes and alert.task_id not in statuses and not alert.closed:
            # Canvas never made this row's task: stop the job asking for it while dismissed.
            alert.closed = True
            alert.save(update_fields=["closed"])
        if not closes or alert is None:
            continue
        effects.append(UpdateTask(id=alert.task_id, status=TaskStatus.CLOSED).apply())
        effects.append(
            AddTaskComment(
                task_id=alert.task_id,
                body=f"Dismissed from the Failed Faxes dashboard by {person_name(actor)}.",
                author_id=actor.id,
            ).apply()
        )
        alert.closed = True
        alert.save(update_fields=["closed"])
        open_ids.discard(alert.task_id)
    return effects


def restore_rows(
    payload: dict[str, Any],
    staff_id: str,
    secrets: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
) -> list[Effect]:
    """Bring dismissed rows back and reopen the tasks their dismissal closed.

    A task that was already closed before the dismissal, or that a later failure has
    since replaced, stays as it is. A row dismissed before it ever got a task gets one now.
    """
    keys = _row_keys(payload)
    actor = _actor(staff_id)
    # Load every row before changing any, so one bad key changes nothing.
    rows = _load_rows(keys)
    dismissals = {
        (dismissal.source_type, dismissal.source_id): dismissal
        for dismissal in FaxDismissal.objects.filter(source_id__in=[row.record_id for row in rows])
    }
    existing = {
        str(task_id)
        for task_id in Task.objects.filter(
            id__in=[row.alert.task_id for row in rows if row.alert is not None and row.alert.task_id]
        ).values_list("id", flat=True)
    }
    effects: list[Effect] = []
    new_sent: dict[str, set[str]] = {}
    new_received: set[str] = set()
    missing: list[FaxAlert] = []
    for row in rows:
        dismissal = dismissals.pop((row.source_type, row.record_id), None)
        if dismissal is None:
            continue
        closed_id = dismissal.closed_task_id or ""
        dismissal.delete()
        alert = row.alert
        if alert is None or alert.task_id not in existing:
            # Never had a task, or Canvas never made it: make one now.
            if alert is not None:
                missing.append(alert)
            if row.source_type == RECEIVED_TYPE:
                new_received.add(row.record_id)
            else:
                new_sent.setdefault(row.source_type, set()).add(row.record_id)
            continue
        if not closed_id or alert.task_id != closed_id:
            continue
        effects.append(UpdateTask(id=closed_id, status=TaskStatus.OPEN).apply())
        effects.append(
            AddTaskComment(task_id=closed_id, body=f"Task reopened by {person_name(actor)}.", author_id=actor.id).apply()
        )
        alert.closed = False
        alert.save(update_fields=["closed"])
    effects.extend(
        restored_task_effects(secrets or {}, environment or {}, new_sent, new_received, missing=missing)
    )
    return effects


def _alert_for_task(task_id: str) -> FaxAlert:
    """The alert behind a task. Only tasks this plugin made can be changed from the dashboard.

    A task replaced in a hand-off to a team still finds its alert, so a dashboard opened
    before the hand-off acts on the row's current task instead of failing.
    """
    key = str(_parse_uuid(task_id, "task id"))
    alert: FaxAlert | None = FaxAlert.objects.filter(
        Q(task_id=key) | Q(previous_task_ids__contains=key)
    ).first()
    if alert is None:
        raise ActionError("Task not found", HTTPStatus.NOT_FOUND)
    return alert


def current_task_id(task_id: str) -> str:
    """The id of the row's task now, which a hand-off to a team replaces."""
    current: str = _alert_for_task(task_id).task_id
    return current


def _require_task(alert: FaxAlert) -> Task:
    """The alert's task, which must exist before it can be moved or commented on."""
    task = Task.objects.filter(id=alert.task_id).select_related("assignee", "patient").first()
    if task is None:
        raise ActionError(
            "This fax's task hasn't been made yet. Try again in a few minutes.", HTTPStatus.CONFLICT
        )
    return task


def _actor(staff_id: str) -> Staff:
    staff = Staff.objects.filter(id=staff_id).first()
    if staff is None:
        raise ActionError("Staff member not found", HTTPStatus.FORBIDDEN)
    return staff


def build_reassign(payload: dict[str, Any], staff_id: str) -> list[Effect]:
    """Move a task to a person or team and leave a comment saying who did it."""
    actor = _actor(staff_id)
    alert = _alert_for_task(_text(payload, "task_id"))
    task = _require_task(alert)
    choice = _text(payload, "assignee")
    if choice.startswith(STAFF_PREFIX):
        target = Staff.objects.filter(id=choice[len(STAFF_PREFIX) :], active=True).first()
        if target is None:
            raise ActionError("Assignee not found", HTTPStatus.NOT_FOUND)
        name = person_name(target)
        alert.assignee = choice
        alert.save(update_fields=["assignee"])
        comment = AddTaskComment(
            task_id=alert.task_id,
            body=f"Reassigned to {name} by {person_name(actor)}.",
            author_id=actor.id,
        )
        return [to_person(alert.task_id, target.id).apply(), comment.apply()]
    if not choice.startswith(TEAM_PREFIX):
        raise ActionError("Choose a person or a team")
    team = Team.objects.filter(id=_parse_uuid(choice[len(TEAM_PREFIX) :], "team id")).first()
    if team is None:
        raise ActionError("Assignee not found", HTTPStatus.NOT_FOUND)
    if task.assignee is not None:
        # A person holds it and can't be removed: close theirs and open one for the team.
        return to_team(alert, task, team, by=person_name(actor), author_id=actor.id).effects
    handoff = to_team(alert, task, team)
    comment = AddTaskComment(
        task_id=handoff.task_id,
        body=f"Reassigned to {team.name} by {person_name(actor)}.",
        author_id=actor.id,
    )
    return [*handoff.effects, comment.apply()]


def build_comment(payload: dict[str, Any], staff_id: str) -> Effect:
    """A reply on a task, written under the logged-in staff member's name."""
    actor = _actor(staff_id)
    alert = _alert_for_task(_text(payload, "task_id"))
    _require_task(alert)
    body = _text(payload, "body")
    if not body:
        raise ActionError("Write a comment first")
    if len(body) > MAX_COMMENT:
        raise ActionError("That comment is too long")
    return AddTaskComment(task_id=alert.task_id, body=body, author_id=actor.id).apply()
