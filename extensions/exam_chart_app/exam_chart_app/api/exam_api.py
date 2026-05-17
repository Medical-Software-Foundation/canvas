"""ExamChartingAPI — SimpleAPI for the exam-tab back end.

Routes:
  - GET  /exam/static/exam.css   → exam.css (Checkpoint 1)
  - GET  /exam/static/exam.js    → exam.js  (Checkpoint 1)
  - GET  /exam/templates?code=…  → HPI prefill for a code
  - POST /exam/finalize          → emit commands for the filled sections

Auth: StaffSessionAuthMixin — staff session only, no API-key fallback.
"""
from __future__ import annotations

from http import HTTPStatus

from canvas_sdk.commands import (
    HistoryOfPresentIllnessCommand,
    PhysicalExamCommand,
    ReasonForVisitCommand,
    ReviewOfSystemsCommand,
)
from canvas_sdk.v1.data import Condition
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from django.db import DatabaseError, OperationalError
from logger import log

from exam_chart_app.api.emitters import (
    _ORDER_EMITTERS,
    _emit_diagnosis_block,
    _emit_questionnaire,
)
from exam_chart_app.data.draft_state import (
    DraftTooLargeError,
    get_draft,
    mark_ever_finalized,
    mark_finalized,
    set_draft,
    was_ever_finalized,
)
from exam_chart_app.data.narratives import set_narrative
from exam_chart_app.data.questionnaires import (
    find_questionnaires,
    get_questionnaire_detail,
)
from exam_chart_app.data.templates import get_hpi_template
from exam_chart_app.data.validators import looks_like_uuid


# Cache the rendered+encoded bytes for static assets. exam.js is ~90 KB
# and is fetched on every tab open; re-rendering it from disk per request
# is wasteful. The cache is process-local — a plugin reinstall reloads
# the module, picking up template edits.
_STATIC_CACHE: dict[str, bytes] = {}

# exam.js is authored as 8 source chunks under `templates/exam_js/` (each
# is a slice of one IIFE — the opener lives in 00_iframe.js, the closer
# in 70_finalize.js). The runtime serves them as a single bundle via
# concatenation, so the browser still loads one script. Editing any
# chunk is what changes the served bundle on the next install.
_EXAM_JS_PARTS = (
    "templates/exam_js/00_iframe.js",
    "templates/exam_js/10_state.js",
    "templates/exam_js/20_draft.js",
    "templates/exam_js/30_search_rfv.js",
    "templates/exam_js/40_questionnaire.js",
    "templates/exam_js/50_diagnoses.js",
    "templates/exam_js/60_orders.js",
    "templates/exam_js/70_finalize.js",
)
# Cache key for the concatenated exam.js bundle. MUST NOT start with `_`
# — the Canvas plugin sandbox composes subscript writes into a virtual
# attribute path (`<receiver>.<key>`) and blocks any path segment that
# starts with `_`. `_STATIC_CACHE[<underscore-prefixed-key>] = value`
# raises `AttributeError: Forbidden assignment to a non-module attribute`.
EXAM_JS_CACHE_KEY = "exam.js[concat]"


def _static_bytes(filename: str) -> bytes:
    cached = _STATIC_CACHE.get(filename)
    if cached is None:
        cached = render_to_string(filename).encode()
        _STATIC_CACHE[filename] = cached
    return cached


def _exam_js_bytes() -> bytes:
    """Concatenate the exam.js source chunks into one bundle (cached)."""
    cached = _STATIC_CACHE.get(EXAM_JS_CACHE_KEY)
    if cached is None:
        parts = [render_to_string(p) for p in _EXAM_JS_PARTS]
        cached = "".join(parts).encode()
        _STATIC_CACHE[EXAM_JS_CACHE_KEY] = cached
    return cached


