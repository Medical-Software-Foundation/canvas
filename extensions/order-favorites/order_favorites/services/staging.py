"""Turn chosen favorites into staged prescribe, lab order, and imaging order commands in one note.

Who is named on the order:
  - Prescriptions: no prescriber is sent, so Canvas applies its own rule, as in its Prescribe command:
    the person adding when their role is in the practice's prescriber roles, otherwise blank for the
    prescriber to fill in before signing.
  - Lab and imaging orders: a personal favorite's saved ordering provider if still active with a
    usable NPI, otherwise the note's provider on the same terms, otherwise the person adding.
Any of them can be changed in the command before it is signed.

A lab favorite whose partner is inactive or whose tests the lab no longer offers is skipped whole,
never added as a partial order. An imaging favorite is skipped whole when Canvas's imaging search no
longer leads from its code to its study, since Canvas would then leave the Image field blank or fill
in another study, and also when that search doesn't answer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from canvas_sdk.commands import ImagingOrderCommand, LabOrderCommand, PrescribeCommand
from canvas_sdk.commands.constants import ClinicalQuantity, ServiceProvider
from canvas_sdk.effects import Effect
from canvas_sdk.v1.data import Note

from order_favorites.models import Favorite
from order_favorites.services.catalog import check_tests, usable_provider
from order_favorites.services.lookups import LookupFailed, check_image

PRIORITIES = {
    "Routine": ImagingOrderCommand.Priority.ROUTINE,
    "Urgent": ImagingOrderCommand.Priority.URGENT,
    "STAT": ImagingOrderCommand.Priority.STAT,
}


def _note_provider_id(note: Note) -> str | None:
    provider = usable_provider(str(note.provider.id)) if note.provider is not None else None
    return str(provider.id) if provider is not None else None


def ordering_provider_for(favorite: Favorite, note: Note, adder_id: str) -> str:
    # Only personal favorites save an ordering provider; one left on an older practice favorite is ignored.
    saved = None if favorite.shared else usable_provider(favorite.details.get("ordering_provider_id") or None)
    if saved is not None:
        return str(saved.id)
    return _note_provider_id(note) or adder_id


def _rx_effect(favorite: Favorite, note: Note) -> Effect:
    """Fields left blank on the favorite stay blank in the command, for the prescriber to fill in."""
    d = favorite.details
    unit = (
        ClinicalQuantity(representative_ndc=d["representative_ndc"], ncpdp_quantity_qualifier_code=d["ncpdp_quantity_qualifier_code"])
        if d.get("representative_ndc") and d.get("ncpdp_quantity_qualifier_code")
        else None
    )
    return PrescribeCommand(
        note_uuid=str(note.id),
        fdb_code=d["fdb_code"],
        sig=d.get("sig") or "",
        days_supply=int(d["days_supply"]) if d.get("days_supply") not in (None, "") else None,
        quantity_to_dispense=Decimal(str(d["quantity"])) if d.get("quantity") not in (None, "") else None,
        type_to_dispense=unit,
        refills=int(d["refills"]) if d.get("refills") not in (None, "") else None,
        pharmacy=d.get("pharmacy_ncpdp_id") or None,
    ).originate()


def _imaging_effect(favorite: Favorite, note: Note, adder_id: str) -> Effect:
    """Fields left blank on the favorite are left out of the command, for whoever signs to fill in.
    ImagingOrderCommand can't send an explicit service_provider=None, so it is only passed when set."""
    d = favorite.details
    optional: dict[str, Any] = {}
    if d.get("priority") in PRIORITIES:
        optional["priority"] = PRIORITIES[d["priority"]]
    if d.get("additional_details"):
        optional["additional_details"] = d["additional_details"]
    if d.get("comment"):
        optional["comment"] = d["comment"]
    if d.get("imaging_center"):
        optional["service_provider"] = ServiceProvider(**d["imaging_center"])
    return ImagingOrderCommand(
        note_uuid=str(note.id),
        image_code=d["image_code"],
        diagnosis_codes=[dx["code"] for dx in d.get("diagnoses", [])],
        ordering_provider_key=ordering_provider_for(favorite, note, adder_id),
        **optional,
    ).originate()


def _imaging_skip(favorite: Favorite) -> str | None:
    """Why an imaging favorite can't be added, or None when it can."""
    d = favorite.details
    try:
        study = check_image(d.get("image_code") or "", d.get("image_code_system") or "")
    except LookupFailed:
        return "image_check"
    return None if study is not None else "image"


def stage(favorites: list[Favorite], note: Note, adder_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Effect]]:
    """Returns (added, skipped, effects). skipped entries carry a reason the panel can explain."""
    added: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    effects: list[Effect] = []
    for favorite in favorites:
        entry = {"id": favorite.dbid, "name": favorite.name, "kind": favorite.kind, "shared": favorite.shared}
        if favorite.kind == "rx":
            effects.append(_rx_effect(favorite, note))
            added.append(entry)
            continue
        if favorite.kind == "imaging":
            reason = _imaging_skip(favorite)
            if reason is not None:
                skipped.append({**entry, "reason": reason, "image": favorite.details.get("image_name", "")})
                continue
            effects.append(_imaging_effect(favorite, note, adder_id))
            added.append(entry)
            continue

        # What's left is a lab favorite: expand_sets passes only order kinds.
        d = favorite.details
        codes = [t["code"] for t in d.get("tests", [])]
        check = check_tests(d.get("lab_partner_id", ""), codes)
        if not check["partner_found"] or not check["partner_active"]:
            skipped.append({**entry, "reason": "partner", "lab": d.get("lab_partner_name", "")})
            continue
        if check["stale"] or not codes:
            names = {t["code"]: t.get("name") or t["code"] for t in d.get("tests", [])}
            skipped.append({**entry, "reason": "stale", "lab": check["partner_name"], "stale": [names[c] for c in check["stale"]]})
            continue
        effects.append(
            LabOrderCommand(
                note_uuid=str(note.id),
                lab_partner=d["lab_partner_id"],
                tests_order_codes=codes,
                ordering_provider_key=ordering_provider_for(favorite, note, adder_id),
                diagnosis_codes=[dx["code"] for dx in d.get("diagnoses", [])],
                fasting_required=bool(d.get("fasting")),
                comment=d.get("comment") or None,
            ).originate()
        )
        added.append(entry)
    return added, skipped, effects
