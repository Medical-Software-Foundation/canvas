"""Builds the daily readiness board from Canvas SDK data.

Step 2 covers today's appointments and the scope/provider/location filters.
Readiness columns (labs/imaging/referral/auth), outreach, and the action
panels are layered on in later steps.

All queries are bulk and keyed off a single appointment fetch (no per-patient
queries in a loop).
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from django.db.models import Prefetch, Q

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import PatientMetadata as PatientMetadataEffect
from canvas_sdk.effects.task import (
    AddTask,
    AddTaskComment,
    TaskStatus as EffectTaskStatus,
    UpdateTask,
)
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.imaging import ImagingOrder, ImagingReport
from canvas_sdk.v1.data.lab import LabOrder, LabReport
from canvas_sdk.v1.data.common import ContactPointSystem
from canvas_sdk.v1.data.message import Message
from canvas_sdk.v1.data.patient import PatientContactPoint, PatientMetadata
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.prescription import Prescription
from canvas_sdk.v1.data.referral import Referral, ReferralReport
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import Task, TaskPriority, TaskStatus
from canvas_sdk.v1.data.team import Team

# Plugin-owned patient-metadata keys (this plugin owns the namespace; no access
# key required for PatientMetadata upserts).
OUTREACH_KEY = "dd.outreach.log"           # value = JSON list of attempts
OVERRIDE_PREFIX = "dd.override."           # + category -> "true" marks complete
OVERRIDABLE = ("labs", "imaging", "referral", "auth")
OUTREACH_CHANNELS = ("Call", "Fax", "Email")
OUTREACH_RECIPIENTS = ("PCP", "Patient")

# Max items listed in each action panel (the count reflects the true total).
PANEL_LIMIT = 5

# Appointment progress states that mean "this visit isn't happening today".
DEAD_STATUSES = (
    AppointmentProgressStatus.CANCELLED,
    AppointmentProgressStatus.NOSHOWED,
)

# Readiness cell states.
COMPLETE = "complete"      # an order exists and a result/report has come back
INCOMPLETE = "incomplete"  # an order exists but no result yet (needs chasing)
NOT_NEEDED = "not-needed"   # no order on file for this category

# Each readiness category: (key, order model, report model, order→reports
# relation). Readiness is computed per order: an order is "resulted" when it has
# at least one non-junked report linked through that relation. The relation
# differs per model — labs use a M2M through LabTest (`LabOrder.reports`),
# imaging a reverse FK (`ImagingOrder.results`), referrals a reverse FK
# (`Referral.reports`) — but each resolves to the order's non-junked reports.
_CATEGORIES = (
    ("labs", LabOrder, LabReport, "reports"),
    ("imaging", ImagingOrder, ImagingReport, "results"),
    ("referral", Referral, ReferralReport, "reports"),
)


def resolve_tz(tz_name: str | None) -> ZoneInfo | dt_timezone:
    """Resolve a timezone name (browser- or admin-supplied) to a tzinfo.

    Falls back to UTC for empty or unrecognized names so a bad value never
    breaks the board. (ZoneInfoNotFoundError subclasses KeyError.)
    """
    if not tz_name or tz_name.strip().upper() == "UTC":
        return dt_timezone.utc
    try:
        return ZoneInfo(tz_name.strip())
    except (KeyError, ValueError):
        return dt_timezone.utc


def _patient_name(patient: Any) -> str:
    """Render a patient as 'Last, First' (falling back gracefully)."""
    if patient is None:
        return "Unknown patient"
    last = (patient.last_name or "").strip()
    first = (patient.first_name or "").strip()
    if last and first:
        return f"{last}, {first}"
    return last or first or "Unknown patient"


def _format_time(dt_local: datetime) -> str:
    """Format a local datetime as e.g. '9:00 AM' (no leading zero)."""
    hour = dt_local.hour % 12 or 12
    suffix = "AM" if dt_local.hour < 12 else "PM"
    return f"{hour}:{dt_local.minute:02d} {suffix}"


def _day_window(
    tz: ZoneInfo | dt_timezone, offset: int = 0
) -> tuple[datetime, datetime, Any]:
    """Return (start, end, date) for today+offset in the clinic timezone.

    The bounds are timezone-aware so the DB comparison is correct regardless of
    how far the clinic zone is from UTC. offset=0 → today, 1 → tomorrow.
    """
    day = datetime.now(tz).date() + timedelta(days=offset)
    start_dt = datetime.combine(day, time.min, tzinfo=tz)
    end_dt = start_dt + timedelta(days=1)
    return start_dt, end_dt, day


def _chart_base(customer_identifier: str | None) -> str:
    """Base URL for patient-chart deep-links on the target instance."""
    identifier = (customer_identifier or "example").strip() or "example"
    return f"https://{identifier}.canvasmedical.com"


def build_board(
    *,
    tz_name: str | None,
    staff_id: str | None,
    scope: str,
    provider_id: str | None,
    location_id: str | None,
    customer_identifier: str | None = None,
    messaging_app_id: str | None = None,
    day: str = "today",
) -> dict[str, Any]:
    """Build the board payload: the day's rows plus filter option lists."""
    tz = resolve_tz(tz_name)
    offset = 1 if day == "tomorrow" else 0
    start_dt, end_dt, today = _day_window(tz, offset)

    # Base set: all of today's real, scheduled appointments. Drives both the
    # filter option lists and (after further filtering) the rows.
    base_qs = (
        Appointment.objects.filter(
            start_time__gte=start_dt,
            start_time__lt=end_dt,
            patient__isnull=False,
            entered_in_error__isnull=True,
        )
        .exclude(status__in=DEAD_STATUSES)
    )

    providers = _provider_options(base_qs)
    locations = _location_options(base_qs)

    # Apply the active filters to produce the visible rows. A chosen provider
    # (dropdown) wins over the "My day" logged-in user; whichever is in effect
    # scopes both the rows and the tasks panel (by assignee). Using a single
    # effective id avoids double-filtering into an empty set when "mine" and an
    # explicit provider disagree.
    row_qs = base_qs
    effective_provider = provider_id or (staff_id if scope == "mine" else None)
    if effective_provider:
        row_qs = row_qs.filter(provider__id=effective_provider)
    if location_id:
        row_qs = row_qs.filter(location__id=location_id)
    task_assignee_id: str | None = effective_provider

    row_qs = row_qs.select_related("patient", "provider", "location").order_by("start_time")

    appts = list(row_qs)
    patient_pks = {appt.patient_id for appt in appts}
    details = _readiness_details(patient_pks, tz)
    meta = _metadata_by_patient(patient_pks)
    phones = _phones_by_patient(patient_pks)

    rows = []
    for appt in appts:
        local = appt.start_time.astimezone(tz)
        cat_detail = details.get(appt.patient_id, {})
        pmeta = meta.get(appt.patient_id, {})
        overrides = pmeta.get("overrides", set())

        def _state(category: str) -> str:
            # A manual "Mark complete" override always wins.
            if category in overrides:
                return COMPLETE
            return str(cat_detail.get(category, {}).get("state", NOT_NEEDED))

        def _items(category: str) -> list[dict[str, str]]:
            return list(cat_detail.get(category, {}).get("items", []))

        rows.append(
            {
                "appointment_id": str(appt.id),
                "time_iso": appt.start_time.isoformat(),
                "time_display": _format_time(local),
                "patient_id": str(appt.patient.id),
                "patient_name": _patient_name(appt.patient),
                "provider": appt.provider.credentialed_name if appt.provider else "—",
                "location": appt.location.full_name if appt.location else "—",
                "phone": phones.get(appt.patient_id, ""),
                "readiness": {
                    "labs": _state("labs"),
                    "imaging": _state("imaging"),
                    "referral": _state("referral"),
                    # Authorization has no SDK source — purely the manual flag.
                    "auth": COMPLETE if "auth" in overrides else NOT_NEEDED,
                },
                "details": {
                    "labs": _items("labs"),
                    "imaging": _items("imaging"),
                    "referral": _items("referral"),
                    "auth": [],
                },
                "overrides": sorted(overrides),
                "outreach": _outreach_summary(pmeta.get("outreach"), tz),
                "outreach_count": pmeta.get("outreach_count", 0),
                "outreach_detail": _outreach_detail(pmeta.get("outreach_log"), tz),
            }
        )

    return {
        "date_display": _date_label(today),
        "date_iso": today.isoformat(),
        "day": "tomorrow" if offset else "today",
        "scope": scope if scope in ("all", "mine") else "all",
        # The signed-in user's id, so the UI can default the provider filter to
        # them (only meaningful if they appear in `providers`).
        "current_staff_id": staff_id or "",
        "rows": rows,
        "providers": providers,
        "locations": locations,
        # Tasks follow the provider filter (as assignee), independent of which
        # patients are scheduled. Tomorrow view → tasks due tomorrow.
        "panels": build_panels(
            patient_pks,
            tz,
            phones,
            due_window=(start_dt, end_dt) if offset else None,
            task_assignee_id=task_assignee_id,
        ),
        "chart_base": _chart_base(customer_identifier),
        "messaging_app": (messaging_app_id or "").strip(),
        "staff_options": staff_options(),
        "team_options": team_options(),
        "priorities": [p.value for p in TaskPriority],
    }


