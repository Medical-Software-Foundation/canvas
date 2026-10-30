"""SimpleAPI endpoints for the questionnaire follow-up admin page.

Serves the pairing editor and the two things it reads - the stored rules and the
instance's questionnaire list - plus the endpoint it saves back to.

Access is gated by the ADMIN_STAFF_KEYS plugin variable (a comma-separated list
of staff keys), which is NOT editable from the page itself. It fails closed: with
the variable unset, nobody gets in. There is deliberately no hardcoded bypass - the
variable is set outside this page (plugin settings or `canvas config set`), so the
page can never lock the last admin out, and every admin is visible in one place the
practice controls. The app-drawer icon stays visible to everyone - the SDK has no
per-staff icon control - so access is enforced here, on open.
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from logger import log

from questionnaire_followup.api.admin_page import ACCESS_DENIED_HTML, build_admin_html
from questionnaire_followup.services.config_store import (
    COMPARATORS,
    MAX_RULES,
    describe_rule,
    inactive_reason,
    load_config,
    save_config,
)
from questionnaire_followup.services.decision import Trace, editable_note_ids, owed_forms
from questionnaire_followup.services.questionnaires import list_questionnaires


class FollowUpAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """Endpoints backing the pairing editor."""

    PREFIX = ""

    def _staff_id(self) -> str:
        return str(self.request.headers.get("canvas-logged-in-user-id", ""))

    def _admin_allowed(self) -> bool:
        """Whether the logged-in staff member may view or change the pairings."""
        staff_id = self._staff_id()
        raw = (self.secrets.get("ADMIN_STAFF_KEYS") or "").strip()
        if not raw:
            log.warning(
                "ADMIN_STAFF_KEYS not configured, denying Questionnaire Follow-Up access"
            )
            return False
        allowed = {key.strip() for key in raw.split(",") if key.strip()}
        if staff_id and staff_id in allowed:
            return True
        log.warning(f"Questionnaire Follow-Up access denied for staff key '{staff_id}'")
        return False

    def _parse_body(self) -> dict[str, Any]:
        """Parse the request body as a JSON object; anything else reads as empty.

        ``ValueError`` covers every way the SDK's ``json()`` fails on a bad body:
        base64, UTF-8 and JSON decoding errors all subclass it.
        """
        try:
            parsed = self.request.json()
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @api.get("/admin/ui")
    def serve_admin(self) -> list[Response | Effect]:
        """Return the pairing editor, or an access-denied page."""
        if not self._admin_allowed():
            return [HTMLResponse(ACCESS_DENIED_HTML, status_code=HTTPStatus.FORBIDDEN)]
        return [HTMLResponse(build_admin_html())]

    @api.get("/admin/config")
    def get_config(self) -> list[Response | Effect]:
        """Return the current pairing rules for the form."""
        if not self._admin_allowed():
            return [JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)]
        return [JSONResponse({"config": load_config()})]

    @api.post("/admin/config")
    def put_config(self) -> list[Response | Effect]:
        """Persist the pairing rules edited in the form."""
        if not self._admin_allowed():
            return [
                JSONResponse(
                    {"success": False, "error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN
                )
            ]
        # CSRF defence. The SDK parses a JSON body whatever its declared type, so a
        # cross-site `<form enctype="text/plain">` could otherwise post a forged config
        # with an admin's session. A cross-origin `application/json` request needs a
        # CORS preflight, which a foreign site cannot pass. The editor sends this type.
        if self.request.content_type != "application/json":
            return [
                JSONResponse(
                    {"success": False, "error": "Content-Type must be application/json"},
                    status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
            ]
        config = self._parse_body().get("config")
        if not isinstance(config, dict) or not isinstance(config.get("rules"), list):
            return [
                JSONResponse(
                    {"success": False, "error": "Invalid configuration"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if len(config["rules"]) > MAX_RULES:
            return [
                JSONResponse(
                    {"success": False, "error": f"At most {MAX_RULES} pairings can be saved."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        # A comparator this version cannot read is refused rather than stored and
        # silently coerced: "at most" read back as "at least" is its own inverse,
        # and the rule would fire on exactly the patients it was meant to skip.
        unknown = sorted(
            str(rule.get("comparator"))
            for rule in config["rules"]
            if isinstance(rule, dict) and rule.get("comparator") not in (None, "", *COMPARATORS)
        )
        if unknown:
            return [
                JSONResponse(
                    {"success": False, "error": f"Unrecognized score rule: {', '.join(unknown)}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if save_config(config):
            return [JSONResponse({"success": True})]
        return [
            JSONResponse(
                {
                    "success": False,
                    "error": "Could not save - the custom data namespace may not be set up. "
                    "Reinstall the plugin.",
                }
            )
        ]

    @api.get("/admin/questionnaires")
    def admin_questionnaires(self) -> list[Response | Effect]:
        """List this instance's active questionnaires for the pairing pickers."""
        if not self._admin_allowed():
            return [JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)]
        return [JSONResponse({"questionnaires": list_questionnaires()})]

    @api.get("/admin/diagnose")
    def diagnose(self) -> list[Response | Effect]:
        """Explain, rule by rule, what this patient would currently be shown and why.

        Answers the one question this plugin cannot otherwise answer: a pairing is
        configured, the patient was screened, and nothing appeared - which gate
        stopped it? The handler logs only when it presents something, so a quiet
        portal load and a handler that never ran look identical in the logs.

        Read-only. It runs the same ``owed_forms`` the portal handler runs, with a
        trace attached, so what this reports is what the handler does rather than a
        second implementation that can drift.

        ``?patient=<id>`` is the patient id as the portal event carries it. It is
        echoed back, because a patient whose chart plainly shows a screen while
        this reports none usually means the id is not the record being looked at.

        **This is the only route that returns anything about a patient**, and it
        deliberately includes their screening score: "scored 2, needs 3" is the
        single most useful thing it can say, and a listed admin can already read
        that score off the chart. Two consequences, both intended:

        - The response is marked ``Cache-Control: no-store``.
        - It carries no per-patient authorization beyond the admin list, so a
          listed admin can ask about any patient. That matches the rest of the
          plugin and the staff it is for; it is not a route to widen.

        ⛔ **This is not the same call as the one made for the log line in the
        portal handler, which deliberately omits scores.** A log is pushed to an
        aggregator and kept; this is pulled, once, by a named admin who asked.
        Don't "fix" either to match the other.
        """
        if not self._admin_allowed():
            return [JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)]
        patient_id = (self.request.query_params.get("patient") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "Pass ?patient=<patient id>"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        config = load_config()
        rules = config.get("rules", [])
        # Rules that can never fire as written are reported here rather than being
        # silently absent: "switched off" is the most common answer of all, and
        # owed_forms never sees those rules.
        trace: Trace = [
            {
                "rule_id": rule.get("id", ""),
                "rule": rule.get("name", ""),
                "trigger_code": rule.get("trigger_code", ""),
                "followup_code": rule.get("followup_code", ""),
                "condition": describe_rule(rule),
                "outcome": "inactive",
                "detail": reason,
            }
            for rule in rules
            if (reason := inactive_reason(rule)) is not None
        ]

        now = datetime.now(UTC)
        owed = owed_forms(
            [r for r in rules if inactive_reason(r) is None], patient_id, now, trace
        )
        note_ids = editable_note_ids({screen.note_id for _, screen, _ in owed})
        # owed_forms traces in gate order, because it batches each gate across all
        # rules. Put the entries back into the order the admin edited them in, so
        # the diagnostic reads down the page the way the editor does.
        order = {str(rule.get("id", "")): index for index, rule in enumerate(rules)}
        trace.sort(key=lambda entry: order.get(str(entry["rule_id"]), len(order)))
        return [
            JSONResponse(
                {
                    "patient_id": patient_id,
                    "checked_at": now.isoformat(),
                    "rules_configured": len(rules),
                    "forms_owed": [
                        {
                            "rule": rule["name"],
                            "questionnaire": followup.name,
                            "code": rule["followup_code"],
                            "note": note_ids.get(screen.note_id) or "a new note",
                        }
                        for rule, screen, followup in owed
                    ],
                    "rules": trace,
                },
                # The only route here that returns anything about a patient: their
                # screening scores and the dates they were taken. Stored responses
                # would leave that in a browser cache or an intermediary long after
                # the admin closed the tab, so it is marked not to be stored at all.
                headers={"Cache-Control": "no-store"},
            )
        ]
