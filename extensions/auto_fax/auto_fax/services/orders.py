"""Work out what the note's **Fax orders** button would send, and send it.

The button's modal (the preview) and the send endpoint both call ``build_plan``,
so the staff member confirms exactly what goes out. A plan is a fixed number of
queries per note, however many orders or rules there are:

- the note's committed, not entered-in-error order commands (one query)
- their command metadata, only when a rule checks metadata (one query)
- the referral, imaging and lab order records, only for ``order_documents``
  rules (one query per order type present)
- the recipients (see ``services/recipients.py``)
- earlier plugin faxes of the note and of each order type (one query each)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.fax import (
    FaxImagingOrderEffect,
    FaxLabOrderEffect,
    FaxNoteEffect,
    FaxReferralEffect,
)
from canvas_sdk.v1.data import (
    Command,
    CommandMetadata,
    ImagingOrder,
    ImagingOrderActionEvent,
    LabOrder,
    LabOrderActionEvent,
    Note,
    NoteActionEvent,
    Referral,
    ReferralActionEvent,
)
from logger import log

from auto_fax.services.config import (
    MEDICATION_ORDER_TYPES,
    MODE_OFF,
    ORDER_ADJUST_PRESCRIPTION,
    ORDER_CHANGE_MEDICATION,
    ORDER_DME,
    ORDER_IMAGING,
    ORDER_LAB,
    ORDER_MEDICATION_STATEMENT,
    ORDER_PRESCRIBE,
    ORDER_REFERRAL,
    ORDER_REFILL,
    ORDER_STOP_MEDICATION,
    SEND_ORDER_DOCUMENTS,
    SEND_WHOLE_NOTE,
    TRIGGER_FAX_ORDERS_BUTTON,
    Config,
    Rule,
)
from auto_fax.services.delivery import (
    cover_kwargs,
    destination,
    plugin_faxes,
    today_for,
)
from auto_fax.services.fax_number import e164, for_fax_effect, masked
from auto_fax.services.recipients import resolve_recipients

# Command schema key -> the order type rules name it by.
ORDER_TYPE_BY_SCHEMA_KEY: dict[str, str] = {
    "refer": ORDER_REFERRAL,
    "imagingOrder": ORDER_IMAGING,
    "labOrder": ORDER_LAB,
    "orderDme": ORDER_DME,
    "prescribe": ORDER_PRESCRIBE,
    "adjustPrescription": ORDER_ADJUST_PRESCRIPTION,
    "refill": ORDER_REFILL,
    "changeMedication": ORDER_CHANGE_MEDICATION,
    "stopMedication": ORDER_STOP_MEDICATION,
    "medicationStatement": ORDER_MEDICATION_STATEMENT,
}

ORDER_LABELS: dict[str, str] = {
    ORDER_REFERRAL: "Referral",
    ORDER_IMAGING: "Imaging order",
    ORDER_LAB: "Lab order",
    ORDER_DME: "DME order",
    ORDER_PRESCRIBE: "Prescription",
    ORDER_ADJUST_PRESCRIPTION: "Adjusted prescription",
    ORDER_REFILL: "Refill",
    ORDER_CHANGE_MEDICATION: "Medication change",
    ORDER_STOP_MEDICATION: "Stopped medication",
    ORDER_MEDICATION_STATEMENT: "Medication statement",
}

# Order types with a document of their own: its model, the action event model
# and field that record its faxes, and the fax effect plus the keyword it takes
# the document's id under.
_DOCUMENTS: dict[str, tuple[Any, Any, str, Any, str]] = {
    ORDER_REFERRAL: (
        Referral,
        ReferralActionEvent,
        "referral",
        FaxReferralEffect,
        "referral_id",
    ),
    ORDER_IMAGING: (
        ImagingOrder,
        ImagingOrderActionEvent,
        "imaging_order",
        FaxImagingOrderEffect,
        "imaging_order_id",
    ),
    ORDER_LAB: (
        LabOrder,
        LabOrderActionEvent,
        "lab_order",
        FaxLabOrderEffect,
        "lab_order_id",
    ),
}

_LABEL_MAX = 80


@dataclass(frozen=True)
class Order:
    """One committed order in the note that a button rule picks up."""

    command_id: str
    order_type: str
    label: str
    committed_at: datetime
    document_id: str | None = None

    @property
    def type_label(self) -> str:
        """The order type in words."""
        return ORDER_LABELS[self.order_type]


@dataclass
class Delivery:
    """Everything one fax number gets from one click."""

    name: str
    kind: str
    digits: str
    rule: Rule
    send_as: str
    orders: list[Order] = field(default_factory=list)
    # Orders whose own document this plugin hasn't faxed to this number yet
    # (``order_documents`` only).
    unsent: list[Order] = field(default_factory=list)
    last_sent: datetime | None = None
    already_sent: bool = False

    @property
    def fax_count(self) -> int:
        """Faxes a first send makes: one whole note, or one per unsent document."""
        if self.send_as == SEND_WHOLE_NOTE:
            return 1
        return len(self.unsent)


@dataclass
class Plan:
    """What the button would send for one note."""

    note_id: str
    location_id: str | None
    deliveries: list[Delivery] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    order_types: frozenset[str] = frozenset()
    metadata_notes: list[str] = field(default_factory=list)
    test_number: bool = False

    @property
    def has_orders(self) -> bool:
        """Whether any recipient has an order to send."""
        return any(delivery.orders for delivery in self.deliveries)

    @property
    def all_already_sent(self) -> bool:
        """Whether every recipient already has everything (a send would be a resend)."""
        return bool(self.deliveries) and all(d.already_sent for d in self.deliveries)


def button_rules(
    config: Config, note_type_code: str | None, location_id: str | None
) -> list[Rule]:
    """The button rules that cover a note of this type at this location."""
    return [
        rule
        for rule in config.rules
        if rule.trigger == TRIGGER_FAX_ORDERS_BUTTON
        and rule.matches(note_type_code, location_id)
    ]


def find_note(
    config: Config, dbid: Any = None, note_id: str | None = None
) -> tuple[Any, list[Rule]] | None:
    """The note (by database id or by id) and the button rules covering it.

    None when the plugin is off, no button rule exists or covers the note, or
    the note or its patient is missing. No query runs unless a button rule exists.
    """
    if config.mode == MODE_OFF or not any(
        rule.trigger == TRIGGER_FAX_ORDERS_BUTTON for rule in config.rules
    ):
        return None
    if dbid:
        lookup: dict[str, Any] = {"dbid": dbid}
    elif note_id:
        lookup = {"id": note_id}
    else:
        return None
    note = (
        Note.objects.select_related(
            "note_type_version", "patient", "location", "provider"
        )
        .filter(**lookup)
        .first()
    )
    if note is None or note.patient is None:
        return None
    rules = button_rules(config, note_type_code_of(note), location_id_of(note))
    return (note, rules) if rules else None


def note_type_code_of(note: Any) -> str | None:
    """The note's type code, or None."""
    return note.note_type_version.code if note.note_type_version else None


