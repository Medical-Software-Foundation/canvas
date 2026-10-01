"""Derive and upsert one patient's PatientPanelStats row.

The single source of truth for stats values. Reused by event handlers, the
reconciliation cron, and backfill. Query semantics mirror the decoration
subqueries in services.patient_query so sort order matches displayed values.
"""

from datetime import datetime
from typing import TypedDict

import arrow
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.patient import PatientFacilityAddress
from canvas_sdk.v1.data.protocol_current import ProtocolCurrent
from canvas_sdk.v1.data.protocol_result import ProtocolResultStatus
from canvas_sdk.v1.data.task import Task, TaskStatus
from django.db.models import Count, Max, Min, Q
from logger import log

from patient_panel.models import PatientPanelStats

EXCLUDED_NOTE_TYPES: tuple[str, ...] = ("message", "letter", "data", "ccda")

# Canvas hard limit: each bulk_create call must not exceed this many records.
_CANVAS_BULK_LIMIT: int = 10_000


class StatValues(TypedDict):
    last_visit_dt: datetime | None
    next_visit_dt: datetime | None
    room_number: str | None
    tasks_open_count: int
    gaps_due_count: int


def compute_stat_values(patient_dbid: int) -> StatValues:
    now = arrow.utcnow().datetime

    last_visit_dt = (
        Note.objects.filter(
            patient__dbid=patient_dbid,
            note_type_version__is_billable=True,
            datetime_of_service__lte=now,
        )
        .exclude(note_type__in=EXCLUDED_NOTE_TYPES)
        .exclude(Q(current_state__state=NoteStates.DELETED) | Q(current_state__state=NoteStates.CANCELLED))
        .order_by("-datetime_of_service")
        .values_list("datetime_of_service", flat=True)
        .first()
    )

    next_visit_dt = (
        Note.objects.filter(patient__dbid=patient_dbid, datetime_of_service__gt=now)
        .exclude(Q(current_state__state=NoteStates.DELETED) | Q(current_state__state=NoteStates.CANCELLED))
        .order_by("datetime_of_service")
        .values_list("datetime_of_service", flat=True)
        .first()
    )

    room_number = (
        PatientFacilityAddress.objects.filter(patient__dbid=patient_dbid)
        .values_list("room_number", flat=True)
        .first()
    )

    tasks_open_count = Task.objects.filter(
        patient__dbid=patient_dbid, status=TaskStatus.OPEN
    ).count()

    gaps_due_count = ProtocolCurrent.objects.filter(
        patient__dbid=patient_dbid, status=ProtocolResultStatus.STATUS_DUE
    ).count()

    return StatValues(
        last_visit_dt=last_visit_dt,
        next_visit_dt=next_visit_dt,
        room_number=room_number,
        tasks_open_count=tasks_open_count,
        gaps_due_count=gaps_due_count,
    )


def recompute_stats_for_patient(patient_dbid: int) -> None:
    """Idempotent upsert of one patient's stats row."""
    values = compute_stat_values(patient_dbid)
    PatientPanelStats.objects.update_or_create(
        patient_id=patient_dbid,
        defaults={**values, "updated": arrow.utcnow().datetime},
    )


def recompute_stats_for_patient_uuid(patient_uuid: str) -> None:
    """Convenience for handlers that have the UUID from event context."""
    dbid = (
        Patient.objects.filter(id=patient_uuid).values_list("dbid", flat=True).first()
    )
    if dbid is not None:
        recompute_stats_for_patient(dbid)


