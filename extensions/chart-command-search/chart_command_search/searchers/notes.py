from __future__ import annotations

from django.db.models import Q

from canvas_sdk.v1.data.note import Note

from chart_command_search.searchers.constants import MAX_RESULTS
from chart_command_search.searchers.helpers import (
    build_note_link,
    detail,
    extract_body_text,
    fmt_date,
    make_result,
    match_snippet,
    note_type_name,
    parse_multi,
    staff_name,
)
from chart_command_search.searchers.types import Result


def search_notes(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    qs = Note.objects.filter(
        patient__id=patient_id,
        note_type_version__category="encounter",
    ).select_related(
        "provider", "note_type_version", "current_state"
    ).prefetch_related("commands")
    statuses = parse_multi(status)
    if statuses:
        nt_q = Q()
        for s in statuses:
            if s.startswith("note_type_"):
                nt_q |= Q(note_type_version__note_type__dbid=s.removeprefix("note_type_"))
        if nt_q:
            qs = qs.filter(nt_q)
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(body__icontains=q)
            | Q(commands__data__icontains=q)
        ).distinct()
    if date_from:
        qs = qs.filter(datetime_of_service__date__gte=date_from)
    if date_to:
        qs = qs.filter(datetime_of_service__date__lte=date_to)
    provider_ids = parse_multi(provider_id)
    if provider_ids:
        qs = qs.filter(provider__id__in=provider_ids)
    qs = qs.order_by("-datetime_of_service")[:MAX_RESULTS]

    results: list[Result] = []
    for note in qs:
        title = (getattr(note, "title", "") or "").strip()
        note_type = note_type_name(note)
        type_label = note_type or title or "Note"
        provider = getattr(note, "provider", None)
        body_text = extract_body_text(getattr(note, "body", None))
        preview = body_text[:200] + "..." if len(body_text) > 200 else body_text

        rfv = ""
        for cmd in note.commands.all():
            if cmd.schema_key == "reasonForVisit":
                coding = (cmd.data or {}).get("coding") or {}
                rfv = str(
                    coding.get("text", "") or (cmd.data or {}).get("comment", "")
                ).strip()
                if rfv:
                    break

        details: list[dict[str, str]] = []
        if rfv:
            details.append(detail("Reason for visit", rfv))
        if provider:
            details.append(detail("Provider", staff_name(provider)))
        if title and title != type_label:
            details.append(detail("Title", title))

        if q and body_text:
            snippet = match_snippet(q, body_text)
            if snippet:
                details.append(detail("Matched in", f"Body: {snippet}"))

        current_state = getattr(note, "current_state", None)
        cs = getattr(current_state, "state", None) if current_state else None
        if cs == "DLT":
            note_state = "Deleted"
            note_state_class = "deleted"
        elif current_state is not None and not current_state.editable():
            note_state = "Locked"
            note_state_class = "locked"
        else:
            note_state = "Unlocked"
            note_state_class = "unlocked"

        if statuses:
            state_keys = {"locked", "unlocked", "deleted"} & statuses
            if state_keys and note_state_class not in state_keys:
                continue

        results.append(
            make_result(
                category="note",
                type_label=type_label,
                summary=preview,
                details=details,
                state=note_state,
                state_class=note_state_class,
                permalink=build_note_link(patient_id, note),
                date=fmt_date(getattr(note, "datetime_of_service", None)),
                source=note_type or "",
            )
        )
    return results
