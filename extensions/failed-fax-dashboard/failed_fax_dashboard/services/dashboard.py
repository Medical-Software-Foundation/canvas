"""One page of the dashboard: filter, sort, split into sections, page, and describe the rows."""

from datetime import datetime
from typing import Any, Callable

from canvas_sdk.v1.data import ServiceProvider, Staff, Team

from failed_fax_dashboard.models import AlertStart
from failed_fax_dashboard.services.alerts import (
    FALLBACK_TEAM_SETTING,
    RECEIVED_TEAM_SETTING,
    find_team,
)

from failed_fax_dashboard.services.contacts import DIRECTORY_SOURCE, contact_from_provider
from failed_fax_dashboard.services.documents import document_path, match_documents
from failed_fax_dashboard.services.failures import (
    WINDOW_DAYS,
    ReceivedRow,
    SentRow,
    attach_tasks,
    collect_received,
    collect_sent,
    cutoff_for,
    directory_name,
)
from failed_fax_dashboard.services.history import Attempt
from failed_fax_dashboard.services.preferences import clean_tab_view, load_views
from failed_fax_dashboard.services.sources import SOURCES
from failed_fax_dashboard.services.tasks import (
    ASSIGNEE_STAFF,
    ASSIGNEE_TEAM,
    TaskInfo,
    is_mine,
    team_ids_of,
    task_comments,
)
from failed_fax_dashboard.services.util import normalize_number, person_name

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
ME = "__me"
MIN_DIGITS_TO_SEARCH = 3
# Columns whose first click sorts biggest or newest first.
NEWEST_FIRST = ("when", "attempts", "pages")

SENT_SORTS: dict[str, Callable[[Any], Any]] = {
    "patient": lambda row: row.patient_sort,
    "item": lambda row: row.spec.label.lower(),
    "problem": lambda row: row.problem_text.lower(),
    "recipient": lambda row: row.party_name.lower(),
    "sender": lambda row: row.sender_sort,
    "when": lambda row: row.when.timestamp(),
    "pages": lambda row: row.pages or 0,
    "attempts": lambda row: len(row.attempts),
}
RECEIVED_SORTS: dict[str, Callable[[Any], Any]] = {
    "recipient": lambda row: row.party_name.lower(),
    "problem": lambda row: row.problem_text.lower(),
    "pages": lambda row: row.pages or 0,
    "when": lambda row: row.when.timestamp(),
    "task": lambda row: row.task.assignee_sort if row.task is not None else "",
}


def _split_people(values: list[str], staff_id: str) -> tuple[set[str], set[str]]:
    """Staff ids and team ids picked in the person filter (``__me`` is the logged-in staff)."""
    staff_ids: set[str] = set()
    team_ids: set[str] = set()
    for value in values:
        if value == ME:
            staff_ids.add(staff_id)
        elif value.startswith("staff:"):
            staff_ids.add(value[len("staff:") :])
        elif value.startswith("team:"):
            team_ids.add(value[len("team:") :])
    return staff_ids, team_ids


def matches(row: SentRow | ReceivedRow, view: dict[str, Any], staff_id: str) -> bool:
    """Whether the row passes the tab's search, item type, and person filters."""
    kinds = view.get("kinds") or []
    if kinds and (not isinstance(row, SentRow) or row.spec.type_key not in kinds):
        return False
    if view["people"]:
        staff_ids, team_ids = _split_people(view["people"], staff_id)
        wanted = bool(row.sender_staff_ids & staff_ids)
        task = row.task
        if task is not None:
            wanted = wanted or (
                (task.assignee_kind == ASSIGNEE_STAFF and task.assignee_id in staff_ids)
                or (task.assignee_kind == ASSIGNEE_TEAM and task.assignee_id in team_ids)
            )
        if not wanted:
            return False
    query = view["q"].strip().lower()
    if query:
        digits = normalize_number(query)
        in_text = query in row.search_text
        in_number = len(digits) >= MIN_DIGITS_TO_SEARCH and digits in normalize_number(row.number)
        if not in_text and not in_number:
            return False
    return True


def _attempt_json(attempt: Attempt, index: int) -> dict[str, Any]:
    return {
        "at": attempt.created.isoformat(),
        "number": index + 1,
        "who": attempt.sender.label,
        "outcome": attempt.outcome,
        "reason": attempt.reason if attempt.outcome == "failed" else "",
    }


