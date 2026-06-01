from __future__ import annotations

from typing import Any

from django.db.models import Q
from logger import log

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.note import Note, NoteType

from chart_command_search.searchers.constants import MAX_RESULTS
from chart_command_search.searchers.helpers import (
    build_note_link,
    detail,
    extract_body_text,
    fmt_datetime,
    make_result,
    note_type_name,
    parse_multi,
    staff_name,
)
from chart_command_search.searchers.types import Result


def search_appointments(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    qs = Appointment.objects.filter(
        Q(patient__id=patient_id) | Q(note__patient__id=patient_id),
        entered_in_error__isnull=True,
    ).select_related("provider").distinct()
    if q:
        qs = qs.filter(Q(comment__icontains=q) | Q(description__icontains=q))
    statuses = parse_multi(status)
    if statuses:
        qs = qs.filter(status__in=statuses)
    if date_from:
        qs = qs.filter(start_time__date__gte=date_from)
    if date_to:
        qs = qs.filter(start_time__date__lte=date_to)
    provider_ids = parse_multi(provider_id)
    if provider_ids:
        qs = qs.filter(provider__id__in=provider_ids)
    qs = qs.order_by("-start_time")[:MAX_RESULTS]

    appointments = list(qs)
    if not appointments:
        return []

    note_type_ids = {
        a.note_type_id for a in appointments if getattr(a, "note_type_id", None)
    }
    note_type_map: dict[int, str] = {}
    if note_type_ids:
        try:
            for nt in NoteType.objects.filter(dbid__in=note_type_ids):
                note_type_map[nt.dbid] = nt.name
        except Exception as exc:
            log.error("Failed to fetch note types for appointments: %s", exc)

    note_ids = {a.note_id for a in appointments if getattr(a, "note_id", None)}
    notes_map: dict[int, Any] = {}
    if note_ids:
        try:
            for n in (
                Note.objects.filter(dbid__in=note_ids)
                .select_related("provider", "note_type_version", "current_state")
                .prefetch_related("commands")
            ):
                notes_map[n.dbid] = n
        except Exception as exc:
            log.error("Failed to fetch notes for appointments: %s", exc)

    _NOTE_STATE_LABELS: dict[str, str] = {
        "SCH": "Scheduling", "BKD": "Booked", "CVD": "Checked in",
        "CLD": "Cancelled", "NSW": "No-showed", "RVT": "Reverted",
        "SGN": "Signed", "LKD": "Completed", "RLK": "Completed",
        "PSH": "Completed", "ULK": "Unlocked", "RST": "Restored",
        "NEW": "New",
    }
    _NOTE_STATE_CLASS: dict[str, str] = {
        "SCH": "unconfirmed", "BKD": "confirmed", "CVD": "arrived",
        "CLD": "cancelled", "NSW": "noshowed", "RVT": "unconfirmed",
        "SGN": "completed", "LKD": "completed", "RLK": "completed",
        "PSH": "completed", "ULK": "confirmed", "RST": "confirmed",
        "NEW": "unconfirmed",
    }
    _APPT_STATUS_LABELS: dict[str, str] = {
        "unconfirmed": "Unconfirmed", "attempted": "Attempted",
        "confirmed": "Confirmed", "arrived": "Arrived",
        "roomed": "Roomed", "exited": "Exited",
        "noshowed": "No-showed", "cancelled": "Cancelled",
    }
    _APPT_STATUS_CLASS: dict[str, str] = {
        "unconfirmed": "unconfirmed", "attempted": "attempted",
        "confirmed": "confirmed", "arrived": "arrived",
        "roomed": "roomed", "exited": "exited",
        "noshowed": "noshowed", "cancelled": "cancelled",
    }

    results: list[Result] = []
    for appt in appointments:
        appt_note_id_for_state: int | None = getattr(appt, "note_id", None)
        note_for_state = notes_map.get(appt_note_id_for_state) if appt_note_id_for_state else None
        note_state_code = ""
        if note_for_state:
            cs = getattr(note_for_state, "current_state", None)
            if cs:
                note_state_code = getattr(cs, "state", "")

        _SIGNED_STATES = {"SGN", "LKD", "RLK", "PSH"}
        if note_state_code in _SIGNED_STATES:
            continue

        if note_state_code and note_state_code in _NOTE_STATE_LABELS:
            appt_status = _NOTE_STATE_LABELS[note_state_code]
            raw_status = _NOTE_STATE_CLASS.get(note_state_code, "active")
        else:
            raw_status = str(getattr(appt, "status", "") or "").lower()
            appt_status = _APPT_STATUS_LABELS.get(
                raw_status, raw_status.replace("_", " ").title()
            )
        provider = staff_name(getattr(appt, "provider", None))
        duration = getattr(appt, "duration_minutes", None)
        comment = getattr(appt, "comment", "") or ""
        description = getattr(appt, "description", "") or ""
        nt_id: int | None = getattr(appt, "note_type_id", None)
        appt_type = note_type_map.get(nt_id, "") if nt_id is not None else ""

        type_label = appt_type or "Appointment"

        appt_note_id: int | None = getattr(appt, "note_id", None)
        note = notes_map.get(appt_note_id) if appt_note_id else None

        summary = description or comment or ""
        if not summary and note:
            for cmd in note.commands.all():
                if cmd.schema_key == "reasonForVisit":
                    coding = (cmd.data or {}).get("coding") or {}
                    summary = str(
                        coding.get("text", "") or (cmd.data or {}).get("comment", "")
                    ).strip()
                    break

        details: list[dict[str, str]] = []
        if provider:
            details.append(detail("Provider", provider))
        if duration:
            details.append(detail("Duration", f"{duration} min"))
        if comment:
            details.append(detail("Comment", comment))

        if note:
            body_text = extract_body_text(getattr(note, "body", None))
            if body_text:
                details.append(detail("Content", body_text))

        state_class = raw_status if note_state_code else _APPT_STATUS_CLASS.get(raw_status, "active")
        permalink = build_note_link(patient_id, note) if note else ""

        results.append(
            make_result(
                category="appointment",
                type_label=type_label,
                summary=summary,
                details=details,
                state=appt_status,
                state_class=state_class,
                permalink=permalink,
                date=fmt_datetime(getattr(appt, "start_time", None)),
            )
        )
    return results
