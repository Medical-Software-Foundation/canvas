"""The routes the in-command panel calls.

The panel lives in a sandboxed command frame that can't send a session cookie,
so each call carries the token signed when the panel was attached. Every call
is a POST whose body is a JSON object holding the token and the call's
parameters, sent as text/plain so the browser makes it without a CORS preflight
and the token stays out of URLs and access logs. The note is always read from
the verified token, never from the request, and a token stops working once the
Assess or Diagnose it was signed for is entered in error. Every call is refused
once the note is no longer open, and the panel then hides itself.

- ``POST /panel/catalog``: the note's charted conditions, and the active
  quickpicks and order sets shown in the panel. Each item says which of those
  conditions it is for, its order group, and whether it is already on the note.
- ``POST /panel/apply``: stage one order set, or several quickpicks at once.
  Quickpicks take the chosen conditions they match as their indication (the
  charted ICD-10 when none match), lab quickpicks for the same lab partner
  merge into one lab order, and quickpicks already on the note are skipped.
  Assessment commands in an order set are left out here: the Assess or
  Diagnose the panel sits in is the diagnosis.
- ``POST /panel/quick-add``: add one empty command of a quick-add type on the
  line below the Assess or Diagnose. Orders with an indications field get the
  ICD-10 that command is charting.

Every command added from the panel is linked to the Assessment behind the Assess
or Diagnose the panel sits in, wherever the command takes a link: Plan,
Instruct, Perform, Follow-up, and Task always could, and SDK 0.247.0 added Lab,
Image, Refer, Prescribe, and the other orders (KOALA-7603). Orders also get
their indications from the panel, since a plugin-made link doesn't fill them.
"""

from http import HTTPStatus
from typing import Any
from uuid import uuid4

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.commands import PlanCommand
from canvas_sdk.v1.data.assessment import Assessment
from canvas_sdk.v1.data.condition import ConditionCoding
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note
from logger import log

from charting_tools.command_catalog import CATALOG
from charting_tools.diagnoses import matches, source_label
from charting_tools.icd10 import condition_id_of, normalize_icd10
from charting_tools.insertion import (
    build_commands,
    lab_partners_of,
    merge_lab_orders,
    originate_effects,
    set_indications,
    set_note_provider,
)
from charting_tools.labs import preferred_lab_partner_id
from charting_tools.kinds import ASSESSMENT, KIND_LABELS, ORDER_SET, QUICKPICK, kind_of
from charting_tools.models.note_template import NoteTemplate
from charting_tools.note_conditions import added_quickpicks, command_icd10, note_diagnoses
from charting_tools.note_states import note_is_open
from charting_tools.panel import PANEL_PREFIX, charted_code_cache_key
from charting_tools.settings import panel_signing_key
from charting_tools.tokens import verify_token

# How the panel groups quickpicks, in the order a note reads.
ORDER_GROUPS = [
    ("labs", "Labs", ("labOrder",)),
    ("imaging", "Imaging", ("imagingOrder",)),
    ("dme", "DME", ("orderDme",)),
    ("referrals", "Referrals", ("refer",)),
    ("education", "Education", ("instruct",)),
    ("prescriptions", "Prescriptions", ("prescribe", "refill", "adjustPrescription", "stopMedication")),
    ("procedures", "Procedures", ("perform", "immunize")),
    ("plan", "Plan", ("plan",)),
    ("follow_up", "Follow-ups", ("followUp",)),
    ("tasks", "Tasks", ("task",)),
    ("goals", "Goals", ("goal", "updateGoal", "closeGoal")),
]
GROUP_BY_COMMAND = {key: group for group, _, keys in ORDER_GROUPS for key in keys}

# How long a code read from the command stays cached. Short, so a condition
# changed on the Assess is picked up soon.
CHARTED_CODE_TTL_SECONDS = 300

# The commands the panel's quick-add buttons add, empty.
QUICK_ADD_COMMANDS = ("plan", "refer", "labOrder", "imagingOrder", "orderDme", "prescribe", "instruct", "perform")

