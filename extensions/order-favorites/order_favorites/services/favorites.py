"""Saving, checking, and listing favorites.

clean_favorite turns a request body into (kind, name, details) or an error message. It runs before
every save, from the chart panel, the admin app, and import, so all three accept exactly the same
orders. Lab tests are checked against the live catalog on save; a lab favorite that later goes
stale is flagged in lists and skipped when someone tries to add it.

An order set (kind "set") is a named list of prescription and lab favorites that are added together.
It points to the favorites rather than copying them, so editing a favorite changes it in every set,
and a deleted favorite simply drops out. A practice set may only include practice favorites; a
personal set may include its owner's own favorites and practice favorites.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Q

from order_favorites.models import Favorite, HiddenFavorite
from canvas_sdk.v1.data import LabPartner, LabPartnerTest

from order_favorites.services.catalog import parse_uuid, check_tests, provider_dict, usable_provider
from order_favorites.services.lookups import ICD10_CODE, icd10_display, normalize_icd10

MAX_NAME = 120
MAX_SIG = 1000
MAX_COMMENT = 500
MAX_TESTS = 50
MAX_DIAGNOSES = 12
MAX_SET_ITEMS = 30
ORDER_KINDS = ("rx", "lab")


class Invalid(ValueError):
    """A favorite that can't be saved, with a message the user can act on."""


def _text(body: dict[str, Any], key: str, limit: int, label: str, required: bool = True) -> str:
    value = str(body.get(key) or "").strip()
    if required and not value:
        raise Invalid(f"{label} is required.")
    if len(value) > limit:
        raise Invalid(f"{label} can be at most {limit} characters.")
    return value


def _blank(body: dict[str, Any], key: str) -> bool:
    return str(body.get(key) if body.get(key) is not None else "").strip() == ""


def _whole(body: dict[str, Any], key: str, label: str, low: int, high: int) -> int:
    try:
        value = int(str(body.get(key)).strip())
    except (TypeError, ValueError):
        raise Invalid(f"{label} must be a whole number.") from None
    if not low <= value <= high:
        raise Invalid(f"{label} must be between {low} and {high}.")
    return value


def _quantity(body: dict[str, Any]) -> str:
    try:
        quantity = Decimal(str(body.get("quantity")).strip())
    except (ArithmeticError, ValueError):  # decimal.InvalidOperation is an ArithmeticError; the sandbox blocks importing it
        raise Invalid("Quantity must be a number.") from None
    if not (Decimal("0") < quantity <= Decimal("99999")):
        raise Invalid("Quantity must be more than 0.")
    return format(quantity.normalize(), "f")


def _rx_details(body: dict[str, Any]) -> dict[str, Any]:
    """Only the medication is required. Sig, supply, quantity, unit, and refills may be left blank;
    the prescribe command asks for whatever is missing before it can be signed."""
    fdb_code = _text(body, "fdb_code", 20, "Medication")
    if not fdb_code.isdigit():
        raise Invalid("Pick the medication from the search list.")
    ndc = _text(body, "representative_ndc", 20, "Unit", required=False)
    qualifier = _text(body, "ncpdp_quantity_qualifier_code", 10, "Unit", required=False)
    if bool(ndc) != bool(qualifier):
        raise Invalid("Pick the unit from the list.")
    pharmacy_id = str(body.get("pharmacy_ncpdp_id") or "").strip()
    return {
        "fdb_code": fdb_code,
        "medication": _text(body, "medication", 300, "Medication"),
        "sig": _text(body, "sig", MAX_SIG, "Sig", required=False),
        "days_supply": None if _blank(body, "days_supply") else _whole(body, "days_supply", "Days supply", 1, 365),
        "quantity": None if _blank(body, "quantity") else _quantity(body),
        "unit": _text(body, "unit", 100, "Unit", required=False) if ndc else "",
        "representative_ndc": ndc,
        "ncpdp_quantity_qualifier_code": qualifier,
        "refills": None if _blank(body, "refills") else _whole(body, "refills", "Refills", 0, 99),
        "pharmacy_ncpdp_id": pharmacy_id,
        "pharmacy_name": _text(body, "pharmacy_name", 200, "Pharmacy", required=False) if pharmacy_id else "",
    }


def _lab_details(body: dict[str, Any]) -> dict[str, Any]:
    partner_id = _text(body, "lab_partner_id", 64, "Lab partner")
    codes: list[str] = []
    for test in body.get("tests") or []:
        code = str((test or {}).get("code") or "").strip() if isinstance(test, dict) else ""
        if code and code not in codes:
            codes.append(code)
    if not codes:
        raise Invalid("Add at least one test.")
    if len(codes) > MAX_TESTS:
        raise Invalid(f"A lab favorite can have at most {MAX_TESTS} tests.")
    check = check_tests(partner_id, codes)
    if not check["partner_found"] or not check["partner_active"]:
        raise Invalid("Pick an active lab partner.")
    if check["stale"]:
        raise Invalid(f"{check['partner_name']} doesn't offer {', '.join(check['stale'])}. Remove it and add its replacement.")
    names = {t["code"]: str(t.get("name") or "") for t in body.get("tests") or [] if isinstance(t, dict)}

    diagnoses: list[dict[str, str]] = []
    for dx in body.get("diagnoses") or []:
        code = normalize_icd10(str((dx or {}).get("code") or "")) if isinstance(dx, dict) else ""
        if not ICD10_CODE.match(code):
            raise Invalid(f"{icd10_display(code) or 'A diagnosis'} isn't an ICD-10 code. Pick diagnoses from the search list.")
        if code not in {d["code"] for d in diagnoses}:
            diagnoses.append({"code": code, "text": str(dx.get("text") or "")[:300]})
    if len(diagnoses) > MAX_DIAGNOSES:
        raise Invalid(f"A lab favorite can have at most {MAX_DIAGNOSES} diagnoses.")

    provider_id = str(body.get("ordering_provider_id") or "").strip()
    provider_name = ""
    if provider_id:
        provider = usable_provider(provider_id)
        if provider is None:
            raise Invalid("The ordering provider must be active staff with an NPI.")
        provider_name = provider_dict(provider)["name"]

    return {
        "lab_partner_id": partner_id,
        "lab_partner_name": check["partner_name"],
        "tests": [{"code": code, "name": names.get(code, "")} for code in codes],
        "diagnoses": diagnoses,
        "ordering_provider_id": provider_id,
        "ordering_provider_name": provider_name,
        "comment": _text(body, "comment", MAX_COMMENT, "Comment", required=False),
        "fasting": bool(body.get("fasting")),
    }


