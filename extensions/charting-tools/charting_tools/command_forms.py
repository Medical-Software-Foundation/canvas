"""Pre-fill forms for the commands a template can hold.

``FORM_SPECS`` describes each command's form for the builder: the fields, their
input type, and for searched fields the lookup route (``api/search_api.py``)
that supplies choices. The builder stores what the admin fills in as the
command entry's ``fields`` dict, and ``apply_form`` copies those values onto
the SDK command when the template is used.

Every field is optional: a blank one leaves that part of the command for the
clinician, which is the point of a partially filled command.

Coded choices are stored whole (code and display together), so the builder can
redisplay a saved choice without searching again.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from canvas_sdk.commands import (
    ImagingOrderCommand,
    PrescribeCommand,
    ReferCommand,
)
from canvas_sdk.commands.commands.task import AssigneeType, TaskAssigner
from canvas_sdk.commands.constants import ClinicalQuantity, CodeSystems, Coding, ServiceProvider
from canvas_sdk.v1.data.dme import DmeProduct
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.task import TaskPriority
from logger import log

# Canvas rejects a lab comment over 128 characters.
LAB_COMMENT_LIMIT = 127
# Order DME's free-text item and length of need hold at most this many characters.
DME_TEXT_LIMIT = 255

_ORDER_PRIORITIES = ["Routine", "Urgent", "STAT"]


def _choices(values: list[str]) -> list[dict[str, str]]:
    return [{"value": v, "label": v} for v in values]


# Field types the builder renders: text, textarea, number, checkbox, select,
# search (one coded choice), multisearch (several), lab_partner (select fed by
# the lab-partner route; the test search depends on it), note_type, assignee.
FORM_SPECS: dict[str, list[dict[str, Any]]] = {
    "plan": [
        {"key": "narrative", "label": "Plan", "type": "textarea"},
    ],
    "instruct": [
        {"key": "instruction", "label": "Instruction", "type": "search", "route": "/search/instruction"},
        {"key": "comment", "label": "Comment", "type": "textarea"},
    ],
    "labOrder": [
        # One entry per lab partner, each with that partner's tests. A quickpick
        # can carry several, so one "CMP" works with whichever lab is chosen.
        {"key": "labs", "label": "Lab partner and tests", "type": "lab_variants", "route": "/search/lab-tests"},
        {"key": "fasting_required", "label": "Fasting required", "type": "checkbox"},
        {"key": "comment", "label": "Comment", "type": "text", "max_length": LAB_COMMENT_LIMIT},
    ],
    "imagingOrder": [
        {"key": "image", "label": "Study", "type": "search", "route": "/search/imaging"},
        {"key": "service_provider", "label": "Imaging center", "type": "search", "route": "/search/contact?for=imaging"},
        {"key": "priority", "label": "Priority", "type": "select", "choices": _choices(_ORDER_PRIORITIES)},
        {"key": "additional_details", "label": "Note to radiologist", "type": "textarea"},
        {"key": "comment", "label": "Comment", "type": "textarea"},
    ],
    "orderDme": [
        # A product from the formulary, or free text: {"product": {...}} or {"free_text": "..."}.
        {"key": "item", "label": "Item", "type": "dme_item", "route": "/search/dme-products", "max_length": DME_TEXT_LIMIT},
        {"key": "quantity", "label": "Quantity", "type": "number", "min": 1},
        {"key": "length_of_need", "label": "Length of need", "type": "text", "max_length": DME_TEXT_LIMIT},
        {"key": "service_provider", "label": "Send to", "type": "search", "route": "/search/contact?for=dme"},
    ],
    "refer": [
        {"key": "service_provider", "label": "Refer to", "type": "search", "route": "/search/contact?for=refer"},
        {
            "key": "clinical_question",
            "label": "Clinical question",
            "type": "select",
            "choices": _choices([q.value for q in ReferCommand.ClinicalQuestion]),
        },
        {"key": "priority", "label": "Priority", "type": "select", "choices": _choices(_ORDER_PRIORITIES)},
        {"key": "notes_to_specialist", "label": "Notes to specialist", "type": "textarea"},
        {"key": "include_visit_note", "label": "Include visit note", "type": "checkbox"},
        {"key": "comment", "label": "Comment", "type": "textarea"},
    ],
    "followUp": [
        {"key": "reason_for_visit", "label": "Reason for visit", "type": "text"},
        {"key": "note_type", "label": "Note type", "type": "note_type"},
        {"key": "requested_in_days", "label": "Requested in (days)", "type": "number", "min": 0},
        {"key": "comment", "label": "Comment", "type": "textarea"},
    ],
    "task": [
        {"key": "title", "label": "Title", "type": "text"},
        {"key": "assignee", "label": "Assign to", "type": "assignee"},
        {
            "key": "priority",
            "label": "Priority",
            "type": "select",
            "choices": [{"value": p.value, "label": p.label} for p in TaskPriority],
        },
        {"key": "due_in_days", "label": "Due in (days)", "type": "number", "min": 0},
        {"key": "labels", "label": "Labels (comma-separated)", "type": "text"},
        {"key": "comment", "label": "Comment", "type": "textarea"},
    ],
    "prescribe": [
        {"key": "medication", "label": "Medication", "type": "search", "route": "/search/medication"},
        {"key": "type_to_dispense", "label": "Dispense as", "type": "dispense", "depends_on": "medication"},
        {"key": "sig", "label": "Sig", "type": "textarea"},
        {"key": "days_supply", "label": "Days supply", "type": "number", "min": 0},
        {"key": "quantity_to_dispense", "label": "Quantity", "type": "number", "min": 0, "step": "any"},
        {"key": "refills", "label": "Refills", "type": "number", "min": 0},
        {
            "key": "substitutions",
            "label": "Substitutions",
            "type": "select",
            "choices": [
                {"value": "allowed", "label": "Allowed"},
                {"value": "not_allowed", "label": "Not allowed"},
            ],
        },
        {"key": "pharmacy", "label": "Pharmacy", "type": "search", "route": "/search/pharmacy"},
        {"key": "note_to_pharmacist", "label": "Note to pharmacist", "type": "textarea"},
    ],
}


def has_form(schema_key: str) -> bool:
    """Whether the builder offers a pre-fill form for this command."""
    return schema_key in FORM_SPECS


def clean_fields(schema_key: str, raw: Any, max_lab_partners: int = 20) -> dict[str, Any]:
    """Keep only the declared, non-blank fields of a submitted form."""
    if not isinstance(raw, dict) or schema_key not in FORM_SPECS:
        return {}
    allowed = {spec["key"] for spec in FORM_SPECS[schema_key]}
    cleaned = {
        key: value
        for key, value in raw.items()
        if key in allowed and value not in (None, "", [], {})
    }
    if schema_key == "orderDme" and "item" in cleaned:
        item = _clean_dme_item(cleaned["item"])
        if item:
            cleaned["item"] = item
        else:
            cleaned.pop("item")
    if schema_key == "labOrder":
        labs = lab_variants(raw)
        if max_lab_partners > 1:
            # Several labs (a quickpick): a lab left without tests isn't offered.
            labs = [v for v in labs if v["tests"]]
        labs = labs[:max_lab_partners]
        cleaned.pop("labs", None)
        if labs:
            cleaned["labs"] = labs
    return cleaned


def lab_variants(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """A lab order's partners and their tests, one entry per partner.

    Lab orders saved before partners became a list carry ``lab_partner`` and
    ``tests`` instead; those read as a single entry.
    """
    raw = fields.get("labs")
    if not isinstance(raw, list):
        raw = [{"lab_partner": fields.get("lab_partner"), "tests": fields.get("tests")}]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        partner: dict[str, Any] = item["lab_partner"] if isinstance(item.get("lab_partner"), dict) else {}
        partner_id = _text(partner.get("id"))
        if not partner_id or partner_id in seen:
            continue
        seen.add(partner_id)
        tests = [
            {"code": _text(t.get("code")), "display": _text(t.get("display"))}
            for t in item.get("tests") or []
            if isinstance(t, dict) and _text(t.get("code"))
        ]
        out.append({"lab_partner": {"id": partner_id, "display": _text(partner.get("display"))}, "tests": tests})
    return out


def _text(value: Any) -> str:
    return str(value or "").strip()


def _whole(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _decimal(value: Any) -> Decimal | None:
    # PrescribeCommand.quantity_to_dispense won't coerce a string.
    try:
        return Decimal(str(value).strip())
    except (ArithmeticError, TypeError, ValueError):
        return None


def _in_days(value: Any, today: date) -> date | None:
    days = _whole(value)
    return today + timedelta(days=days) if days is not None and days >= 0 else None


def apply_form(
    command: Any, fields: dict[str, Any], today: date, lab_partner_id: str | None = None
) -> None:
    """Copy a template entry's pre-filled values onto ``command`` in place.

    ``today`` anchors relative dates ("follow up in 90 days"), so a template
    stays correct no matter when it is used. ``lab_partner_id`` picks which of
    a lab order's partners to use; without one, the first is used. A lab
    order with no form still gets ``lab_partner_id`` as its lab.
    """
    if command.Meta.key == "labOrder":
        _lab_order(command, fields or {}, today, lab_partner_id)
        return
    if not fields:
        return
    applier = _APPLIERS.get(command.Meta.key)
    if applier is not None:
        applier(command, fields, today)


def _plan(cmd: Any, f: dict[str, Any], today: date) -> None:
    if _text(f.get("narrative")):
        cmd.narrative = _text(f["narrative"])


def _instruct(cmd: Any, f: dict[str, Any], today: date) -> None:
    instruction = f.get("instruction") or {}
    if isinstance(instruction, dict) and _text(instruction.get("concept_id")):
        cmd.coding = Coding(
            system=CodeSystems.SNOMED,
            code=_text(instruction["concept_id"]),
            display=_text(instruction.get("display")),
        )
    if _text(f.get("comment")):
        cmd.comment = _text(f["comment"])


def _lab_order(cmd: Any, f: dict[str, Any], today: date, lab_partner_id: str | None = None) -> None:
    labs = lab_variants(f)
    chosen = next((v for v in labs if v["lab_partner"]["id"] == lab_partner_id), labs[0] if labs else None)
    if chosen is not None:
        cmd.lab_partner = chosen["lab_partner"]["id"]
        codes = [t["code"] for t in chosen["tests"]]
        if codes:
            cmd.tests_order_codes = codes
    elif lab_partner_id:
        # No lab set up on the form: use the given one (the patient's preferred lab).
        cmd.lab_partner = lab_partner_id
    if f.get("fasting_required"):
        cmd.fasting_required = True
    if _text(f.get("comment")):
        cmd.comment = _text(f["comment"])[:LAB_COMMENT_LIMIT]


def _imaging_order(cmd: Any, f: dict[str, Any], today: date) -> None:
    provider = _service_provider(f.get("service_provider"))
    if provider is not None:
        cmd.service_provider = provider
    image = f.get("image") or {}
    if isinstance(image, dict) and _text(image.get("code")):
        cmd.image_code = _text(image["code"])
    if f.get("priority") in {p.value for p in ImagingOrderCommand.Priority}:
        cmd.priority = ImagingOrderCommand.Priority(f["priority"])
    if _text(f.get("additional_details")):
        cmd.additional_details = _text(f["additional_details"])
    if _text(f.get("comment")):
        cmd.comment = _text(f["comment"])


def _service_provider(contact: Any) -> ServiceProvider | None:
    """A contact picked from the referral directory, as the commands take it."""
    if not isinstance(contact, dict) or not (_text(contact.get("last_name")) or _text(contact.get("practice_name"))):
        return None
    return ServiceProvider(
        first_name=_text(contact.get("first_name")),
        last_name=_text(contact.get("last_name")),
        specialty=_text(contact.get("specialty")),
        practice_name=_text(contact.get("practice_name")),
        business_phone=_text(contact.get("business_phone")),
        business_fax=_text(contact.get("business_fax")),
        business_address=_text(contact.get("business_address")),
    )


def _clean_dme_item(raw: Any) -> dict[str, Any] | None:
    """A DME item kept to one of its two shapes: a formulary product, or free text."""
    if not isinstance(raw, dict):
        return None
    product = raw.get("product")
    if isinstance(product, dict) and _text(product.get("id")):
        return {"product": {k: _text(product.get(k)) for k in ("id", "code", "code_system", "name", "display")}}
    if "free_text" in raw:
        return {"free_text": _text(raw.get("free_text"))[:DME_TEXT_LIMIT]}
    return None


def dme_product_ref(product: Any) -> dict[str, str]:
    """A DME product as the form stores it: id, code, code system, and a display."""
    return {
        "id": str(product.id),
        "code": str(product.code or ""),
        "code_system": str(product.code_system or ""),
        "name": str(product.name or ""),
        "display": f"{product.name} ({product.code})" if product.code else str(product.name or ""),
    }


def _order_dme(cmd: Any, f: dict[str, Any], today: date) -> None:
    raw_item = f.get("item")
    item: dict[str, Any] = raw_item if isinstance(raw_item, dict) else {}
    if not item and _text(f.get("free_text_item")):
        # The flat field saved by version 0.16.1.
        item = {"free_text": f["free_text_item"]}
    raw_product = item.get("product")
    product: dict[str, Any] | None = raw_product if isinstance(raw_product, dict) else None
    if product is not None and _text(product.get("id")):
        # Only an active formulary product: one taken off it since is left out.
        if DmeProduct.objects.filter(id=_text(product["id"]), active=True).exists():
            cmd.dme_product_id = _text(product["id"])
        else:
            log.warning(f"DME product {product.get('code') or product['id']!r} is no longer active")
    elif _text(item.get("free_text")):
        cmd.free_text_item = _text(item["free_text"])[:DME_TEXT_LIMIT]
    quantity = _whole(f.get("quantity"))
    if quantity is not None and quantity >= 1:
        cmd.quantity = quantity
    if _text(f.get("length_of_need")):
        cmd.length_of_need = _text(f["length_of_need"])[:DME_TEXT_LIMIT]
    provider = _service_provider(f.get("service_provider"))
    if provider is not None:
        cmd.service_provider = provider


def _refer(cmd: Any, f: dict[str, Any], today: date) -> None:
    provider = _service_provider(f.get("service_provider"))
    if provider is not None:
        cmd.service_provider = provider
    if f.get("clinical_question") in {q.value for q in ReferCommand.ClinicalQuestion}:
        cmd.clinical_question = ReferCommand.ClinicalQuestion(f["clinical_question"])
    if f.get("priority") in {p.value for p in ReferCommand.Priority}:
        cmd.priority = ReferCommand.Priority(f["priority"])
    if _text(f.get("notes_to_specialist")):
        cmd.notes_to_specialist = _text(f["notes_to_specialist"])
    if f.get("include_visit_note"):
        cmd.include_visit_note = True
    if _text(f.get("comment")):
        cmd.comment = _text(f["comment"])


def _follow_up(cmd: Any, f: dict[str, Any], today: date) -> None:
    if _text(f.get("reason_for_visit")):
        cmd.structured = False
        cmd.reason_for_visit = _text(f["reason_for_visit"])
    note_type = f.get("note_type") or {}
    if isinstance(note_type, dict) and _text(note_type.get("unique_identifier")):
        # Stored by the identifier every version shares; resolved to the
        # current version now so an edited note type still applies.
        current = (
            NoteType.objects.filter(
                unique_identifier=_text(note_type["unique_identifier"]),
                is_active=True,
                deprecated_at__isnull=True,
            )
            .order_by("-dbid")
            .first()
        )
        if current is not None:
            cmd.note_type_id = str(current.id)
        else:
            log.warning(f"Follow-up note type {note_type!r} is no longer active")
    requested = _in_days(f.get("requested_in_days"), today)
    if requested is not None:
        cmd.requested_date = requested
    if _text(f.get("comment")):
        cmd.comment = _text(f["comment"])


def _task(cmd: Any, f: dict[str, Any], today: date) -> None:
    if _text(f.get("title")):
        cmd.title = _text(f["title"])
    assignee = f.get("assignee") or {}
    kind = assignee.get("to") if isinstance(assignee, dict) else None
    if kind == AssigneeType.UNASSIGNED:
        cmd.assign_to = TaskAssigner(to=AssigneeType.UNASSIGNED)
    elif kind in (AssigneeType.STAFF, AssigneeType.TEAM):
        dbid = _whole(assignee.get("id"))
        if dbid is not None:
            cmd.assign_to = TaskAssigner(to=AssigneeType(kind), id=dbid)
    if f.get("priority") in {p.value for p in TaskPriority}:
        cmd.priority = TaskPriority(f["priority"])
    due = _in_days(f.get("due_in_days"), today)
    if due is not None:
        cmd.due_date = due
    labels = [label.strip() for label in _text(f.get("labels")).split(",") if label.strip()]
    if labels:
        cmd.labels = labels
    if _text(f.get("comment")):
        cmd.comment = _text(f["comment"])


def _prescribe(cmd: Any, f: dict[str, Any], today: date) -> None:
    medication = f.get("medication") or {}
    if isinstance(medication, dict) and _text(medication.get("fdb_code")):
        cmd.fdb_code = _text(medication["fdb_code"])
    dispense = f.get("type_to_dispense") or {}
    if (
        isinstance(dispense, dict)
        and _text(dispense.get("representative_ndc"))
        and _text(dispense.get("ncpdp_quantity_qualifier_code"))
    ):
        cmd.type_to_dispense = ClinicalQuantity(
            representative_ndc=_text(dispense["representative_ndc"]),
            ncpdp_quantity_qualifier_code=_text(dispense["ncpdp_quantity_qualifier_code"]),
        )
    if _text(f.get("sig")):
        cmd.sig = _text(f["sig"])
    days_supply = _whole(f.get("days_supply"))
    if days_supply is not None:
        cmd.days_supply = days_supply
    refills = _whole(f.get("refills"))
    if refills is not None:
        cmd.refills = refills
    quantity = _decimal(f.get("quantity_to_dispense")) if f.get("quantity_to_dispense") not in (None, "") else None
    if quantity is not None:
        cmd.quantity_to_dispense = quantity
    if f.get("substitutions") in {s.value for s in PrescribeCommand.Substitutions}:
        cmd.substitutions = PrescribeCommand.Substitutions(f["substitutions"])
    pharmacy = f.get("pharmacy") or {}
    # Left unset unless chosen, so the patient's preferred pharmacy stands.
    if isinstance(pharmacy, dict) and _text(pharmacy.get("ncpdp_id")):
        cmd.pharmacy = _text(pharmacy["ncpdp_id"])
    if _text(f.get("note_to_pharmacist")):
        cmd.note_to_pharmacist = _text(f["note_to_pharmacist"])


# Lab orders are applied by apply_form directly, since they take the chosen partner.
_APPLIERS = {
    "plan": _plan,
    "instruct": _instruct,
    "imagingOrder": _imaging_order,
    "orderDme": _order_dme,
    "refer": _refer,
    "followUp": _follow_up,
    "task": _task,
    "prescribe": _prescribe,
}