# The command frame is sandboxed, so its requests carry an opaque origin that a
# named origin can't match. The token in the body is what authorizes a call.
CORS = {"Access-Control-Allow-Origin": "*"}


def _json(payload: dict, status: HTTPStatus) -> list[Response | Effect]:
    return [JSONResponse(payload, status_code=status, headers=CORS)]


class PanelAPI(SimpleAPI):
    """Catalog and apply for the in-command panel."""

    PREFIX = PANEL_PREFIX

    def authenticate(self, credentials: Credentials) -> bool:
        # Each route checks the signed token in its query string instead; the
        # frame has no session to authenticate here.
        return True

    def _params(self) -> dict[str, Any]:
        """The call's JSON body, or nothing when it isn't a JSON object."""
        try:
            body = self.request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _verified(self) -> tuple[str, str] | None:
        """The token's note and command, while that command is still on the note.

        The command may be committed: its panel stays while the note is open.
        The token's expiry isn't enforced here. The token is saved in the
        command's panel and is only re-signed when the command is edited, so an
        Assess or Diagnose left untouched for hours would otherwise keep an
        expired token, even across page reloads. What bounds a token instead is
        its signature, its command not being entered in error, and every route
        refusing a note that isn't open.
        """
        token = str(self._params().get("token") or "")
        key = panel_signing_key(self.secrets)
        if not token or not key:
            return None
        verified = verify_token(token, key, allow_expired=True)
        if verified is None:
            return None
        note_uuid, origin_command_uuid = verified
        live = (
            Command.objects.filter(id=origin_command_uuid, note__id=note_uuid, entered_in_error__isnull=True)
            .exclude(state="entered_in_error")
            .exists()
        )
        return verified if live else None

    def _charted(self, origin_command_uuid: str) -> str:
        """The ICD-10 code the panel's Assess or Diagnose is charting.

        Cached from the command's events when they carry it. An Assess's events
        carry its condition rather than a code, so otherwise it's read from the
        command (for an Assess, the condition's ICD-10 coding) and cached.
        """
        if not origin_command_uuid:
            return ""
        cache = get_cache()
        key = charted_code_cache_key(origin_command_uuid)
        code = normalize_icd10(str(cache.get(key) or ""))
        if not code:
            code = command_icd10(origin_command_uuid)
            if code:
                cache.set(key, code, timeout_seconds=CHARTED_CODE_TTL_SECONDS)
        return code

    @api.post("/catalog")
    def catalog(self) -> list[Response | Effect]:
        """The note's conditions plus the panel's quickpicks and order sets."""
        verified = self._verified()
        if verified is None:
            return _json({"error": "invalid or expired token"}, HTTPStatus.UNAUTHORIZED)
        note_uuid, origin_command_uuid = verified
        charted = self._charted(origin_command_uuid)

        note = Note.objects.defer("body").filter(id=note_uuid).first()
        if note is None or not note_is_open(note.dbid):
            return _json({"error": "note is not open"}, HTTPStatus.CONFLICT)
        conditions = note_diagnoses(note)
        if charted and charted not in {c["code"] for c in conditions}:
            # The command the panel sits in may not be saved with its code yet.
            conditions.insert(0, {"code": charted, "label": charted})
        added = added_quickpicks(note) if note is not None else set()
        codes = [c["code"] for c in conditions]

        items = []
        for row in NoteTemplate.objects.filter(active=True, show_in_panel=True).order_by("name"):
            kind = kind_of(row)
            if kind not in (QUICKPICK, ORDER_SET):
                continue
            match_codes = set(row.diagnosis_match_codes or [])
            first_key = ((row.commands or [{}])[0] or {}).get("schema_key", "")
            items.append(
                {
                    "id": row.template_id,
                    "name": row.name,
                    "kind": kind,
                    "kind_label": KIND_LABELS[kind],
                    "group": GROUP_BY_COMMAND.get(first_key, "other") if kind == QUICKPICK else "",
                    "command_count": len(row.commands or []),
                    "diagnoses": [source_label(s) for s in row.diagnosis_sources or []],
                    "conditions": [code for code in codes if code in match_codes],
                    "diagnosis_match": matches(row.diagnosis_match_codes, charted),
                    "added": row.template_id in added,
                    "lab_partners": lab_partners_of(row) if kind == QUICKPICK else [],
                    "tags": list(row.tags or []),
                }
            )
        return _json(
            {
                "items": items,
                "conditions": conditions,
                "charted_icd10": charted,
                "preferred_lab_partner": preferred_lab_partner(note, items) if note is not None else None,
                "groups": [{"key": key, "label": label} for key, label, _ in ORDER_GROUPS]
                + [{"key": "other", "label": "Other"}],
            },
            HTTPStatus.OK,
        )

    @api.post("/quick-add")
    def quick_add(self) -> list[Response | Effect]:
        """Add one empty command below the Assess or Diagnose the panel sits in."""
        verified = self._verified()
        if verified is None:
            return _json({"error": "invalid or expired token"}, HTTPStatus.UNAUTHORIZED)
        note_uuid, origin_command_uuid = verified
        schema_key = str(self._params().get("command") or "")
        if schema_key not in QUICK_ADD_COMMANDS:
            return _json({"error": "unknown command"}, HTTPStatus.BAD_REQUEST)
        # The body is read to place the command below the Assess or Diagnose.
        note = Note.objects.filter(id=note_uuid).first()
        if note is None:
            return _json({"error": "note not found"}, HTTPStatus.NOT_FOUND)
        if not note_is_open(note.dbid):
            return _json({"error": "note is not open"}, HTTPStatus.CONFLICT)

        command = CATALOG[schema_key].command_class(note_uuid=str(note.id), command_uuid=str(uuid4()))
        ref = assessment_ref(note, origin_command_uuid)
        if schema_key == "plan" and self._params().get("carry_forward") is True:
            # The patient's last plan for this diagnosis, from an earlier note.
            narrative = last_plan_for(note, self._charted(origin_command_uuid))
            if narrative is None:
                return _json({"error": "no earlier plan for this diagnosis"}, HTTPStatus.NOT_FOUND)
            # A blank plan already linked to this assessment is filled in rather
            # than adding a second one.
            blank = blank_linked_plan(note, ref[1]) if ref is not None else None
            if blank is not None:
                log.info(f"Panel carried a plan forward into plan {blank} on note {note_uuid}")
                return [
                    PlanCommand(command_uuid=blank, narrative=narrative).edit(),
                    *_json({"status": "updated", "command": "plan"}, HTTPStatus.OK),
                ]
            command.narrative = narrative
        charted = self._charted(origin_command_uuid)
        if charted:
            set_indications(command, [charted])
        set_note_provider(command, note)
        if schema_key == "labOrder":
            # The patient's preferred lab (their "preferred_lab" metadata), set
            # when the order is created so an open note shows it without a reload.
            lab = preferred_lab_partner_id(note.patient_id)
            if lab:
                command.lab_partner = lab
        link_assessment([command], ref[0] if ref is not None else None)
        # Whether the link was attached: the command only takes one when this
        # instance's SDK gives it an assessment field.
        log.info(
            f"Panel quick-added {schema_key} to note {note_uuid}; "
            f"assessment field: {hasattr(command, 'assessment_id')}, linked: {bool(getattr(command, 'assessment_id', None))}"
        )
        return [
            command.originate(line_number=line_below(note, origin_command_uuid)),
            *_json({"status": "added", "command": schema_key}, HTTPStatus.OK),
        ]

    @api.post("/apply")
    def apply(self) -> list[Response | Effect]:
        """Stage one order set, or several quickpicks, on the token's note."""
        verified = self._verified()
        if verified is None:
            return _json({"error": "invalid or expired token"}, HTTPStatus.UNAUTHORIZED)
        note_uuid, origin_command_uuid = verified
        params = self._params()
        ids = [i for i in str(params.get("ids") or params.get("id") or "").split(",") if i.strip()]
        # The panel's Lab choice, which starts on the patient's preferred lab.
        lab_partner_id = str(params.get("lab_partner") or "").strip() or None
        if not ids:
            return _json({"error": "nothing chosen"}, HTTPStatus.BAD_REQUEST)

        note = Note.objects.defer("body").filter(id=note_uuid).first()
        if note is None:
            return _json({"error": "note not found"}, HTTPStatus.NOT_FOUND)
        if not note_is_open(note.dbid):
            return _json({"error": "note is not open"}, HTTPStatus.CONFLICT)
        charted = self._charted(origin_command_uuid)

        rows = {
            row.template_id: row
            for row in NoteTemplate.objects.filter(template_id__in=ids, active=True, show_in_panel=True)
            if kind_of(row) in (QUICKPICK, ORDER_SET)
        }
        order_sets = [rows[i] for i in ids if i in rows and kind_of(rows[i]) == ORDER_SET]
        if order_sets:
            if len(ids) > 1:
                return _json({"error": "add one order set at a time"}, HTTPStatus.BAD_REQUEST)
            row = order_sets[0]
            built = build_commands(
                row,
                note,
                [charted] if charted else None,
                skip_sections=(ASSESSMENT,),
                lab_partner_id=lab_partner_id,
                use_preferred_lab=False,
            )
            link_assessment([item.command for item in built], assessment_for(note, origin_command_uuid))
            effects = originate_effects(built, self.secrets, replace_line=False)
            if not effects:
                return _json({"error": "nothing to add"}, HTTPStatus.BAD_REQUEST)
            log.info(f"Panel applied order set {row.template_id} to note {note_uuid}")
            return [*effects, *_json({"status": "added", "added": [row.template_id]}, HTTPStatus.OK)]

        chosen = [normalize_icd10(c) for c in str(params.get("conditions") or "").split(",") if c.strip()]
        already = added_quickpicks(note)
        built = []
        added = []
        for template_id in dict.fromkeys(ids):
            row = rows.get(template_id)
            if row is None or template_id in already:
                continue
            match_codes = set(row.diagnosis_match_codes or [])
            indications = [c for c in chosen if c in match_codes] or ([charted] if charted else [])
            built.extend(
                build_commands(
                    row, note, indications or None, lab_partner_id=lab_partner_id, use_preferred_lab=False
                )
            )
            added.append(template_id)
        if not built:
            return _json({"error": "already added", "added": []}, HTTPStatus.CONFLICT)

        link_assessment([item.command for item in built], assessment_for(note, origin_command_uuid))
        effects = originate_effects(
            merge_lab_orders(built), self.secrets, replace_line=False, mark_quickpicks=True
        )
        log.info(f"Panel added quickpicks {added} to note {note_uuid}")
        return [*effects, *_json({"status": "added", "added": added}, HTTPStatus.OK)]


