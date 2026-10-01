"""Fax attempts per item and number, and who gets credit for each send."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from canvas_sdk.v1.data import Staff

from failed_fax_dashboard.models import FaxResend
from failed_fax_dashboard.services.sources import SourceSpec
from failed_fax_dashboard.services.util import BOT_STAFF_ID, chunked, to_e164

FAXED = "FAXED"
HISTORY_CHUNK = 500

KIND_STAFF = "staff"
KIND_RESENT = "resent"
KIND_AUTO = "auto"
KIND_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Sender:
    """Who sent one attempt: a person, a person who clicked Resend, or no one in particular."""

    kind: str
    staff_id: str = ""
    first_name: str = ""
    last_name: str = ""

    @property
    def name(self) -> str:
        """The person's name (empty for an automatic or unknown sender)."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_person(self) -> bool:
        """Whether a staff member can be credited with this send."""
        return self.kind in (KIND_STAFF, KIND_RESENT)

    @property
    def label(self) -> str:
        """How the dashboard and task comments word the sender."""
        if self.kind == KIND_RESENT:
            return f"Resent by {self.name}"
        if self.kind == KIND_STAFF:
            return self.name
        if self.kind == KIND_AUTO:
            return "Sent automatically"
        return "Unknown sender"


@dataclass(frozen=True)
class Attempt:
    """One send of an item to a number."""

    event_id: str
    created: datetime
    delivered: bool | None
    reason: str
    pages: int | None
    to_number: str
    sender: Sender

    @property
    def outcome(self) -> str:
        """``delivered``, ``failed``, or ``pending`` (no result yet)."""
        if self.delivered is True:
            return "delivered"
        if self.delivered is False:
            return "failed"
        return "pending"


def _originator(event: Any) -> Sender:
    """The sender as Canvas recorded it, before resends are credited."""
    originator = event.originator
    if originator is None:
        return Sender(KIND_UNKNOWN)
    try:
        staff = originator.staff
    except Staff.DoesNotExist:
        return Sender(KIND_UNKNOWN)
    if staff.id == BOT_STAFF_ID:
        return Sender(KIND_AUTO, staff.id, staff.first_name, staff.last_name)
    return Sender(KIND_STAFF, staff.id, staff.first_name, staff.last_name)


def _attempt(event: Any) -> Attempt:
    fax = event.fax
    return Attempt(
        event_id=str(event.id),
        created=event.created,
        delivered=event.delivered_by_fax,
        reason=event.fax_result_msg or "",
        pages=fax.fax_pages if fax is not None else None,
        to_number=fax.to_fax_number if fax is not None else "",
        sender=_originator(event),
    )


def credit_resends(
    attempts: list[Attempt], resends: list[FaxResend]
) -> list[Attempt]:
    """Replace Canvas Bot senders with the person who clicked Resend.

    Resends are taken in click order. Each takes the earliest Canvas Bot attempt created
    after the click that no earlier click already took. A bot attempt no click claims
    stays "Sent automatically".
    """
    claimed: dict[str, Sender] = {}
    for resend in sorted(resends, key=lambda item: item.resent_at):
        for attempt in attempts:
            if (
                attempt.sender.kind == KIND_AUTO
                and attempt.event_id not in claimed
                and attempt.created > resend.resent_at
            ):
                person: Any = resend.staff
                claimed[attempt.event_id] = Sender(
                    KIND_RESENT, person.id, person.first_name, person.last_name
                )
                break
    return [
        Attempt(
            event_id=attempt.event_id,
            created=attempt.created,
            delivered=attempt.delivered,
            reason=attempt.reason,
            pages=attempt.pages,
            to_number=attempt.to_number,
            sender=claimed.get(attempt.event_id, attempt.sender),
        )
        for attempt in attempts
    ]


def load_attempts(spec: SourceSpec, item_dbids: list[int]) -> dict[tuple[int, str], list[Attempt]]:
    """Every send of the given items, grouped by (item, E.164 number), oldest first.

    Resends from the dashboard are credited to the person who clicked (notes only).
    """
    grouped: dict[tuple[int, str], list[Attempt]] = {}
    for chunk in chunked(sorted(set(item_dbids)), HISTORY_CHUNK):
        events = (
            spec.model.objects.filter(
                event_type=FAXED, **{f"{spec.item_field}_id__in": chunk}
            )
            .select_related("fax", "originator__staff")
            .order_by("created")
        )
        for event in events:
            key = (
                getattr(event, f"{spec.item_field}_id"),
                to_e164(event.fax.to_fax_number if event.fax is not None else ""),
            )
            grouped.setdefault(key, []).append(_attempt(event))

    if spec.type_key == "note" and grouped:
        resends: dict[tuple[int, str], list[FaxResend]] = {}
        for resend in FaxResend.objects.filter(note_id__in=sorted(set(item_dbids))).select_related(
            "staff"
        ):
            resends.setdefault((resend.note_id, resend.fax_number), []).append(resend)
        for key, group in resends.items():
            if key in grouped:
                grouped[key] = credit_resends(grouped[key], group)
    return grouped
