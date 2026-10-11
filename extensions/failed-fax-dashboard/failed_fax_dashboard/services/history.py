"""Fax attempts per item and number, and who gets credit for each send."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from canvas_sdk.v1.data import Staff

from failed_fax_dashboard.models import FaxResend
from failed_fax_dashboard.services.sources import SourceSpec
from failed_fax_dashboard.services.util import BOT_STAFF_ID, chunked, to_e164

FAXED = "FAXED"
HISTORY_CHUNK = 500
# A Resend click is matched only to a Canvas Bot send this soon after it. The same window
# is how long a click with no send yet counts as "waiting": the fax effect can be rejected
# after the click returns, and then no send ever arrives.
RESEND_WINDOW = timedelta(minutes=15)

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
        """How the dashboard words the sender. A resend shows the person, since the attempt list shows it was resent."""
        if self.kind in (KIND_STAFF, KIND_RESENT):
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


def _claims(attempts: list[Attempt], resends: list[FaxResend]) -> dict[str, FaxResend]:
    """Which Resend click each Canvas Bot attempt belongs to, by attempt id.

    Clicks are taken in click order. Each takes the earliest Canvas Bot attempt created
    within ``RESEND_WINDOW`` after the click that no earlier click already took.
    """
    claimed: dict[str, FaxResend] = {}
    for resend in sorted(resends, key=lambda item: item.resent_at):
        for attempt in attempts:
            if (
                attempt.sender.kind == KIND_AUTO
                and attempt.event_id not in claimed
                and resend.resent_at < attempt.created <= resend.resent_at + RESEND_WINDOW
            ):
                claimed[attempt.event_id] = resend
                break
    return claimed


def _credited(attempt: Attempt, resend: FaxResend) -> Attempt:
    person: Any = resend.staff
    return Attempt(
        event_id=attempt.event_id,
        created=attempt.created,
        delivered=attempt.delivered,
        reason=attempt.reason,
        pages=attempt.pages,
        to_number=attempt.to_number,
        sender=Sender(KIND_RESENT, person.id, person.first_name, person.last_name),
    )


def resend_row_number(resend: FaxResend) -> str:
    """The number of the row a resend was made from (its own number for older resends)."""
    number: str = resend.from_fax_number or resend.fax_number
    return number


class Histories(dict[tuple[int, str], list[Attempt]]):
    """Attempts by (item, E.164 number of the row they belong to), oldest first.

    ``moved`` maps an attempt id to the row number it was moved to: a resend to a corrected
    number belongs to the row it was made from. ``waiting`` holds rows with a Resend click
    that no send has answered yet, inside ``RESEND_WINDOW``.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.moved: dict[str, str] = {}
        self.waiting: set[tuple[int, str]] = set()

    def row_number(self, event_id: str, number: str) -> str:
        """The E.164 number of the row an attempt belongs to."""
        return self.moved.get(event_id, number)


def load_attempts(
    spec: SourceSpec, item_dbids: list[int], now: datetime | None = None
) -> Histories:
    """Every send of the given items, grouped by (item, row's E.164 number), oldest first.

    Resends from the dashboard are credited to the person who clicked (notes only), and a
    resend to a different number is filed under the row it was made from.
    """
    raw: dict[tuple[int, str], list[Attempt]] = {}
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
            raw.setdefault(key, []).append(_attempt(event))

    histories = Histories()
    if spec.type_key != "note" or not item_dbids:
        histories.update(raw)
        return histories

    by_number: dict[tuple[int, str], list[FaxResend]] = {}
    for resend in FaxResend.objects.filter(note_id__in=sorted(set(item_dbids))).select_related("staff"):
        by_number.setdefault((resend.note_id, resend.fax_number), []).append(resend)
    answered: set[int] = set()
    for key, group in raw.items():
        claims = _claims(group, by_number.get(key, []))
        answered.update(resend.dbid for resend in claims.values())
        for attempt in group:
            resend = claims.get(attempt.event_id)
            row = (key[0], resend_row_number(resend)) if resend is not None else key
            histories.setdefault(row, []).append(_credited(attempt, resend) if resend is not None else attempt)
            if row != key:
                histories.moved[attempt.event_id] = row[1]
    for row, group in histories.items():
        group.sort(key=lambda item: item.created)

    moment = now or datetime.now(timezone.utc)
    for resends in by_number.values():
        for resend in resends:
            if resend.dbid not in answered and resend.resent_at > moment - RESEND_WINDOW:
                histories.waiting.add((resend.note_id, resend_row_number(resend)))
    return histories