def line_below(note: Any, command_uuid: str) -> int:
    """The note body line just after a command, or -1 (the end) when it isn't found."""
    for index, line in enumerate(note.body or []):
        if (
            isinstance(line, dict)
            and line.get("type") == "command"
            and str((line.get("data") or {}).get("command_uuid") or "") == command_uuid
        ):
            return index + 1
    return -1


def assessment_for(note: Any, command_uuid: str) -> str | None:
    """The id of the Assessment behind an Assess or Diagnose command on the note."""
    ref = assessment_ref(note, command_uuid)
    return ref[0] if ref is not None else None


def assessment_ref(note: Any, command_uuid: str) -> tuple[str, int] | None:
    """The Assessment behind an Assess or Diagnose command on the note, as (id, dbid).

    An Assess command is anchored to its Assessment; a Diagnose command is
    anchored to its Condition, whose Assessment in this note is the one.
    """
    if not command_uuid:
        return None
    anchor = (
        Command.objects.filter(id=command_uuid, note_id=note.dbid)
        .values_list("anchor_object_type", "anchor_object_dbid")
        .first()
    )
    if anchor is None or not anchor[1]:
        return None
    live = Assessment.objects.filter(note_id=note.dbid, entered_in_error__isnull=True, deleted=False)
    if anchor[0] == "assessment":
        found = live.filter(dbid=anchor[1])
    elif anchor[0] == "condition":
        found = live.filter(condition_id=anchor[1]).order_by("dbid")
    else:
        return None
    row = found.values_list("id", "dbid").first()
    return (str(row[0]), int(row[1])) if row else None


