from __future__ import annotations

from typing import Any

from django.db.models import Q
from logger import log

from canvas_sdk.v1.data.letter import Letter, LetterActionEvent
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
    strip_html,
)
from chart_command_search.searchers.types import Result


def search_letters(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    qs = Note.objects.filter(
        patient__id=patient_id, note_type_version__category="letter"
    ).select_related("provider", "note_type_version")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    if date_from:
        qs = qs.filter(datetime_of_service__date__gte=date_from)
    if date_to:
        qs = qs.filter(datetime_of_service__date__lte=date_to)
    provider_ids = parse_multi(provider_id)
    if provider_ids:
        qs = qs.filter(provider__id__in=provider_ids)
    qs = qs.order_by("-datetime_of_service")[:MAX_RESULTS]

    notes = list(qs)

    note_dbids = [n.dbid for n in notes]
    letters_map: dict[int, Any] = {}
    letter_events_map: dict[int, list[Any]] = {}
    if note_dbids:
        try:
            for letter in Letter.objects.filter(
                note__dbid__in=note_dbids
            ).select_related("note"):
                letters_map[letter.note_id] = letter
            letter_dbids = [l.dbid for l in letters_map.values()]
            if letter_dbids:
                for evt in LetterActionEvent.objects.filter(
                    letter__dbid__in=letter_dbids
                ).order_by("-created"):
                    letter_events_map.setdefault(evt.letter_id, []).append(evt)
        except Exception as exc:
            log.error("Failed to fetch letters/events: %s", exc)

    letter_statuses = parse_multi(status)

    results: list[Result] = []
    for note in notes:
        title = (getattr(note, "title", "") or "").strip()
        note_type = note_type_name(note)
        provider = getattr(note, "provider", None)
        type_label = note_type or title or "Letter"
        if type_label.lower() == "letter encounter":
            type_label = "Letter"

        letter = letters_map.get(note.dbid)
        letter_content = ""
        if letter:
            letter_content = (getattr(letter, "content", "") or "").strip()
            letter_content = strip_html(letter_content)

        summary = ""
        if letter_content:
            summary = letter_content[:200] + "..." if len(letter_content) > 200 else letter_content
        else:
            body_text = extract_body_text(getattr(note, "body", None))
            if body_text:
                summary = body_text[:200] + "..." if len(body_text) > 200 else body_text

        details: list[dict[str, str]] = []
        if provider:
            details.append(detail("Provider", staff_name(provider)))
        if title and title != type_label:
            details.append(detail("Title", title))

        if q:
            body_text = extract_body_text(getattr(note, "body", None))
            if title and q.lower() in title.lower():
                details.append(detail("Matched in", "Title"))
            elif q.lower() in (letter_content or body_text).lower():
                search_text = letter_content or body_text
                snippet = match_snippet(q, search_text)
                details.append(
                    detail("Matched in", f"Body: {snippet}" if snippet else "Body")
                )

        state = ""
        state_class = ""
        if letter:
            events = letter_events_map.get(letter.dbid, [])
            fax_event = None
            was_printed = False
            for evt in events:
                etype = getattr(evt, "event_type", "")
                if etype == "FAXED" and fax_event is None:
                    fax_event = evt
                elif etype == "PRINTED":
                    was_printed = True
            if fax_event:
                delivered = getattr(fax_event, "delivered_by_fax", None)
                if delivered is True:
                    state = "Faxed"
                    state_class = "completed"
                elif delivered is False:
                    state = "Fax failed"
                    state_class = "cancelled"
                else:
                    state = "Fax pending"
                    state_class = "pending"
            elif was_printed or getattr(letter, "printed", None) is not None:
                state = "Printed"
                state_class = "active"

        if letter_statuses:
            state_lower = state.lower().replace(" ", "_").replace(":", "")
            if state_lower.startswith("fax_failed"):
                state_lower = "fax_failed"
            if state_lower not in letter_statuses:
                continue

        results.append(
            make_result(
                category="letter",
                type_label=type_label,
                summary=summary,
                details=details,
                state=state,
                state_class=state_class,
                permalink=build_note_link(patient_id, note),
                date=fmt_date(getattr(note, "datetime_of_service", None)),
            )
        )
    return results
