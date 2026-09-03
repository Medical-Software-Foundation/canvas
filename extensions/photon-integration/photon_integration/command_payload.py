"""Extract a Photon prescription payload from a committed command's ``data``.

Used by the note-footer "Send to Photon" flow to turn a signed Canvas
prescribe/refill/adjust command into the fields the browser submits to Photon.
"""

from __future__ import annotations

from typing import Any

_MEDICATION_NAME_KEYS = ("text", "label", "name", "description", "display")
_DISPENSE_UNIT_KEYS = ("description", "text", "label", "name")

# Photon's dispense units that are valid for a *prescription* (dosage forms).
# Note: Photon's full `dispenseUnits` query also returns packaging units
# (Vial, Syringe, Pen, Drop, Spray, ...) that createPrescription rejects, so
# they are intentionally excluded — a "0.5 mL vial" maps to its dose unit
# (Milliliter), not "Vial".
PHOTON_DISPENSE_UNITS = (
    "Applicator", "Blister", "Caplet", "Capsule", "Each", "Film", "Gram", "Gum",
    "Implant", "Insert", "Kit", "Lancet", "Lozenge", "Milliliter", "Packet",
    "Pad", "Patch", "Pen Needle", "Ring", "Sponge", "Stick", "Strip",
    "Suppository", "Swab", "Tablet", "Troche", "Unspecified", "Wafer",
)
# Whole-text synonyms ONLY. We deliberately do not pull a unit word out of a
# compound description: "0.75 mL syringe" must NOT become "Milliliter" (that
# changes 4 syringes into 4 mL). Such compound/packaging units are rejected so
# the provider sends them via the Elements modal instead.
_UNIT_SYNONYMS = {
    "ml": "Milliliter", "milliliter": "Milliliter", "milliliters": "Milliliter",
    "g": "Gram", "gm": "Gram", "gram": "Gram", "grams": "Gram",
    "ea": "Each", "cap": "Capsule", "caps": "Capsule", "tab": "Tablet",
    "tabs": "Tablet",
}


def resolve_dispense_unit(text: str | None) -> str | None:
    """Resolve Canvas free-text unit to a valid Photon unit, or None if unmappable.

    STRICT, for clinical safety: only an exact whole-text match to a Photon unit
    (or a whole-text synonym like "mL") maps. Anything compound — "0.75 mL
    syringe", "0.5 mL vial" — returns None so it is blocked at commit and not
    auto-sent with the wrong quantity semantics.
    """
    if not text:
        return None
    normalized = text.strip().lower()
    for unit in PHOTON_DISPENSE_UNITS:
        if unit.lower() == normalized:
            return unit
    return _UNIT_SYNONYMS.get(normalized)


def medication_term(data: dict[str, Any]) -> str | None:
    """Best-effort medication name from the command data."""
    # Adjust Prescription carries the new drug in change_medication_to.
    for source_key in ("change_medication_to", "prescribe"):
        source = data.get(source_key)
        if isinstance(source, str) and source.strip():
            return source.strip()
        if isinstance(source, dict):
            for key in _MEDICATION_NAME_KEYS:
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def fdb_code(data: dict[str, Any]) -> str | None:
    """FDB code (med_medication_id) of the selected medication.

    In committed command data the medication lives in ``prescribe`` (or
    ``change_medication_to`` for Adjust Prescription) as ``{text, value}`` where
    ``value`` is the FDB code. That code resolves to an RxNorm rxcui via Canvas's
    Ontologies service.
    """
    for source_key in ("change_medication_to", "prescribe"):
        source = data.get(source_key)
        if isinstance(source, dict):
            value = source.get("value")
            if value not in (None, ""):
                return str(value)
    return None


def representative_ndc(data: dict[str, Any]) -> str | None:
    """NDC of the dispensed product, used to resolve an RxNorm code."""
    type_to_dispense = data.get("type_to_dispense")
    if isinstance(type_to_dispense, dict):
        for key in ("representative_ndc", "ndc", "code"):
            value = type_to_dispense.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def dispense_unit_text(data: dict[str, Any]) -> str | None:
    type_to_dispense = data.get("type_to_dispense")
    if isinstance(type_to_dispense, str) and type_to_dispense.strip():
        return type_to_dispense.strip()
    if isinstance(type_to_dispense, dict):
        for key in _DISPENSE_UNIT_KEYS:
            value = type_to_dispense.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def extract_rx(data: dict[str, Any]) -> dict[str, Any]:
    """Build the (treatment-less) prescription fields from command ``data``.

    ``treatmentId`` and ``patientId`` are added by the caller after resolving
    them against Photon. Returns ``term`` (medication name) for catalog lookup.
    """
    quantity = data.get("quantity_to_dispense")
    substitutions = str(data.get("substitutions") or "").lower()
    return {
        "term": medication_term(data),
        "fdbCode": fdb_code(data),
        "ndc": representative_ndc(data),
        "instructions": (data.get("sig") or "").strip(),
        "dispenseQuantity": float(quantity) if quantity is not None else None,
        # None when the unit can't be safely represented in Photon's vocabulary;
        # the caller treats that as "can't send".
        "dispenseUnit": resolve_dispense_unit(dispense_unit_text(data)),
        "refillsAllowed": int(data.get("refills") or 0),
        "daysSupply": data.get("days_supply"),
        "notes": data.get("note_to_pharmacist") or None,
        # DAW = no substitution allowed.
        "dispenseAsWritten": "not" in substitutions,
    }
