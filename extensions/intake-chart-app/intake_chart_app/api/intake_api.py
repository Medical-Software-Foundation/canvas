"""IntakeAPI - SimpleAPI handlers for the Intake tab.

Routes:
  - GET  /intake/form-state?note_id=...                load saved drafts
  - POST /intake/section/save?section=...&note_id=...  persist a section's draft
  - POST /intake/commit?note_id=...                    commit drafts as
                                                       Canvas commands

Auth: ``StaffSessionAuthMixin`` — staff session only, no API-key
fallback.
"""
from __future__ import annotations

import json
import uuid
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from urllib.parse import urlencode

from canvas_sdk.utils.http import Http, ontologies_http
from requests import exceptions as requests_exceptions
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import Questionnaire
from logger import log

from intake_chart_app.data.form_state import (
    FormStateSnapshot,
    get_all_section_drafts as _get_all_section_drafts,
    set_section as _set_section,
)
from intake_chart_app.data.multi_command_sections import (
    SECTIONS as MULTI_COMMAND_SECTIONS,
    MultiCommandSection,
)
from intake_chart_app.data.single_command_sections import (
    SECTIONS as SINGLE_COMMAND_SECTIONS,
    SingleCommandSection,
)

# Cap on the JSON-serialised size of a section's draft. The modal's
# worst-case payload (e.g. all six multi-row sections with a couple dozen
# rows each) is well under 100 KB; anything past 500 KB indicates a runaway
# client (large pasted text, malformed loop) and shouldn't be persisted.
_MAX_SECTION_PAYLOAD_BYTES = 500_000

# Static assets are rendered from Django templates that take no context,
# so the encoded bytes can be cached after the first request — every
# subsequent request would otherwise re-run render_to_string + UTF-8 encode
# on identical input. Cannot prime at module load: render_to_string
# requires plugin context, which is only available inside a handler. The
# cache survives until the worker restarts (plugin reinstall, etc).
_static_cache: dict[str, bytes] = {}


def _cached_static(template_name: str) -> bytes:
    cached = _static_cache.get(template_name)
    if cached is not None:
        return cached
    # ``render_to_string`` is typed loosely in the SDK shim; the encoded
    # result is concretely ``bytes`` so a local annotation pins the
    # return type for mypy.
    rendered: bytes = render_to_string(template_name).encode()
    _static_cache[template_name] = rendered
    return rendered


def _json(body: Any, status: HTTPStatus = HTTPStatus.OK) -> JSONResponse:
    """Wrap a JSON-serialisable payload as a JSONResponse. JSONResponse may
    carry canvas-app signaling metadata (CSRF, refresh headers) that raw
    Response does not.

    ``body`` is intentionally ``Any``: the search endpoints return JSON
    arrays (``[count, ids, None, rows]`` per the NLM Clinical Tables shape)
    while the form-state and commit endpoints return objects.
    """
    return JSONResponse(body, status_code=status)


def _looks_like_uuid(value: str) -> bool:
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _note_exists(note_uuid: str) -> bool:
    if not _looks_like_uuid(note_uuid):
        return False
    return bool(Note.objects.filter(id=note_uuid).exists())


def _summarize_effects(effects: list[Effect]) -> dict[str, int]:
    """Bucket emitted command effects by lifecycle for the front-end."""
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


