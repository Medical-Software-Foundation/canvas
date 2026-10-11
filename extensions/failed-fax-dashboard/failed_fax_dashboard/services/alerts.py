"""The scheduled job's logic: one task per failed item and number, kept up to date.

A first failure for an item and number creates the task. Each later failure moves it to
that attempt's sender and reopens it. A later delivered attempt closes it. Each failed
attempt is handled once, and failures from before the job first ran get no task.

Effects apply only after the job returns, so the job can't tell whether Canvas accepted a
new task. An open alert whose task still doesn't exist ``TASK_RETRY_AFTER`` later gets
its task made again, up to ``TASK_RETRIES_MAX`` times.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus, UpdateTask
from canvas_sdk.v1.data import Fax, FaxDirection, Staff, Task, Team
from django.db import IntegrityError
from django.db.transaction import atomic
from django.db.models import Q
from logger import log

from failed_fax_dashboard.models import AlertStart, FaxAlert
from failed_fax_dashboard.services.documents import document_path, match_documents
from failed_fax_dashboard.services.handoff import to_person, to_team
from failed_fax_dashboard.services.failures import (
    WINDOW_DAYS,
    dismissed_keys,
    event_number,
    command_ids,
    item_link,
)
from failed_fax_dashboard.services.history import FAXED, Attempt, Sender, load_attempts
from failed_fax_dashboard.services.routing import (
    provider_ids,
    role_holders,
    routed_holder,
    routing_from,
    warn_if_unknown_role,
)
from failed_fax_dashboard.services.sources import (
    RECEIVED_TYPE,
    SOURCES,
    SourceSpec,
    exclude_deleted_notes,
    walk,
)
from failed_fax_dashboard.services.tasks import TASK_RETRIES_MAX
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
# How long after asking for a task the job waits before treating it as rejected.
TASK_RETRY_AFTER = timedelta(minutes=10)
# The fields each part of the job changes, so a save never overwrites a change made from
# the dashboard in the meantime.
HANDLED_FIELDS = ["last_handled_event_id", "last_handled_at", "assignee", "closed"]
NEW_TASK_FIELDS = ["task_id", "task_made_at", "task_retries"]


def save_fields(alert: FaxAlert, fields: list[str]) -> bool:
    """Save a new alert whole, or only the given fields of an existing one.

    False when a new alert clashes with one saved for the same item and number in the
    meantime (a restore and the scheduled job at the same moment). The other one made
    the task, so the caller drops its own.
    """
    if not alert._state.adding:
        alert.save(update_fields=fields)
        return True
    try:
        with atomic():
            alert.save()
    except IntegrityError:
        log.info(f"A task for {alert.source_type} {alert.item_id} was made at the same moment. Keeping that one.")
        return False
    return True


def missing_task_alerts(now: datetime) -> list[FaxAlert]:
    """Open alerts whose task Canvas never made, asked for at least ``TASK_RETRY_AFTER`` ago."""
    horizon = now - timedelta(days=WINDOW_DAYS)
    candidates = [
        alert
        for alert in FaxAlert.objects.filter(closed=False, last_handled_at__gte=horizon)
        .filter(Q(task_made_at__isnull=True) | Q(task_made_at__lt=now - TASK_RETRY_AFTER))
        .filter(Q(task_retries__isnull=True) | Q(task_retries__lt=TASK_RETRIES_MAX))
        if alert.task_id
    ]
    if not candidates:
        return []
    existing = {
        str(task_id)
        for task_id in Task.objects.filter(id__in=[alert.task_id for alert in candidates]).values_list(
            "id", flat=True
        )
    }
    missing = [alert for alert in candidates if alert.task_id not in existing]
    for alert in missing:
        attempt = (alert.task_retries or 0) + 1
        last = " This is the last try." if attempt == TASK_RETRIES_MAX else ""
        log.warning(
            f"Task {alert.task_id} for a failed fax was never made. Asking again "
            f"(try {attempt} of {TASK_RETRIES_MAX}).{last}"
        )
    return missing


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


def _assign_fields(assignee: str) -> dict[str, str]:
    """The one assignee field for a new task. Never send the unused side: the SDK turns
    ``None`` into ``{"id": None}``, which Canvas rejects along with the whole effect."""
    if assignee.startswith(STAFF_PREFIX):
        return {"assignee_id": assignee[len(STAFF_PREFIX) :]}
    return {"team_id": assignee[len(TEAM_PREFIX) :]}


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


def _assignee_name(assignee: str, attempt: Attempt, fallback: Team | None, holder: Staff | None = None) -> str:
    if holder is not None:
        return person_name(holder)
    if assignee.startswith(STAFF_PREFIX):
        return attempt.sender.name
    return fallback.name if fallback is not None else ""


def sent_failure_effects(
    secrets: dict[str, Any],
    environment: dict[str, Any],
    start: datetime,
    now: datetime,
    since: datetime | None = None,
    retry: list[FaxAlert] | None = None,
    only: dict[str, set[str]] | None = None,
) -> list[Effect]:
    """Create or update tasks for sent faxes whose failure was recorded since ``since``.

    ``start`` (the job's first run) bounds dismissals and the no-backfill rule: a failure
    sent before it never gets a task. ``retry`` alerts get their missing task made again.
    ``only`` (item type to action event ids) handles just those failures, for a row
    restored before its task was made.
    """
    since = since or start
    retrying = {alert.dbid for alert in retry or []}
    skipped = 0
    fallback = find_team(secrets, FALLBACK_TEAM_SETTING)
    routing = routing_from(secrets)
    warn_if_unknown_role(routing)
    zone = practice_zone(environment)
    due = due_today(now, zone)
    dismissed = dismissed_keys(start)
    effects: list[Effect] = []

    for spec in SOURCES:
        failed = spec.model.objects.filter(
            event_type=FAXED, delivered_by_fax=False, created__gte=start, **spec.item_filters
        )
        if only is not None:
            failed = failed.filter(id__in=sorted(only.get(spec.type_key, set())))
        else:
            again = [alert.last_handled_event_id for alert in retry or [] if alert.source_type == spec.type_key]
            failed = failed.filter(Q(modified__gt=since) | Q(id__in=again)) if again else failed.filter(
                modified__gt=since
            )
        events = list(
            exclude_deleted_notes(failed, spec)
            .select_related("fax", "originator__staff", *spec.select_related)
            .defer(*spec.defer)
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
        # A provider's failure goes to the patient's care team member in the configured role.
        senders = {
            attempt.sender.staff_id
            for history in histories.values()
            for attempt in history
            if attempt.sender.is_person
        }
        providers = provider_ids(routing, senders)
        patients = {
            str(patient.id) for patient in (walk(event, spec.patient_path) for event in events) if patient is not None
        }
        holders = role_holders(routing, patients) if providers else {}
        made_now: set[str] = set()
        for event in events:
            number = event_number(event)
            # A resend to a corrected number belongs to the row it was made from.
            e164 = histories.row_number(str(event.id), to_e164(number))
            item_id = str(getattr(event, spec.item_field).id)
            if (spec.type_key, str(event.id)) in dismissed:
                continue
            attempts = histories.get((getattr(event, f"{spec.item_field}_id"), e164), [])
            attempt = next((item for item in attempts if item.event_id == str(event.id)), None)
            if attempt is None:
                continue
            alert = alerts.get((item_id, e164))
            if alert is not None and event.created <= alert.last_handled_at and alert.dbid not in retrying:
                continue
            patient = walk(event, spec.patient_path)
            holder = routed_holder(
                attempt.sender.staff_id, str(patient.id) if patient is not None else None, providers, holders
            )
            assignee = f"{STAFF_PREFIX}{holder.id}" if holder is not None else _sent_assignee(attempt.sender, fallback)
            if not assignee:
                skipped += 1
                continue
            routed_note = (
                f"Sent by {attempt.sender.name}. Assigned to {person_name(holder)}, the patient's {routing.care_team_role}."
                if holder is not None
                else ""
            )
            link = item_link(spec, event, patient, walk(event, spec.note_path), commands)
            task = live_tasks.get(alert.task_id) if alert is not None else None
            fresh = alert is not None and alert.task_id in made_now
            fields_changed = list(HANDLED_FIELDS)
            mark = len(effects)

            if alert is None or (task is None and not fresh):
                task_id = str(uuid4())
                comment = _failure_comment(spec, attempt, link, environment, routed_note)
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
                alert.task_made_at = now
                # A retry counts toward the limit; a task asked for by a new failure starts over.
                alert.task_retries = (alert.task_retries or 0) + 1 if alert.dbid in retrying else 0
                fields_changed += NEW_TASK_FIELDS
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
                    moved = f"Moved from {before} to {_assignee_name(assignee, attempt, fallback, holder)}."
                if routed_note:
                    moved = f"{moved} {routed_note}".strip()
                comment = _failure_comment(spec, attempt, link, environment, moved)
                if assignee.startswith(STAFF_PREFIX) or fallback is None:
                    effects.append(
                        to_person(task_id, assignee[len(STAFF_PREFIX) :], due=due, status=TaskStatus.OPEN).apply()
                    )
                else:
                    handoff = to_team(alert, task, fallback, due=due, reopen=True)
                    effects.extend(handoff.effects)
                    if handoff.task_id != task_id:
                        # A replacement task: a later failure in this run must not make another.
                        made_now.add(handoff.task_id)
                    task_id = handoff.task_id
                effects.append(AddTaskComment(task_id=task_id, body=comment).apply())

            alert.last_handled_event_id = str(event.id)
            alert.last_handled_at = event.created
            alert.assignee = assignee
            alert.closed = False
            if not save_fields(alert, fields_changed):
                del effects[mark:]
                continue
            alerts[(item_id, e164)] = alert
    if skipped:
        log.warning(
            f"{skipped} failed fax(es) sent automatically got no task: {FALLBACK_TEAM_SETTING} "
            "is empty or doesn't match one team."
        )
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
            .defer(*spec.defer)
            .order_by("created")
        )
        delivered = list(delivered)
        if not delivered:
            continue
        histories = load_attempts(spec, [getattr(event, f"{spec.item_field}_id") for event in delivered])
        for event in delivered:
            # A delivered resend to a corrected number clears the row it was made from.
            number = histories.row_number(str(event.id), to_e164(event_number(event)))
            alert = alerts.get((str(getattr(event, spec.item_field).id), number))
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
            alert.save(update_fields=["closed"])
    return effects


def received_failure_effects(
    secrets: dict[str, Any],
    environment: dict[str, Any],
    start: datetime,
    now: datetime,
    since: datetime | None = None,
    retry: list[FaxAlert] | None = None,
    only: set[str] | None = None,
) -> list[Effect]:
    """One task per received fax that arrived in part since ``since`` (and after the start).

    ``retry`` alerts get their missing task made again. ``only`` (fax ids) handles just
    those faxes, for a row restored before its task was made.
    """
    since = since or start
    team = find_team(secrets, RECEIVED_TEAM_SETTING)
    incoming = Fax.objects.filter(direction=FaxDirection.INBOUND, success=False, created__gte=start)
    if team is None:
        skipped = incoming.filter(modified__gt=since).count() if only is None else len(only)
        if skipped:
            log.warning(
                f"{skipped} partly received fax(es) got no task: {RECEIVED_TEAM_SETTING} "
                "is empty or doesn't match one team."
            )
        return []
    dismissed = dismissed_keys(start)
    again = {alert.item_id: alert for alert in retry or [] if alert.source_type == RECEIVED_TYPE}
    if only is not None:
        incoming = incoming.filter(id__in=sorted(only))
    elif again:
        incoming = incoming.filter(Q(modified__gt=since) | Q(id__in=list(again)))
    else:
        incoming = incoming.filter(modified__gt=since)
    faxes = [
        fax for fax in incoming.order_by("created") if (RECEIVED_TYPE, str(fax.id)) not in dismissed
    ]
    known = {
        alert.item_id
        for alert in FaxAlert.objects.filter(
            source_type=RECEIVED_TYPE, item_id__in=[str(fax.id) for fax in faxes]
        )
    }
    faxes = [fax for fax in faxes if str(fax.id) not in known or str(fax.id) in again]
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
        alert = again.get(str(fax.id))
        if alert is not None:
            alert.task_id = task_id
            alert.task_made_at = now
            alert.task_retries = (alert.task_retries or 0) + 1
            alert.assignee = f"{TEAM_PREFIX}{team.id}"
            alert.closed = False
            alert.save(update_fields=[*NEW_TASK_FIELDS, "assignee", "closed"])
            continue
        new_alert = FaxAlert(
            source_type=RECEIVED_TYPE,
            item_id=str(fax.id),
            fax_number=to_e164(number),
            task_id=task_id,
            task_made_at=now,
            last_handled_event_id=str(fax.id),
            last_handled_at=fax.created,
            assignee=f"{TEAM_PREFIX}{team.id}",
        )
        if not save_fields(new_alert, []):
            del effects[-2:]
    return effects


def restored_task_effects(
    secrets: dict[str, Any],
    environment: dict[str, Any],
    sent: dict[str, set[str]],
    received: set[str],
    now: datetime | None = None,
    missing: list[FaxAlert] | None = None,
) -> list[Effect]:
    """Tasks for restored rows that never got one (dismissed before the job reached them).

    ``sent`` maps an item type to action event ids; ``received`` holds fax ids. ``missing``
    holds the rows' alerts whose task Canvas never made, so those are asked for again.
    """
    start_row = AlertStart.objects.first()
    if start_row is None or not (any(sent.values()) or received):
        return []
    moment = now or datetime.now(timezone.utc)
    effects: list[Effect] = []
    if any(sent.values()):
        effects.extend(
            sent_failure_effects(secrets, environment, start_row.started_at, moment, retry=missing, only=sent)
        )
    if received:
        effects.extend(
            received_failure_effects(
                secrets, environment, start_row.started_at, moment, retry=missing, only=received
            )
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
    retry = missing_task_alerts(moment)
    effects = sent_failure_effects(secrets, environment, start, moment, since, retry=retry)
    effects.extend(received_failure_effects(secrets, environment, start, moment, since, retry=retry))
    effects.extend(close_delivered_effects(moment, environment, since))
    start_row.last_run_at = moment
    start_row.save(update_fields=["last_run_at"])
    return effects