def _task_json(
    task: TaskInfo, comments: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "is_open": task.is_open,
        "due": task.due.isoformat() if task.due is not None else None,
        "url": task.url,
        "assignee": {
            "kind": task.assignee_kind,
            "id": task.assignee_id,
            "name": task.assignee_name,
        },
        "comments": comments,
    }


# Who a row's task will go to while the scheduled job hasn't made it yet: (kind, id).
Owner = tuple[str, str]


def expected_owner(
    row: SentRow | ReceivedRow,
    start: datetime | None,
    fallback: Team | None,
    received_team: Team | None,
) -> Owner | None:
    """Where the scheduled job will put this row's task on its next run, or None.

    None when the row already has a task, when its failure was recorded before the job's
    first run (those never get one), or when no one would get the task.
    """
    if row.task is not None or start is None:
        return None
    if isinstance(row, SentRow):
        if row.event.modified <= start:
            return None
        attempt = next((item for item in row.attempts if item.event_id == str(row.event.id)), row.latest)
        if attempt.sender.is_person:
            return (ASSIGNEE_STAFF, attempt.sender.staff_id)
        return (ASSIGNEE_TEAM, str(fallback.id)) if fallback is not None else None
    if row.fax.modified <= start or received_team is None:
        return None
    return (ASSIGNEE_TEAM, str(received_team.id))


def row_is_mine(row: SentRow | ReceivedRow, owner: Owner | None, staff_id: str, teams: set[str]) -> bool:
    """Whether the row belongs to the viewer.

    With a task: the task's assignee. Waiting for its task: whoever the task will go to.
    Never getting a task (failed before the job started): the person who sent it.
    """
    if row.task is not None:
        return is_mine(row.task, staff_id, teams)
    if owner is not None:
        kind, owner_id = owner
        return owner_id == staff_id if kind == ASSIGNEE_STAFF else owner_id in teams
    if isinstance(row, SentRow):
        attempt = next((item for item in row.attempts if item.event_id == str(row.event.id)), row.latest)
        return attempt.sender.is_person and attempt.sender.staff_id == staff_id
    return False


def _sent_json(
    row: SentRow, mine: bool, comments: dict[str, list[dict[str, Any]]], task_pending: bool = False
) -> dict[str, Any]:
    latest = row.latest
    is_note = row.spec.type_key == "note"
    task = row.task
    task_with = None
    if task is not None and task.assignee_kind:
        with_sender = (
            task.assignee_kind == ASSIGNEE_STAFF
            and latest.sender.is_person
            and task.assignee_id == latest.sender.staff_id
        )
        if not with_sender:
            task_with = {"name": task.assignee_name, "team": task.assignee_kind == ASSIGNEE_TEAM}
    return {
        "key": row.key,
        "direction": "sent",
        "source_type": row.spec.type_key,
        "source_id": str(row.event.id),
        "type_label": row.spec.label,
        "patient_name": row.patient_name,
        "link_url": row.link_url,
        "problem": {"pending": row.pending, "text": row.problem_text},
        "contact": row.contact.as_dict() if row.contact is not None else None,
        "fax_number": row.number,
        "sender": {"label": latest.sender.label, "kind": latest.sender.kind},
        "task_with": task_with,
        "occurred_at": row.when.isoformat(),
        "pages": row.pages,
        "attempts": [_attempt_json(attempt, index) for index, attempt in enumerate(row.attempts)],
        "can_resend": is_note and not row.pending,
        "resend_pending": is_note and row.pending,
        "directory_name": directory_name(row),
        "mine": mine,
        "task": _task_json(task, comments.get(task.id, [])) if task is not None else None,
        "task_pending": task_pending,
    }


def _received_json(
    row: ReceivedRow, mine: bool, comments: dict[str, list[dict[str, Any]]], task_pending: bool = False
) -> dict[str, Any]:
    task = row.task
    return {
        "key": row.key,
        "direction": "received",
        "source_type": "received_fax",
        "source_id": str(row.fax.id),
        "contact": row.contact.as_dict() if row.contact is not None else None,
        "fax_number": row.number,
        "problem": {"pending": False, "text": row.problem_text},
        "occurred_at": row.when.isoformat(),
        "pages": row.pages,
        "link_url": row.link_url,
        "mine": mine,
        "task": _task_json(task, comments.get(task.id, [])) if task is not None else None,
        "task_pending": task_pending,
    }