def _commit_single_section(
    note_uuid: str,
    section: SingleCommandSection,
    snapshot: FormStateSnapshot,
) -> tuple[list[Effect], dict[str, str] | None]:
    """Originate (first commit) or edit (subsequent commits) one
    single-command section. Returns ``(effects, error)`` — ``error`` is
    ``None`` on success or a ``{"section": ..., "error": ...}`` dict on
    failure (so the caller can short-circuit; commit is all-or-nothing).

    The ``snapshot`` mediates every AttributeHub read/write so multiple
    section commits share one materialised hub view.
    """
    draft = snapshot.get_section(section.section_id)
    if not section.is_emit_ready(draft):
        return [], None

    kwargs = section.build_kwargs(draft)
    if not kwargs:
        return [], None

    existing_uuid = snapshot.get_originated_command(section.section_id)
    try:
        if existing_uuid:
            cmd = section.command_class(
                note_uuid=note_uuid, command_uuid=existing_uuid, **kwargs
            )
            effect = cmd.edit()
            log.info(
                f"[IntakeAPI] commit section={section.section_id} edit "
                f"command_uuid={existing_uuid}"
            )
        else:
            new_uuid = str(uuid.uuid4())
            cmd = section.command_class(
                note_uuid=note_uuid, command_uuid=new_uuid, **kwargs
            )
            effect = cmd.originate()
            snapshot.set_originated_command(section.section_id, new_uuid)
            log.info(
                f"[IntakeAPI] commit section={section.section_id} originate "
                f"command_uuid={new_uuid}"
            )
        return [effect], None
    except (ValueError, TypeError) as exc:
        log.error(
            f"[IntakeAPI] commit section={section.section_id} failed: {exc!r}"
        )
        return [], {"section": section.section_id, "error": str(exc)}


# In-process cache of questionnaire_code -> Questionnaire UUID. The bundled
# row is created by Canvas on plugin install and doesn't change between
# plugin reloads, so caching the lookup avoids a DB hit per commit.
_questionnaire_id_cache: dict[str, str] = {}


def _resolve_questionnaire_id(code: str) -> str | None:
    """Return the Canvas Questionnaire UUID for a YAML-bundled INTERNAL code,
    or None if no matching row exists (most commonly: the plugin was just
    installed and the questionnaire row hasn't been created yet, or the YAML
    was hand-deleted from the manifest)."""
    if not code:
        return None
    if code in _questionnaire_id_cache:
        return _questionnaire_id_cache[code]
    row = (
        Questionnaire.objects.filter(code=code, code_system="INTERNAL")
        .order_by("-modified")
        .first()
    )
    if row is None:
        return None
    qid = str(row.id)
    _questionnaire_id_cache[code] = qid
    return qid