def _short_dt(dt: datetime | None, tz: ZoneInfo | dt_timezone, with_time: bool = False) -> str:
    """Format a datetime as 'Jun 26' (or 'Jun 26, 9:00 AM') in the clinic tz."""
    if dt is None:
        return ""
    local = dt.astimezone(tz)
    base = f"{local.strftime('%b')} {local.day}"
    return f"{base}, {_format_time(local)}" if with_time else base


def _med_name(med: Any) -> str:
    """Best-effort medication label from its codings (prefetched)."""
    if med is None:
        return "Medication"
    for coding in med.codings.all():
        if coding.display:
            return str(coding.display)
    return str(med.national_drug_code or "Medication")


def build_panels(
    patient_ids: set[Any],
    tz: ZoneInfo | dt_timezone,
    phones: dict[Any, str] | None = None,
    due_window: tuple[datetime, datetime] | None = None,
    task_assignee_id: str | None = None,
) -> dict[str, Any]:
    """Build the three action panels.

    Each panel returns a true total `count` plus up to PANEL_LIMIT `items`.

    Tasks are **not** scoped to the board's patients: by default the panel lists
    every open task, and when the board is filtered to a provider it is scoped to
    that provider's assigned tasks (``task_assignee_id``). Refills and messages
    stay scoped to the board's patients (``patient_ids``).

    When ``due_window`` is supplied (the "Tomorrow" view), the tasks panel is
    narrowed to tasks *due* within that window — "what's due tomorrow". Refills
    and messages carry no due date, so they are never date-filtered and show the
    same set regardless of the day toggle.
    """
    phones = phones or {}
    empty = {"count": 0, "items": []}

    # Tasks — open tasks, soonest due first. Scoped to the selected provider (as
    # assignee) when filtered, otherwise all open tasks. Independent of which
    # patients are scheduled today. In the Tomorrow view, restrict to tasks due
    # tomorrow.
    task_qs = (
        Task.objects.filter(status=TaskStatus.OPEN)
        .select_related("patient", "assignee", "team")
        .order_by("due")
    )
    if task_assignee_id:
        # Match the Staff UUID (`id`), not the raw integer assignee_id (dbid) FK.
        task_qs = task_qs.filter(assignee__id=task_assignee_id)
    if due_window is not None:
        task_qs = task_qs.filter(due__gte=due_window[0], due__lt=due_window[1])

    task_items = list(task_qs[:PANEL_LIMIT])
    # Tasks can reference patients who aren't on today's board, so make sure we
    # have phone numbers for click-to-dial on any such patients too.
    extra_pks = {t.patient_id for t in task_items if t.patient_id and t.patient_id not in phones}
    if extra_pks:
        phones = {**phones, **_phones_by_patient(extra_pks)}

    tasks = {
        "count": task_qs.count(),
        "items": [
            {
                "id": str(t.id),
                "title": t.title or "Task",
                "patient_name": _patient_name(t.patient),
                "patient_id": str(t.patient.id) if t.patient else "",
                "phone": phones.get(t.patient_id, ""),
                "meta": _short_dt(t.due, tz) or "No due date",
                # Current field values, so the in-dashboard editor can prefill.
                # Emit the Staff/Team UUIDs (matching the picker options), not the
                # raw integer dbid FKs.
                "assignee_id": str(t.assignee.id) if t.assignee else "",
                "team_id": str(t.team.id) if t.team else "",
                "due_iso": t.due.date().isoformat() if t.due else "",
                "priority": t.priority or "",
                "status": t.status or "OPEN",
            }
            for t in task_items
        ],
    }

    # Refills + messages remain scoped to the board's patients.
    if not patient_ids:
        return {"tasks": tasks, "refills": dict(empty), "messages": dict(empty)}

    # Refills — refill prescriptions for today's patients, most recent first.
    rx_qs = (
        Prescription.objects.filter(
            patient_id__in=patient_ids, is_refill=True, entered_in_error__isnull=True
        )
        .select_related("patient", "medication")
        .prefetch_related("medication__codings")
        .order_by("-written_date")
    )
    refills = {
        "count": rx_qs.count(),
        "items": [
            {
                "medication": _med_name(rx.medication),
                "patient_name": _patient_name(rx.patient),
                "patient_id": str(rx.patient.id) if rx.patient else "",
                "phone": phones.get(rx.patient_id, ""),
                "meta": (rx.status or "").replace("-", " ").title()
                or _short_dt(rx.written_date, tz),
            }
            for rx in rx_qs[:PANEL_LIMIT]
        ],
    }

    # New messages — unread, sent by one of today's patients (sender is a Patient).
    # patient_ids hold the Patient pk (the value carried by every patient_id FK
    # column). Traverse via `pk`, not the external UUID `id` field.
    msg_qs = (
        Message.objects.filter(read__isnull=True, sender__patient__pk__in=patient_ids)
        .select_related("sender__patient")
        .order_by("-created")
    )
    messages = {
        "count": msg_qs.count(),
        "items": [
            {
                "patient_name": _patient_name(m.sender.patient),
                "patient_id": str(m.sender.patient.id) if m.sender and m.sender.patient else "",
                "phone": phones.get(m.sender.patient.pk, "") if m.sender and m.sender.patient else "",
                "snippet": (m.content or "").strip()[:200],
                "meta": _short_dt(m.created, tz, with_time=True),
            }
            for m in msg_qs[:PANEL_LIMIT]
        ],
    }

    return {"tasks": tasks, "refills": refills, "messages": messages}


