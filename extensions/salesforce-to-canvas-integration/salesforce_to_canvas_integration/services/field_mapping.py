"""Salesforce → Canvas field mapper.

Reads a JSON map of the form::

    {
        "FirstName":             {"target": "first_name"},
        "MailingStreet":         {"target": "address_line_1"},
        "Preferred_Language__c": {"target": "metadata.preferred_language"}
    }

and converts a Salesforce record payload into a flat dict of Canvas-shaped
fields plus a ``metadata`` sub-dict for any ``metadata.*`` targets.

The mapper intentionally has no Canvas SDK dependency so it can be tested in
isolation and reused by other plugins.
"""

from dataclasses import dataclass, field
from typing import Any

GENDER_NORMALISATION: dict[str, str] = {
    "male": "male",
    "m": "male",
    "female": "female",
    "f": "female",
    "other": "other",
    "nonbinary": "other",
    "non-binary": "other",
    "non binary": "other",
    "unknown": "unknown",
    "u": "unknown",
}


@dataclass(frozen=True)
class FieldMappingState:
    """The resolved active field mapping profile and the stored Custom rows.

    ``profile`` is always one of the three profile names. ``custom`` is a list of
    ``(salesforce_field, canvas_target)`` pairs in stored order, sanitized so
    callers never see a malformed row. Lives in this Canvas free service module
    because a frozen dataclass cannot be defined in the model module, which needs
    ``from __future__ import annotations`` for its Django field subscripts and
    that string annotation form breaks dataclass evaluation in the plugin
    sandbox. See journal cnv-941/051.
    """

    profile: str
    custom: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MappedPatient:
    """Output of the field mapper. ``metadata`` holds opaque key/value pairs."""

    canvas_fields: dict[str, Any]
    metadata: dict[str, str]
    telecom: dict[str, str] = field(default_factory=dict)

    def has_required(self, *, required: tuple[str, ...] = ("last_name",)) -> bool:
        return all(self.canvas_fields.get(r) for r in required)


class MappingError(ValueError):
    """Raised when the mapping definition is malformed at runtime."""


def _split_street(value: str) -> tuple[str, str]:
    if "\n" in value:
        first, rest = value.split("\n", 1)
        return first.strip(), rest.strip()
    return value.strip(), ""


def _normalise_gender(value: str) -> str | None:
    return GENDER_NORMALISATION.get(value.strip().lower())


def _assign(target: str, value: Any, canvas: dict[str, Any]) -> None:
    """Apply a single ``target → value`` write, including address-line split."""
    if value is None:
        return
    if target == "address_line_1":
        line_1, line_2 = _split_street(str(value))
        if line_1:
            canvas["address_line_1"] = line_1
        if line_2 and "address_line_2" not in canvas:
            canvas["address_line_2"] = line_2
        return
    if target == "sex_at_birth":
        normalised = _normalise_gender(str(value))
        if normalised:
            canvas["sex_at_birth"] = normalised
        return
    canvas[target] = value


def map_record(
    sf_record: dict[str, Any], field_mapping: dict[str, dict[str, str]]
) -> MappedPatient:
    """Translate a Salesforce record into Canvas-shaped fields + metadata.

    Unknown SF fields are silently ignored — the customer mapping is the
    single source of truth for what crosses over.
    """
    canvas_fields: dict[str, Any] = {}
    metadata: dict[str, str] = {}
    telecom: dict[str, str] = {}

    for sf_name, spec in field_mapping.items():
        target = (spec.get("target") or "").strip()
        if not target:
            raise MappingError(f"Mapping for {sf_name!r} is missing a target")

        value = sf_record.get(sf_name)
        if value is None or value == "":
            continue

        if target.startswith("metadata."):
            metadata[target.removeprefix("metadata.")] = str(value)
            continue

        if target.startswith("telecom."):
            telecom[target.removeprefix("telecom.")] = str(value)
            continue

        _assign(target, value, canvas_fields)

    return MappedPatient(
        canvas_fields=canvas_fields,
        metadata=metadata,
        telecom=telecom,
    )


@dataclass(frozen=True)
class PromotePrefill:
    """Gap filled merge of an incoming event over its freshest prior event.

    ``mapped`` is the merge an operator sees on the promote to create form, with
    the incoming modify winning every field it populates and the prior event
    filling only the fields the incoming payload left empty. ``gap_filled`` names
    the canvas fields that came from the prior event, so the form can flag the
    only values sourced from history. ``changed`` names the canvas fields the
    incoming payload populated with a value that differs from the prior snapshot,
    the server side diff scoped to the promote case. See journal cnv-909/088.
    """

    mapped: MappedPatient
    gap_filled: tuple[str, ...]
    changed: tuple[str, ...]


def build_promote_prefill(
    incoming: MappedPatient, prior: MappedPatient | None
) -> PromotePrefill:
    """Merge an incoming event over its freshest prior event for promote.

    The incoming payload is the source of truth for every field it populates,
    because it is the fresher Salesforce snapshot. The prior event only fills
    fields the incoming payload left empty, so a field the modify changed can
    never be clobbered by prefill and there is no protect logic to build.
    ``map_record`` already drops empty and missing values, so a plain merge with
    the incoming values last gives exactly that gap fill. With no prior event the
    incoming record is returned unchanged and nothing is gap filled. See journal
    cnv-909/088, the Payload Contract and Prefill For Missing Fields sections.
    """
    if prior is None:
        return PromotePrefill(mapped=incoming, gap_filled=(), changed=())

    merged_canvas = {**prior.canvas_fields, **incoming.canvas_fields}
    merged_telecom = {**prior.telecom, **incoming.telecom}
    merged_metadata = {**prior.metadata, **incoming.metadata}

    gap_filled = tuple(
        sorted(k for k in prior.canvas_fields if k not in incoming.canvas_fields)
    )
    changed = tuple(
        sorted(
            k
            for k, value in incoming.canvas_fields.items()
            if k in prior.canvas_fields and prior.canvas_fields[k] != value
        )
    )
    return PromotePrefill(
        mapped=MappedPatient(
            canvas_fields=merged_canvas,
            metadata=merged_metadata,
            telecom=merged_telecom,
        ),
        gap_filled=gap_filled,
        changed=changed,
    )


__all__ = (
    "FieldMappingState",
    "MappedPatient",
    "MappingError",
    "PromotePrefill",
    "build_promote_prefill",
    "map_record",
)