def _commit_questionnaire_section(
    note_uuid: str,
    section: SingleCommandSection,
    snapshot: FormStateSnapshot,
) -> tuple[list[Effect], dict[str, str] | None]:
    """Originate (first commit) or edit (subsequent) a questionnaire-backed
    single-command section.

    Differs from ``_commit_single_section`` in three ways:
      1. Resolves the bundled ``questionnaire_id`` at commit time by
         INTERNAL ``code`` lookup (cached in-process).
      2. First save emits originate() + edit() — two effects. The
         originate() creates the empty command row; ``cmd.questions`` is
         then a populated list of ``BaseQuestion`` instances we can call
         ``add_response()`` on; edit() applies those responses.
      3. Per-question ``add_response`` failures are caught + logged so one
         malformed answer doesn't kill the section save.

    Returns ``(effects, error)``. ``error`` is ``None`` on success or a
    ``{"section": ..., "error": ...}`` dict (so the caller can short-
    circuit; commit is all-or-nothing).
    """
    draft = snapshot.get_section(section.section_id)
    if not section.is_emit_ready(draft):
        return [], None

    questionnaire_code = getattr(section, "questionnaire_code", "")
    questionnaire_id = _resolve_questionnaire_id(questionnaire_code)
    if not questionnaire_id:
        log.warning(
            f"[IntakeAPI] commit section={section.section_id} skipped — "
            f"no Questionnaire row for code={questionnaire_code!r}"
        )
        return [], None

    kwargs = section.build_kwargs(draft)
    answers: dict[str, str] = kwargs.get("answers", {}) if isinstance(kwargs, dict) else {}

    existing_uuid = snapshot.get_originated_command(section.section_id)
    is_first_save = existing_uuid is None
    command_uuid = existing_uuid or str(uuid.uuid4())

    try:
        cmd = section.command_class(
            note_uuid=note_uuid,
            command_uuid=command_uuid,
            questionnaire_id=questionnaire_id,
        )
    except (ValueError, TypeError) as exc:
        log.error(
            f"[IntakeAPI] commit section={section.section_id} failed: {exc!r}"
        )
        return [], {"section": section.section_id, "error": str(exc)}

    effects: list[Effect] = []
    if is_first_save:
        effects.append(cmd.originate())
        snapshot.set_originated_command(section.section_id, command_uuid)
        log.info(
            f"[IntakeAPI] commit section={section.section_id} originate "
            f"command_uuid={command_uuid}"
        )

    # Walk the bundled questions matching by INTERNAL code; for each filled
    # answer, dispatch to add_response by question type (radio = pick the
    # option whose value matches; text = pass through).
    questions = list(cmd.questions or [])
    questions_by_code: dict[str, Any] = {}
    for q in questions:
        code = (q.coding or {}).get("code", "") if isinstance(q.coding, dict) else ""
        if code:
            questions_by_code[code] = q

    for question_code, raw_value in answers.items():
        q = questions_by_code.get(question_code)
        if q is None:
            log.warning(
                f"[IntakeAPI] commit section={section.section_id} unknown "
                f"question_code={question_code!r}; skipping"
            )
            continue
        # Dispatch by the question's declared type rather than by
        # ``len(options) > 0``: a TXT question carries a placeholder option
        # in our bundled YAML (to satisfy the JSON schema's responses
        # ``minItems: 1`` rule), so a presence-check would route TXT picks
        # through the radio branch, find no matching option value, and skip
        # the answer entirely — losing the Details textarea on every commit.
        q_type = getattr(q, "type", "") or ""
        try:
            if q_type == "SING":
                options = list(getattr(q, "options", []) or [])
                picked = next(
                    (opt for opt in options if getattr(opt, "value", None) == raw_value),
                    None,
                )
                if picked is None:
                    log.warning(
                        f"[IntakeAPI] commit section={section.section_id} no "
                        f"option matched question_code={question_code!r} "
                        f"value={raw_value!r}; skipping"
                    )
                    continue
                q.add_response(option=picked)
            elif q_type == "TXT":
                q.add_response(text=str(raw_value))
            else:
                # Unknown / unsupported (INT, MULT, …): skip silently. The
                # SocialHistorySection only emits SING/TXT today so this is
                # purely defensive.
                log.warning(
                    f"[IntakeAPI] commit section={section.section_id} "
                    f"unsupported question type={q_type!r} for "
                    f"question_code={question_code!r}; skipping"
                )
        except (ValueError, TypeError) as exc:
            log.warning(
                f"[IntakeAPI] commit section={section.section_id} "
                f"add_response failed question_code={question_code!r}: {exc!r}"
            )

    try:
        effects.append(cmd.edit())
    except (ValueError, TypeError) as exc:
        log.error(
            f"[IntakeAPI] commit section={section.section_id} edit failed: {exc!r}"
        )
        return [], {"section": section.section_id, "error": str(exc)}

    log.info(
        f"[IntakeAPI] commit section={section.section_id} effects={len(effects)} "
        f"questionnaire_id={questionnaire_id}"
    )
    return effects, None


# Map our internal section_id to the home-app's ChartSectionReview.section
# string value. The home-app DRF endpoint accepts these literal strings
# (matching ChartSectionReview.SECTION_CONDITIONS etc. in
# api/models/chart_section_review.py).
_REVIEW_SECTION_BY_ID: dict[str, str] = {
    "problems": "conditions",
    "allergies": "allergies",
    "medications": "medications",
}

# Host-suffix allowlist for the Host-header fallback when the
# ``canvas-instance-origin`` secret is unset. The review POST forwards the
# staff session cookie, so the destination URL must be a vetted Canvas
# instance — without this check, a malicious Host header could redirect the
# cookie-bearing request to an attacker-controlled origin.
_CANVAS_HOST_SUFFIXES: tuple[str, ...] = (
    ".canvasmedical.com",
)