def _set_details(body: dict[str, Any], owner: int | None, shared: bool) -> dict[str, Any]:
    ids: list[int] = []
    for value in body.get("items") or []:
        try:
            dbid = int(str(value))
        except (TypeError, ValueError):
            raise Invalid("Pick favorites from the list.") from None
        if dbid not in ids:
            ids.append(dbid)
    if not ids:
        raise Invalid("Pick at least one favorite for the set.")
    if len(ids) > MAX_SET_ITEMS:
        raise Invalid(f"An order set can have at most {MAX_SET_ITEMS} favorites.")
    allowed = Q(shared=True) if shared else Q(shared=True) | Q(shared=False, owner_id=owner)
    found = set(Favorite.objects.filter(allowed, dbid__in=ids, kind__in=ORDER_KINDS).values_list("dbid", flat=True))
    if len(found) != len(ids):
        raise Invalid(
            "A practice order set can only include practice favorites." if shared else "Pick favorites from the list."
        )
    return {"items": ids}


def clean_favorite(
    body: dict[str, Any], kind: str | None = None, *, owner: int | None = None, shared: bool = False
) -> tuple[str, str, dict[str, Any]]:
    """(kind, name, details) from a request body. Raises Invalid with a message for the user.

    owner and shared say whose set it will be, which decides what an order set may include.
    """
    kind = kind or str(body.get("kind") or "")
    if kind not in ("rx", "lab", "set"):
        raise Invalid("Choose prescription, lab, or order set.")
    name = _text(body, "name", MAX_NAME, "Name")
    if kind == "set":
        return kind, name, _set_details(body, owner, shared)
    details = _rx_details(body) if kind == "rx" else _lab_details(body)
    return kind, name, details


def expand_sets(chosen: list[Favorite], usable: dict[int, Favorite]) -> list[Favorite]:
    """The orders to add: each order set replaced by its favorites, in order, each favorite once.

    usable holds the favorites the person may add (visible to them, of an enabled order type); set
    members outside it, such as a deleted favorite or a turned-off order type, are left out.
    """
    orders: list[Favorite] = []
    seen: set[int] = set()
    for favorite in chosen:
        members = [usable.get(i) for i in favorite.details.get("items", [])] if favorite.kind == "set" else [favorite]
        for member in members:
            if member is not None and member.kind in ORDER_KINDS and member.dbid not in seen:
                seen.add(member.dbid)
                orders.append(member)
    return orders


def stale_map(favorites: list[Favorite]) -> dict[int, list[str]]:
    """For each lab favorite, the test codes the lab no longer offers (all of them if the partner is
    gone or inactive). Two queries for the whole list."""
    labs = [f for f in favorites if f.kind == "lab"]
    if not labs:
        return {}
    partner_ids = {str(f.details.get("lab_partner_id", "")) for f in labs}
    valid_ids = [p for p in partner_ids if parse_uuid(p) is not None]
    active = {str(pid) for pid in LabPartner.objects.filter(id__in=valid_ids, active=True).values_list("id", flat=True)}
    codes = {t["code"] for f in labs for t in f.details.get("tests", [])}
    offered = {
        (str(pid), code)
        for pid, code in LabPartnerTest.objects.filter(lab_partner__id__in=list(active), order_code__in=codes).values_list(
            "lab_partner__id", "order_code"
        )
    }
    result: dict[int, list[str]] = {}
    for favorite in labs:
        pid = str(favorite.details.get("lab_partner_id", ""))
        tests = [t["code"] for t in favorite.details.get("tests", [])]
        result[favorite.dbid] = tests if pid not in active else [c for c in tests if (pid, c) not in offered]
    return result


def favorite_json(favorite: Favorite, me: int | None, hidden: set[int] | None = None, stale: list[str] | None = None) -> dict[str, Any]:
    owner = favorite.owner
    return {
        "id": favorite.dbid,
        "kind": favorite.kind,
        "name": favorite.name,
        "shared": favorite.shared,
        "mine": not favorite.shared and favorite.owner_id == me,
        "owner": f"{owner.first_name or ''} {owner.last_name or ''}".strip() if owner else "",
        "hidden": favorite.dbid in (hidden or set()),
        "stale": stale or [],
        **favorite.details,
    }


def visible_to(me: int | None, kinds: list[str]) -> Any:
    """Practice favorites plus this person's own personal favorites, of the enabled kinds."""
    mine = Q(shared=False, owner_id=me) if me is not None else Q(pk__in=[])
    return Favorite.objects.select_related("owner").filter(Q(shared=True) | mine, kind__in=kinds).order_by("name", "dbid")


def hidden_ids(me: int | None) -> set[int]:
    if me is None:
        return set()
    return set(HiddenFavorite.objects.filter(staff_id=me).values_list("favorite_id", flat=True))
