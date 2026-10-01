"""Describes the six faxable item types and how to read each one."""

from dataclasses import dataclass, field
from typing import Any

from canvas_sdk.effects.task import AddTask
from canvas_sdk.v1.data import (
    ImagingOrderActionEvent,
    IntegrationTaskActionEvent,
    LabOrderActionEvent,
    LetterActionEvent,
    NoteActionEvent,
    ReferralActionEvent,
)
from canvas_sdk.v1.data.note import NoteStates

RECEIVED_TYPE = "received_fax"
RECEIVED_LABEL = "Received fax"

DATA_INTEGRATION_PATH = "/data-integration"


@dataclass(frozen=True)
class SourceSpec:
    """How to query one action event model and read the item it points to."""

    type_key: str
    label: str
    model: Any
    # Name of the foreign key to the faxed item on the action event.
    item_field: str
    # Attribute chains (starting at the action event) to the patient and the note.
    patient_path: tuple[str, ...] | None
    note_path: tuple[str, ...] | None
    select_related: tuple[str, ...]
    # Filters/excludes that drop retracted or deleted items.
    item_filters: dict[str, Any] = field(default_factory=dict)
    item_excludes: dict[str, Any] = field(default_factory=dict)
    # Attribute chain to the linkable object for follow-up tasks, with its task type.
    link_path: tuple[str, ...] | None = None
    link_type: AddTask.LinkableObjectType | None = None
    # Attribute chain to the ServiceProvider the item names as its recipient, if it has one.
    contact_path: tuple[str, ...] | None = None
    # Attribute chain to a lab's name, for lab orders (the order carries no ServiceProvider).
    lab_name_path: tuple[str, ...] | None = None
    # Card note shown with the contact, and the item as written in a sentence.
    contact_source: str = "Matched in your contact directory"
    noun: str = ""
    # For items that are note commands: the chart's command type key and the Command
    # anchor type, so links open the command itself instead of just its note.
    command_type: str | None = None
    anchor_type: str | None = None


def _live_item(prefix: str) -> dict[str, Any]:
    """Filters that drop entered-in-error and deleted orders."""
    return {f"{prefix}__entered_in_error__isnull": True, f"{prefix}__deleted": False}


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        type_key="note",
        label="Note",
        model=NoteActionEvent,
        item_field="note",
        patient_path=("note", "patient"),
        note_path=("note",),
        select_related=("note__patient",),
        item_excludes={"note__current_state__state": NoteStates.DELETED},
        noun="note",
    ),
    SourceSpec(
        type_key="referral",
        label="Referral",
        model=ReferralActionEvent,
        item_field="referral",
        patient_path=("referral", "patient"),
        note_path=("referral", "note"),
        select_related=("referral__patient", "referral__note", "referral__service_provider"),
        item_filters=_live_item("referral"),
        link_path=("referral",),
        link_type=AddTask.LinkableObjectType.REFERRAL,
        contact_path=("referral", "service_provider"),
        contact_source="From the referral",
        noun="referral",
        command_type="refer",
        anchor_type="referral",
    ),
    SourceSpec(
        type_key="imaging_order",
        label="Imaging order",
        model=ImagingOrderActionEvent,
        item_field="imaging_order",
        patient_path=("imaging_order", "patient"),
        note_path=("imaging_order", "note"),
        select_related=(
            "imaging_order__patient",
            "imaging_order__note",
            "imaging_order__imaging_center",
        ),
        item_filters=_live_item("imaging_order"),
        link_path=("imaging_order",),
        link_type=AddTask.LinkableObjectType.IMAGING,
        contact_path=("imaging_order", "imaging_center"),
        contact_source="From the imaging order",
        noun="imaging order",
        command_type="imagingOrder",
        anchor_type="imagingorder",
    ),
    SourceSpec(
        type_key="lab_order",
        label="Lab order",
        model=LabOrderActionEvent,
        item_field="lab_order",
        patient_path=("lab_order", "patient"),
        note_path=("lab_order", "note"),
        select_related=("lab_order__patient", "lab_order__note"),
        item_filters=_live_item("lab_order"),
        lab_name_path=("lab_order", "ontology_lab_partner"),
        contact_source="Lab from the order, details from your contact directory",
        noun="lab order",
        command_type="labOrder",
        anchor_type="laborder",
    ),
    SourceSpec(
        type_key="letter",
        label="Letter",
        model=LetterActionEvent,
        item_field="letter",
        patient_path=("letter", "note", "patient"),
        note_path=("letter", "note"),
        select_related=("letter__note__patient",),
        item_excludes={"letter__note__current_state__state": NoteStates.DELETED},
        noun="letter",
    ),
    SourceSpec(
        type_key="integration_task",
        label="Data Integration document",
        model=IntegrationTaskActionEvent,
        item_field="integration_task",
        patient_path=("integration_task", "patient"),
        note_path=None,
        select_related=("integration_task__patient",),
        noun="Data Integration document",
    ),
)

SOURCES_BY_KEY: dict[str, SourceSpec] = {spec.type_key: spec for spec in SOURCES}

TYPE_LABELS: dict[str, str] = {
    **{spec.type_key: spec.label for spec in SOURCES},
    RECEIVED_TYPE: RECEIVED_LABEL,
}


def walk(obj: Any, path: tuple[str, ...] | None) -> Any:
    """Follow an attribute chain, returning None as soon as a link is missing."""
    if path is None:
        return None
    current = obj
    for name in path:
        if current is None:
            return None
        current = getattr(current, name)
    return current