def _date_label(day: Any) -> str:
    """Format a date as 'Wednesday, June 25' without platform-specific codes."""
    return f"{day.strftime('%A')}, {day.strftime('%B')} {day.day}"


def record_outreach(
    patient_id: str,
    *,
    channel: str,
    recipient_type: str,
    recipient: str,
    outcome: str,
    note: str,
    user: str,
) -> Effect:
    """Append an outreach attempt to the patient's log and return the upsert."""
    existing = (
        PatientMetadata.objects.filter(patient__id=patient_id, key=OUTREACH_KEY).first()
    )
    try:
        log = json.loads(existing.value) if existing and existing.value else []
    except (ValueError, TypeError):
        log = []
    if not isinstance(log, list):
        log = []
    log.append(
        {
            "date": datetime.now(dt_timezone.utc).isoformat(),
            "channel": channel,
            "recipient_type": recipient_type,
            "recipient": recipient,
            "outcome": outcome,
            "note": note,
            "user": user,
        }
    )
    return PatientMetadataEffect(patient_id=patient_id, key=OUTREACH_KEY).upsert(json.dumps(log))


def set_override(patient_id: str, category: str, complete: bool) -> Effect:
    """Set/clear a manual 'Mark complete' override for a readiness category."""
    key = f"{OVERRIDE_PREFIX}{category}"
    return PatientMetadataEffect(patient_id=patient_id, key=key).upsert("true" if complete else "false")


