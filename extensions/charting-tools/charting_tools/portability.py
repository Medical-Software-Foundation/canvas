"""Moving configured items between Canvas environments.

The export holds every template, quickpick, order set, and rule as it is
stored, including the expanded diagnosis lists, so an upload doesn't need UMLS
to re-expand picks it already has.

Most references are stable across environments: questionnaires by code, ICD-10
codes, and instruction, imaging, medication, pharmacy, and referral codings.
Some are ids that differ per environment, so the upload matches them on
arrival, keeping the id when the target has it and otherwise matching by name:

- note types (template note types, Follow-up note types, rule note-type conditions)
- lab partners (lab orders), whose tests must exist at the matched lab
- task assignees (staff and teams)

Anything that can't be matched is reported. An item with an unmatched note type
or lab, or a lab test the matched lab doesn't offer, is not uploaded; a task
assignee that can't be matched is left unset, with a warning.
"""

from json import dumps, loads
from typing import Any

from canvas_sdk.v1.data.dme import DmeProduct
from canvas_sdk.v1.data.lab import LabPartner, LabPartnerTest
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.team import Team

from charting_tools.command_forms import dme_product_ref, lab_variants
from charting_tools.kinds import KINDS, RULE, kind_of
from charting_tools.note_types import note_type_options

EXPORT_FORMAT = "charting_tools.export"
EXPORT_VERSION = 1

# The fields an export carries per item.
EXPORT_FIELDS = (
    "template_id",
    "name",
    "kind",
    "active",
    "show_in_menu",
    "show_in_panel",
    "note_types",
    "diagnosis_sources",
    "diagnosis_match_codes",
    "tags",
    "rule",
    "commands",
)

TEAM_PREFIX = "Team: "


def export_item(row: Any) -> dict[str, Any]:
    """One stored item, as the export carries it."""
    return {
        "template_id": row.template_id,
        "name": row.name,
        "kind": kind_of(row),
        "active": bool(row.active),
        "show_in_menu": row.show_in_menu is not False,
        "show_in_panel": bool(row.show_in_panel),
        "note_types": row.note_types or [],
        "diagnosis_sources": row.diagnosis_sources or [],
        "diagnosis_match_codes": row.diagnosis_match_codes or [],
        "tags": row.tags or [],
        "rule": row.rule if kind_of(row) == RULE else None,
        "commands": row.commands or [],
    }


def export_document(rows: Any, exported_at: str) -> dict[str, Any]:
    """The whole export: a header and every item, in name order."""
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": exported_at,
        "items": [export_item(row) for row in rows],
    }