def compute_all_stat_values() -> dict[int, StatValues]:
    """Set-based stats for every patient that has at least one relevant record,
    in ~5 aggregate GROUP BY queries (vs ~5 per patient). Keys are patient dbids.
    Patients with no relevant records are absent — callers default them. Filter
    semantics mirror compute_stat_values() exactly."""
    now = arrow.utcnow().datetime

    last_visits: dict[int, datetime] = dict(
        Note.objects.filter(
            note_type_version__is_billable=True,
            datetime_of_service__lte=now,
        )
        .exclude(note_type__in=EXCLUDED_NOTE_TYPES)
        .exclude(Q(current_state__state=NoteStates.DELETED) | Q(current_state__state=NoteStates.CANCELLED))
        .values("patient_id")
        .annotate(v=Max("datetime_of_service"))
        .values_list("patient_id", "v")
    )
    next_visits: dict[int, datetime] = dict(
        Note.objects.filter(datetime_of_service__gt=now)
        .exclude(Q(current_state__state=NoteStates.DELETED) | Q(current_state__state=NoteStates.CANCELLED))
        .values("patient_id")
        .annotate(v=Min("datetime_of_service"))
        .values_list("patient_id", "v")
    )
    tasks_open: dict[int, int] = dict(
        Task.objects.filter(status=TaskStatus.OPEN)
        .values("patient_id")
        .annotate(c=Count("id"))
        .values_list("patient_id", "c")
    )
    gaps_due: dict[int, int] = dict(
        ProtocolCurrent.objects.filter(status=ProtocolResultStatus.STATUS_DUE)
        .values("patient_id")
        .annotate(c=Count("id"))
        .values_list("patient_id", "c")
    )

    # First-seen room per patient — iterator keeps memory flat for large tables.
    rooms: dict[int, str | None] = {}
    for pid, room in (
        PatientFacilityAddress.objects.values_list("patient_id", "room_number").iterator(chunk_size=2000)
    ):
        if pid not in rooms:
            rooms[pid] = room

    pids: set[int] = set(last_visits) | set(next_visits) | set(tasks_open) | set(gaps_due) | set(rooms)
    return {
        pid: StatValues(
            last_visit_dt=last_visits.get(pid),
            next_visit_dt=next_visits.get(pid),
            room_number=rooms.get(pid),
            tasks_open_count=tasks_open.get(pid, 0),
            gaps_due_count=gaps_due.get(pid, 0),
        )
        for pid in pids
    }


# ── Set-based bulk reconciliation ─────────────────────────────────────────

# Must stay ≤ 10,000 — Canvas hard limit per bulk_create call.
_CHUNK: int = 1_000

_DEFAULT: StatValues = StatValues(
    last_visit_dt=None,
    next_visit_dt=None,
    room_number=None,
    tasks_open_count=0,
    gaps_due_count=0,
)

_UPDATE_FIELDS: list[str] = [
    "last_visit_dt",
    "next_visit_dt",
    "room_number",
    "tasks_open_count",
    "gaps_due_count",
    "updated",
]


def _bulk_upsert(rows: list[PatientPanelStats]) -> None:
    """Upsert a chunk of rows. len(rows) must be ≤ _CHUNK ≤ 10,000."""
    PatientPanelStats.objects.bulk_create(
        rows,
        batch_size=_CHUNK,
        update_conflicts=True,
        unique_fields=["patient"],
        update_fields=_UPDATE_FIELDS,
    )


def reconcile_all_stats() -> int:
    """Full reconciliation as ~5 aggregate queries + chunked bulk-upsert.
    Source of truth / drift repair; safe to run repeatedly (idempotent upsert)."""
    stats = compute_all_stat_values()
    now = arrow.utcnow().datetime
    processed = 0
    chunk: list[PatientPanelStats] = []

    for dbid in Patient.objects.values_list("dbid", flat=True).iterator(chunk_size=2_000):
        vals = stats.get(dbid, _DEFAULT)
        chunk.append(PatientPanelStats(patient_id=dbid, updated=now, **vals))
        if len(chunk) >= _CHUNK:
            _bulk_upsert(chunk)
            processed += len(chunk)
            chunk = []

    if chunk:
        _bulk_upsert(chunk)
        processed += len(chunk)

    log.info("[panel_stats] reconcile upserted %s patient rows", processed)
    return processed
