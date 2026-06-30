"""SimpleAPI endpoints for Group Therapy.

Serves the modal UI, lists a day's group sessions (derived from the schedule),
per-attendee diagnosis lookups, and the per-patient documentation endpoint.
Documentation lands in an attendee's existing appointment note - the plugin
never creates a note or an appointment.
"""

from __future__ import annotations

from datetime import date
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.v1.data.staff import Staff
from logger import log

from group_therapy.api.admin_modal import build_admin_html
from group_therapy.api.modal import build_modal_html
from group_therapy.services.conditions import active_conditions, default_condition_id
from group_therapy.services.config_store import (
    group_rfv_codes,
    load_config,
    save_config,
    template_for_codes,
)
from group_therapy.services.medications import active_medications
from group_therapy.services.effects import (
    build_checkin_effects,
    build_documentation_effects,
    build_no_show_effects,
)
from group_therapy.services.questionnaires import list_questionnaires, question_schema
from group_therapy.services.sessions import find_group_sessions


_ADMIN_DENIED_HTML = (
    "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
    "<link href='https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap' rel='stylesheet'>"
    "<style>body{font-family:'Lato',sans-serif;background:#f5f6f8;color:#1f2933;"
    "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;}"
    ".card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:40px 48px;max-width:420px;"
    "box-shadow:0 8px 24px rgba(0,0,0,0.06);}h1{color:#111827;font-size:20px;margin:0 0 8px;}"
    "p{color:#6b7280;font-size:14px;margin:0;}</style></head>"
    "<body><div class='card'><h1>Access restricted</h1>"
    "<p>You do not have access to Group Therapy Setup. Ask an administrator to add your staff key.</p>"
    "</div></body></html>"
)

# The Canvas root/superuser staff key is identical on every instance; it is
# always allowed into Setup as a break-glass admin (the SDK exposes no
# superuser flag, so this key is matched explicitly).
_ROOT_STAFF_KEYS = {"4150cd20de8a470aa570a852859ac87e"}


def _parse_body(request) -> dict:
    """Parse request body as JSON, handling bytes or string."""
    try:
        return request.json()
    except Exception:
        try:
            import json

            body = request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            return json.loads(body)
        except Exception:
            return {}


def _duration_label(minutes) -> str:
    """Render a duration value as 'N min', or '' when unknown."""
    try:
        return f"{int(minutes)} min"
    except (TypeError, ValueError):
        return ""


def _provider_name(provider_id: str, default: str = "Provider") -> str:
    """Resolve a provider's display name, returning ``default`` when the staff
    record is missing or the lookup fails. Callers that need to tell "unknown"
    apart from a real name pass ``default=""`` rather than testing the fallback."""
    try:
        staff = Staff.objects.filter(id=provider_id).first()
        if staff:
            return f"{staff.first_name} {staff.last_name}".strip()
    except (AttributeError, ValueError) as exc:
        log.warning(f"provider name lookup failed for id={provider_id}: {exc}")
    return default