def read_document(raw: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """The items in an uploaded export, or why it can't be read."""
    if not isinstance(raw, dict) or raw.get("format") != EXPORT_FORMAT:
        return None, "This isn't a Charting Admin export file"
    if raw.get("version") != EXPORT_VERSION:
        return None, f"This export is version {raw.get('version')!r}; this plugin reads version {EXPORT_VERSION}"
    items = raw.get("items")
    if not isinstance(items, list):
        return None, "The export has no items"
    bad = [i for i, item in enumerate(items, start=1) if not isinstance(item, dict) or item.get("kind") not in KINDS]
    if bad:
        return None, f"Item {bad[0]} isn't a template, quickpick, order set, or rule"
    return items, None


class Resolver:
    """Matches an export's environment-specific references to this environment."""

    def __init__(self) -> None:
        self._note_types: dict[str, str] | None = None
        self._labs: dict[str, str] | None = None
        self._tests: dict[str, set[str]] = {}
        self._assignees: dict[str, dict[str, Any]] | None = None
        self._dme: dict[str, dict[str, str] | None] = {}

    # Note types: kept by unique identifier, else matched by name.
    def note_type(self, ref: Any) -> dict[str, str] | None:
        if not isinstance(ref, dict):
            return None
        if self._note_types is None:
            self._note_types = {o["unique_identifier"]: o["name"] for o in note_type_options()}
        uid = str(ref.get("unique_identifier") or "")
        if uid in self._note_types:
            return {"unique_identifier": uid, "name": self._note_types[uid]}
        wanted = str(ref.get("name") or "").strip().casefold()
        for option_uid, name in self._note_types.items():
            if wanted and name.strip().casefold() == wanted:
                return {"unique_identifier": option_uid, "name": name}
        return None

    # Lab partners: kept by id, else matched by name.
    def lab_partner(self, ref: Any) -> dict[str, str] | None:
        if not isinstance(ref, dict):
            return None
        if self._labs is None:
            self._labs = {str(i): str(n) for i, n in LabPartner.objects.filter(active=True).values_list("id", "name")}
        partner_id = str(ref.get("id") or "")
        if partner_id in self._labs:
            return {"id": partner_id, "display": self._labs[partner_id]}
        wanted = str(ref.get("display") or "").strip().casefold()
        for option_id, name in self._labs.items():
            if wanted and name.strip().casefold() == wanted:
                return {"id": option_id, "display": name}
        return None

    def missing_tests(self, partner_id: str, codes: list[str]) -> list[str]:
        if partner_id not in self._tests:
            self._tests[partner_id] = set(
                LabPartnerTest.objects.filter(lab_partner__id=partner_id).values_list("order_code", flat=True)
            )
        return [code for code in codes if code not in self._tests[partner_id]]

    # DME products: kept by id, else matched by code system and code.
    def dme_product(self, ref: Any) -> dict[str, str] | None:
        if not isinstance(ref, dict):
            return None
        # Remembered per reference, since an upload repeats the same products.
        key = f"{ref.get('id')}|{ref.get('code_system')}|{ref.get('code')}"
        if key not in self._dme:
            active = DmeProduct.objects.filter(active=True)
            product = active.filter(id=str(ref.get("id") or "")).first() if _is_uuid(ref.get("id")) else None
            if product is None and ref.get("code"):
                product = active.filter(code=str(ref["code"]), code_system=str(ref.get("code_system") or "")).first()
            self._dme[key] = dme_product_ref(product) if product is not None else None
        return self._dme[key]

    # Task assignees: kept by id when the name agrees, else matched by name.
    def assignee(self, ref: Any) -> dict[str, Any] | None:
        if not isinstance(ref, dict) or ref.get("to") not in ("staff", "team"):
            return ref if isinstance(ref, dict) else None
        if self._assignees is None:
            self._assignees = {}
            for dbid, first, last in Staff.objects.filter(active=True).values_list("dbid", "first_name", "last_name"):
                self._assignees[f"staff:{dbid}"] = {"to": "staff", "id": dbid, "display": f"{first} {last}".strip()}
            for dbid, name in Team.objects.values_list("dbid", "name"):
                self._assignees[f"team:{dbid}"] = {"to": "team", "id": dbid, "display": f"{TEAM_PREFIX}{name}"}
        wanted = _bare(ref.get("display"))
        same = self._assignees.get(f"{ref['to']}:{ref.get('id')}")
        if same is not None and _bare(same["display"]) == wanted:
            return same
        for option in self._assignees.values():
            if option["to"] == ref["to"] and wanted and _bare(option["display"]) == wanted:
                return option
        return None


def _is_uuid(value: Any) -> bool:
    text = str(value or "").replace("-", "")
    return len(text) == 32 and all(c in "0123456789abcdefABCDEF" for c in text)


def _bare(display: Any) -> str:
    text = str(display or "").strip()
    if text.startswith(TEAM_PREFIX):
        text = text[len(TEAM_PREFIX):]
    return text.casefold()


def remap_item(item: dict[str, Any], resolver: Resolver) -> tuple[dict[str, Any], list[str], list[str]]:
    """The item with its references matched here, plus (problems, warnings).

    Problems stop the item from being uploaded; warnings don't.
    """
    # A copy to change (the sandbox has no copy module; the item is JSON anyway).
    body: dict[str, Any] = loads(dumps(item))
    problems: list[str] = []
    warnings: list[str] = []

    note_types = []
    for ref in body.get("note_types") or []:
        matched = resolver.note_type(ref)
        if matched is None:
            problems.append(f"Note type {_label(ref, 'name')!r} doesn't exist here")
        else:
            note_types.append(matched)
    body["note_types"] = note_types

    body["commands"] = _remap_commands(body.get("commands") or [], resolver, problems, warnings, "")
    rule = body.get("rule")
    if isinstance(rule, dict):
        for condition in rule.get("conditions") or []:
            if condition.get("type") == "note_type":
                kept = []
                for ref in condition.get("note_types") or []:
                    matched = resolver.note_type(ref)
                    if matched is None:
                        problems.append(f"Condition note type {_label(ref, 'name')!r} doesn't exist here")
                    else:
                        kept.append(matched)
                condition["note_types"] = kept
        for index, action in enumerate(rule.get("actions") or [], start=1):
            where = f"Action {index}: "
            if action.get("commands"):
                action["commands"] = _remap_commands(action["commands"], resolver, problems, warnings, where)
            schema_key = ((action.get("target") or {}).get("schema_key")) or ""
            if action.get("fields"):
                action["fields"] = _remap_fields(schema_key, action["fields"], resolver, problems, warnings, where)
    return body, problems, warnings


def _remap_commands(
    commands: list[Any], resolver: Resolver, problems: list[str], warnings: list[str], where: str
) -> list[Any]:
    out = []
    for index, command in enumerate(commands, start=1):
        if isinstance(command, dict) and command.get("fields"):
            command = {
                **command,
                "fields": _remap_fields(
                    command.get("schema_key", ""), command["fields"], resolver, problems, warnings,
                    f"{where}Command {index}: ",
                ),
            }
        out.append(command)
    return out


def _remap_fields(
    schema_key: str, fields: Any, resolver: Resolver, problems: list[str], warnings: list[str], where: str
) -> Any:
    if not isinstance(fields, dict):
        return fields
    fields = dict(fields)
    if schema_key == "labOrder":
        labs = []
        for variant in lab_variants(fields):
            partner = resolver.lab_partner(variant["lab_partner"])
            if partner is None:
                problems.append(f"{where}lab {variant['lab_partner'].get('display') or '?'!r} doesn't exist here")
                continue
            codes = [t["code"] for t in variant["tests"]]
            missing = resolver.missing_tests(partner["id"], codes)
            if missing:
                problems.append(f"{where}{partner['display']} doesn't offer test(s) {', '.join(missing)}")
                continue
            labs.append({"lab_partner": partner, "tests": variant["tests"]})
        fields.pop("lab_partner", None)
        fields.pop("tests", None)
        fields["labs"] = labs
    if schema_key == "orderDme" and isinstance(fields.get("item"), dict) and fields["item"].get("product"):
        ref = fields["item"]["product"]
        matched = resolver.dme_product(ref)
        if matched is None:
            label = ref.get("display") or ref.get("code") or "?"
            problems.append(f"{where}DME product {label!r} isn't on this formulary")
        else:
            fields["item"] = {"product": matched}
    if schema_key == "followUp" and fields.get("note_type"):
        matched = resolver.note_type(fields["note_type"])
        if matched is None:
            problems.append(f"{where}follow-up note type {_label(fields['note_type'], 'name')!r} doesn't exist here")
        else:
            fields["note_type"] = matched
    if schema_key == "task" and fields.get("assignee"):
        matched = resolver.assignee(fields["assignee"])
        if matched is None:
            warnings.append(f"{where}assignee {_label(fields['assignee'], 'display')!r} isn't here, so it's left unset")
            fields.pop("assignee")
        else:
            fields["assignee"] = matched
    return fields


def _label(ref: Any, key: str) -> str:
    return str(ref.get(key) or "?") if isinstance(ref, dict) else "?"