def _safe_canvas_origin(secret_origin: str, host_header: str) -> str:
    """Resolve the home-app origin used for the ChartSectionReview POST.

    Order:
      1. Operator-configured ``canvas-instance-origin`` secret. Admins set
         this explicitly per install — trusted.
      2. Request's ``Host`` header, but only when its bare hostname ends
         with a known Canvas suffix (see ``_CANVAS_HOST_SUFFIXES``). This
         keeps the convenience of zero-config installs without letting an
         attacker-influenced Host steer the cookie-bearing review POST to
         a non-Canvas server.

    Returns ``""`` when no safe origin is available; ``_post_section_review``
    treats empty as "skip this side-channel" and logs a warning, so an
    unknown Host produces a logged no-op rather than a leaked cookie.
    """
    cleaned = (secret_origin or "").strip().rstrip("/")
    if cleaned:
        return cleaned
    host = (host_header or "").strip()
    if not host:
        return ""
    # ``urlsplit`` from urllib.parse isn't on Canvas's RestrictedPython
    # allowlist, so do the port strip manually. IPv6 literals (which
    # contain ``:``) get mangled by this split, but the suffix check
    # below still rejects them because no IPv6 hostname ends with a
    # Canvas suffix.
    bare = host.split(":", 1)[0].lower()
    if not bare:
        return ""
    for suffix in _CANVAS_HOST_SUFFIXES:
        if bare.endswith(suffix):
            return f"https://{host}"
    log.warning(
        f"[IntakeAPI] refusing Host fallback for review POST — "
        f"Host={host!r} does not match Canvas suffix"
    )
    return ""

# AttributeHub key suffix for the per-section ChartSectionReviewCommand uuid.
# Stored under ``command:<section_id>:reviewed`` (sharing FormState's
# get_originated_command/set_originated_command path).
_REVIEW_STATE_SUFFIX = ":reviewed"


def _all_rows_confirmed(rows: dict[str, Any]) -> bool:
    """Every row's action is ``confirm`` (the default). True when the MA
    didn't engage with any row's edit/remove affordance and didn't add new
    rows."""
    for row in rows.values():
        action = (row.get("action") if isinstance(row, dict) else "") or "confirm"
        if action.lower() != "confirm":
            return False
    return True


def _post_section_review(
    note_uuid: str,
    section_id: str,
    *,
    instance_origin: str,
    forwarded_cookie: str,
    note: Note | None = None,
) -> bool:
    """Mark a section as reviewed by POSTing to the same home-app DRF
    endpoint the chart sidebar's "Mark as Reviewed" button uses.

    Plugin Effects emitting ``ORIGINATE_CHART_SECTION_REVIEW_COMMAND`` only
    create a generic ``Command`` row and never invoke
    ``api/models/chart_section_review.ChartSectionReview.save()`` — the
    method that auto-populates ``entries`` (active items at review time)
    and ``content`` (the rendered display text). Without those fields, the
    Commands tab card renders empty / not at all.

    Hitting the REST endpoint runs the model's ``save()`` override, which
    is what produces the rich "Reviewed: <Section>" card listing each
    item. The user's incoming session cookie is forwarded so the request
    authenticates as the staff member who clicked Commit.

    Security envelope on the forwarded cookie:
      - Source: the cookie comes from the request that already passed
        ``StaffSessionAuthMixin`` at the ``/intake/commit`` boundary, so
        no attacker-influenced cookie can reach this helper.
      - Scope: forwarding preserves the staff's existing chart-write
        permissions; it does NOT elevate. ``ChartSectionReview.save()``
        runs as that same staff member on the home-app side.
      - Destination: gated upstream by ``_safe_canvas_origin``, which
        rejects any ``Host`` not matching ``.canvasmedical.com`` (unless
        the operator explicitly set ``canvas-instance-origin``). The
        cookie can only travel to a Canvas-owned origin.
      - Logging: only ``bool(forwarded_cookie)`` is ever logged here;
        the cookie value itself is never written to logs or telemetry.
      - CSRF: no surface — the request originates from the authenticated
        session itself, not from an external referrer.

    Pass ``note`` to skip the per-section ``Note.objects.get`` — the
    ``commit()`` entry point pre-fetches the row once for all sections.

    Returns ``True`` on 2xx, ``False`` otherwise (logged but not raised so
    one section's failure doesn't drag the others down).
    """
    review_section = _REVIEW_SECTION_BY_ID.get(section_id)
    if not review_section:
        return False
    if not instance_origin or not forwarded_cookie:
        log.warning(
            f"[IntakeAPI] skip review for section={section_id}: "
            f"missing origin={bool(instance_origin)} cookie={bool(forwarded_cookie)}"
        )
        return False

    if note is None:
        try:
            note = Note.objects.select_related("patient").get(id=note_uuid)
        except Note.DoesNotExist:
            log.warning(
                f"[IntakeAPI] skip review for section={section_id}: "
                f"note not found {note_uuid!r}"
            )
            return False

    payload = {
        "patient": note.patient.dbid,
        "note": note.dbid,
        "section": review_section,
    }
    url = f"{instance_origin.rstrip('/')}/ChartSectionReview/"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Cookie": forwarded_cookie,
    }
    try:
        resp = Http().post(url, json=payload, headers=headers)
    except requests_exceptions.RequestException as exc:
        log.error(
            f"[IntakeAPI] review POST failed section={section_id} "
            f"url={url}: {exc!r}"
        )
        return False

    status = getattr(resp, "status_code", 0)
    if 200 <= status < 300:
        log.info(
            f"[IntakeAPI] commit section={section_id} review-posted "
            f"section_value={review_section!r} status={status}"
        )
        return True
    log.warning(
        f"[IntakeAPI] review POST non-2xx section={section_id} "
        f"status={status} body={getattr(resp, 'text', '')[:300]!r}"
    )
    return False