def link_assessment(commands: list[Any], assessment_id: str | None) -> None:
    """Link each command that takes an assessment to ``assessment_id``."""
    if not assessment_id:
        return
    for command in commands:
        # The sandbox blocks reading an SDK class's attributes, so ask the
        # command itself whether it has the field.
        if hasattr(command, "assessment_id"):
            command.assessment_id = assessment_id


def preferred_lab_partner(note: Any, items: list[dict[str, Any]]) -> str | None:
    """The patient's preferred lab, when the panel's lab quickpicks offer it.

    A lab none of them is set up for isn't in the Lab choice, so it can't be
    preselected.
    """
    preferred = preferred_lab_partner_id(getattr(note, "patient_id", None))
    if not preferred:
        return None
    offered = {str(p.get("id")) for item in items for p in item.get("lab_partners") or []}
    return preferred if preferred in offered else None


# How many of the patient's most recent plans are looked through for one linked
# to the diagnosis.
PLANS_SCANNED = 100


def last_plan_for(note: Any, icd10: str) -> str | None:
    """The narrative of the patient's most recent committed plan, from an earlier
    note, that was linked to an Assess of a condition coded ``icd10``.

    A linked plan names its Assessment in ``data["assessment"]["value"]``; the
    Assessment's condition carries the ICD-10 coding. None when there is no
    such plan, or no code to match.
    """
    if not icd10 or not getattr(note, "patient_id", None):
        return None
    plans = list(
        Command.objects.filter(
            patient_id=note.patient_id,
            schema_key="plan",
            committer__isnull=False,
            entered_in_error__isnull=True,
        )
        .exclude(note_id=note.dbid)
        .order_by("-note__datetime_of_service", "-dbid")
        .values_list("data", flat=True)[:PLANS_SCANNED]
    )
    linked = [
        (assessment_dbid, data)
        for data in plans
        if (assessment_dbid := condition_id_of(((data or {}).get("assessment") or {}).get("value"))) is not None
    ]
    if not linked:
        return None
    condition_by_assessment = dict(
        Assessment.objects.filter(dbid__in={a for a, _ in linked}).values_list("dbid", "condition_id")
    )
    matching_conditions = set(
        ConditionCoding.objects.filter(
            condition_id__in=set(condition_by_assessment.values()) - {None},
        ).values_list("condition_id", "system", "code")
    )
    coded = {
        condition_id
        for condition_id, system, code in matching_conditions
        if "icd" in str(system or "").lower() and "10" in str(system or "") and normalize_icd10(str(code)) == icd10
    }
    for assessment_dbid, data in linked:
        if condition_by_assessment.get(assessment_dbid) in coded:
            narrative = str((data or {}).get("narrative") or "").strip()
            if narrative:
                return narrative
    return None


def blank_linked_plan(note: Any, assessment_dbid: int) -> str | None:
    """The id of an uncommitted, empty Plan on the note linked to the Assessment, if any."""
    rows = (
        Command.objects.filter(
            note_id=note.dbid,
            schema_key="plan",
            state="staged",
            committer__isnull=True,
            entered_in_error__isnull=True,
        )
        .order_by("dbid")
        .values_list("id", "data")
    )
    for command_id, data in rows:
        data = data or {}
        linked = condition_id_of((data.get("assessment") or {}).get("value"))
        if linked == assessment_dbid and not str(data.get("narrative") or "").strip():
            return str(command_id)
    return None
