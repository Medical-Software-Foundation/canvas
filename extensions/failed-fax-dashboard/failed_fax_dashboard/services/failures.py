"""Finds failed sent and received faxes for the dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from canvas_sdk.v1.data import Fax, FaxDirection, Staff

from failed_fax_dashboard.models import FaxDismissal
from failed_fax_dashboard.services.sources import (
    DATA_INTEGRATION_PATH,
    RECEIVED_LABEL,
    RECEIVED_TYPE,
    SOURCES,
    SourceSpec,
    walk,
)

WINDOW_DAYS = 90
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

FAXED = "FAXED"


def normalize_number(number: str | None) -> str:
    """Reduce a fax number to its digits so formatting differences still match."""
    return "".join(ch for ch in (number or "") if ch.isdigit())


def person_name(person: Any) -> str:
    """First and last name of a patient or staff member, or an empty string."""
    if person is None:
        return ""
    return f"{person.first_name} {person.last_name}".strip()


def sender_name(event: Any) -> str:
    """Name of the staff member who sent the fax, or an empty string."""
    originator = event.originator
    if originator is None:
        return ""
    try:
        return person_name(originator.staff)
    except Staff.DoesNotExist:
        return ""


def note_link(patient: Any, note: Any) -> str | None:
    """Path to a note in the patient's chart, or None when either is missing."""
    if patient is None or note is None:
        return None
    return f"/patient/{patient.id}?noteId={note.dbid}"


def _failed_events(spec: SourceSpec, cutoff: datetime) -> list[Any]:
    """Faxed events for one item type that were not delivered, newest first."""
    queryset = (
        spec.model.objects.filter(
            event_type=FAXED,
            delivered_by_fax=False,
            created__gte=cutoff,
            **spec.item_filters,
        )
        .exclude(**spec.item_excludes)
        .select_related("fax", "originator__staff", *spec.select_related)
        .order_by("-created")
    )
    return list(queryset)


def _latest_delivered(spec: SourceSpec, events: list[Any]) -> dict[tuple[int, str], datetime]:
    """Latest delivery time per (item, normalized number) among delivered faxes."""
    item_ids = {getattr(event, f"{spec.item_field}_id") for event in events}
    oldest = min(event.created for event in events)
    rows = spec.model.objects.filter(
        event_type=FAXED,
        delivered_by_fax=True,
        created__gte=oldest,
        **{f"{spec.item_field}_id__in": item_ids},
    ).values_list(f"{spec.item_field}_id", "fax__to_fax_number", "created")
    latest: dict[tuple[int, str], datetime] = {}
    for item_id, number, created in rows:
        key = (item_id, normalize_number(number))
        if key not in latest or created > latest[key]:
            latest[key] = created
    return latest


def _dismissed_ids(source_type: str, source_ids: list[str]) -> set[str]:
    """Ids among ``source_ids`` that staff already dismissed."""
    if not source_ids:
        return set()
    return set(
        FaxDismissal.objects.filter(source_type=source_type, source_id__in=source_ids).values_list(
            "source_id", flat=True
        )
    )


def _sent_rows(spec: SourceSpec, cutoff: datetime) -> list[tuple[datetime, dict[str, Any]]]:
    """Rows for failed sent faxes of one item type, minus cleared and dismissed ones."""
    events = _failed_events(spec, cutoff)
    if not events:
        return []
    delivered = _latest_delivered(spec, events)
    dismissed = _dismissed_ids(spec.type_key, [str(event.id) for event in events])

    rows: list[tuple[datetime, dict[str, Any]]] = []
    for event in events:
        number = event.fax.to_fax_number if event.fax is not None else ""
        item_id = getattr(event, f"{spec.item_field}_id")
        cleared_at = delivered.get((item_id, normalize_number(number)))
        if cleared_at is not None and cleared_at > event.created:
            continue
        if str(event.id) in dismissed:
            continue

        patient = walk(event, spec.patient_path)
        note = walk(event, spec.note_path)
        if spec.note_path is None:
            link_url: str | None = DATA_INTEGRATION_PATH
            link_label = "Open Data Integration"
        else:
            link_url = note_link(patient, note)
            link_label = "Open note" if spec.type_key != "letter" else "Open letter"
        rows.append(
            (
                event.created,
                {
                    "key": f"{spec.type_key}:{event.id}",
                    "type": spec.type_key,
                    "type_label": spec.label,
                    "direction": "sent",
                    "source_id": str(event.id),
                    "patient_name": person_name(patient),
                    "fax_number": number,
                    "sender": sender_name(event),
                    "occurred_at": event.created.isoformat(),
                    "pages": event.fax.fax_pages if event.fax is not None else None,
                    "reason": event.fax_result_msg,
                    "link_url": link_url,
                    "link_label": link_label,
                    "can_resend": spec.type_key == "note",
                },
            )
        )
    return rows


def _received_rows(cutoff: datetime) -> list[tuple[datetime, dict[str, Any]]]:
    """Rows for inbound faxes that failed to arrive completely."""
    faxes = list(
        Fax.objects.filter(
            direction=FaxDirection.INBOUND, success=False, created__gte=cutoff
        ).order_by("-created")
    )
    dismissed = _dismissed_ids(RECEIVED_TYPE, [str(fax.id) for fax in faxes])
    return [
        (
            fax.created,
            {
                "key": f"{RECEIVED_TYPE}:{fax.id}",
                "type": RECEIVED_TYPE,
                "type_label": RECEIVED_LABEL,
                "direction": "received",
                "source_id": str(fax.id),
                "patient_name": "",
                "fax_number": fax.from_fax_number,
                "sender": "",
                "occurred_at": (fax.date_utc or fax.created).isoformat(),
                "pages": fax.fax_pages,
                "reason": "",
                "link_url": DATA_INTEGRATION_PATH,
                "link_label": "Open Data Integration",
                "can_resend": False,
            },
        )
        for fax in faxes
        if str(fax.id) not in dismissed
    ]


def failed_fax_page(
    page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, now: datetime | None = None
) -> dict[str, Any]:
    """Return one page of failed fax rows from the last 90 days, newest first."""
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)

    collected: list[tuple[datetime, dict[str, Any]]] = []
    for spec in SOURCES:
        collected.extend(_sent_rows(spec, cutoff))
    collected.extend(_received_rows(cutoff))
    collected.sort(key=lambda pair: pair[0], reverse=True)

    total = len(collected)
    start = (page - 1) * page_size
    return {
        "rows": [row for _, row in collected[start : start + page_size]],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max((total + page_size - 1) // page_size, 1),
        "window_days": WINDOW_DAYS,
    }