# One-shot prompt the Assistant panel (ChatApp) reads + sends on open.
PREP_PROMPT_KEY = "dd.prep_prompt"


def stage_prep_prompt(patient_id: str, prompt: str) -> Effect:
    """Stage an Appointment Prep prompt the Assistant panel will auto-send once."""
    return PatientMetadataEffect(patient_id=patient_id, key=PREP_PROMPT_KEY).upsert(prompt)


def create_task(
    patient_id: str,
    title: str,
    due: datetime | None = None,
    *,
    assignee_id: str | None = None,
    team_id: str | None = None,
    priority: str | None = None,
) -> Effect:
    """Create an open follow-up task for a patient, labelled for this dashboard."""
    kwargs: dict[str, Any] = {
        "patient_id": patient_id,
        "title": title,
        "due": due,
        "status": EffectTaskStatus.OPEN,
        "labels": ["daily-dashboard"],
    }
    if assignee_id:
        kwargs["assignee_id"] = assignee_id
    if team_id:
        kwargs["team_id"] = team_id
    if priority in _TASK_PRIORITY:
        kwargs["priority"] = _TASK_PRIORITY[priority]
    return AddTask(**kwargs).apply()


_TASK_STATUS = {s.value: s for s in EffectTaskStatus}  # OPEN/COMPLETED/CLOSED
_TASK_PRIORITY = {p.value: p for p in TaskPriority}     # stat/urgent/routine


