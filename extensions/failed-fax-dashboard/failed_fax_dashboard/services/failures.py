"""Finds failed sent and received faxes: one row per item and fax number."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from canvas_sdk.v1.data import Command, Fax, FaxDirection, ServiceProvider

from failed_fax_dashboard.models import FaxDismissal
from failed_fax_dashboard.services.contacts import (
    DIRECTORY_SOURCE,
    Contact,
    contact_from_provider,
    directory_matches,
    provider_name,
    sent_contact,
)
from failed_fax_dashboard.services.history import FAXED, Attempt, load_attempts
from failed_fax_dashboard.services.sources import (
    DATA_INTEGRATION_PATH,
    RECEIVED_TYPE,
    SOURCES,
    SourceSpec,
    walk,
)
from failed_fax_dashboard.services.tasks import (
    TaskInfo,
    alert_key,
    load_alerts,
    load_tasks,
)
from failed_fax_dashboard.services.util import last_ten, name_key, person_name, to_e164

WINDOW_DAYS = 90

RECEIVED_PROBLEM = "Only part of the fax arrived"
PENDING_PROBLEM = "Resent, waiting for delivery"


def note_link(patient: Any, note: Any) -> str | None:
    """Path to a note in the patient's chart, or None when either is missing."""
    if patient is None or note is None:
        return None
    return f"/patient/{patient.id}?noteId={note.dbid}"


@dataclass
class SentRow:
    """A failed sent fax: the latest failed send of one item to one number."""

    spec: SourceSpec
    event: Any
    item_id: str
    number: str
    e164: str
    attempts: list[Attempt]
    patient: Any
    link_url: str | None
    contact: Contact | None = None
    directory: ServiceProvider | None = None
    task: TaskInfo | None = None

    @property
    def key(self) -> str:
        """Stable id of the row: the item type and the latest failed send."""
        return f"{self.spec.type_key}:{self.event.id}"

    @property
    def latest(self) -> Attempt:
        """The most recent attempt, failed or still pending."""
        return self.attempts[-1]

    @property
    def pending(self) -> bool:
        """Whether the latest attempt is still waiting for a result."""
        return self.latest.outcome == "pending"

    @property
    def when(self) -> datetime:
        """When the latest attempt was sent."""
        return self.latest.created

    @property
    def pages(self) -> int | None:
        """Pages in the latest attempt."""
        return self.latest.pages

    @property
    def patient_name(self) -> str:
        """Patient's name, or an empty string for items with no patient."""
        return person_name(self.patient)

    @property
    def patient_sort(self) -> str:
        """Patient's last name, then first name."""
        if self.patient is None:
            return ""
        return name_key(self.patient.first_name, self.patient.last_name)

    @property
    def problem_text(self) -> str:
        """The fax service's reason, or the waiting message after a resend."""
        return PENDING_PROBLEM if self.pending else self.latest.reason

    @property
    def party_name(self) -> str:
        """Recipient's name, or the number when the recipient is not in the directory."""
        return self.contact.name if self.contact is not None else self.number

    @property
    def sender_sort(self) -> str:
        """Latest sender's last name, then first name (empty when no person sent it)."""
        sender = self.latest.sender
        return name_key(sender.first_name, sender.last_name) if sender.is_person else ""

    @property
    def search_text(self) -> str:
        """Lowercase text the search box looks in."""
        contact = self.contact.name if self.contact is not None else ""
        return " ".join([self.patient_name, contact, self.spec.label]).lower()

    @property
    def sender_staff_ids(self) -> set[str]:
        """Staff id of the latest sender, when a person sent it."""
        sender = self.latest.sender
        return {sender.staff_id} if sender.is_person else set()


@dataclass
class ReceivedRow:
    """A received fax that arrived only in part."""

    fax: Fax
    number: str
    e164: str
    contact: Contact | None = None
    task: TaskInfo | None = None
    link_url: str = DATA_INTEGRATION_PATH

    @property
    def key(self) -> str:
        """Stable id of the row."""
        return f"{RECEIVED_TYPE}:{self.fax.id}"

    @property
    def when(self) -> datetime:
        """When the fax came in."""
        return self.fax.date_utc or self.fax.created  # type: ignore[no-any-return]

    @property
    def pages(self) -> int | None:
        """Pages that arrived."""
        pages: int | None = self.fax.fax_pages
        return pages

    @property
    def problem_text(self) -> str:
        """Received faxes carry no reason from the fax service."""
        return RECEIVED_PROBLEM

    @property
    def party_name(self) -> str:
        """Sender's name, or the number when the sender is not in the directory."""
        return self.contact.name if self.contact is not None else self.number

    @property
    def search_text(self) -> str:
        """Lowercase text the search box looks in."""
        return self.contact.name.lower() if self.contact is not None else ""

    @property
    def sender_staff_ids(self) -> set[str]:
        """A received fax has no Canvas sender."""
        return set()


def cutoff_for(now: datetime | None) -> datetime:
    """Start of the 90-day look-back window."""
    return (now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)


def dismissed_keys(cutoff: datetime) -> set[tuple[str, str]]:
    """(source type, record id) pairs staff dismissed inside the window."""
    return set(
        FaxDismissal.objects.filter(dismissed_at__gte=cutoff).values_list("source_type", "source_id")
    )


def event_number(event: Any) -> str:
    """The number an action event's fax was sent to."""
    return event.fax.to_fax_number if event.fax is not None else ""


