"""Extract a Photon prescription payload from a committed command's ``data``.

Used by the note-footer "Send to Photon" flow to turn a signed Canvas
prescribe/refill/adjust command into the fields the browser submits to Photon.
"""

from __future__ import annotations

from typing import Any

_MEDICATION_NAME_KEYS = ("text", "label", "name", "description", "display")
_DISPENSE_UNIT_KEYS = ("description", "text", "label", "name")


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


def representative_ndc(data: dict[str, Any]) -> str | None:
    """NDC of the dispensed product, used to resolve an RxNorm code."""
    type_to_dispense = data.get("type_to_dispense")
    if isinstance(type_to_dispense, dict):
        for key in ("representative_ndc", "ndc", "code"):
            value = type_to_dispense.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _dispense_unit(data: dict[str, Any]) -> str | None:
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
        "ndc": representative_ndc(data),
        "instructions": (data.get("sig") or "").strip(),
        "dispenseQuantity": float(quantity) if quantity is not None else None,
        "dispenseUnit": _dispense_unit(data),
        "refillsAllowed": int(data.get("refills") or 0),
        "daysSupply": data.get("days_supply"),
        "notes": data.get("note_to_pharmacist") or None,
        # DAW = no substitution allowed.
        "dispenseAsWritten": "not" in substitutions,
    }