def update_task(
    task_id: str,
    *,
    status: str | None = None,
    assignee_id: str | None = None,
    team_id: str | None = None,
    title: str | None = None,
    due: datetime | None = None,
    priority: str | None = None,
) -> Effect:
    """Update a task's fields. Only provided values are sent (others untouched)."""
    kwargs: dict[str, Any] = {"id": task_id}
    if status in _TASK_STATUS:
        kwargs["status"] = _TASK_STATUS[status]
    if assignee_id:
        kwargs["assignee_id"] = assignee_id
    if team_id:
        kwargs["team_id"] = team_id
    if title:
        kwargs["title"] = title
    if due is not None:
        kwargs["due"] = due
    if priority in _TASK_PRIORITY:
        kwargs["priority"] = _TASK_PRIORITY[priority]
    return UpdateTask(**kwargs).apply()


def comment_task(task_id: str, body: str) -> Effect:
    """Add a comment to a task."""
    return AddTaskComment(task_id=task_id, body=body).apply()


def staff_options() -> list[dict[str, str]]:
    """All active staff, for the task assignee picker."""
    options = []
    for s in Staff.objects.filter(active=True).order_by("first_name", "last_name"):
        name = (s.credentialed_name or "").strip() or f"{s.first_name} {s.last_name}".strip()
        options.append({"id": str(s.id), "name": name or "Unknown"})
    return options


def team_options() -> list[dict[str, str]]:
    """All teams, for the task team picker."""
    return [
        {"id": str(t.id), "name": t.name or "Team"}
        for t in Team.objects.all().order_by("name")
    ]


def _phones_by_patient(patient_pks: set[Any]) -> dict[Any, str]:
    """Primary phone per patient (lowest rank), in one bulk query."""
    if not patient_pks:
        return {}
    phones: dict[Any, str] = {}
    for cp in (
        PatientContactPoint.objects.filter(
            patient_id__in=patient_pks, system=ContactPointSystem.PHONE
        ).order_by("rank")
    ):
        # First (lowest rank) wins per patient.
        if cp.patient_id not in phones and cp.value:
            phones[cp.patient_id] = cp.value
    return phones


def _meta_entry() -> dict[str, Any]:
    return {"overrides": set(), "outreach": None, "outreach_count": 0, "outreach_log": []}


def _metadata_by_patient(patient_pks: set[Any]) -> dict[Any, dict[str, Any]]:
    """Read this plugin's patient metadata (overrides + outreach log) in bulk."""
    if not patient_pks:
        return {}

    out: dict[Any, dict[str, Any]] = {pk: _meta_entry() for pk in patient_pks}
    for m in PatientMetadata.objects.filter(patient_id__in=patient_pks, key__startswith="dd."):
        entry = out.setdefault(m.patient_id, _meta_entry())
        if m.key == OUTREACH_KEY:
            try:
                log = json.loads(m.value or "[]")
            except (ValueError, TypeError):
                log = []
            if isinstance(log, list) and log:
                entry["outreach"] = log[-1]  # newest attempt is appended last
                entry["outreach_count"] = len(log)
                entry["outreach_log"] = log
        elif m.key.startswith(OVERRIDE_PREFIX) and (m.value or "").strip().lower() == "true":
            entry["overrides"].add(m.key[len(OVERRIDE_PREFIX):])
    return out