class GroupTherapyAPI(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for schedule-derived group therapy documentation."""

    PREFIX = ""

    # ------------------------------------------------------------------ #
    #  GET /ui - serve the HTML modal
    # ------------------------------------------------------------------ #
    @api.get("/ui")
    def serve_ui(self) -> list[Response | Effect]:
        """Return the full HTML modal page with server-injected context."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        # default="" so an unresolved lookup is blank (JS falls back to "you"),
        # without blanking a real provider who happens to be named "Provider".
        logged_in_name = _provider_name(staff_id, default="") if staff_id else ""

        html = build_modal_html(
            logged_in_staff_id=staff_id,
            logged_in_name=logged_in_name,
        )
        return [HTMLResponse(html)]

    # ------------------------------------------------------------------ #
    #  GET /sessions?date=YYYY-MM-DD - the day's group sessions
    # ------------------------------------------------------------------ #
    @api.get("/sessions")
    def sessions(self) -> list[Response | Effect]:
        """List the date's group sessions (provider + time + roster)."""
        date_str = self.request.query_params.get("date", "").strip()
        if not date_str:
            return [
                JSONResponse({"error": "date is required"}, status_code=HTTPStatus.BAD_REQUEST)
            ]
        try:
            session_date = date.fromisoformat(date_str)
        except ValueError:
            return [
                JSONResponse({"error": "invalid date"}, status_code=HTTPStatus.BAD_REQUEST)
            ]
        # the group RFV codes come from the configured templates (admin-managed)
        found = find_group_sessions(session_date, group_rfv_codes(load_config()))
        return [JSONResponse({"sessions": found})]

    # ------------------------------------------------------------------ #
    #  GET /patient/conditions?patient_id=...
    # ------------------------------------------------------------------ #
    @api.get("/patient/conditions")
    def patient_conditions(self) -> list[Response | Effect]:
        """Return the attendee's active ICD-10 conditions and the auto-select default."""
        patient_id = self.request.query_params.get("patient_id", "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        conditions = active_conditions(patient_id)
        return [
            JSONResponse(
                {"conditions": conditions, "default_id": default_condition_id(conditions)}
            )
        ]

    # ------------------------------------------------------------------ #
    #  GET /patient/medications?patient_id=... - active meds (read-only)
    # ------------------------------------------------------------------ #
    @api.get("/patient/medications")
    def patient_medications(self) -> list[Response | Effect]:
        """Return the patient's active medication display names (screening template)."""
        patient_id = self.request.query_params.get("patient_id", "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        return [JSONResponse({"medications": active_medications(patient_id)})]

    # ------------------------------------------------------------------ #
    #  POST /session/checkin - bulk check in scheduled appointment notes
    # ------------------------------------------------------------------ #
    @api.post("/session/checkin")
    def checkin(self) -> list[Response | Effect]:
        """Check in the given appointment notes (Booked -> Checked in)."""
        body = _parse_body(self.request)
        note_ids = [n for n in body.get("note_ids", []) if n]
        effects: list[Response | Effect] = []
        for note_id in note_ids:
            effects.extend(build_checkin_effects(note_id))
        effects.append(JSONResponse({"success": True, "checked_in": len(note_ids)}))
        return effects

    # ------------------------------------------------------------------ #
    #  POST /session/complete-patient - document one attendee
    # ------------------------------------------------------------------ #
    @api.post("/session/complete-patient")
    def complete_patient(self) -> list[Response | Effect]:
        """Document one attendee into their appointment note, or mark a no-show."""
        body = _parse_body(self.request)

        provider_id = body.get("provider_id", "")
        participant = body.get("participant", {})
        patient_id = participant.get("id", "")
        target_note_id = participant.get("target_note_id", "")
        if not patient_id:
            return [
                JSONResponse(
                    {"success": False, "error": "Missing patient"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        status = participant.get("status", "present")

        # No editable target note -> cannot document this attendee
        if not target_note_id:
            return [
                JSONResponse(
                    {
                        "success": True,
                        "action": "skipped",
                        "reason": "no open appointment note",
                        "patient_id": patient_id,
                    }
                )
            ]

        # Absent -> non-billable no-show on the appointment note
        if status == "absent":
            effects: list[Response | Effect] = list(build_no_show_effects(target_note_id))
            effects.append(
                JSONResponse({"success": True, "action": "no_show", "patient_id": patient_id})
            )
            return effects

        # Resolve the template (by the session's RFV codes) for CPT + billing mode.
        doc = load_config()
        template = template_for_codes(doc, body.get("rfv_codes", [])) or {}
        billing_mode = doc.get("billing_mode", "group")
        cpt_code = template.get("cpt_code", "")

        # Header meta from the appointment + the resolved per-attendee sections.
        # The modal sends free-text/medications already resolved as summary
        # sections, and questionnaire sections as {code, answers} specs.
        provider_name = _provider_name(provider_id) if provider_id else "Provider"
        meta_pairs = [
            ("Provider", provider_name),
            ("Date", body.get("session_date", "")),
            ("Facilitator", body.get("facilitator", "")),
            ("Duration", _duration_label(body.get("duration_minutes", ""))),
        ]
        summary_sections = [
            (s.get("label", ""), s.get("value", "")) for s in participant.get("summary_sections", [])
        ]

        effects = list(
            build_documentation_effects(
                target_note_id=target_note_id,
                meta_pairs=meta_pairs,
                summary_sections=summary_sections,
                questionnaire_specs=participant.get("questionnaires", []),
                condition_id=participant.get("condition_id", "") or None,
                billing_mode=billing_mode,
                cpt_code=cpt_code,
                sign=False,
                participant_index=body.get("participant_index", 0),
                check_in=bool(participant.get("needs_checkin", False)),
            )
        )
        effects.append(
            JSONResponse({"success": True, "action": "documented", "patient_id": patient_id})
        )
        return effects

    # ------------------------------------------------------------------ #
    #  GET /template?rfv=code1,code2 - resolved template + live questionnaire schema
    # ------------------------------------------------------------------ #
    @api.get("/template")
    def template(self) -> list[Response | Effect]:
        """Return the template matching the session's RFV codes, with each
        questionnaire section's live question schema attached for rendering."""
        rfv = self.request.query_params.get("rfv", "")
        codes = [c.strip() for c in rfv.split(",") if c.strip()]
        doc = load_config()
        matched = template_for_codes(doc, codes)
        if not matched:
            return [JSONResponse({"template": None, "billing_mode": doc.get("billing_mode", "group")})]
        sections = []
        for section in matched.get("sections", []):
            item = dict(section)
            if section.get("type") == "questionnaire":
                item["schema"] = question_schema(section.get("code", ""))
            sections.append(item)
        resolved = dict(matched)
        resolved["sections"] = sections
        return [JSONResponse({"template": resolved, "billing_mode": doc.get("billing_mode", "group")})]

    # ------------------------------------------------------------------ #
    #  Admin: form-based template builder (config lives in custom_data)
    #  Access-gated by the ADMIN_STAFF_KEYS plugin variable (comma-separated
    #  staff keys allowed to edit templates) - NOT editable from the UI itself.
    #  Fails closed: if the variable is unset/blank, no one can open Setup. The
    #  app-drawer icon stays visible to all (the SDK has no per-staff icon
    #  control); access is enforced here on open.
    # ------------------------------------------------------------------ #
    def _admin_allowed(self) -> bool:
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        # Break-glass: the Canvas root/superuser staff key is the same on every
        # instance and is always allowed, even when ADMIN_STAFF_KEYS is unset, so
        # an instance can never be locked out of its own template config.
        if staff_id in _ROOT_STAFF_KEYS:
            return True
        raw = (self.secrets.get("ADMIN_STAFF_KEYS") or "").strip()
        if not raw:
            log.warning("ADMIN_STAFF_KEYS not configured, denying Group Therapy Setup access")
            return False
        allowed = {key.strip() for key in raw.split(",") if key.strip()}
        return bool(staff_id) and staff_id in allowed

    @api.get("/admin/ui")
    def serve_admin(self) -> list[Response | Effect]:
        """Return the admin template-builder page, or an access-denied page."""
        if not self._admin_allowed():
            return [HTMLResponse(_ADMIN_DENIED_HTML)]
        return [HTMLResponse(build_admin_html())]

    @api.get("/admin/config")
    def get_config(self) -> list[Response | Effect]:
        """Return the current templates config document for the admin form."""
        if not self._admin_allowed():
            return [JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)]
        return [JSONResponse({"config": load_config()})]

    @api.post("/admin/config")
    def put_config(self) -> list[Response | Effect]:
        """Persist the templates config edited in the admin form."""
        if not self._admin_allowed():
            return [JSONResponse({"success": False, "error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)]
        body = _parse_body(self.request)
        config = body.get("config")
        if not isinstance(config, dict) or not isinstance(config.get("templates"), list):
            return [
                JSONResponse(
                    {"success": False, "error": "invalid config"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if save_config(config):
            return [JSONResponse({"success": True})]
        return [
            JSONResponse(
                {
                    "success": False,
                    "error": "Could not save - the custom data namespace may not be set up. Reinstall the plugin.",
                }
            )
        ]

    @api.get("/admin/questionnaires")
    def admin_questionnaires(self) -> list[Response | Effect]:
        """List the instance's questionnaires/SAs/exams for the section picker."""
        if not self._admin_allowed():
            return [JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)]
        return [JSONResponse({"questionnaires": list_questionnaires()})]