def location_id_of(note: Any) -> str | None:
    """The note's practice location id, or None."""
    return str(note.location.id) if note.location else None


def describe(data: Any) -> str:
    """A short name for the order from its command data, or "".

    Command data differs by command type. The ordered item is a coding with a
    ``text`` (or a list of them, for lab tests), so this takes the first one
    found rather than knowing every command's field names.
    """
    if not isinstance(data, dict):
        return ""
    for value in data.values():
        texts: list[str] = []
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            texts = [value["text"]]
        elif isinstance(value, list):
            texts = [
                item["text"]
                for item in value
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
        joined = ", ".join(text.strip() for text in texts if text.strip())
        if joined:
            return (
                joined if len(joined) <= _LABEL_MAX else joined[: _LABEL_MAX - 1] + "…"
            )
    return ""


def type_names(order_types: frozenset[str]) -> str:
    """Order types in words, with the six medication types as one "Medications"."""
    names = []
    rest = order_types
    if MEDICATION_ORDER_TYPES <= order_types:
        names.append("Medications")
        rest = order_types - MEDICATION_ORDER_TYPES
    names.extend(ORDER_LABELS[t] for t in sorted(rest))
    return ", ".join(names)


def _committed_orders(note_id: str, order_types: frozenset[str]) -> list[Any]:
    schema_keys = sorted(
        key for key, kind in ORDER_TYPE_BY_SCHEMA_KEY.items() if kind in order_types
    )
    return list(
        Command.objects.filter(
            note__id=note_id,
            schema_key__in=schema_keys,
            state="committed",
            entered_in_error__isnull=True,
        ).order_by("created", "dbid")
    )


def _metadata_by_command(commands: list[Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    rows = CommandMetadata.objects.filter(
        command__id__in=[str(c.id) for c in commands]
    ).values_list("command__id", "key", "value")
    for command_id, key, value in rows:
        result.setdefault(str(command_id), {})[key] = value
    return result


def _document_ids(commands: list[Any]) -> dict[str, str]:
    """Command id -> the id of its referral, imaging or lab order record."""
    result: dict[str, str] = {}
    for order_type, (model, *_rest) in _DOCUMENTS.items():
        dbids = {
            c.anchor_object_dbid: str(c.id)
            for c in commands
            if ORDER_TYPE_BY_SCHEMA_KEY[c.schema_key] == order_type
            and c.anchor_object_dbid
        }
        if not dbids:
            continue
        for dbid, document_id in model.objects.filter(
            dbid__in=sorted(dbids)
        ).values_list("dbid", "id"):
            result[dbids[dbid]] = str(document_id)
    return result


def _note_faxes(note_id: str) -> dict[str, datetime]:
    """E.164 number -> when this plugin last faxed the note there."""
    latest: dict[str, datetime] = {}
    rows = plugin_faxes(NoteActionEvent.objects.filter(note__id=note_id)).values_list(
        "fax__to_fax_number", "created"
    )
    for number, created in rows:
        if number and (number not in latest or created > latest[number]):
            latest[number] = created
    return latest


def _document_faxes(orders: list[Order]) -> dict[tuple[str, str], datetime]:
    """(document id, E.164 number) -> when this plugin last faxed it there."""
    latest: dict[tuple[str, str], datetime] = {}
    by_type: dict[str, list[str]] = {}
    for order in orders:
        if order.document_id:
            by_type.setdefault(order.order_type, []).append(order.document_id)
    for order_type, ids in by_type.items():
        _model, event_model, relation, *_rest = _DOCUMENTS[order_type]
        rows = plugin_faxes(
            event_model.objects.filter(**{f"{relation}__id__in": sorted(ids)})
        ).values_list(f"{relation}__id", "fax__to_fax_number", "created")
        for document_id, number, created in rows:
            key = (str(document_id), number)
            if number and (key not in latest or created > latest[key]):
                latest[key] = created
    return latest


def build_plan(note: Any, rules: list[Rule], test_digits: str | None) -> Plan:
    """What the button would send for this note under these rules."""
    note_id = str(note.id)
    plan = Plan(
        note_id=note_id,
        location_id=location_id_of(note),
        test_number=bool(test_digits),
        order_types=frozenset().union(*(rule.order_types for rule in rules)),
        metadata_notes=[
            f"{type_names(rule.order_types)}: only orders marked "
            + ", ".join(f"{key} = {value}" for key, value in rule.command_metadata)
            for rule in rules
            if rule.command_metadata
        ],
    )

    commands = _committed_orders(note_id, plan.order_types)
    metadata = (
        _metadata_by_command(commands)
        if commands and any(rule.command_metadata for rule in rules)
        else {}
    )
    wants_documents = any(rule.send_as == SEND_ORDER_DOCUMENTS for rule in rules)
    documents = _document_ids(commands) if commands and wants_documents else {}
    orders = [
        Order(
            command_id=str(c.id),
            order_type=ORDER_TYPE_BY_SCHEMA_KEY[c.schema_key],
            label=describe(c.data),
            committed_at=c.modified,
            document_id=documents.get(str(c.id)),
        )
        for c in commands
    ]

    recipients = resolve_recipients(
        str(note.patient.id), rules, today_for(note.provider)
    )
    by_number: dict[str, Delivery] = {}
    for recipient in recipients:
        if recipient.problem or not recipient.fax_digits:
            label = (
                f"{recipient.name} ({recipient.kind})"
                if recipient.name
                else recipient.kind
            )
            problem = f"{label}: {recipient.problem}"
            # Two rules naming the same recipient report its problem once.
            if problem not in plan.problems:
                plan.problems.append(problem)
            continue
        rule = recipient.rule
        rule_orders = [
            order
            for order in orders
            if order.order_type in rule.order_types
            and rule.matches_metadata(metadata.get(order.command_id, {}))
        ]
        digits = destination(recipient, test_digits)
        delivery = by_number.get(digits)
        if delivery is None:
            delivery = Delivery(
                name=recipient.name,
                kind=recipient.kind,
                digits=digits,
                rule=rule,
                send_as=rule.send_as,
            )
            by_number[digits] = delivery
        elif rule.send_as == SEND_WHOLE_NOTE:
            # Two rules for one number: the whole note already carries every order.
            delivery.send_as = SEND_WHOLE_NOTE
        known = {order.command_id for order in delivery.orders}
        delivery.orders.extend(o for o in rule_orders if o.command_id not in known)

    for delivery in by_number.values():
        if delivery.send_as != SEND_ORDER_DOCUMENTS:
            continue
        # An order whose referral, imaging or lab record can't be found has no
        # document to fax. Say so rather than list it as if it will be sent.
        missing = [o for o in delivery.orders if not o.document_id]
        if missing:
            delivery.orders = [o for o in delivery.orders if o.document_id]
            names = ", ".join(
                f"{o.type_label}{f' ({o.label})' if o.label else ''}" for o in missing
            )
            problem = f"{names}: no document on file to fax yet"
            if problem not in plan.problems:
                plan.problems.append(problem)

    deliveries = [d for d in by_number.values() if d.orders]
    if deliveries:
        _mark_already_sent(note_id, deliveries)
    plan.deliveries = deliveries
    return plan


def _mark_already_sent(note_id: str, deliveries: list[Delivery]) -> None:
    whole = [d for d in deliveries if d.send_as == SEND_WHOLE_NOTE]
    by_document = [d for d in deliveries if d.send_as == SEND_ORDER_DOCUMENTS]
    if whole:
        note_faxes = _note_faxes(note_id)
        for delivery in whole:
            delivery.last_sent = note_faxes.get(e164(delivery.digits))
            # Sent already when the last fax went out after every order in it
            # was committed. An order committed since then makes it new again.
            newest = max(order.committed_at for order in delivery.orders)
            delivery.already_sent = (
                delivery.last_sent is not None and delivery.last_sent >= newest
            )
    if by_document:
        faxed = _document_faxes([o for d in by_document for o in d.orders])
        for delivery in by_document:
            number = e164(delivery.digits)
            sent_at = [
                faxed[(o.document_id, number)]
                for o in delivery.orders
                if o.document_id and (o.document_id, number) in faxed
            ]
            delivery.last_sent = max(sent_at) if sent_at else None
            delivery.unsent = [
                o
                for o in delivery.orders
                if o.document_id and (o.document_id, number) not in faxed
            ]
            delivery.already_sent = not delivery.unsent


def fax_effects(plan: Plan, resend: bool, dry_run: bool) -> tuple[list[Effect], int]:
    """The fax effects for a confirmed send, and how many faxes they are.

    Without ``resend``, a recipient that already has everything is skipped,
    and an ``order_documents`` recipient gets only the documents not yet faxed
    to it. In a dry run nothing is returned; the faxes are only logged.
    """
    effects: list[Effect] = []
    count = 0
    for delivery in plan.deliveries:
        if delivery.already_sent and not resend:
            continue
        subject = f"orders for note {plan.note_id}"
        common = {
            "recipient_name": delivery.name,
            "recipient_fax_number": for_fax_effect(delivery.digits),
            **cover_kwargs(delivery.rule, plan.location_id, subject),
        }
        label = (
            f"{subject} rule {delivery.rule.name!r} -> {delivery.kind} at "
            f"{masked(delivery.digits)}"
            + (" (test number)" if plan.test_number else "")
        )
        if delivery.send_as == SEND_WHOLE_NOTE:
            count += 1
            log.info(
                f"[auto_fax] {'dry run, would fax' if dry_run else 'faxing'} "
                f"whole note with {len(delivery.orders)} order(s): {label}"
            )
            if not dry_run:
                effects.append(FaxNoteEffect(note_id=plan.note_id, **common).apply())
            continue
        to_send = (
            [o for o in delivery.orders if o.document_id] if resend else delivery.unsent
        )
        for order in to_send:
            count += 1
            log.info(
                f"[auto_fax] {'dry run, would fax' if dry_run else 'faxing'} "
                f"{order.order_type} order {order.command_id}: {label}"
            )
            if dry_run:
                continue
            _model, _events, _relation, effect_class, id_field = _DOCUMENTS[
                order.order_type
            ]
            effects.append(
                effect_class(**{id_field: order.document_id}, **common).apply()
            )
    return effects, count
