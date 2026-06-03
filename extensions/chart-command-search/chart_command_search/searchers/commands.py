from __future__ import annotations

from typing import Any

from django.db.models import Q
from logger import log

from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.lab import LabOrder, LabTest

try:
    from canvas_sdk.v1.data.prescription import Prescription
except ImportError:
    Prescription: Any = None

from chart_command_search.searchers.command_helpers import (
    extract_command_details,
    extract_command_heading,
)
from chart_command_search.searchers.constants import (
    COMMAND_TYPE_LABELS,
    MAX_RESULTS,
    _MED_COMMAND_KEYS,
    _PRESCRIPTION_STATUS_MAP,
)
from chart_command_search.searchers.helpers import (
    build_command_link,
    detail,
    fmt_date,
    make_result,
    note_type_name,
    parse_multi,
    resolve_command_query,
)
from chart_command_search.searchers.types import Result


def search_commands(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    qs = Command.objects.filter(patient__id=patient_id).exclude(
        schema_key__in=_MED_COMMAND_KEYS
    ).select_related(
        "note", "note__note_type_version"
    )
    statuses = parse_multi(status)
    if statuses:
        q_filter = Q()
        if "committed" in statuses:
            q_filter |= Q(state="committed")
        if "uncommitted" in statuses:
            q_filter |= ~Q(state="committed")
        if "entered_in_error" in statuses:
            q_filter |= Q(entered_in_error=True)
        if q_filter:
            qs = qs.filter(q_filter)
    if q:
        _, matched_keys = resolve_command_query(q)
        q_match = Q(data__icontains=q)
        if matched_keys:
            q_match |= Q(schema_key__in=matched_keys)
        qs = qs.filter(q_match)
    if date_from:
        qs = qs.filter(note__datetime_of_service__date__gte=date_from)
    if date_to:
        qs = qs.filter(note__datetime_of_service__date__lte=date_to)
    provider_ids = parse_multi(provider_id)
    if provider_ids:
        qs = qs.filter(note__provider__id__in=provider_ids)
    qs = qs.order_by("-note__datetime_of_service")[:MAX_RESULTS]

    cmds = list(qs)

    lab_note_dbids = [
        cmd.note.dbid
        for cmd in cmds
        if cmd.schema_key == "labOrder" and cmd.note
    ]
    lab_test_statuses: dict[int, set[str]] = {}
    lab_order_info: dict[int, dict[str, str]] = {}
    if lab_note_dbids:
        try:
            orders = list(
                LabOrder.objects.filter(note__dbid__in=lab_note_dbids)
            )
            order_to_note: dict[int, int] = {}
            for o in orders:
                order_to_note[o.dbid] = o.note_id
                lab_order_info[o.note_id] = {
                    "tx": (getattr(o, "transmission_type", "") or "").strip(),
                    "hg_id": (getattr(o, "healthgorilla_id", "") or "").strip(),
                    "manual": (
                        getattr(o, "manual_processing_status", "") or ""
                    ).strip(),
                }
            if order_to_note:
                for t in LabTest.objects.filter(
                    lab_order__dbid__in=list(order_to_note.keys())
                ):
                    note_dbid = order_to_note.get(t.lab_order_id, 0)
                    if note_dbid:
                        lab_test_statuses.setdefault(note_dbid, set()).add(
                            getattr(t, "status", "") or ""
                        )
        except Exception as exc:
            log.error("Failed to enrich lab order statuses: %s", exc)

    results: list[Result] = []
    for cmd in cmds:
        note = cmd.note
        details = extract_command_details(cmd.schema_key, cmd.data or {})
        heading = extract_command_heading(cmd.schema_key, cmd.data or {})

        if q:
            matched_field = ""
            q_lower = q.lower()
            for d in details:
                if q_lower in d["value"].lower():
                    matched_field = d["label"]
                    break
            if matched_field:
                details.append(detail("Matched in", matched_field))

        state_str = str(cmd.state)
        is_eie = getattr(cmd, "entered_in_error", False)
        if is_eie:
            display_state = "Entered in error"
            display_state_class = "cancelled"
        elif cmd.schema_key == "labOrder" and note and state_str == "committed":
            test_statuses = lab_test_statuses.get(note.dbid, set())
            order_info = lab_order_info.get(note.dbid, {})
            tx_type = order_info.get("tx", "")
            hg_id = order_info.get("hg_id", "")
            manual_status = order_info.get("manual", "")
            has_failed = bool(test_statuses & {"SF", "PF"})
            has_received = "RE" in test_statuses
            has_reviewed = "RV" in test_statuses
            if has_reviewed:
                display_state = "Reviewed"
                display_state_class = "completed"
            elif has_received:
                display_state = "Results In"
                display_state_class = "active"
            elif has_failed:
                display_state = "Error"
                display_state_class = "cancelled"
            elif "PR" in test_statuses:
                display_state = "Processing"
                display_state_class = "pending"
            elif "SE" in test_statuses:
                display_state = "Sending"
                display_state_class = "pending"
            elif "SR" in test_statuses:
                display_state = "Staged"
                display_state_class = "pending"
            elif manual_status == "FLAGGED":
                display_state = "Flagged"
                display_state_class = "cancelled"
            elif manual_status == "PROCESSED":
                display_state = "Processed"
                display_state_class = "completed"
            elif manual_status == "IN_PROGRESS":
                display_state = "Signed"
                display_state_class = "completed"
            elif manual_status == "NEEDS_REVIEW":
                display_state = "Committed"
                display_state_class = "committed"
            elif hg_id or tx_type == "H":
                display_state = "Sent"
                display_state_class = "active"
            elif tx_type == "F":
                display_state = "Faxed"
                display_state_class = "completed"
            else:
                display_state = "Committed"
                display_state_class = "committed"
        elif state_str == "committed":
            display_state = "Committed"
            display_state_class = "committed"
        else:
            display_state = "Uncommitted"
            display_state_class = "uncommitted"
        note_type = note_type_name(note) if note else ""
        cmd_link = build_command_link(patient_id, cmd)
        results.append(
            make_result(
                category="command",
                type_label=COMMAND_TYPE_LABELS.get(cmd.schema_key, cmd.schema_key),
                summary=heading,
                details=details,
                state=display_state,
                state_class=display_state_class,
                permalink=cmd_link,
                date=fmt_date(getattr(note, "datetime_of_service", None)),
                source=note_type or "",
            )
        )
    return results


def search_medications(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    qs = Command.objects.filter(
        patient__id=patient_id, schema_key__in=_MED_COMMAND_KEYS
    ).select_related("note", "note__note_type_version", "note__current_state")

    statuses = parse_multi(status)

    if q:
        _, matched_keys = resolve_command_query(q)
        q_match = Q(data__icontains=q)
        if matched_keys:
            q_match |= Q(schema_key__in=matched_keys & _MED_COMMAND_KEYS)
        qs = qs.filter(q_match)
    if date_from:
        qs = qs.filter(note__datetime_of_service__date__gte=date_from)
    if date_to:
        qs = qs.filter(note__datetime_of_service__date__lte=date_to)
    provider_ids = parse_multi(provider_id)
    if provider_ids:
        qs = qs.filter(note__provider__id__in=provider_ids)
    qs = qs.order_by("-note__datetime_of_service")[:MAX_RESULTS]

    commands = list(qs)
    if not commands:
        return []

    note_dbids = {cmd.note.dbid for cmd in commands if cmd.note}
    prescriptions_map: dict[int, list[Any]] = {}
    if note_dbids and Prescription is not None:
        try:
            for rx in Prescription.objects.filter(note__dbid__in=note_dbids):
                prescriptions_map.setdefault(rx.note_id, []).append(rx)
        except Exception as exc:
            log.error("Failed to fetch prescriptions by note: %s", exc)
    if not prescriptions_map and Prescription is not None:
        try:
            for rx in Prescription.objects.filter(
                patient__id=patient_id
            ).order_by("-written_date")[:MAX_RESULTS]:
                if rx.note_id and rx.note_id not in prescriptions_map:
                    prescriptions_map.setdefault(rx.note_id, []).append(rx)
        except Exception as exc:
            log.error("Failed to fetch prescriptions by patient: %s", exc)

    _STATUS_FILTER_MAP: dict[str, str] = {
        "accepted": "accepted",
        "delivered": "delivered",
        "signed": "accepted",
        "pending": "pending",
        "received": "pending",
        "in_queue": "pending",
        "transmitted": "transmitted",
        "open": "pending",
        "error": "error",
        "cancelled": "cancelled",
        "cancel_requested": "cancelled",
        "cancel_denied": "cancelled",
    }

    results: list[Result] = []
    for cmd in commands:
        note = cmd.note
        heading = extract_command_heading(cmd.schema_key, cmd.data or {})
        details = extract_command_details(cmd.schema_key, cmd.data or {})

        state = ""
        state_class = ""
        note_dbid = note.dbid if note else None

        rxs = prescriptions_map.get(note_dbid, [])
        if rxs:
            rx_status = (getattr(rxs[0], "status", "") or "").lower()
            if rx_status and rx_status != "open":
                badge_info = _PRESCRIPTION_STATUS_MAP.get(rx_status)
                if badge_info:
                    state, state_class = badge_info

        if not state and note:
            cs = getattr(note, "current_state", None)
            note_state = getattr(cs, "state", "") if cs else ""
            _NOTE_TO_MED_STATUS: dict[str, tuple[str, str]] = {
                "SGN": ("Signed", "completed"),
                "LKD": ("Signed", "completed"),
                "RLK": ("Signed", "completed"),
                "PSH": ("Signed", "completed"),
            }
            if note_state in _NOTE_TO_MED_STATUS:
                state, state_class = _NOTE_TO_MED_STATUS[note_state]

        if not state:
            state_str = str(cmd.state)
            is_eie = getattr(cmd, "entered_in_error", False)
            if is_eie:
                state = "Entered in error"
                state_class = "cancelled"
            elif state_str == "committed":
                state = "Committed"
                state_class = "committed"
            else:
                state = "Uncommitted"
                state_class = "uncommitted"

        if statuses:
            status_key = state.lower().replace(" ", "_")
            mapped_key = _STATUS_FILTER_MAP.get(status_key, status_key)
            if mapped_key not in statuses:
                continue

        note_type = note_type_name(note) if note else ""
        cmd_link = build_command_link(patient_id, cmd)
        results.append(
            make_result(
                category="command",
                type_label=COMMAND_TYPE_LABELS.get(cmd.schema_key, cmd.schema_key),
                summary=heading,
                details=details,
                state=state,
                state_class=state_class,
                permalink=cmd_link,
                date=fmt_date(getattr(note, "datetime_of_service", None)),
                source=note_type or "",
            )
        )
    return results


def search_commands_all(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    kwargs = {"date_from": date_from, "date_to": date_to, "provider_id": provider_id}
    results: list[Result] = []
    results.extend(search_commands(patient_id, q, status, **kwargs))
    results.extend(search_medications(patient_id, q, status, **kwargs))
    results.sort(key=lambda r: r.get("date", ""), reverse=True)
    return results[:MAX_RESULTS]
