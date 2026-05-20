from __future__ import annotations

from typing import Any

from django.db.models import Q

from canvas_sdk.v1.data.message import Message

from chart_command_search.searchers.constants import MAX_RESULTS
from chart_command_search.searchers.helpers import (
    build_note_link,
    fmt_date,
    make_result,
    parse_multi,
    staff_name,
    strip_html,
)
from chart_command_search.searchers.types import Result


def search_messages(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    statuses = parse_multi(status)
    provider_ids = parse_multi(provider_id)

    def _apply_msg_filters(qs: Any) -> Any:
        if statuses:
            q_filter = Q()
            if "read" in statuses:
                q_filter |= Q(read__isnull=False)
            if "unread" in statuses:
                q_filter |= Q(read__isnull=True)
            if q_filter:
                qs = qs.filter(q_filter)
        if date_from:
            qs = qs.filter(created__date__gte=date_from)
        if date_to:
            qs = qs.filter(created__date__lte=date_to)
        if provider_ids:
            qs = qs.filter(note__provider__id__in=provider_ids)
        return qs

    base_qs = Message.objects.filter(note__patient__id=patient_id)
    if q:
        base_qs = base_qs.filter(
            Q(content__icontains=q)
            | Q(sender__staff__first_name__icontains=q)
            | Q(sender__staff__last_name__icontains=q)
            | Q(recipient__staff__first_name__icontains=q)
            | Q(recipient__staff__last_name__icontains=q)
        )
    qs = _apply_msg_filters(base_qs)
    try:
        qs = qs.select_related("sender", "recipient", "note", "note__provider")
        messages = list(qs.order_by("-created")[:MAX_RESULTS])
    except Exception:
        qs = _apply_msg_filters(base_qs)
        qs = qs.select_related("sender", "note", "note__provider")
        messages = list(qs.order_by("-created")[:MAX_RESULTS])

    results: list[Result] = []
    for msg in messages:
        content = strip_html(getattr(msg, "content", "") or "")
        sender = getattr(msg, "sender", None)
        sender_name = staff_name(sender)

        recipient = getattr(msg, "recipient", None)
        recipient_name = staff_name(recipient) if recipient else ""

        note = getattr(msg, "note", None)
        note_provider = getattr(note, "provider", None) if note else None
        provider_name = staff_name(note_provider)

        is_outbound = sender is not None and getattr(sender, "is_staff", False)
        preview = content[:200] + "..." if len(content) > 200 else content

        if is_outbound:
            label_name = sender_name or provider_name or "Staff"
            type_label = f"From {label_name}"
        else:
            label_name = recipient_name or provider_name
            type_label = f"To {label_name}" if label_name else "From patient"

        msg_state = ""
        msg_state_class = ""
        if not is_outbound:
            is_read = getattr(msg, "read", None) is not None
            msg_state = "Read" if is_read else "Unread"
            msg_state_class = "completed" if is_read else "pending"

        details: list[dict[str, str]] = []

        permalink = build_note_link(patient_id, note) if note else ""
        results.append(
            make_result(
                category="message",
                type_label=type_label,
                summary=preview,
                details=details,
                state=msg_state,
                state_class=msg_state_class,
                permalink=permalink,
                date=fmt_date(getattr(msg, "created", None)),
            )
        )
    return results
