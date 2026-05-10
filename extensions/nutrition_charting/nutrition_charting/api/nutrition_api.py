"""SimpleAPI handlers for the Nutrition Charting plugin.

Phase B brings the staff-session API to life:
  - GET  /charting/auto-populate?patient_id=...   chart pull (Medical Chart Review)
  - GET  /charting/form-state?note_id=...         saved sections + visit type
  - POST /charting/save?section=...&note_id=...   persist a section; emit
                                                  VitalsCommand for the
                                                  medical_chart_review section

The print API is still a Phase A stub; the real template renders in Phase E.
"""

from __future__ import annotations

import json
import uuid
from hmac import compare_digest
from http import HTTPStatus
from typing import Any

from canvas_sdk.commands import StructuredAssessmentCommand, VitalsCommand
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import (
    Credentials,
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from canvas_sdk.v1.data import ServiceProvider as ServiceProviderRecord
from canvas_sdk.v1.data.note import Note
from django.db.models import Q
from logger import log
from pydantic import ValidationError


def _is_db_error(exc: BaseException) -> bool:
    """Match `django.db.DatabaseError` (and its subclasses) without
    importing it. The plugin sandbox's RestrictedPython allowlist
    permits `django.db.models` for ORM access but blocks
    `from django.db import DatabaseError` at module load. Walking the
    exception's MRO for any class named `DatabaseError` recognises
    transient DB issues (OperationalError, IntegrityError, etc.)
    without the blocked import."""
    return any(c.__name__ == "DatabaseError" for c in type(exc).__mro__)

# Cap typeahead results so the dropdown stays bounded and the query stays cheap.
_REFER_SEARCH_LIMIT = 20

from nutrition_charting.applications.print_template import render_print_html
from nutrition_charting.data.form_state import (
    clear_originated_command as _clear_originated_command,
    get_form_state as _get_form_state,
    get_multi_command_map as _get_multi_command_map,
    get_originated_command as _get_originated_command,
    record_originated_command as _record_originated_command,
    save_multi_command_map as _save_multi_command_map,
    save_section as _save_section,
)
from nutrition_charting.data.medical_chart_review import build_chart_review
from nutrition_charting.data.multi_command_sections import MULTI_COMMAND_SECTIONS
from nutrition_charting.data.print_payload import build_print_payload
from nutrition_charting.data.questionnaires import (
    QUESTIONNAIRE_SECTIONS,
    resolve_questionnaire_id,
    summarize_section as summarize_questionnaire_section,
)
from nutrition_charting.data.single_command_sections import SINGLE_COMMAND_SECTIONS

MEDICAL_CHART_REVIEW_SECTION = "medical_chart_review"


def _json(body: dict, status: HTTPStatus = HTTPStatus.OK) -> Response:
    return Response(
        json.dumps(body, default=str).encode(),
        status_code=status,
        content_type="application/json",
    )


def _staff_session_authenticated(request: Any) -> bool:
    try:
        user = SessionCredentials(request).logged_in_user
    except InvalidCredentialsError:
        return False
    return bool(user.get("type") == "Staff")


def _looks_like_uuid(value: str) -> bool:
    """Cheap shape check — defends against URL tampering / typos before we
    let a value flow into a Django UUIDField query (which would raise
    ValidationError on hit) or into the AttributeHub key (which would
    silently pollute storage with garbage)."""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _staff_has_note_access(note_uuid: str) -> bool:
    """Defense-in-depth ownership check. Returns True only when:
      1. `note_uuid` is a syntactically valid UUID,
      2. a `Note` with that UUID exists in the database,
      3. that `Note` has a `Patient` attached.

    This is NOT a per-staff ACL — Canvas staff sessions already grant broad
    chart access. It exists to refuse writes against tampered or stale
    note_ids that would otherwise let a request scribble AttributeHub rows
    the requester couldn't observe through normal chart navigation. Read
    endpoints stay open (per the plugin's threat model) but every write
    endpoint goes through this gate.
    """
    if not _looks_like_uuid(note_uuid):
        return False
    try:
        note = Note.objects.select_related("patient").get(id=note_uuid)
    except Note.DoesNotExist:
        return False
    return note.patient is not None


def _summarize_effects(effects: list[Effect]) -> dict[str, int]:
    """Bucket emitted command effects by lifecycle so the front-end knows
    whether the save included any deletes (the only case where the host's
    Commands tab fails to live-update).

    Uses plain rebinding (`counts[key] = counts[key] + 1`) instead of
    augmented index assignment because RestrictedPython forbids the latter
    in the plugin sandbox.
    """
    originate = 0
    edit = 0
    delete = 0
    for eff in effects:
        try:
            name = EffectType.Name(eff.type)
        except (ValueError, AttributeError):
            continue
        if name.startswith("ORIGINATE_"):
            originate = originate + 1
        elif name.startswith("EDIT_"):
            edit = edit + 1
        elif name.startswith("DELETE_"):
            delete = delete + 1
    return {"originate": originate, "edit": edit, "delete": delete}


def _coerce_int(value: Any) -> int | None:
    """Round form-supplied numeric strings to int (VitalsCommand wants ints)."""
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _vitals_effects(note_uuid: str, payload: dict) -> list[Effect]:
    """Originate (or edit, on resave) a VitalsCommand for this section."""
    if not note_uuid or not isinstance(payload, dict):
        return []

    nested = payload.get("anthropometrics")
    source: dict[str, Any] = nested if isinstance(nested, dict) else payload

    height = _coerce_int(source.get("height"))
    weight = _coerce_int(source.get("weight"))
    if height is None and weight is None:
        return []

    fields: dict[str, Any] = {}
    if height is not None:
        fields["height"] = height
    if weight is not None:
        fields["weight_lbs"] = weight

    return _originate_or_edit(
        VitalsCommand,
        note_uuid=note_uuid,
        section_id=MEDICAL_CHART_REVIEW_SECTION,
        fields=fields,
    )


def _structured_assessment_effects(
    note_uuid: str, section_id: str, payload: dict,
) -> list[Effect]:
    """Emit StructuredAssessment effects for a questionnaire-backed section.

    `originate()` only creates the command shell — it ignores per-question
    response data. To populate each question's response we have to build the
    command, call `add_response(text=...)` on each `cmd.questions[i]`, then
    call `cmd.edit()`. Pattern adapted from the `freed_scribe` plugin.

    First save: originate (creates the row) + edit (applies responses).
    Resave: edit only (with the previously stashed command_uuid).
    """
    if not note_uuid or section_id not in QUESTIONNAIRE_SECTIONS:
        return []

    questionnaire_id = resolve_questionnaire_id(section_id)
    if not questionnaire_id:
        log.warning(
            f"[NutritionChartingAPI] no Questionnaire registered for section={section_id}; "
            "skipping StructuredAssessment emission"
        )
        return []

    result = summarize_questionnaire_section(section_id, payload)
    field_defs = QUESTIONNAIRE_SECTIONS[section_id]["fields"]

    existing_uuid = _get_originated_command(note_uuid, section_id)
    is_first_save = existing_uuid is None
    command_uuid = existing_uuid or str(uuid.uuid4())

    cmd_kwargs: dict[str, Any] = {
        "note_uuid": note_uuid,
        "command_uuid": command_uuid,
        "questionnaire_id": questionnaire_id,
    }
    if result:
        cmd_kwargs["result"] = result
    cmd = StructuredAssessmentCommand(**cmd_kwargs)

    effects: list[Effect] = []
    if is_first_save:
        effects.append(cmd.originate())
        _record_originated_command(note_uuid, section_id, command_uuid)

    questions = list(cmd.questions or [])

    for idx, (field_id, _label) in enumerate(field_defs):
        if idx >= len(questions):
            break
        raw = payload.get(field_id)
        text = "" if raw is None else str(raw).strip()
        if not text:
            continue
        # `add_response` validates the response against the question's
        # pydantic schema; tolerate per-field validation rejection so one
        # malformed answer doesn't kill the entire section save. Anything
        # else (AttributeError, TypeError) propagates so Sentry sees it.
        try:
            questions[idx].add_response(text=text)
        except ValidationError as exc:
            log.warning(
                f"[NutritionChartingAPI] add_response failed for "
                f"section={section_id} field={field_id}: {exc!r}"
            )

    effects.append(cmd.edit())
    return effects


def _single_command_effects(
    note_uuid: str, section_id: str, payload: dict,
) -> list[Effect]:
    """Originate / edit / delete a single-command section.

    Pass-2 update: if the section is no longer emit-ready (e.g. dietician
    unchecked the "Monitor at team meeting" box) but a command was previously
    originated, we emit a `delete()` so the stale command doesn't linger on
    the note.
    """
    section = SINGLE_COMMAND_SECTIONS.get(section_id)
    if not note_uuid or not section:
        return []

    command_class = section["command_class"]
    existing_uuid = _get_originated_command(note_uuid, section_id)

    if not section["is_emit_ready"](payload):
        if existing_uuid:
            log.info(
                f"[NutritionChartingAPI] section={section_id} no longer emit-ready; "
                "deleting previously-emitted command"
            )
            cmd = command_class(command_uuid=existing_uuid)
            _clear_originated_command(note_uuid, section_id)
            return [cmd.delete()]
        return []

    fields = section["build_kwargs"](payload)
    if not fields:
        return []

    return _originate_or_edit(
        command_class,
        note_uuid=note_uuid,
        section_id=section_id,
        fields=fields,
    )


def _multi_command_effects(
    note_uuid: str, section_id: str, payload: dict,
) -> list[Effect]:
    """Reconcile the multi-command section's rows against the previously-
    originated command map.

    Payload contract: `payload["rows"]` is a list of dicts, each with at
    least a `row_id` and the section's row fields. Reconciliation rules:

      - row in payload + ready  + not in map  -> originate, add to map
      - row in payload + ready  + in map      -> edit (preserve command_uuid)
      - row in payload + !ready + in map      -> delete, remove from map
      - row in payload + !ready + not in map  -> skip (nothing to clean up)
      - row in map but not in payload         -> delete, remove from map
    """
    section = MULTI_COMMAND_SECTIONS.get(section_id)
    if not note_uuid or not section:
        return []

    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = []

    command_class = section["command_class"]
    build_kwargs = section["build_kwargs"]
    is_ready = section["is_row_ready"]

    existing_map: dict[str, str] = dict(_get_multi_command_map(note_uuid, section_id))
    new_map: dict[str, str] = {}
    effects: list[Effect] = []
    seen_row_ids: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("row_id") or "").strip()
        if not row_id or row_id in seen_row_ids:
            continue
        seen_row_ids.add(row_id)

        existing_uuid = existing_map.pop(row_id, None)
        if not is_ready(row):
            if existing_uuid:
                cmd = command_class(command_uuid=existing_uuid)
                effects.append(cmd.delete())
            continue

        fields = build_kwargs(row)
        if not fields:
            # Defensive: builder rejected the row even though it looked ready.
            if existing_uuid:
                cmd = command_class(command_uuid=existing_uuid)
                effects.append(cmd.delete())
            continue

        if existing_uuid:
            cmd = command_class(
                note_uuid=note_uuid, command_uuid=existing_uuid, **fields,
            )
            effects.append(cmd.edit())
            new_map[row_id] = existing_uuid
        else:
            new_uuid = str(uuid.uuid4())
            cmd = command_class(
                note_uuid=note_uuid, command_uuid=new_uuid, **fields,
            )
            effects.append(cmd.originate())
            new_map[row_id] = new_uuid

    # Anything still in existing_map was removed by the dietician — delete it.
    for stale_uuid in existing_map.values():
        cmd = command_class(command_uuid=stale_uuid)
        effects.append(cmd.delete())

    _save_multi_command_map(note_uuid, section_id, new_map)
    return effects


