"""Admin API and pages for building note templates, quickpicks, and order sets."""

import hashlib
from datetime import datetime, timezone
from uuid import uuid4
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import AppointmentMetadata
from canvas_sdk.v1.data.note import NoteMetadata
from canvas_sdk.v1.data.patient import PatientMetadata

from charting_tools.carry_forward import supports_carry_forward
from charting_tools.command_catalog import CATALOG
from charting_tools.command_forms import FORM_SPECS, clean_fields
from charting_tools.diagnoses import clean_sources, expand_sources, needs_umls
from charting_tools.portability import Resolver, export_document, read_document, remap_item
from charting_tools.rules import CODED_CONDITION_TYPES, clean_rule
from charting_tools.kinds import (
    QUICKPICK,
    RULE,
    KIND_LABELS,
    KINDS,
    SECTION_BY_COMMAND,
    TEMPLATE,
    allows_command,
    kind_of,
    max_commands,
    uses_diagnoses,
)
from charting_tools.models.note_template import NoteTemplate
from charting_tools.note_types import note_type_options
from charting_tools.questionnaires import (
    USE_CASE_BY_COMMAND,
    clean_answers,
    key_for,
    needs_questionnaire,
    options_by_command,
    question_form,
    resolve,
)
from charting_tools.settings import (
    TEMPLATE_ADMIN_ROLES,
    scribe_enabled,
    staff_can_manage_templates,
)
from charting_tools.umls import UmlsError, api_key

MAX_NAME_LENGTH = 80
MAX_COMMANDS = 30
MAX_PROMPT_LENGTH = 2000


def _error(message: str, status: HTTPStatus) -> list[Response | Effect]:
    return [JSONResponse({"error": message}, status_code=status)]


OVERRIDES_CSS = "templates/static/canvas-overrides.css"


def styles_version() -> str:
    """A fingerprint of the plugin's own stylesheet, put in its URL so a new
    install's styles load at once instead of waiting out the browser cache."""
    return hashlib.sha256(render_to_string(OVERRIDES_CSS).encode()).hexdigest()[:12]


def _css(template_path: str) -> Response:
    return Response(
        render_to_string(template_path).encode(),
        status_code=HTTPStatus.OK,
        content_type="text/css",
        headers={"Cache-Control": "private, max-age=3600"},
    )