def failed_events(spec: SourceSpec, cutoff: datetime) -> list[Any]:
    """Faxed events of one item type that were not delivered, with everything the row needs."""
    queryset = (
        spec.model.objects.filter(
            event_type=FAXED,
            delivered_by_fax=False,
            created__gte=cutoff,
            **spec.item_filters,
        )
        .exclude(**spec.item_excludes)
        .select_related("fax", "originator__staff", *spec.select_related)
        .order_by("created")
    )
    return list(queryset)


def command_ids(spec: SourceSpec, events: list[Any]) -> dict[int, str]:
    """Command id for each faxed item that is a note command, keyed by the item's dbid.

    One query per item type. Items that aren't commands (notes, letters, documents) get none.
    """
    if spec.anchor_type is None or not events:
        return {}
    dbids = {getattr(event, spec.item_field).dbid for event in events}
    return {
        anchor: str(command_id)
        for anchor, command_id in Command.objects.filter(
            anchor_object_type=spec.anchor_type, anchor_object_dbid__in=dbids
        ).values_list("anchor_object_dbid", "id")
    }


def item_link(
    spec: SourceSpec,
    event: Any,
    patient: Any,
    note: Any,
    commands: dict[int, str] | None = None,
) -> str | None:
    """Where the row's item link goes.

    Orders and referrals open their command inside the note, the same link Canvas's own
    permalinks use. Without a matching command they fall back to the note.
    """
    if spec.type_key == "integration_task":
        return f"{DATA_INTEGRATION_PATH}/{event.integration_task_id}"
    base = note_link(patient, note)
    if base is None or spec.command_type is None:
        return base
    item = getattr(event, spec.item_field)
    command_id = (commands or {}).get(item.dbid)
    if command_id is None:
        return base
    return (
        f"{base}&commandType={spec.command_type}&commandId={item.dbid}"
        f"&commandUuid={command_id}"
    )


def collect_sent(cutoff: datetime) -> list[SentRow]:
    """Failed sent faxes: one row per item and number, minus cleared and dismissed ones.

    A row clears when a later attempt to the same number was delivered.
    """
    dismissed = dismissed_keys(cutoff)
    rows: list[SentRow] = []
    for spec in SOURCES:
        newest: dict[tuple[int, str], Any] = {}
        for event in failed_events(spec, cutoff):
            key = (getattr(event, f"{spec.item_field}_id"), to_e164(event_number(event)))
            newest[key] = event
        if not newest:
            continue
        histories = load_attempts(spec, [key[0] for key in newest])
        commands = command_ids(spec, list(newest.values()))
        for key, event in newest.items():
            attempts = histories.get(key, [])
            if not attempts or any(
                attempt.delivered is True and attempt.created > event.created for attempt in attempts
            ):
                continue
            if (spec.type_key, str(event.id)) in dismissed:
                continue
            patient = walk(event, spec.patient_path)
            rows.append(
                SentRow(
                    spec=spec,
                    event=event,
                    item_id=str(getattr(event, spec.item_field).id),
                    number=event_number(event),
                    e164=key[1],
                    attempts=attempts,
                    patient=patient,
                    link_url=item_link(spec, event, patient, walk(event, spec.note_path), commands),
                )
            )
    directory = directory_matches([row.number for row in rows])
    for row in rows:
        row.directory = directory.get(last_ten(row.number))
        row.contact = sent_contact(row.spec, row.event, row.number, row.directory)
    return rows


def collect_received(cutoff: datetime) -> list[ReceivedRow]:
    """Inbound faxes that failed to arrive in full, minus dismissed ones."""
    dismissed = dismissed_keys(cutoff)
    faxes = [
        fax
        for fax in Fax.objects.filter(
            direction=FaxDirection.INBOUND, success=False, created__gte=cutoff
        ).order_by("created")
        if (RECEIVED_TYPE, str(fax.id)) not in dismissed
    ]
    directory = directory_matches([fax.from_fax_number for fax in faxes])
    rows: list[ReceivedRow] = []
    for fax in faxes:
        provider = directory.get(last_ten(fax.from_fax_number))
        rows.append(
            ReceivedRow(
                fax=fax,
                number=fax.from_fax_number,
                e164=to_e164(fax.from_fax_number),
                contact=contact_from_provider(provider, DIRECTORY_SOURCE) if provider else None,
            )
        )
    return rows


def _with_earlier(task: TaskInfo | None, alert: Any) -> TaskInfo | None:
    """The row's task, carrying the ids of tasks it replaced."""
    if task is None or alert is None or not alert.previous_task_ids:
        return task
    return replace(task, earlier_ids=tuple(part for part in alert.previous_task_ids.split(",") if part))


def attach_tasks(sent: list[SentRow], received: list[ReceivedRow]) -> None:
    """Give each row the automatic task the scheduled job made for it, if any."""
    alerts = load_alerts([row.item_id for row in sent] + [str(row.fax.id) for row in received])
    tasks = load_tasks([alert.task_id for alert in alerts.values()])
    for sent_row in sent:
        alert = alerts.get(alert_key(sent_row.spec.type_key, sent_row.item_id, sent_row.e164))
        sent_row.task = _with_earlier(tasks.get(alert.task_id) if alert is not None else None, alert)
    for received_row in received:
        alert = alerts.get(alert_key(RECEIVED_TYPE, str(received_row.fax.id), received_row.e164))
        received_row.task = _with_earlier(tasks.get(alert.task_id) if alert is not None else None, alert)


def directory_name(row: SentRow) -> str:
    """Name of the single directory contact with the row's number, for the resend form."""
    return provider_name(row.directory) if row.directory is not None else ""
