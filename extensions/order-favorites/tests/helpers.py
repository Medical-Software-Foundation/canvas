from __future__ import annotations

import json
from typing import Any

from canvas_generated.messages.effects_pb2 import EffectType

from order_favorites.models import Favorite

RX_DETAILS = {
    "fdb_code": "123456",
    "medication": "amoxicillin 500 mg capsule",
    "sig": "Take 1 capsule by mouth three times daily",
    "days_supply": 10,
    "quantity": "30",
    "unit": "capsule",
    "representative_ndc": "00093310905",
    "ncpdp_quantity_qualifier_code": "C48480",
    "refills": 0,
    "pharmacy_ncpdp_id": "",
    "pharmacy_name": "",
}


def rx_body(**kw: Any) -> dict[str, Any]:
    return {"kind": "rx", "name": "Amoxicillin 500 mg · 10 day", **RX_DETAILS, **kw}


def lab_details(partner: Any, codes: list[str], **kw: Any) -> dict[str, Any]:
    return {
        "lab_partner_id": str(partner.id),
        "lab_partner_name": partner.name,
        "tests": [{"code": c, "name": c} for c in codes],
        "diagnoses": [],
        "ordering_provider_id": "",
        "ordering_provider_name": "",
        "comment": "",
        "fasting": False,
        **kw,
    }


def favorite(owner: Any, kind: str = "rx", shared: bool = False, name: str = "Fav", details: dict[str, Any] | None = None) -> Favorite:
    return Favorite.objects.create(kind=kind, name=name, shared=shared, owner_id=owner.dbid, details=details if details is not None else dict(RX_DETAILS))


def effects_of(results: list[Any], name: str) -> list[dict[str, Any]]:
    return [json.loads(r.payload)["data"] for r in results if hasattr(r, "type") and EffectType.Name(r.type) == name]