def serialize(template: NoteTemplate) -> dict[str, Any]:
    """Render a template for the JSON API."""
    return {
        "id": template.template_id,
        "name": template.name,
        "kind": kind_of(template),
        "active": template.active,
        "show_in_menu": template.show_in_menu is not False,
        "show_in_panel": bool(template.show_in_panel),
        "note_types": template.note_types or [],
        "diagnosis_sources": template.diagnosis_sources or [],
        "tags": template.tags or [],
        "rule": _public_rule(template.rule) if kind_of(template) == RULE else None,
        "commands": template.commands,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


def _public_rule(rule: Any) -> dict[str, Any]:
    """A rule as the builder edits it, without the expanded diagnosis lists."""
    if not isinstance(rule, dict):
        return {}
    conditions = [{k: v for k, v in c.items() if k != "match_codes"} for c in rule.get("conditions") or []]
    return {**rule, "conditions": conditions}


MAX_TAGS = 20
MAX_TAG_LENGTH = 40


def clean_tags(raw: Any) -> list[str]:
    """Filter tags: trimmed, de-duplicated ignoring case, in the order given."""
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for value in raw:
        tag = " ".join(str(value or "").split())[:MAX_TAG_LENGTH]
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            tags.append(tag)
    return tags[:MAX_TAGS]


def parse_entries(kind: str, raw_commands: list[Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Validate and normalize a list of command entries for ``kind``."""
    noun = KIND_LABELS[kind]
    commands: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_commands, start=1):
        if not isinstance(raw, dict):
            return None, f"Command {index} is malformed"
        schema_key = str(raw.get("schema_key") or "")
        if schema_key not in CATALOG:
            return None, f"Command {index} has an unsupported type {schema_key!r}"
        if not allows_command(kind, schema_key):
            return None, f"{CATALOG[schema_key].label} can't be added to a {noun.lower()}"
        prompt = str(raw.get("scribe_prompt") or "").strip()
        if len(prompt) > MAX_PROMPT_LENGTH:
            return None, f"Command {index} prompt must be {MAX_PROMPT_LENGTH} characters or fewer"
        entry: dict[str, Any] = {
            "schema_key": schema_key,
            # Carry forward is for note templates; quickpicks and order sets start fresh.
            "carry_forward": kind == TEMPLATE
            and bool(raw.get("carry_forward"))
            and supports_carry_forward(schema_key),
            "scribe_prompt": prompt,
        }
        # Only quickpicks offer a choice of lab partner (in the panel's filter).
        fields = clean_fields(schema_key, raw.get("fields"), max_lab_partners=20 if kind == QUICKPICK else 1)
        if fields:
            entry["fields"] = fields
        if needs_questionnaire(schema_key):
            if key_for(schema_key, raw.get("questionnaire")) is None:
                return None, f"Command {index} needs a questionnaire"
            chosen = raw["questionnaire"]
            entry["questionnaire"] = {
                "code_system": str(chosen.get("code_system") or ""),
                "code": str(chosen.get("code") or ""),
                "name": str(chosen.get("name") or ""),
            }
            answers = clean_answers(raw.get("answers"))
            if answers:
                entry["answers"] = answers
        commands.append(entry)

    return commands, None


def validate_payload(body: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(clean_fields, None)`` for a valid body, or ``(None, error)``."""
    if not isinstance(body, dict):
        return None, "Body must be a JSON object"

    kind = body.get("kind") or TEMPLATE
    if kind not in KINDS:
        return None, f"Unknown kind {kind!r}"
    noun = KIND_LABELS[kind]

    name = str(body.get("name") or "").strip()
    if not name:
        return None, f"{noun} name is required"
    if len(name) > MAX_NAME_LENGTH:
        return None, f"{noun} name must be {MAX_NAME_LENGTH} characters or fewer"

    if kind == RULE:
        rule, error = clean_rule(body.get("rule"))
        if rule is None:
            return None, error
        actions, error = parse_actions(body)
        if actions is None:
            return None, error
        rule["actions"] = actions
        return {
            "kind": RULE,
            "name": name,
            "commands": [],
            "active": body.get("active", True) is not False,
            "show_in_menu": False,
            "show_in_panel": False,
            "note_types": [],
            "diagnosis_sources": [],
            "rule": rule,
        }, None

    raw_commands = body.get("commands")
    if not isinstance(raw_commands, list) or not raw_commands:
        return None, "Add at least one command"
    limit = max_commands(kind, MAX_COMMANDS)
    if len(raw_commands) > limit:
        return None, (
            "A quickpick holds exactly one command"
            if limit == 1
            else f"A {noun.lower()} can hold at most {limit} commands"
        )

    commands, error = parse_entries(kind, raw_commands)
    if commands is None:
        return None, error

    show_in_menu = body.get("show_in_menu", True) is not False
    # Note-type insertion is for templates; the in-command panel is for the others.
    show_in_panel = bool(body.get("show_in_panel")) and kind != TEMPLATE
    raw_note_types = (body.get("note_types") or []) if kind == TEMPLATE else []
    if not isinstance(raw_note_types, list):
        return None, "Note types must be a list"
    note_types: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_note_types:
        identifier = str(raw.get("unique_identifier") or "") if isinstance(raw, dict) else ""
        if not identifier:
            return None, "Each note type needs a unique_identifier"
        if identifier not in seen:
            seen.add(identifier)
            note_types.append({"unique_identifier": identifier, "name": str(raw.get("name") or "")})
    if kind == TEMPLATE and not show_in_menu and not note_types:
        return None, 'Turn on at least one place it shows up: the "/" menu, or new notes of a type'
    if kind != TEMPLATE and not show_in_menu and not show_in_panel:
        return None, 'Turn on at least one place it shows up: the "/" menu, or Assess and Diagnose'

    return {
        "kind": kind,
        "name": name,
        "commands": commands,
        "active": body.get("active", True) is not False,
        "show_in_menu": show_in_menu,
        "show_in_panel": show_in_panel,
        "note_types": note_types,
        "diagnosis_sources": clean_sources(body.get("diagnosis_sources")) if uses_diagnoses(kind) else [],
        "tags": clean_tags(body.get("tags")) if uses_diagnoses(kind) else [],
    }, None


MAX_ACTIONS = 10


def _target(raw: Any, index: int) -> tuple[dict[str, Any] | None, str | None]:
    """The command an update or remove action acts on: a type, and a questionnaire for questionnaire types."""
    raw = raw if isinstance(raw, dict) else {}
    schema_key = str(raw.get("schema_key") or "")
    if schema_key not in CATALOG:
        return None, f"Action {index}: choose which command"
    target: dict[str, Any] = {"schema_key": schema_key}
    if needs_questionnaire(schema_key):
        chosen = raw.get("questionnaire")
        if key_for(schema_key, chosen) is None:
            return None, f"Action {index}: choose which questionnaire"
        target["questionnaire"] = {
            "code_system": str(chosen.get("code_system") or ""),
            "code": str(chosen.get("code") or ""),
            "name": str(chosen.get("name") or ""),
        }
    return target, None


def parse_actions(body: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    """A rule's actions: add commands, update a command on the note, or remove one.

    A body from before rules had actions carries the commands at the top level
    and the mode in ``rule.action``; that reads as one add action.
    """
    rule_raw: dict[str, Any] = body["rule"] if isinstance(body.get("rule"), dict) else {}
    raw_actions = rule_raw.get("actions")
    if not isinstance(raw_actions, list):
        legacy: dict[str, Any] = rule_raw["action"] if isinstance(rule_raw.get("action"), dict) else {}
        mode = legacy.get("mode")
        raw_actions = [{"type": "add", "mode": mode, "commands": body.get("commands") or []}]
    if not raw_actions:
        return None, "Add at least one action"
    if len(raw_actions) > MAX_ACTIONS:
        return None, f"A rule can have at most {MAX_ACTIONS} actions"

    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_actions, start=1):
        kind = raw.get("type") if isinstance(raw, dict) else None
        if kind == "add":
            raw_commands = raw.get("commands")
            if not isinstance(raw_commands, list) or not raw_commands:
                return None, f"Action {index}: add at least one command"
            commands, error = parse_entries(RULE, raw_commands)
            if commands is None:
                return None, f"Action {index}: {error}"
            mode = "insert" if raw.get("mode") == "insert" else "suggest"
            actions.append({"type": "add", "mode": mode, "commands": commands})
        elif kind == "update":
            target, error = _target(raw.get("target"), index)
            if target is None:
                return None, error
            action: dict[str, Any] = {"type": "update", "target": target}
            fields = clean_fields(target["schema_key"], raw.get("fields"), max_lab_partners=1)
            if fields:
                action["fields"] = fields
            if "questionnaire" in target:
                answers = clean_answers(raw.get("answers"))
                if answers:
                    action["answers"] = answers
            if not fields and not action.get("answers"):
                return None, f"Action {index}: fill in what to change"
            actions.append(action)
        elif kind == "delete":
            target, error = _target(raw.get("target"), index)
            if target is None:
                return None, error
            actions.append({"type": "delete", "target": target})
        else:
            return None, f"Action {index}: choose what the action does"
    return actions, None


def match_codes(
    sources: list[dict[str, Any]],
    secrets: dict[str, Any],
    stored_sources: list[dict[str, Any]] | None = None,
    stored_codes: list[str] | None = None,
) -> tuple[list[str] | None, str | None]:
    """Expand diagnosis picks into the stored match list, or explain why not.

    When UMLS can't answer and the picks are unchanged, the stored list is kept
    rather than failing the save.
    """
    if not sources:
        return [], None
    try:
        return expand_sources(sources, api_key(secrets) if needs_umls(sources) else ""), None
    except UmlsError as error:
        if stored_codes and clean_sources(stored_sources) == sources:
            return list(stored_codes), None
        return None, str(error)


def note_type_problem(note_types: list[dict[str, str]], template_id: str | None) -> str | None:
    """Return an error if a note type is unknown or already assigned to another template.

    One template per note type keeps what a new note receives unambiguous.
    """
    if not note_types:
        return None
    current = {option["unique_identifier"] for option in note_type_options()}
    for note_type in note_types:
        if note_type["unique_identifier"] not in current:
            return f"Note type {note_type['name'] or note_type['unique_identifier']!r} is not active"

    wanted = {note_type["unique_identifier"] for note_type in note_types}
    others = NoteTemplate.objects.filter(active=True)
    if template_id:
        others = others.exclude(template_id=template_id)
    for other in (o for o in others if kind_of(o) == TEMPLATE):
        for note_type in other.note_types or []:
            if note_type.get("unique_identifier") in wanted:
                label = note_type.get("name") or note_type.get("unique_identifier")
                return f"{label!r} is already assigned to template {other.name!r}"
    return None


def missing_questionnaires(commands: list[dict[str, Any]]) -> str | None:
    """Return an error naming the first chosen questionnaire that is no longer active."""
    keyed = [
        (index, command, key_for(command["schema_key"], command["questionnaire"]))
        for index, command in enumerate(commands, start=1)
        if "questionnaire" in command
    ]
    found = resolve({key for _, _, key in keyed if key})
    for index, command, key in keyed:
        if key not in found:
            name = command["questionnaire"]["name"] or command["questionnaire"]["code"]
            return f"Command {index}: questionnaire {name!r} is not active"
    return None


def prepare_rule(
    rule: dict[str, Any], secrets: dict[str, Any], stored: dict[str, Any] | None, rule_id: str | None
) -> str | None:
    """Expand a rule's diagnosis and active-condition picks through UMLS, in place.

    Returns an error, or None when the rule is ready to save.
    """
    stored_conditions = (stored or {}).get("conditions") or []
    for index, condition in enumerate(rule["conditions"]):
        if condition["type"] not in CODED_CONDITION_TYPES:
            continue
        previous = stored_conditions[index] if index < len(stored_conditions) else {}
        codes, error = match_codes(
            condition["sources"], secrets, previous.get("sources"), previous.get("match_codes")
        )
        if codes is None:
            return error or "Could not expand diagnoses"
        condition["match_codes"] = codes
    return None


class NoteTemplatesAPI(StaffSessionAuthMixin, SimpleAPI):
    """CRUD for templates, quickpicks, and order sets, for TEMPLATE_ADMIN_ROLES staff only."""

    def _staff_id(self) -> str | None:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        return str(staff_id) if staff_id else None

    def _is_admin(self) -> bool:
        return staff_can_manage_templates(self._staff_id(), self.secrets)

    def _change_refused(self) -> list[Response | Effect] | None:
        """Why a create, edit, or delete is refused, or None to go ahead.

        Requires an admin, and a JSON request. Plugin routes get no CSRF check,
        and where Canvas is embedded in another site the session cookie is sent
        cross-site, so another site could submit a form as a logged-in admin. A
        form can't set ``Content-Type: application/json``; a script on another
        site can only do so after a CORS preflight the browser won't pass.
        """
        if not self._is_admin():
            return _error("Forbidden", HTTPStatus.FORBIDDEN)
        if self.request.content_type != "application/json":
            return _error("Changes must be sent as JSON", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        return None

    def _name_taken(self, name: str, exclude_template_id: str | None = None) -> bool:
        matches = NoteTemplate.objects.filter(name__iexact=name)
        if exclude_template_id:
            matches = matches.exclude(template_id=exclude_template_id)
        return bool(matches.exists())

    # ── Pages ────────────────────────────────────────────────────────

    @api.get("/admin")
    def admin_page(self) -> list[Response | Effect]:
        """Serve the template builder, or an access notice for non-admins."""
        if not self._is_admin():
            html = render_to_string(
                "templates/forbidden.html",
                {"setting_name": TEMPLATE_ADMIN_ROLES, "styles_version": styles_version()},
            )
            return [HTMLResponse(html, status_code=HTTPStatus.FORBIDDEN)]
        html = render_to_string("templates/admin.html", {"styles_version": styles_version()})
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    # ── Styles ───────────────────────────────────────────────────────
    # Served to any staff session, since the access notice page uses them too.

    @api.get("/static/semantic.min.css")
    def semantic_css(self) -> list[Response | Effect]:
        """Semantic UI 2.4.0, the same build home-app ships."""
        return [_css("templates/static/semantic.min.css")]

    @api.get("/static/canvas-overrides.css")
    def overrides_css(self) -> list[Response | Effect]:
        """Canvas's global Semantic overrides plus this page's layout rules."""
        return [_css(OVERRIDES_CSS)]

    # ── JSON ─────────────────────────────────────────────────────────

    @api.get("/config")
    def config(self) -> list[Response | Effect]:
        """Return the command catalog and whether scribe prompts are enabled."""
        if not self._is_admin():
            return _error("Forbidden", HTTPStatus.FORBIDDEN)
        catalog = [
            {
                "schema_key": schema_key,
                "label": entry.label,
                "carry_forward_supported": supports_carry_forward(schema_key),
                "questionnaire_use_case": USE_CASE_BY_COMMAND.get(schema_key),
                "section": SECTION_BY_COMMAND.get(schema_key),
                "form": FORM_SPECS.get(schema_key, []),
            }
            for schema_key, entry in CATALOG.items()
        ]
        kinds = [
            {
                "kind": kind,
                "label": KIND_LABELS[kind],
                "commands": [key for key in CATALOG if allows_command(kind, key)],
                "max_commands": max_commands(kind, MAX_COMMANDS),
                "uses_diagnoses": uses_diagnoses(kind),
            }
            for kind in KINDS
        ]
        return [
            JSONResponse(
                {
                    "commands": catalog,
                    "kinds": kinds,
                    "questionnaires": options_by_command(),
                    "note_types": note_type_options(),
                    "scribe_enabled": scribe_enabled(self.secrets),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/questionnaire-questions")
    def questionnaire_questions(self) -> list[Response | Effect]:
        """The questions of the active questionnaire a command entry names, for its form."""
        if not self._is_admin():
            return _error("Forbidden", HTTPStatus.FORBIDDEN)
        params = self.request.query_params
        schema_key = str(params.get("schema_key") or "")
        if not needs_questionnaire(schema_key):
            return _error("Not a questionnaire command", HTTPStatus.BAD_REQUEST)
        key = key_for(
            schema_key,
            {"code_system": params.get("code_system") or "", "code": params.get("code") or ""},
        )
        questionnaire = resolve({key}).get(key) if key else None
        if questionnaire is None:
            return _error("Questionnaire is not active", HTTPStatus.NOT_FOUND)
        return [JSONResponse({"questions": question_form(questionnaire)}, status_code=HTTPStatus.OK)]

    @api.get("/metadata-keys")
    def metadata_keys(self) -> list[Response | Effect]:
        """Metadata keys in use for patients, appointments, or notes, for the rule builder."""
        if not self._is_admin():
            return _error("Forbidden", HTTPStatus.FORBIDDEN)
        models = {"patient": PatientMetadata, "appointment": AppointmentMetadata, "note": NoteMetadata}
        model = models.get(str(self.request.query_params.get("source") or ""))
        if model is None:
            return _error("Unknown source", HTTPStatus.BAD_REQUEST)
        keys = model.objects.order_by("key").values_list("key", flat=True).distinct()[:200]
        return [JSONResponse({"keys": [str(k) for k in keys]}, status_code=HTTPStatus.OK)]

    @api.get("/templates")
    def list_templates(self) -> list[Response | Effect]:
        """List every template, active and inactive."""
        if not self._is_admin():
            return _error("Forbidden", HTTPStatus.FORBIDDEN)
        templates = NoteTemplate.objects.order_by("name")
        return [
            JSONResponse(
                {"templates": [serialize(t) for t in templates]}, status_code=HTTPStatus.OK
            )
        ]

    @api.post("/templates")
    def create_template(self) -> list[Response | Effect]:
        """Create a template; its name becomes the "/" menu entry."""
        refused = self._change_refused()
        if refused:
            return refused
        try:
            body = self.request.json()
        except ValueError:
            return _error("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        fields, error = validate_payload(body)
        if fields is None:
            return _error(error or "Invalid template", HTTPStatus.BAD_REQUEST)
        missing = missing_questionnaires(fields["commands"])
        if missing:
            return _error(missing, HTTPStatus.BAD_REQUEST)
        conflict = note_type_problem(fields["note_types"], None) if fields["active"] else None
        if conflict:
            return _error(conflict, HTTPStatus.CONFLICT)
        if self._name_taken(fields["name"]):
            return _error("That name is already in use", HTTPStatus.CONFLICT)
        codes, umls_error = match_codes(fields["diagnosis_sources"], self.secrets)
        if codes is None:
            return _error(umls_error or "Could not expand diagnoses", HTTPStatus.BAD_GATEWAY)
        if fields["kind"] == RULE:
            problem = prepare_rule(fields["rule"], self.secrets, None, None)
            if problem:
                return _error(problem, HTTPStatus.BAD_REQUEST)

        staff_id = self._staff_id() or ""
        template = NoteTemplate(
            template_id=uuid4().hex,
            created_by=staff_id,
            updated_by=staff_id,
            diagnosis_match_codes=codes,
            **fields,
        )
        template.save()
        return [JSONResponse(serialize(template), status_code=HTTPStatus.CREATED)]

    @api.put("/templates/<template_id>")
    def update_template(self) -> list[Response | Effect]:
        """Replace a template's name, commands, and active flag."""
        refused = self._change_refused()
        if refused:
            return refused
        template_id = self.request.path_params["template_id"]
        template = NoteTemplate.objects.filter(template_id=template_id).first()
        if template is None:
            return _error("Template not found", HTTPStatus.NOT_FOUND)
        try:
            body = self.request.json()
        except ValueError:
            return _error("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        if isinstance(body, dict):
            # A row's kind is fixed when it is created.
            body = {**body, "kind": kind_of(template)}
        fields, error = validate_payload(body)
        if fields is None:
            return _error(error or "Invalid template", HTTPStatus.BAD_REQUEST)
        missing = missing_questionnaires(fields["commands"])
        if missing:
            return _error(missing, HTTPStatus.BAD_REQUEST)
        conflict = (
            note_type_problem(fields["note_types"], template_id) if fields["active"] else None
        )
        if conflict:
            return _error(conflict, HTTPStatus.CONFLICT)
        if self._name_taken(fields["name"], exclude_template_id=template_id):
            return _error("That name is already in use", HTTPStatus.CONFLICT)
        codes, umls_error = match_codes(
            fields["diagnosis_sources"],
            self.secrets,
            template.diagnosis_sources,
            template.diagnosis_match_codes,
        )
        if codes is None:
            return _error(umls_error or "Could not expand diagnoses", HTTPStatus.BAD_GATEWAY)

        template.kind = fields["kind"]
        template.show_in_panel = fields["show_in_panel"]
        template.tags = fields.get("tags", [])
        template.diagnosis_sources = fields["diagnosis_sources"]
        template.diagnosis_match_codes = codes
        if fields["kind"] == RULE:
            problem = prepare_rule(fields["rule"], self.secrets, template.rule, template_id)
            if problem:
                return _error(problem, HTTPStatus.BAD_REQUEST)
            template.rule = fields["rule"]
        template.name = fields["name"]
        template.commands = fields["commands"]
        template.active = fields["active"]
        template.show_in_menu = fields["show_in_menu"]
        template.note_types = fields["note_types"]
        template.updated_by = self._staff_id() or ""
        template.save()
        return [JSONResponse(serialize(template), status_code=HTTPStatus.OK)]

    # ── Moving between environments ──────────────────────────────────

    @api.get("/export")
    def export_all(self) -> list[Response | Effect]:
        """Every template, quickpick, order set, and rule, for uploading elsewhere."""
        if not self._is_admin():
            return _error("Forbidden", HTTPStatus.FORBIDDEN)
        document = export_document(
            NoteTemplate.objects.order_by("name"), datetime.now(timezone.utc).isoformat()
        )
        return [JSONResponse(document, status_code=HTTPStatus.OK)]

    @api.post("/import")
    def import_all(self) -> list[Response | Effect]:
        """Preview, or upload, an export from another environment.

        The body is ``{"export": <export file>, "apply": bool}``. Each item is
        matched to an existing one by kind and name and updated, or created.
        Items with problems are left out and listed. Without ``apply`` nothing
        is saved.
        """
        refused = self._change_refused()
        if refused:
            return refused
        try:
            body = self.request.json()
        except ValueError:
            return _error("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        if not isinstance(body, dict):
            return _error("Body must be a JSON object", HTTPStatus.BAD_REQUEST)
        items, error = read_document(body.get("export"))
        if items is None:
            return _error(error or "Invalid export", HTTPStatus.BAD_REQUEST)
        apply = body.get("apply") is True
        results = self._import_items(items, apply)
        return [
            JSONResponse(
                {
                    "applied": apply,
                    "items": results,
                    "counts": {
                        action: sum(1 for r in results if r["action"] == action)
                        for action in ("create", "update", "skip")
                    },
                },
                status_code=HTTPStatus.OK,
            )
        ]

    def _import_items(self, items: list[dict[str, Any]], apply: bool) -> list[dict[str, Any]]:
        resolver = Resolver()
        staff_id = self._staff_id() or ""
        seen_names: set[str] = set()
        claimed_note_types: dict[str, str] = {}  # note type -> item name, within this upload
        results = []
        for item in items:
            name = str(item.get("name") or "").strip()
            kind = str(item.get("kind") or TEMPLATE)
            result: dict[str, Any] = {"name": name, "kind": kind, "action": "skip", "problems": [], "warnings": []}
            results.append(result)

            remapped, problems, warnings = remap_item(item, resolver)
            result["warnings"] = warnings
            if name.casefold() in seen_names:
                problems.append("The file has this name more than once")
            seen_names.add(name.casefold())

            existing = NoteTemplate.objects.filter(name__iexact=name).first() if name else None
            if existing is not None and kind_of(existing) != kind:
                problems.append(f"The name is already used here by a {KIND_LABELS[kind_of(existing)].lower()}")
            fields, error = validate_payload({**remapped, "kind": kind})
            if fields is None:
                problems.append(error or "Invalid item")
            else:
                missing = missing_questionnaires(fields["commands"])
                if missing:
                    problems.append(missing)
                if fields["active"]:
                    conflict = note_type_problem(
                        fields["note_types"], existing.template_id if existing is not None else None
                    )
                    if conflict:
                        problems.append(conflict)
                    for note_type in fields["note_types"]:
                        uid = note_type["unique_identifier"]
                        if uid in claimed_note_types:
                            problems.append(f"{note_type['name']!r} is also assigned to {claimed_note_types[uid]!r} in this file")
                        claimed_note_types.setdefault(uid, name)
                codes, codes_error = self._file_codes(
                    fields["diagnosis_sources"], item.get("diagnosis_sources"), item.get("diagnosis_match_codes")
                )
                if codes is None:
                    problems.append(codes_error or "Could not expand diagnoses")
                if fields["kind"] == RULE:
                    rule_error = self._file_rule_codes(fields["rule"], item.get("rule"))
                    if rule_error:
                        problems.append(rule_error)

            result["problems"] = problems
            if problems or fields is None:
                continue
            result["action"] = "update" if existing is not None else "create"
            if apply:
                self._save_imported(existing, fields, codes or [], staff_id)
        return results

    def _file_codes(
        self, sources: list[dict[str, Any]], file_sources: Any, file_codes: Any
    ) -> tuple[list[str] | None, str | None]:
        """The file's expanded diagnosis list when its picks are unchanged, else a fresh expansion."""
        if sources and isinstance(file_codes, list) and file_codes and clean_sources(file_sources) == sources:
            return [str(c) for c in file_codes], None
        return match_codes(sources, self.secrets)

    def _file_rule_codes(self, rule: dict[str, Any], file_rule: Any) -> str | None:
        """Fill each coded condition's expanded list from the file, or expand it."""
        file_conditions = (file_rule or {}).get("conditions") or [] if isinstance(file_rule, dict) else []
        for index, condition in enumerate(rule["conditions"]):
            if condition["type"] not in CODED_CONDITION_TYPES:
                continue
            previous = file_conditions[index] if index < len(file_conditions) else {}
            codes, error = self._file_codes(
                condition["sources"], previous.get("sources"), previous.get("match_codes")
            )
            if codes is None:
                return error or "Could not expand diagnoses"
            condition["match_codes"] = codes
        return None

    def _save_imported(self, existing: Any, fields: dict[str, Any], codes: list[str], staff_id: str) -> None:
        if existing is None:
            NoteTemplate(
                template_id=uuid4().hex,
                created_by=staff_id,
                updated_by=staff_id,
                diagnosis_match_codes=codes,
                **fields,
            ).save()
            return
        existing.kind = fields["kind"]
        existing.name = fields["name"]
        existing.commands = fields["commands"]
        existing.active = fields["active"]
        existing.show_in_menu = fields["show_in_menu"]
        existing.show_in_panel = fields["show_in_panel"]
        existing.note_types = fields["note_types"]
        existing.tags = fields.get("tags", [])
        existing.diagnosis_sources = fields["diagnosis_sources"]
        existing.diagnosis_match_codes = codes
        if fields["kind"] == RULE:
            existing.rule = fields["rule"]
        existing.updated_by = staff_id
        existing.save()

    @api.delete("/templates/<template_id>")
    def delete_template(self) -> list[Response | Effect]:
        """Delete a template, which removes its "/" menu entry."""
        refused = self._change_refused()
        if refused:
            return refused
        template = NoteTemplate.objects.filter(
            template_id=self.request.path_params["template_id"]
        ).first()
        if template is None:
            return _error("Template not found", HTTPStatus.NOT_FOUND)
        template.delete()
        return [JSONResponse({"deleted": True}, status_code=HTTPStatus.OK)]