def _link_documents(rows: list[ReceivedRow]) -> None:
    """Point each received row at its document, and take the sender from the document."""
    documents = match_documents([row.fax for row in rows])
    for row in rows:
        document = documents.get(str(row.fax.id))
        row.link_url = document_path(document)
        provider: ServiceProvider | None = document.service_provider if document else None
        if provider is not None:
            row.contact = contact_from_provider(provider, DIRECTORY_SOURCE)


def view_from_params(tab: str, params: Any, saved: dict[str, Any]) -> dict[str, Any]:
    """The tab's settings from query parameters (or from the saved settings with ``saved=1``)."""
    if params.get("saved") == "1":
        return clean_tab_view(tab, saved)
    sort_key = params.get("sort") or "when"
    default_dir = -1 if sort_key in NEWEST_FIRST else 1
    sort_dir = {"1": 1, "-1": -1}.get(params.get("dir"), default_dir)
    collapsed = {part for part in (params.get("collapsed") or "").split(",") if part}
    return clean_tab_view(
        tab,
        {
            "q": params.get("q") or "",
            "kinds": [part for part in (params.get("kinds") or "").split(",") if part],
            "people": [part for part in (params.get("people") or "").split(",") if part],
            "sort": {"key": sort_key, "dir": sort_dir},
            "collapsed": {"mine": "mine" in collapsed, "rest": "rest" in collapsed},
        },
    )


def _int(raw: Any, default: int) -> int:
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def dashboard_page(
    tab: str,
    params: Any,
    staff_id: str,
    now: datetime | None = None,
    secrets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything the dashboard needs for one tab at the requested filter, sort, and page.

    A failure the scheduled job hasn't reached yet is sectioned under whoever its task will
    go to, so it doesn't move between sections a few minutes later.
    """
    cutoff = cutoff_for(now)
    saved_views = load_views(staff_id)
    view = view_from_params(tab, params, saved_views[tab])

    sent = collect_sent(cutoff)
    received = collect_received(cutoff)
    attach_tasks(sent, received)
    me = Staff.objects.filter(id=staff_id).first()
    teams = team_ids_of(me)
    start_row = AlertStart.objects.first()
    start = start_row.started_at if start_row is not None else None
    settings = secrets or {}
    fallback = find_team(settings, FALLBACK_TEAM_SETTING, quiet=True)
    received_team = find_team(settings, RECEIVED_TEAM_SETTING, quiet=True)

    rows: list[SentRow] | list[ReceivedRow] = sent if tab == "sent" else received
    sorts: dict[str, Any] = SENT_SORTS if tab == "sent" else RECEIVED_SORTS
    shown = [row for row in rows if matches(row, view, staff_id)]
    shown.sort(key=sorts[view["sort"]["key"]], reverse=view["sort"]["dir"] == -1)

    owners = {row.key: expected_owner(row, start, fallback, received_team) for row in shown}
    mine_rows = [row for row in shown if row_is_mine(row, owners[row.key], staff_id, teams)]
    mine_keys = {row.key for row in mine_rows}
    rest_rows = [row for row in shown if row.key not in mine_keys]
    ordered = [] if view["collapsed"]["mine"] else list(mine_rows)
    if not view["collapsed"]["rest"]:
        ordered.extend(rest_rows)

    page_size = min(max(_int(params.get("page_size"), DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
    total_pages = max((len(ordered) + page_size - 1) // page_size, 1)
    page = min(max(_int(params.get("page"), 1), 1), total_pages)
    page_rows = ordered[(page - 1) * page_size : page * page_size]

    if tab == "received":
        _link_documents(page_rows)  # type: ignore[arg-type]
    task_ids = [row.task.id for row in page_rows if row.task is not None]
    comments = task_comments(task_ids, staff_id)

    payload_rows = []
    for row in page_rows:
        is_row_mine = row.key in mine_keys
        pending = owners[row.key] is not None
        if isinstance(row, SentRow):
            payload_rows.append(_sent_json(row, is_row_mine, comments, pending))
        else:
            payload_rows.append(_received_json(row, is_row_mine, comments, pending))

    return {
        "tab": tab,
        "rows": payload_rows,
        "view": view,
        "views": saved_views,
        "totals": {"sent": len(sent), "received": len(received)},
        "shown": len(shown),
        "counts": {"mine": len(mine_rows), "rest": len(rest_rows)},
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "window_days": WINDOW_DAYS,
        "me": {"id": staff_id, "name": person_name(me), "team_ids": sorted(teams)},
        "kinds": [{"value": spec.type_key, "label": spec.label} for spec in SOURCES],
    }

