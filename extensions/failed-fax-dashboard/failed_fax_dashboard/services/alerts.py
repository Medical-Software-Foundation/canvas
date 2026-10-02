"""The scheduled job's logic: one task per failed item and number, kept up to date.

A first failure for an item and number creates the task. Each later failure moves it to
that attempt's sender and reopens it. A later delivered attempt closes it. Each failed
attempt is handled once, and failures from before the job first ran get no task.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus, UpdateTask
from canvas_sdk.v1.data import Fax, FaxDirection, Staff, Task, Team
from logger import log

from failed_fax_dashboard.models import AlertStart, FaxAlert
from failed_fax_dashboard.services.documents import document_path, match_documents
from failed_fax_dashboard.services.failures import (
    WINDOW_DAYS,
    dismissed_keys,
    event_number,
    command_ids,
    item_link,
)
from failed_fax_dashboard.services.history import FAXED, Attempt, Sender, load_attempts
from failed_fax_dashboard.services.sources import RECEIVED_TYPE, SOURCES, SourceSpec, walk
from failed_fax_dashboard.services.util import (
    STAFF_PREFIX,
    TEAM_PREFIX,
    due_today,
    format_local,
    full_url,
    person_name,
    practice_zone,
    to_e164,
)

LABEL = "Failed fax"
FALLBACK_TEAM_SETTING = "FAILED_FAX_FALLBACK_TEAM"
RECEIVED_TEAM_SETTING = "RECEIVED_FAX_TASK_TEAM"
RECEIVED_PROBLEM = "Only part of the fax arrived"
# Each run re-reads this far back past the previous run, so a fax whose result lands
# while a run is in progress (or a run that was skipped) is still picked up.
RUN_OVERLAP = timedelta(minutes=15)


def _plural(count: int | None, word: str) -> str:
    amount = count or 0
    return f"{amount} {word}" + ("" if amount == 1 else "s")


def find_team(secrets: dict[str, Any], setting: str, *, quiet: bool = False) -> Team | None:
    """The team named in a setting, matched exactly. Empty or unknown names give None.

    The scheduled job warns about a name that matches no team or several; page loads pass
    ``quiet`` so the warning isn't repeated on every view.
    """
    name = (secrets.get(setting) or "").strip()
    if not name:
        return None
    teams = list(Team.objects.filter(name=name)[:2])
    if len(teams) != 1:
        if not quiet:
            log.warning(f"{setting} is '{name}', which matches {len(teams)} teams. No task made.")
        return None
    return teams[0]


def _sent_assignee(sender: Sender, fallback: Team | None) -> str:
    """``staff:<id>`` for the sender, else the fallback team, else '' (no task)."""
    if sender.is_person:
        return f"{STAFF_PREFIX}{sender.staff_id}"
    if fallback is not None:
        return f"{TEAM_PREFIX}{fallback.id}"
    return ""


def _assign_fields(assignee: str) -> dict[str, str | None]:
    """The assignee/team pair for a task effect. The unused side is cleared."""
    if assignee.startswith(STAFF_PREFIX):
        return {"assignee_id": assignee[len(STAFF_PREFIX) :], "team_id": None}
    return {"assignee_id": None, "team_id": assignee[len(TEAM_PREFIX) :]}


def _failure_comment(
    spec: SourceSpec,
    attempt: Attempt,
    link: str | None,
    environment: dict[str, Any],
    moved: str,
) -> str:
    """Reason first and link last: the task list shows only the start of the latest comment."""
    zone = practice_zone(environment)
    reason = (attempt.reason or "The fax was not delivered").rstrip(" .")
    parts = [f"{reason}. Sent {format_local(attempt.created, zone)}, {_plural(attempt.pages, 'page')}."]
    if moved:
        parts.append(moved)
    if link:
        parts.append(f"Open the {spec.noun}: {full_url(environment, link)}")
    return " ".join(parts)


def _task_assignee(task: Task) -> str:
    """``staff:<id>`` or ``team:<id>`` for whoever holds the task now ('' when no one)."""
    if task.assignee is not None:
        return f"{STAFF_PREFIX}{task.assignee.id}"
    if task.team is not None:
        return f"{TEAM_PREFIX}{task.team.id}"
    return ""


def _current_assignee_name(task: Task) -> str:
    if task.assignee is not None:
        return person_name(task.assignee)
    if task.team is not None:
        team_name: str = task.team.name
        return team_name
    return "no one"


def _assignee_name(assignee: str, attempt: Attempt, fallback: Team | None) -> str:
    if assignee.startswith(STAFF_PREFIX):
        return attempt.sender.name
    return fallback.name if fallback is not None else ""


def sent_failure_effects(
    secrets: dict[str, Any],
    environment: dict[str, Any],
    start: datetime,
    now: datetime,
    since: datetime | None = None,
) -> list[Effect]:
    """Create or update tasks for sent faxes whose failure was recorded since ``since``.

    ``start`` (the job's first run) still bounds dismissals and the no-backfill rule.
    """
    since = since or start
    fallback = find_team(secrets, FALLBACK_TEAM_SETTING)
    zone = practice_zone(environment)
    due = due_today(now, zone)
    dismissed = dismissed_keys(start)
    effects: list[Effect] = []

    for spec in SOURCES:
        events = list(
            spec.model.objects.filter(
                event_type=FAXED,
                delivered_by_fax=False,
                modified__gt=since,
                **spec.item_filters,
            )
            .exclude(**spec.item_excludes)
            .select_related("fax", "originator__staff", *spec.select_related)
            .order_by("created")
        )
        if not events:
            continue
        histories = load_attempts(spec, [getattr(event, f"{spec.item_field}_id") for event in events])
        commands = command_ids(spec, events)
        alerts = {
            (alert.item_id, alert.fax_number): alert
            for alert in FaxAlert.objects.filter(
                source_type=spec.type_key,
                item_id__in=[str(getattr(event, spec.item_field).id) for event in events],
            )
        }
        live_tasks = {
            str(task.id): task
            for task in Task.objects.filter(
                id__in=[alert.task_id for alert in alerts.values()]
            ).select_related("assignee", "team")
        }
        made_now: set[str] = set()
        for event in events:
            number = event_number(event)
            e164 = to_e164(number)
            item_id = str(getattr(event, spec.item_field).id)
            if (spec.type_key, str(event.id)) in dismissed:
                continue
            attempts = histories.get((getattr(event, f"{spec.item_field}_id"), e164), [])
            attempt = next((item for item in attempts if item.event_id == str(event.id)), None)
            if attempt is None:
                continue
            alert = alerts.get((item_id, e164))
            if alert is not None and event.created <= alert.last_handled_at:
                continue
            assignee = _sent_assignee(attempt.sender, fallback)
            if not assignee:
                continue
            patient = walk(event, spec.patient_path)
            link = item_link(spec, event, patient, walk(event, spec.note_path), commands)
            task = live_tasks.get(alert.task_id) if alert is not None else None
            fresh = alert is not None and alert.task_id in made_now

            if alert is None or (task is None and not fresh):
                task_id = str(uuid4())
                comment = _failure_comment(spec, attempt, link, environment, "")
                fields: dict[str, Any] = {
                    "id": task_id,
                    "title": f"Fax didn't go through: {spec.label} to {number}",
                    "due": due,
                    "labels": [LABEL],
                    "patient_id": patient.id if patient is not None else None,
                    **_assign_fields(assignee),
                }
                linked = walk(event, spec.link_path)
                if linked is not None and spec.link_type is not None:
                    fields["linked_object_id"] = str(linked.id)
                    fields["linked_object_type"] = spec.link_type
                effects.append(AddTask(**fields).apply())
                effects.append(AddTaskComment(task_id=task_id, body=comment).apply())
                alert = alert or FaxAlert(source_type=spec.type_key, item_id=item_id, fax_number=e164)
                alert.task_id = task_id
                made_now.add(task_id)
            else:
                task_id = alert.task_id
                moved = ""
                if task is not None:
                    current = _task_assignee(task)
                    before = _current_assignee_name(task)
                else:
                    current, before = alert.assignee, "the previous sender"
                if current != assignee:
                    moved = f"Moved from {before} to {_assignee_name(assignee, attempt, fallback)}."
                comment = _failure_comment(spec, attempt, link, environment, moved)
                effects.append(
                    UpdateTask(
                        id=task_id, due=due, status=TaskStatus.OPEN, **_assign_fields(assignee)
                    ).apply()
                )
                effects.append(AddTaskComment(task_id=task_id, body=comment).apply())

            alert.last_handled_event_id = str(event.id)
            alert.last_handled_at = event.created
            alert.assignee = assignee
            alert.closed = False
            alert.save()
            alerts[(item_id, e164)] = alert
    return effects


def close_delivered_effects(
    now: datetime, environment: dict[str, Any], since: datetime | None = None
) -> list[Effect]:
    """Close the task of every open alert whose item was delivered to the same number since ``since``."""
    zone = practice_zone(environment)
    horizon = now - timedelta(days=WINDOW_DAYS)
    since = max(since, horizon) if since is not None else horizon
    effects: list[Effect] = []
    open_alerts = FaxAlert.objects.filter(closed=False, last_handled_at__gte=horizon).exclude(
        source_type=RECEIVED_TYPE
    )
    for spec in SOURCES:
        alerts = {
            (alert.item_id, alert.fax_number): alert
            for alert in open_alerts
            if alert.source_type == spec.type_key
        }
        if not alerts:
            continue
        delivered = (
            spec.model.objects.filter(
                event_type=FAXED,
                delivered_by_fax=True,
                modified__gt=since,
                **{f"{spec.item_field}__id__in": [item for item, _ in alerts]},
            )
            .select_related("fax", spec.item_field)
            .order_by("created")
        )
        for event in delivered:
            key = (str(getattr(event, spec.item_field).id), to_e164(event_number(event)))
            alert = alerts.get(key)
            if alert is None or alert.closed or event.created <= alert.last_handled_at:
                continue
            effects.append(UpdateTask(id=alert.task_id, status=TaskStatus.COMPLETED).apply())
            effects.append(
                AddTaskComment(
                    task_id=alert.task_id,
                    body=f"Delivered {format_local(event.created, zone)}.",
                ).apply()
            )
            alert.closed = True
            alert.save()
    return effects


def received_failure_effects(
    secrets: dict[str, Any],
    environment: dict[str, Any],
    start: datetime,
    now: datetime,
    since: datetime | None = None,
) -> list[Effect]:
    """One task per received fax that arrived in part since ``since`` (and after the start)."""
    since = since or start
    team = find_team(secrets, RECEIVED_TEAM_SETTING)
    if team is None:
        return []
    dismissed = dismissed_keys(start)
    faxes = [
        fax
        for fax in Fax.objects.filter(
            direction=FaxDirection.INBOUND, success=False, modified__gt=since
        ).order_by("created")
        if (RECEIVED_TYPE, str(fax.id)) not in dismissed
    ]
    known = {
        alert.item_id
        for alert in FaxAlert.objects.filter(
            source_type=RECEIVED_TYPE, item_id__in=[str(fax.id) for fax in faxes]
        )
    }
    faxes = [fax for fax in faxes if str(fax.id) not in known]
    if not faxes:
        return []
    documents = match_documents(faxes)
    due = due_today(now, practice_zone(environment))
    effects: list[Effect] = []
    for fax in faxes:
        task_id = str(uuid4())
        link = full_url(environment, document_path(documents.get(str(fax.id))))
        number = fax.from_fax_number
        body = (
            f"{RECEIVED_PROBLEM}. {_plural(fax.fax_pages, 'page')} arrived. "
            f"Ask the sender to fax again. Open Data Integration: {link}"
        )
        effects.append(
            AddTask(
                id=task_id,
                title=f"Fax arrived incomplete from {number}",
                team_id=str(team.id),
                due=due,
                labels=[LABEL],
            ).apply()
        )
        effects.append(AddTaskComment(task_id=task_id, body=body).apply())
        FaxAlert.objects.create(
            source_type=RECEIVED_TYPE,
            item_id=str(fax.id),
            fax_number=to_e164(number),
            task_id=task_id,
            last_handled_event_id=str(fax.id),
            last_handled_at=fax.created,
            assignee=f"{TEAM_PREFIX}{team.id}",
        )
    return effects


def alert_effects(
    secrets: dict[str, Any], environment: dict[str, Any], now: datetime | None = None
) -> list[Effect]:
    """Everything the scheduled job returns on one run."""
    moment = now or datetime.now(timezone.utc)
    start_row = AlertStart.objects.first()
    if start_row is None:
        start_row = AlertStart.objects.create(started_at=moment)
    start = start_row.started_at
    # Read only what changed since the previous run (less the overlap), never before the start.
    previous = start_row.last_run_at
    since = max(start, previous - RUN_OVERLAP) if previous is not None else start
    effects = sent_failure_effects(secrets, environment, start, moment, since)
    effects.extend(received_failure_effects(secrets, environment, start, moment, since))
    effects.extend(close_delivered_effects(moment, environment, since))
    start_row.last_run_at = moment
    start_row.save(update_fields=["last_run_at"])
    return effects