def _originate_or_edit(
    command_cls: type,
    *,
    note_uuid: str,
    section_id: str,
    fields: dict[str, Any],
) -> list[Effect]:
    """Originate the command on first save; on subsequent saves, edit the
    previously originated command in place. Avoids accumulating duplicate
    commands on the note when a dietician saves the same section twice."""
    existing_uuid = _get_originated_command(note_uuid, section_id)
    if existing_uuid:
        cmd = command_cls(note_uuid=note_uuid, command_uuid=existing_uuid, **fields)
        return [cmd.edit()]

    new_uuid = str(uuid.uuid4())
    cmd = command_cls(note_uuid=note_uuid, command_uuid=new_uuid, **fields)
    _record_originated_command(note_uuid, section_id, new_uuid)
    return [cmd.originate()]


class NutritionChartingAPI(StaffSessionAuthMixin, SimpleAPI):
    """Staff-session-only API used by the in-note Nutrition tab front-end.

    Auth is delegated to `StaffSessionAuthMixin` rather than a manual
    `authenticate()` method — the mixin handles None/missing credentials
    and the user-type check uniformly across the SDK.

    Base-class order is load-bearing. `StaffSessionAuthMixin` MUST come
    before `SimpleAPI` so the mixin's `authenticate()` wins via Python's
    MRO. Reversing the bases (or dropping the mixin in a refactor) would
    silently disable auth — `SimpleAPI` would default to "no auth" and
    every endpoint would become anonymous. The `test_charting_api_uses_
    staff_session_mixin` test locks this MRO; do not remove it.
    """

    @api.get("/charting/auto-populate")
    def auto_populate(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id", "")
        log.info(f"[NutritionChartingAPI] auto-populate patient_id={patient_id}")
        # `Patient.DoesNotExist` is handled inside `build_chart_review`;
        # this catch is narrowed to ORM-level errors so AttributeError /
        # TypeError / ImportError after a refactor reach Sentry instead of
        # being swallowed as a generic "auto_populate_failed". The sandbox
        # blocks `from django.db import DatabaseError`, so we catch the
        # base `Exception` and re-raise via `_is_db_error` for the narrow
        # graceful-degradation case.
        try:
            cache: dict[str, Any] = {}
            data = build_chart_review(patient_id, cache=cache)
        except Exception as exc:
            if not _is_db_error(exc):
                raise
            log.error(
                f"[NutritionChartingAPI] auto-populate failed: {exc!r}",
                exc_info=True,
            )
            return [_json(
                {"success": False, "error": "auto_populate_failed"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )]
        return [_json({"success": True, "data": data})]

    @api.get("/charting/form-state")
    def get_form_state(self) -> list[Response | Effect]:
        note_id = self.request.query_params.get("note_id", "")
        state = _get_form_state(note_id)
        return [_json({"success": True, **state})]

    @api.get("/charting/refer-search")
    def refer_search(self) -> list[Response | Effect]:
        """Typeahead for the referral row's "Refer to" field. Searches the
        instance's ServiceProvider directory by first/last name + practice.
        Returns at most `_REFER_SEARCH_LIMIT` rows so the dropdown stays
        bounded; the dietician can refine the query if their target isn't
        in the first page.
        """
        q = (self.request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return [_json({"success": True, "results": []})]

        qs = (
            ServiceProviderRecord.objects.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(practice_name__icontains=q),
            )
            .order_by("last_name", "first_name")[:_REFER_SEARCH_LIMIT]
        )
        results = [
            {
                "id": str(p.id),
                "first_name": p.first_name or "",
                "last_name": p.last_name or "",
                "specialty": p.specialty or "",
                "practice_name": p.practice_name or "",
                "label": p.full_name_and_specialty,
            }
            for p in qs
        ]
        return [_json({"success": True, "results": results})]

    @api.post("/charting/save")
    def save_section(self) -> list[Response | Effect]:
        section = self.request.query_params.get("section", "")
        note_uuid = self.request.query_params.get("note_id", "")
        # `request.json()` raises `json.JSONDecodeError` (a `ValueError`
        # subclass) on malformed payloads. Narrowed to `ValueError` so any
        # other failure (AttributeError on a renamed attr, etc.) propagates
        # to Sentry instead of getting silently 400'd as "invalid_json".
        try:
            body = self.request.json()
        except ValueError:
            return [_json(
                {"success": False, "error": "invalid_json"},
                HTTPStatus.BAD_REQUEST,
            )]
        if not isinstance(body, dict):
            return [_json(
                {"success": False, "error": "body_must_be_object"},
                HTTPStatus.BAD_REQUEST,
            )]
        if not section:
            return [_json(
                {"success": False, "error": "section_required"},
                HTTPStatus.BAD_REQUEST,
            )]

        # Ownership gate (Risk #3): every write goes through
        # `_staff_has_note_access`, which verifies the note exists AND has a
        # patient attached. Returns 403 access_denied uniformly so the
        # response doesn't leak whether the note exists vs. is patient-less.
        if not _staff_has_note_access(note_uuid):
            log.warning(
                f"[NutritionChartingAPI] save refused — access denied "
                f"section={section} note_uuid={note_uuid!r}"
            )
            return [_json(
                {"success": False, "error": "access_denied"},
                HTTPStatus.FORBIDDEN,
            )]

        # Visit type is part of the page-level state; persisted alongside
        # sections but kept out of the section payload to avoid duplication.
        # We piggyback the visit-type write onto save_section so both writes
        # hit the same AttributeHub fetch (saves one redundant get_or_create).
        visit_type = body.pop("visit_type", None)
        _save_section(
            note_uuid, section, body,
            visit_type=visit_type if isinstance(visit_type, str) else None,
        )
        log.info(
            f"[NutritionChartingAPI] save section={section} note={note_uuid} "
            f"keys={sorted(body.keys())}"
        )

        emitted: list[Effect] = []
        if section == MEDICAL_CHART_REVIEW_SECTION:
            emitted.extend(_vitals_effects(note_uuid, body))
        elif section in QUESTIONNAIRE_SECTIONS:
            emitted.extend(_structured_assessment_effects(note_uuid, section, body))
        elif section in SINGLE_COMMAND_SECTIONS:
            emitted.extend(_single_command_effects(note_uuid, section, body))
        elif section in MULTI_COMMAND_SECTIONS:
            emitted.extend(_multi_command_effects(note_uuid, section, body))

        # Surface the originate / edit / delete counts so the front-end can
        # show a "↻ Refresh to see changes" affordance after a destructive
        # save. Canvas live-updates the Commands tab for ORIGINATE/EDIT but
        # not DELETE, so a delete count > 0 is the only case where the
        # dietician needs to refresh.
        ack: dict[str, Any] = {
            "success": True,
            "section": section,
            "effects": _summarize_effects(emitted),
        }
        return [_json(ack), *emitted]


class PrintNutritionNoteAPI(SimpleAPI):
    """Print API. Falls back to `simple-api-key` when no staff session is active.

    Hybrid auth (staff session OR API key) doesn't fit a single SDK mixin,
    so the `authenticate()` method stays manual. The API key branch uses
    `hmac.compare_digest` for constant-time comparison so the secret can't
    be deduced byte-by-byte through response-timing measurement.
    """

    def authenticate(self, credentials: Credentials) -> bool:
        if _staff_session_authenticated(self.request):
            return True

        api_key_secret = self.secrets.get("simple-api-key")
        request_auth_key = self.request.headers.get("Authorization")
        if not api_key_secret or not request_auth_key:
            log.warning(
                "[PrintNutritionNoteAPI] auth failure: no staff session and "
                "no Authorization header / api-key secret configured"
            )
            return False
        if compare_digest(api_key_secret.encode(), request_auth_key.encode()):
            return True
        log.warning(
            "[PrintNutritionNoteAPI] auth failure: Authorization header "
            "did not match the configured simple-api-key"
        )
        return False

    @api.get("/print/")
    def index(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id", "")
        note_id = self.request.query_params.get("note_id", "")
        log.info(f"[PrintNutritionNoteAPI] render patient={patient_id} note={note_id}")
        # Narrow to ORM-level errors so AttributeError / TypeError /
        # ImportError after a refactor surface in Sentry instead of being
        # rendered as a "render failed" page indistinguishable from a
        # transient DB hiccup. See `_is_db_error` for why the catch is
        # broad-then-filter rather than `except DatabaseError`.
        try:
            payload = build_print_payload(note_id, patient_id)
        except Exception as exc:
            if not _is_db_error(exc):
                raise
            log.error(
                f"[PrintNutritionNoteAPI] payload assembly failed: {exc!r}",
                exc_info=True,
            )
            return [HTMLResponse(
                _print_error_page(str(exc)), status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )]
        # Practice info is per-customer config — read from secrets so each
        # Canvas instance can carry its own name/address/phone/fax without
        # a code change.
        payload["practice"] = {
            "name": self.secrets.get("practice-name") or "",
            "address": self.secrets.get("practice-address") or "",
            "phone": self.secrets.get("practice-phone") or "",
            "fax": self.secrets.get("practice-fax") or "",
        }
        html = render_print_html(payload)
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]


def _print_error_page(message: str) -> str:
    """Minimal fallback HTML when payload assembly throws — keeps the modal
    from showing a blank page so the dietician sees something actionable."""
    safe = message.replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Nutrition Note — error</title>"
        "<style>body{font-family:-apple-system,sans-serif;padding:32px;color:#222;}"
        ".err{padding:16px;border:1px solid #ef9a9a;background:#ffebee;border-radius:6px;}"
        "</style></head><body>"
        "<h1>Nutrition Note — render failed</h1>"
        f"<div class='err'><p>The print view couldn't be assembled:</p><pre>{safe}</pre></div>"
        "</body></html>"
    )