class ExamChartingAPI(StaffSessionAuthMixin, SimpleAPI):
    """Form-state + finalize endpoints for the Exam tab."""

    @api.get("/exam/static/exam.css")
    def get_exam_css(self) -> list[Response | Effect]:
        return [Response(
            _static_bytes("templates/exam.css"),
            status_code=HTTPStatus.OK,
            content_type="text/css; charset=utf-8",
        )]

    @api.get("/exam/static/exam.js")
    def get_exam_js(self) -> list[Response | Effect]:
        return [Response(
            _exam_js_bytes(),
            status_code=HTTPStatus.OK,
            content_type="text/javascript; charset=utf-8",
        )]

    @api.get("/exam/questionnaires/list")
    def list_questionnaires(self) -> list[Response | Effect]:
        """Return the chooser-friendly list of ROS + PE candidates."""
        ros_secret = (self.secrets.get("ros-questionnaire-code") or "").strip() or None
        pe_secret = (self.secrets.get("pe-questionnaire-code") or "").strip() or None

        def _serialize(rows: list) -> list[dict[str, str]]:
            return [
                {"id": str(r.id), "name": r.name or "", "code": r.code or ""}
                for r in rows
            ]

        return [JSONResponse(
            {
                "ros": _serialize(find_questionnaires("ros", ros_secret)),
                "pe": _serialize(find_questionnaires("pe", pe_secret)),
            },
            status_code=HTTPStatus.OK,
        )]

    @api.get("/exam/questionnaires/detail")
    def get_questionnaire_by_id(self) -> list[Response | Effect]:
        """Return one questionnaire's question list for rendering."""
        q_id = (self.request.query_params.get("id") or "").strip()
        if not q_id:
            return [JSONResponse(
                {"error": "id query param required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        detail = get_questionnaire_detail(q_id)
        if detail is None:
            return [JSONResponse(
                {"error": "questionnaire not found"},
                status_code=HTTPStatus.NOT_FOUND,
            )]
        return [JSONResponse(detail, status_code=HTTPStatus.OK)]

    @api.get("/exam/me")
    def get_me(self) -> list[Response | Effect]:
        """Return the currently-authenticated staff's id + display name.

        Used by the front-end to default `ordering_provider_key` /
        `prescriber_id` on freshly-added order cards. Source is the
        Canvas session headers (`canvas-logged-in-user-id` /
        `canvas-logged-in-user-type`), which StaffSessionAuthMixin
        guarantees are present for any request that reaches this route.
        """
        from canvas_sdk.v1.data import Staff
        user_id = (self.request.headers.get("canvas-logged-in-user-id") or "").strip()
        user_type = (self.request.headers.get("canvas-logged-in-user-type") or "").strip()
        result: dict[str, str] = {"id": user_id, "type": user_type,
                                  "first_name": "", "last_name": ""}
        if user_id and user_type == "Staff":
            try:
                staff = Staff.objects.get(id=user_id)
                result["first_name"] = staff.first_name or ""
                result["last_name"] = staff.last_name or ""
            except Staff.DoesNotExist:
                pass
        return [JSONResponse(result, status_code=HTTPStatus.OK)]

    @api.get("/exam/patient-conditions")
    def get_patient_conditions(self) -> list[Response | Effect]:
        """List active ICD-10 conditions for a patient.

        Used by the A&P diagnosis picker to switch to AssessCommand
        instead of DiagnoseCommand when the picked code already exists
        as an active patient Condition.

        We don't pre-filter on clinical_status — Canvas's value for
        "active" varies (string "active" vs 2-char code) and missing
        a real match here would silently degrade the existing-condition
        flow. The frontend can filter further if needed.
        """
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse({"conditions": []}, status_code=HTTPStatus.OK)]
        if not looks_like_uuid(patient_id):
            # Patient.id is a UUIDField; passing a non-UUID string raises
            # django.core.exceptions.ValidationError before the query runs.
            # Without this gate the exception escapes the handler, SimpleAPI
            # converts it to an empty-body 500, and the exception-formatting
            # pipeline allocates ~48 MB rendering the traceback (see the
            # questionnaires.py:get_questionnaire_detail mitigation for the
            # same pattern). Treat garbage input the same as "no patient" —
            # the picker shows no existing-condition matches and the
            # provider proceeds with a fresh DiagnoseCommand.
            return [JSONResponse({"conditions": []}, status_code=HTTPStatus.OK)]

        # Bound the result set: a chronic-care patient can carry hundreds of
        # historical Conditions, and the picker only needs a sensible recent
        # slate. 200 is generous for the A&P workflow (the dropdown filters
        # to the typed query before display) and keeps per-request memory
        # predictable.
        PATIENT_CONDITIONS_LIMIT = 200
        conditions = (
            Condition.objects
            .filter(
                patient__id=patient_id,
                entered_in_error__isnull=True,
            )
            .prefetch_related("codings")
            [:PATIENT_CONDITIONS_LIMIT]
        )

        results: list[dict[str, str]] = []
        all_systems_seen: set[str] = set()
        raw_count = 0
        for cond in conditions:
            raw_count += 1
            # Single pass: prefer an ICD-10 coding by system URI, otherwise
            # fall back to the first coding whose code matches the ICD-10
            # letter-then-digit shape (e.g. "N39.0"). Canvas doesn't stamp
            # the system URI consistently, so the shape check is needed.
            picked = None
            shape_match = None
            for coding in cond.codings.all():
                system = (coding.system or "").lower()
                all_systems_seen.add(coding.system or "")
                if "icd" in system:
                    picked = coding
                    break
                if shape_match is None:
                    code = (coding.code or "").strip()
                    if len(code) >= 2 and code[0].isalpha() and code[1].isdigit():
                        shape_match = coding
            if picked is None:
                picked = shape_match
            if picked is None:
                continue
            results.append({
                "id": str(cond.id),
                "code": picked.code or "",
                "display": picked.display or "",
                "system": picked.system or "",
                "clinical_status": cond.clinical_status or "",
            })

        log.info(
            f"[ExamChartingAPI] /exam/patient-conditions patient={patient_id} "
            f"raw_count={raw_count} "
            f"results={len(results)} systems_seen={sorted(all_systems_seen)}"
        )
        return [JSONResponse({"conditions": results}, status_code=HTTPStatus.OK)]

    @api.get("/exam/templates")
    def get_templates(self) -> list[Response | Effect]:
        code = (self.request.query_params.get("code") or "").strip()
        try:
            hpi = get_hpi_template(code)
        except (ValueError, TypeError) as exc:
            # Defense in depth: get_hpi_template already catches
            # JSONDecodeError + FileNotFoundError internally; narrowing
            # here to the residual stdlib raises (e.g. a non-string code).
            log.warning(
                f"[ExamChartingAPI] template load failed for code={code!r}: "
                f"{exc.__class__.__name__}: {exc}"
            )
            hpi = ""
        log.info(f"[ExamChartingAPI] /exam/templates code={code!r} hpi_len={len(hpi)}")
        return [JSONResponse({"hpi": hpi}, status_code=HTTPStatus.OK)]

    @api.get("/exam/state")
    def get_state(self) -> list[Response | Effect]:
        """Return the saved form draft + finalized + chart-commands flags.

        `has_chart_commands` lets the frontend detect the "orphan commands"
        case: the plugin draft was cleared (typically by ExamNoteLifecycle
        on a delete/undelete cycle) but Canvas's own command rows survived
        the soft-delete, so the chart still shows commands the form
        doesn't reflect.

        We must NOT count any-and-all commands on the note here — other
        plugins may finalize their own commands on the same note, and the
        orphan banner is only meaningful when the commands the form is
        missing are ours. The `meta:` AttributeHub row stamped by
        `mark_ever_finalized` records that THIS plugin finalized this
        note, and survives `clear_draft`, so it's the right signal.
        """
        note_uuid = (self.request.query_params.get("note_uuid") or "").strip()
        if not looks_like_uuid(note_uuid):
            return [JSONResponse(
                {"errors": [{"section": "note", "field": "note_uuid",
                             "message": "Missing or invalid note_uuid"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        state, finalized = get_draft(note_uuid)
        has_chart_commands = was_ever_finalized(note_uuid)
        return [JSONResponse(
            {
                "state": state,
                "finalized": finalized,
                "has_chart_commands": has_chart_commands,
            },
            status_code=HTTPStatus.OK,
        )]

    @api.post("/exam/state/save")
    def save_state(self) -> list[Response | Effect]:
        """Persist (replace) the form draft blob for a note.

        Called from the frontend on a debounce after every edit. Body:
        {note_uuid: str, state: dict}. The state shape is whatever the
        frontend currently holds — backend stores it opaquely.
        """
        try:
            payload = self.request.json()
        except (ValueError, TypeError):
            # json.loads raises ValueError on malformed input; TypeError
            # covers e.g. a None body. Narrower than Exception so
            # programming errors (AttributeError on a wrong self.request
            # shape, etc.) still surface in Sentry rather than being
            # masked as "Invalid JSON".
            return [JSONResponse(
                {"errors": [{"section": "body", "field": "", "message": "Invalid JSON"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        if not isinstance(payload, dict):
            return [JSONResponse(
                {"errors": [{"section": "body", "field": "", "message": "Body must be JSON object"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        note_uuid = (payload.get("note_uuid") or "").strip()
        if not looks_like_uuid(note_uuid):
            return [JSONResponse(
                {"errors": [{"section": "note", "field": "note_uuid",
                             "message": "Missing or invalid note_uuid"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        state = payload.get("state")
        if not isinstance(state, dict):
            return [JSONResponse(
                {"errors": [{"section": "state", "field": "", "message": "state must be an object"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        try:
            set_draft(note_uuid, state)
        except DraftTooLargeError as exc:
            log.warning(
                f"[ExamChartingAPI] /exam/state/save rejected oversize draft "
                f"for note={note_uuid}: {exc}"
            )
            return [JSONResponse(
                {"errors": [{
                    "section": "state",
                    "field": "",
                    "message": "Draft payload too large; please remove some content and retry.",
                }]},
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )]
        return [JSONResponse({"success": True}, status_code=HTTPStatus.OK)]

    @api.post("/exam/finalize")
    def finalize(self) -> list[Response | Effect]:
        log.info("[ExamChartingAPI] /exam/finalize entered")
        try:
            payload = self.request.json()
        except (ValueError, TypeError):
            # json.loads raises ValueError on malformed input; TypeError
            # covers e.g. a None body. Narrower than Exception so
            # programming errors (AttributeError on a wrong self.request
            # shape, etc.) still surface in Sentry rather than being
            # masked as "Invalid JSON".
            return [JSONResponse(
                {"errors": [{"section": "body", "field": "", "message": "Invalid JSON"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        if not isinstance(payload, dict):
            return [JSONResponse(
                {"errors": [{"section": "body", "field": "", "message": "Body must be a JSON object"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        note_uuid = (payload.get("note_uuid") or "").strip()
        if not looks_like_uuid(note_uuid):
            return [JSONResponse(
                {"errors": [{"section": "note", "field": "note_uuid", "message": "Missing or invalid note_uuid"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        rfv = payload.get("rfv")
        if not isinstance(rfv, dict):
            rfv = {}
        rfv_coding = rfv.get("coding")
        rfv_comment = str(rfv.get("comment") or "").strip()

        # Build the RFV comment: prefer typed free-text; fall back to the
        # picked NLM display + code. We always emit as a free-text comment
        # (structured=False) because ReasonForVisitCommand validates the
        # coding against the ReasonForVisitSettingCoding table, which
        # doesn't contain NLM ICD-10 codes on most instances. The picked
        # display is the human-readable label the provider chose, so
        # preserving it as text loses no clinical content.
        rfv_text = rfv_comment
        if not rfv_text and isinstance(rfv_coding, dict):
            display = str(rfv_coding.get("display") or "").strip()
            code = str(rfv_coding.get("code") or "").strip()
            if display and code:
                rfv_text = f"{display} ({code})"
            else:
                rfv_text = display or code

        if not rfv_text:
            return [JSONResponse(
                {"errors": [{"section": "rfv", "field": "", "message": "Pick or type a Reason for Visit"}]},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        hpi = payload.get("hpi")
        if not isinstance(hpi, dict):
            hpi = {}
        hpi_narrative = str(hpi.get("narrative") or "").strip()

        effects: list[Effect] = []

        try:
            effects.append(ReasonForVisitCommand(
                note_uuid=note_uuid,
                comment=rfv_text,
            ).originate())
        except (ValueError, TypeError) as exc:
            log.warning(
                f"[ExamChartingAPI] ReasonForVisitCommand.originate failed: "
                f"{exc.__class__.__name__}: {exc}"
            )
            return [JSONResponse(
                {"errors": [{"section": "rfv", "field": "", "message": f"Could not emit RFV: {exc.__class__.__name__}"}]},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )]

        if hpi_narrative:
            try:
                effects.append(HistoryOfPresentIllnessCommand(
                    note_uuid=note_uuid,
                    narrative=hpi_narrative,
                ).originate())
            except (ValueError, TypeError) as exc:
                log.warning(
                    f"[ExamChartingAPI] HPI originate failed: "
                    f"{exc.__class__.__name__}: {exc}"
                )
                return [JSONResponse(
                    {"errors": [{"section": "hpi", "field": "", "message": f"Could not emit HPI: {exc.__class__.__name__}"}]},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )]

        ros_payload = payload.get("ros") if isinstance(payload.get("ros"), dict) else {}
        pe_payload = payload.get("pe") if isinstance(payload.get("pe"), dict) else {}

        # Buffer narrative writes from ROS/PE so they only land after
        # every per-section emitter succeeds. Flushing inline inside
        # `_emit_questionnaire` would leak an AttributeHub row on a
        # later-section failure, violating finalize's all-or-nothing
        # invariant.
        pending_narratives: list[tuple[str, str]] = []

        ros_effects, ros_narratives, ros_error = _emit_questionnaire(
            "ros", ReviewOfSystemsCommand, ros_payload, note_uuid
        )
        if ros_error:
            return [ros_error]
        effects.extend(ros_effects)
        pending_narratives.extend(ros_narratives)

        pe_effects, pe_narratives, pe_error = _emit_questionnaire(
            "pe", PhysicalExamCommand, pe_payload, note_uuid
        )
        if pe_error:
            return [pe_error]
        effects.extend(pe_effects)
        pending_narratives.extend(pe_narratives)

        ap_payload = payload.get("ap") if isinstance(payload.get("ap"), dict) else {}
        if not isinstance(ap_payload, dict):
            ap_payload = {}

        diagnoses_payload = ap_payload.get("diagnoses")
        if not isinstance(diagnoses_payload, list):
            diagnoses_payload = []

        ap_counts = {"diagnose": 0, "assess": 0, "plan": 0}
        for entry in diagnoses_payload:
            block_effects, block_counts, block_error = _emit_diagnosis_block(
                note_uuid, entry
            )
            if block_error:
                return [block_error]
            effects.extend(block_effects)
            ap_counts["diagnose"] = ap_counts["diagnose"] + block_counts["diagnose"]
            ap_counts["assess"] = ap_counts["assess"] + block_counts["assess"]
            ap_counts["plan"] = ap_counts["plan"] + block_counts["plan"]

        orders_payload = ap_payload.get("orders")
        if not isinstance(orders_payload, list):
            orders_payload = []
        order_counts = {
            "lab": 0, "imaging": 0, "prescribe": 0, "refer": 0,
            "goal": 0, "plan_item": 0, "follow_up": 0,
        }
        for order_entry in orders_payload:
            if not isinstance(order_entry, dict):
                continue
            order_type = str(order_entry.get("type") or "").strip().lower()
            emitter = _ORDER_EMITTERS.get(order_type)
            if emitter is None:
                continue
            order_effect, order_error = emitter(note_uuid, order_entry)
            if order_error:
                return [order_error]
            if order_effect is not None:
                effects.append(order_effect)
                order_counts[order_type] = order_counts[order_type] + 1

        log.info(f"[ExamChartingAPI] finalize note={note_uuid} effects={len(effects)}")

        # Failures gate has passed: every per-section emitter returned
        # without error. Flush the buffered narrative writes now. Each
        # call gets its own try/except so one AttributeHub hiccup does
        # not skip the others; failures are logged but do not 500 the
        # successful finalize (the chart's metadata form will fall back
        # to an empty textarea rather than the typed narrative).
        for cmd_uuid, narrative in pending_narratives:
            try:
                set_narrative(cmd_uuid, narrative)
                log.info(
                    f"[ExamChartingAPI] narrative stashed for "
                    f"command_uuid={cmd_uuid} len={len(narrative)}"
                )
            except (DatabaseError, OperationalError):
                # Narrow to DB-class errors: AttributeHub is internal
                # data access, and AttributeError/KeyError/TypeError from
                # programming bugs (renamed SDK methods, sandbox attribute
                # blocks) must reach Sentry rather than be swallowed.
                # log.exception so on-call gets paged for the genuine DB
                # blips this swallow is intended to cover.
                log.exception(
                    f"[ExamChartingAPI] set_narrative failed for "
                    f"command_uuid={cmd_uuid}"
                )

        # Flag the saved draft (if any) as finalized so reopening the
        # tab disables Finalize + shows the read-only banner. Done after
        # effects are built (so a build-time exception bails out before
        # we mark anything), but before they're returned — the flag is
        # safe to set even if the runtime later rejects an effect, since
        # rerunning Finalize would just re-emit (which we are disabling).
        #
        # Also stamp the persistent `meta:` marker so the orphan-commands
        # banner can fire correctly after a delete/undelete cycle that
        # wipes `draft:`. Without the meta marker, the banner would have
        # to fall back to "any commands on the note", which mis-fires
        # whenever any other plugin has emitted commands on the same note.
        try:
            mark_finalized(note_uuid)
            mark_ever_finalized(note_uuid)
        except (DatabaseError, OperationalError):
            # Narrow to DB-class errors so programming bugs reach Sentry.
            # log.exception pages on-call: a swallowed transient here
            # leaves finalized=False, the frontend re-enables the
            # Finalize button on reopen, and a re-click would duplicate
            # every per-section emit. The narrow catch + page is the
            # immediate compliance fix; closing the duplicate-emit gap
            # fully requires frontend-side dedup or backend pre-gate
            # state read.
            log.exception(
                f"[ExamChartingAPI] mark_finalized failed for note={note_uuid}"
            )

        return [JSONResponse(
            {
                "success": True,
                "effects": {
                    "rfv": True,
                    "hpi": bool(hpi_narrative),
                    "ros": bool(ros_effects),
                    "pe": bool(pe_effects),
                    "diagnose_count": ap_counts["diagnose"],
                    "assess_count": ap_counts["assess"],
                    "plan_count": ap_counts["plan"],
                    "lab_count": order_counts["lab"],
                    "imaging_count": order_counts["imaging"],
                    "prescribe_count": order_counts["prescribe"],
                    "refer_count": order_counts["refer"],
                    "goal_count": order_counts["goal"],
                    "plan_item_count": order_counts["plan_item"],
                    "follow_up_count": order_counts["follow_up"],
                },
            },
            status_code=HTTPStatus.OK,
        )] + effects