def _outreach_summary(attempt: dict[str, Any] | None, tz: ZoneInfo | dt_timezone) -> str:
    """One-line summary of the most recent outreach attempt (or '')."""
    if not attempt:
        return ""
    parts = [attempt.get("recipient_type"), attempt.get("channel")]
    label = " ".join(p for p in parts if p)
    date_raw = attempt.get("date")
    when = ""
    if date_raw:
        try:
            when = _short_dt(datetime.fromisoformat(date_raw), tz)
        except (ValueError, TypeError):
            when = ""
    return f"{label} · {when}".strip(" ·") if when else label


_OUTREACH_DETAIL_CAP = 10


def _outreach_detail(
    log: list[Any] | None, tz: ZoneInfo | dt_timezone
) -> list[dict[str, str]]:
    """Recent outreach attempts (newest first) for the cell popover.

    Each entry carries the optional free-text ``note`` that accompanied the log,
    so clicking the outreach cell can surface the message that was recorded.
    """
    if not log:
        return []
    out: list[dict[str, str]] = []
    for attempt in reversed(log[-_OUTREACH_DETAIL_CAP:]):
        if not isinstance(attempt, dict):
            continue
        when = ""
        date_raw = attempt.get("date")
        if date_raw:
            try:
                when = _short_dt(datetime.fromisoformat(date_raw), tz, with_time=True)
            except (ValueError, TypeError):
                when = ""
        out.append(
            {
                "channel": str(attempt.get("channel", "")),
                "recipient_type": str(attempt.get("recipient_type", "")),
                "recipient": str(attempt.get("recipient", "")),
                "outcome": str(attempt.get("outcome", "")),
                "note": str(attempt.get("note", "")),
                "user": str(attempt.get("user", "")),
                "when": when,
            }
        )
    return out


# Per-category detail extractors: (report fields, order fields) describing how
# to label a record and where its date lives. Used to power the cell drill-down.
_DETAIL_CONFIG: dict[str, dict[str, Callable[[Any], Any]]] = {
    "labs": {
        "report_label": lambda r: r.custom_document_name or "Lab report",
        "report_date": lambda r: r.date_performed or r.original_date,
        "order_label": lambda o: "Lab order",
        "order_date": lambda o: o.date_ordered,
        "order_results": lambda o: o.reports.all(),
    },
    "imaging": {
        "report_label": lambda r: r.name or "Imaging report",
        "report_date": lambda r: r.result_date,
        "order_label": lambda o: o.imaging or "Imaging order",
        "order_date": lambda o: o.date_time_ordered,
        "order_results": lambda o: o.results.all(),
    },
    "referral": {
        "report_label": lambda r: r.specialty or "Referral report",
        "report_date": lambda r: r.original_date,
        "order_label": lambda o: "Referral",
        "order_date": lambda o: o.date_referred,
        "order_results": lambda o: o.reports.all(),
    },
}

_ITEM_CAP = 3  # show only the most recent few items per cell