def _commit_multi_section(
    note_uuid: str,
    section: MultiCommandSection,
    snapshot: FormStateSnapshot,
) -> tuple[list[Effect], dict[str, str] | None]:
    """Walk a multi-command section's draft rows + recorded command-uuid map
    through the section's reconciler. If the section had pre-filled rows but
    the MA only confirmed them (no edit/remove/add), stage a deferred
    ``ChartSectionReview`` POST on the snapshot — the dispatch only fires
    after ``commit()`` clears its failures gate, mirroring the
    AttributeHub-buffering pattern."""
    draft = snapshot.get_section(section.section_id)
    rows = draft.get("rows") if isinstance(draft, dict) else None
    if not isinstance(rows, dict) or not rows:
        return [], None

    prior_map = snapshot.get_multi_command_map(section.section_id)
    try:
        effects, new_map = section.reconcile(note_uuid, rows, prior_map)
    except (ValueError, TypeError) as exc:
        log.error(
            f"[IntakeAPI] commit section={section.section_id} failed: {exc!r}"
        )
        return [], {"section": section.section_id, "error": str(exc)}

    if effects:
        snapshot.set_multi_command_map(section.section_id, new_map)
        log.info(
            f"[IntakeAPI] commit section={section.section_id} "
            f"rows={len(rows)} effects={len(effects)} map_size={len(new_map)}"
        )
        return effects, None

    # No per-row effects: every row was Confirm. Stage a ChartSectionReview
    # POST so commit() can fire it after the all-or-nothing failures gate
    # passes. Doing the POST inline would land partial review records on
    # the chart even when a later section fails — the home-app endpoint
    # is not idempotent, so a retry would then duplicate them.
    if _all_rows_confirmed(rows):
        snapshot.stage_review(section.section_id)

    return [], None


def _dispatch_pending_reviews(
    snapshot: FormStateSnapshot,
    *,
    note_uuid: str,
    note: Note,
    instance_origin: str,
    forwarded_cookie: str,
) -> None:
    """Walk every section_id ``stage_review``'d during this commit and
    POST a ``ChartSectionReview`` for each. Called only after the
    failures gate; per-POST errors log a warning via
    ``_post_section_review`` but do not roll back the AttributeHub
    flush — failed reviews are recoverable (the MA can hit "Mark as
    Reviewed" on the chart sidebar manually)."""
    pending = snapshot.pending_review_section_ids
    if not pending:
        return
    for section_id in pending:
        _post_section_review(
            note_uuid,
            section_id,
            instance_origin=instance_origin,
            forwarded_cookie=forwarded_cookie,
            note=note,
        )
    snapshot.clear_pending_reviews()