def _fmt_dateish(value: Any, tz: ZoneInfo | dt_timezone) -> str:
    """Format a date or datetime as 'Jun 26' in the clinic tz (empty if None)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _short_dt(value, tz)
    return f"{value.strftime('%b')} {value.day}"  # plain date


def _sortkey(value: Any) -> float:
    """Sortable recency key for a date/datetime (missing dates sort oldest)."""
    if value is None:
        return float("-inf")
    if isinstance(value, datetime):
        try:
            return value.timestamp()
        except (ValueError, OSError):
            return float("-inf")
    return datetime.combine(value, time.min, tzinfo=dt_timezone.utc).timestamp()


def _readiness_details(
    patient_pks: set[Any], tz: ZoneInfo | dt_timezone
) -> dict[Any, dict[str, dict[str, Any]]]:
    """Per-patient labs/imaging/referral detail (items + derived state), in bulk.

    Readiness is computed **per order**: an order is "resulted" when it has at
    least one non-junked report linked to it. The cell state rolls up:

    - no orders → ``complete`` if any non-junked report exists, else ``not-needed``
    - orders, all resulted → ``complete``
    - orders, at least one still pending → ``incomplete`` (amber)

    So an old report on file no longer turns a cell green while a fresh order is
    still pending. Bulk queries scoped to the board's patients (no N+1): per
    category, one reports query plus one orders query whose linked reports are
    prefetched. Each cell surfaces the most recent ``_ITEM_CAP`` items.
    """
    def _bucket() -> dict[str, Any]:
        return {"reports": 0, "orders": 0, "resulted_orders": 0, "items": []}

    out: dict[Any, dict[str, dict[str, Any]]] = {
        pk: {c: {"state": NOT_NEEDED, "items": []} for c in _DETAIL_CONFIG} for pk in patient_pks
    }
    if not patient_pks:
        return out

    for key, order_model, report_model, reports_attr in _CATEGORIES:
        cfg = _DETAIL_CONFIG[key]
        buckets: dict[Any, dict[str, Any]] = {pk: _bucket() for pk in patient_pks}

        for r in report_model.objects.filter(patient_id__in=patient_pks, junked=False):
            b = buckets.setdefault(r.patient_id, _bucket())
            b["reports"] = b["reports"] + 1  # sandbox forbids augmented item assignment
            raw = cfg["report_date"](r)
            b["items"].append(
                {"label": str(cfg["report_label"](r)), "kind": "report",
                 "date": _fmt_dateish(raw, tz), "_k": _sortkey(raw)}
            )

        # Orders with their non-junked reports prefetched, so per-order "resulted"
        # is a cached lookup rather than a query per order.
        order_qs = order_model.objects.filter(
            patient_id__in=patient_pks, entered_in_error__isnull=True
        ).prefetch_related(
            Prefetch(reports_attr, queryset=report_model.objects.filter(junked=False))
        )
        for o in order_qs:
            b = buckets.setdefault(o.patient_id, _bucket())
            b["orders"] = b["orders"] + 1
            resulted = len(cfg["order_results"](o)) > 0
            if resulted:
                b["resulted_orders"] = b["resulted_orders"] + 1
            raw = cfg["order_date"](o)
            b["items"].append(
                {"label": str(cfg["order_label"](o)), "kind": "order",
                 "date": _fmt_dateish(raw, tz), "_k": _sortkey(raw)}
            )

        for pk in patient_pks:
            b = buckets[pk]
            recent = sorted(b["items"], key=lambda i: i["_k"], reverse=True)[:_ITEM_CAP]
            for item in recent:
                item.pop("_k", None)
            out[pk][key]["items"] = recent
            if b["orders"] == 0:
                out[pk][key]["state"] = COMPLETE if b["reports"] else NOT_NEEDED
            elif b["resulted_orders"] == b["orders"]:
                out[pk][key]["state"] = COMPLETE
            else:
                out[pk][key]["state"] = INCOMPLETE

    return out


def _provider_options(base_qs: Any) -> list[dict[str, str]]:
    """All active providers (clinicians), plus anyone scheduled today.

    "Provider" = active staff with an NPI (clinicians), unioned with whoever is
    actually a provider on today's schedule, so the filter offers the full
    roster — not just providers who happen to have a visit today.
    """
    today_ids = set(
        base_qs.filter(provider__isnull=False).values_list("provider_id", flat=True)
    )
    staff = (
        Staff.objects.filter(active=True)
        .filter(Q(npi_number__gt="") | Q(id__in=today_ids))
        .order_by("first_name", "last_name")
    )
    options = []
    for s in staff:
        name = (s.credentialed_name or "").strip() or f"{s.first_name} {s.last_name}".strip()
        options.append({"id": str(s.id), "name": name or "Unknown"})
    return options


def _location_options(base_qs: Any) -> list[dict[str, str]]:
    """All active practice locations, sorted by name."""
    return [
        {"id": str(loc.id), "name": loc.full_name or "Unknown"}
        for loc in PracticeLocation.objects.filter(active=True).order_by("full_name")
    ]