class IntakeAPI(StaffSessionAuthMixin, SimpleAPI):
    """Form-state load/save + commit for the Intake modal."""

    @api.get("/intake/form-state")
    def get_form_state(self) -> list[Response | Effect]:
        """Return every known section's draft for this note.

        One AttributeHub fetch + one queryset materialisation of its custom
        attributes; the section-id filtering happens in Python. The previous
        implementation issued a separate hub lookup per known section, which
        scaled linearly with the SECTIONS list.
        """
        note_uuid = self.request.query_params.get("note_id", "")
        if not note_uuid:
            return [_json(
                {"success": False, "error": "note_id_required"},
                HTTPStatus.BAD_REQUEST,
            )]

        return [_json({
            "success": True,
            "note_uuid": note_uuid,
            "sections": _get_all_section_drafts(note_uuid),
        })]

    @api.get("/intake/search/medication")
    def search_medication(self) -> list[Response | Effect]:
        """Server-side proxy to Canvas's ontologies FDB grouped-medication
        search. Returns NLM Clinical Tables shaped JSON so the shared
        client-side search parser in intake.js consumes it the same way as
        the ICD-10 endpoint:

            [count, [med_id, ...], null, [[description], ...]]

        The picked code (``fdb_code``) needs to be ``med_medication_id``
        from the FDB record — not an RxCUI — for the resulting
        ``MedicationStatementCommand`` to resolve a medication name.
        """
        term = (self.request.query_params.get("q", "") or "").strip()
        if not term:
            return [_json([0, [], None, []])]
        try:
            # get_json returns a Response object (the name is a historical
            # misnomer — see prescription_favorites' usage). Call .json() to
            # parse the body to a dict.
            response = ontologies_http.get_json(
                f"/fdb/grouped-medication/?{urlencode({'search': term})}"
            )
            payload = response.json() if response is not None else {}
        except requests_exceptions.RequestException as exc:
            log.warning(f"[IntakeAPI] medication search failed term={term!r}: {exc!r}")
            return [_json([0, [], None, []])]
        results = payload.get("results", []) if isinstance(payload, dict) else []
        ids: list[str] = []
        rows: list[list[str]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            med_id = str(r.get("med_medication_id") or "").strip()
            if not med_id:
                continue
            ids.append(med_id)
            rows.append([str(r.get("med_medication_description") or "")])
        return [_json([len(ids), ids, None, rows])]

    @api.get("/intake/search/allergy")
    def search_allergy(self) -> list[Response | Effect]:
        """Server-side proxy to Canvas's ontologies FDB allergy search.

        Returns NLM Clinical Tables shaped JSON so the shared client-side
        search parser in intake.js consumes it the same way as ICD-10 /
        medication results:

            [count, ["<concept_id>|<concept_type>", ...], null, [[description], ...]]

        AllergyCommand expects an ``Allergen(concept_id, concept_type)`` —
        not a free-text string — to render an allergen name in the note.
        Both numbers come from the FDB record; we encode them as a
        ``concept_id|concept_type`` compound code in the hidden field and
        the reconciler splits them back apart. concept_type is filtered to
        the three AllergenType values the SDK accepts: 1, 2, 6.
        """
        term = (self.request.query_params.get("q", "") or "").strip()
        if not term:
            return [_json([0, [], None, []])]
        try:
            response = ontologies_http.get_json(
                f"/fdb/allergy/?{urlencode({'dam_allergen_concept_id_description__fts': term})}"
            )
            payload = response.json() if response is not None else {}
        except requests_exceptions.RequestException as exc:
            log.warning(f"[IntakeAPI] allergy search failed term={term!r}: {exc!r}")
            return [_json([0, [], None, []])]
        results = payload.get("results", []) if isinstance(payload, dict) else []
        allowed_types = {1, 2, 6}
        ids: list[str] = []
        rows: list[list[str]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            concept_id = r.get("dam_allergen_concept_id")
            concept_type = r.get("dam_allergen_concept_id_type")
            if concept_id is None or concept_type not in allowed_types:
                continue
            ids.append(f"{int(concept_id)}|{int(concept_type)}")
            rows.append([str(r.get("dam_allergen_concept_id_description") or "")])
        return [_json([len(ids), ids, None, rows])]

    @api.get("/intake/static/intake.css")
    def get_intake_css(self) -> list[Response | Effect]:
        """Serve the intake modal stylesheet."""
        return [Response(
            _cached_static("templates/intake.css"),
            status_code=HTTPStatus.OK,
            content_type="text/css; charset=utf-8",
        )]

    @api.get("/intake/static/intake.js")
    def get_intake_js(self) -> list[Response | Effect]:
        """Serve the intake modal JavaScript. The script reads its runtime
        config (note_uuid, API base) from a json_script tag rendered by
        the HTML template, so it carries no per-note state itself."""
        return [Response(
            _cached_static("templates/intake.js"),
            status_code=HTTPStatus.OK,
            content_type="text/javascript; charset=utf-8",
        )]

    @api.post("/intake/section/save")
    def save_section(self) -> list[Response | Effect]:
        """Persist a section's draft to AttributeHub."""
        section = self.request.query_params.get("section", "")
        note_uuid = self.request.query_params.get("note_id", "")
        if not section or not note_uuid:
            return [_json(
                {"success": False, "error": "section_and_note_id_required"},
                HTTPStatus.BAD_REQUEST,
            )]
        try:
            body = self.request.json()
        except (ValueError, UnicodeDecodeError):
            # JSON parse failure (ValueError covers json.JSONDecodeError)
            # or non-UTF-8 request body.
            return [_json(
                {"success": False, "error": "invalid_json"},
                HTTPStatus.BAD_REQUEST,
            )]
        if not isinstance(body, dict):
            return [_json(
                {"success": False, "error": "body_must_be_object"},
                HTTPStatus.BAD_REQUEST,
            )]

        # Cap the payload before it hits AttributeHub. A normal full-form
        # draft is < 100 KB; anything past 500 KB is a runaway client.
        try:
            payload_size = len(json.dumps(body, default=str))
        except (TypeError, ValueError):
            return [_json(
                {"success": False, "error": "body_not_serialisable"},
                HTTPStatus.BAD_REQUEST,
            )]
        if payload_size > _MAX_SECTION_PAYLOAD_BYTES:
            log.warning(
                f"[IntakeAPI] save refused — payload too large "
                f"section={section} note={note_uuid} bytes={payload_size}"
            )
            return [_json(
                {
                    "success": False,
                    "error": "payload_too_large",
                    "limit_bytes": _MAX_SECTION_PAYLOAD_BYTES,
                },
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )]

        # Defense-in-depth: refuse to write to AttributeHub for a note_uuid
        # that doesn't resolve to a real Note. Mirrors nutrition_charting.
        if not _note_exists(note_uuid):
            log.warning(
                f"[IntakeAPI] save refused — note not found "
                f"section={section} note_uuid={note_uuid!r}"
            )
            return [_json(
                {"success": False, "error": "note_not_found"},
                HTTPStatus.NOT_FOUND,
            )]

        _set_section(note_uuid, section, body)
        log.info(
            f"[IntakeAPI] save section={section} note={note_uuid} "
            f"keys={sorted(body.keys())}"
        )
        return [_json({"success": True, "section": section})]

    @api.post("/intake/commit")
    def commit(self) -> list[Response | Effect]:
        """Walk every section's draft and emit the right command effects.

        All-or-nothing. If any section's commit raises a validation
        error, the response carries ``{"success": false}`` with the
        failures and **no effects** are returned (so partial writes
        don't land on the note).
        """
        note_uuid = self.request.query_params.get("note_id", "")
        if not note_uuid:
            return [_json(
                {"success": False, "error": "note_id_required"},
                HTTPStatus.BAD_REQUEST,
            )]
        if not _looks_like_uuid(note_uuid):
            log.warning(
                f"[IntakeAPI] commit refused — invalid note_uuid={note_uuid!r}"
            )
            return [_json(
                {"success": False, "error": "note_not_found"},
                HTTPStatus.NOT_FOUND,
            )]
        # Pre-fetch the Note (with patient joined) once for the whole
        # commit. The previous code called `_note_exists` here AND let
        # `_post_section_review` re-fetch the Note for every confirmed
        # multi-section — up to 3 redundant lookups per commit.
        try:
            note = Note.objects.select_related("patient").get(id=note_uuid)
        except Note.DoesNotExist:
            log.warning(
                f"[IntakeAPI] commit refused — note not found "
                f"note_uuid={note_uuid!r}"
            )
            return [_json(
                {"success": False, "error": "note_not_found"},
                HTTPStatus.NOT_FOUND,
            )]

        # Single AttributeHub fetch + one materialisation of every saved
        # attribute. All section helpers read + write through this
        # snapshot, replacing ~20 redundant hub lookups per commit.
        snapshot = FormStateSnapshot(note_uuid)

        # Build the home-app origin for the chart-section-review POST.
        # ``_safe_canvas_origin`` prefers the operator-configured secret and
        # only falls back to the Host header when it points at a known
        # Canvas suffix — without that check, an attacker-influenced Host
        # could steer this cookie-bearing POST to a non-Canvas server. The
        # forwarded cookie authenticates the side-channel POST as the same
        # staff member who clicked Commit.
        instance_origin = _safe_canvas_origin(
            self.secrets.get("canvas-instance-origin", ""),
            self.request.headers.get("Host", ""),
        )
        forwarded_cookie = self.request.headers.get("Cookie", "")

        all_effects: list[Effect] = []
        failures: list[dict[str, str]] = []
        # No outer try/except around this loop on purpose. Per-section
        # helpers return ``(effects, error)`` tuples for *expected*
        # validation failures (collected in ``failures`` and surfaced as
        # the structured ``{success: false}`` ack below). Anything that
        # raises here is unexpected — SDK drift, malformed snapshot
        # data, programmer error — and MUST propagate to the runtime so
        # Sentry sees it. The all-or-nothing invariant is preserved by
        # structure: ``snapshot.flush()`` and ``_dispatch_pending_reviews``
        # only run after this loop exits cleanly, so an uncaught
        # exception leaves zero partial side effects on AttributeHub or
        # the home-app. Do not "harden" this with a blanket
        # ``except Exception`` — that would silently bury bugs.
        for section in SINGLE_COMMAND_SECTIONS:
            if getattr(section, "questionnaire_code", ""):
                section_effects, error = _commit_questionnaire_section(
                    note_uuid, section, snapshot,
                )
            else:
                section_effects, error = _commit_single_section(
                    note_uuid, section, snapshot,
                )
            if error:
                failures.append(error)
            else:
                all_effects.extend(section_effects)
        for multi_section in MULTI_COMMAND_SECTIONS:
            section_effects, error = _commit_multi_section(
                note_uuid,
                multi_section,
                snapshot,
            )
            if error:
                failures.append(error)
            else:
                all_effects.extend(section_effects)

        if failures:
            # All-or-nothing: drop the effects list, skip the snapshot
            # flush, AND skip the staged review-POST dispatch. Any UUIDs
            # staged by earlier successful sections never land on
            # AttributeHub, and any ChartSectionReview rows staged by
            # all-confirmed multi-sections never reach the home-app — so
            # the retry sees a clean slate (no `existing_uuid` truthy, no
            # phantom Reviewed cards) and each section takes the
            # originate() path again.
            return [_json(
                {"success": False, "failures": failures},
                HTTPStatus.BAD_REQUEST,
            )]

        # Every section succeeded — persist staged UUID writes and
        # dispatch staged review POSTs atomically alongside the returned
        # effects.
        snapshot.flush()
        _dispatch_pending_reviews(
            snapshot,
            note_uuid=note_uuid,
            note=note,
            instance_origin=instance_origin,
            forwarded_cookie=forwarded_cookie,
        )

        ack = _json({
            "success": True,
            "effects": _summarize_effects(all_effects),
        })
        log.info(
            f"[IntakeAPI] commit note={note_uuid} "
            f"effects={_summarize_effects(all_effects)}"
        )

        return [ack, *all_effects]
