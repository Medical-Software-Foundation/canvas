"""SimpleAPI routes serving the Daily Readiness Dashboard UI.

HTML, CSS, and JS are each served from their own route (per project
convention) and authenticated against the logged-in staff session. Templates
live under ``templates/`` and are loaded with the SDK's ``render_to_string``.

Step 1 serves only the static shell; the data endpoint (`/app/data`) arrives
in a later step.
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import Staff

from daily_dashboard.services.readiness import (
    OUTREACH_CHANNELS,
    OUTREACH_RECIPIENTS,
    OVERRIDABLE,
    build_board,
    comment_task,
    create_task,
    record_outreach,
    set_override,
    stage_prep_prompt,
    update_task,
)

# Plugin-io base path for the dashboard's own assets, referenced by the HTML.
ASSET_BASE = "/plugin-io/api/daily_dashboard/app"

# Optional clinic timezone (IANA name) for computing "today"; defaults to UTC.
TIMEZONE_SECRET = "CLINIC_TIMEZONE"

# Instance subdomain for patient-chart deep-links. Set this to your Canvas
# instance subdomain; falls back to a placeholder until configured.
CUSTOMER_SECRET = "CUSTOMER_IDENTIFIER"

# Patient-scoped messaging Application to deep-link "Open messages" to. Default
# is the SDK's conversational-view messaging app; override per instance if a
# different messaging app is installed.
MESSAGING_APP_SECRET = "MESSAGING_APP_IDENTIFIER"
DEFAULT_MESSAGING_APP = "messaging_conversational_view.apps.conversational_view:ConversationalViewApp"

# "Appointment Prep" stages a prompt on the patient and opens the Assistant
# panel (ChatApp), which sends the prompt once. App identifier + prompt are
# configurable per instance.
ASSISTANT_PANEL_SECRET = "ASSISTANT_PANEL_APP"
DEFAULT_ASSISTANT_PANEL = "assistant.handlers.chat_app:ChatApp"
ASSISTANT_PROMPT_SECRET = "ASSISTANT_PREP_PROMPT"
DEFAULT_ASSISTANT_PROMPT = (
    "Prep me for this patient's next visit: summarize their active conditions, "
    "current medications, recent lab results, and open orders or referrals, and "
    "flag anything I should review or follow up on before they arrive."
)


def _staff_display_name(staff_id: str | None) -> str:
    """Resolve the logged-in staff's name for the outreach log author."""
    if not staff_id:
        return "Unknown user"
    staff = Staff.objects.filter(id=staff_id).first()
    if staff is None:
        return "Unknown user"
    return (staff.credentialed_name or "").strip() or f"{staff.first_name} {staff.last_name}".strip()


class DashboardIndexRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Serves the dashboard HTML shell."""

    PATH = "/app"

    def get(self) -> list[Response | Effect]:
        """Render the dashboard page."""
        html = render_to_string("templates/index.html", {"asset_base": ASSET_BASE})
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]


class DashboardStylesRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Serves the dashboard CSS."""

    PATH = "/app/styles.css"

    def get(self) -> list[Response | Effect]:
        """Return the stylesheet."""
        css = render_to_string("templates/styles.css")
        return [
            Response(
                css.encode("utf-8"),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]


class DashboardScriptRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Serves the dashboard JavaScript."""

    PATH = "/app/app.js"

    def get(self) -> list[Response | Effect]:
        """Return the script."""
        js = render_to_string("templates/app.js")
        return [
            Response(
                js.encode("utf-8"),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]


class DashboardDataRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Returns today's board data (rows + filter options) as JSON."""

    PATH = "/app/data"

    def get(self) -> list[Response | Effect]:
        """Build the board honoring scope/provider/location query params."""
        params = self.request.query_params
        scope = params.get("scope", "all")
        day = params.get("day", "today")
        provider_id = params.get("provider") or None
        location_id = params.get("location") or None

        # Identity comes from the session headers the auth mixin already
        # validated; used only to scope "My day" to the logged-in provider.
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        # Follow the signed-in user's own timezone (sent by the browser); fall
        # back to a configured clinic timezone, then UTC.
        tz_name = params.get("tz") or self.secrets.get(TIMEZONE_SECRET) or "UTC"

        board = build_board(
            tz_name=tz_name,
            staff_id=staff_id,
            scope=scope,
            day=day,
            provider_id=provider_id,
            location_id=location_id,
            customer_identifier=self.secrets.get(CUSTOMER_SECRET, "example"),
            messaging_app_id=self.secrets.get(MESSAGING_APP_SECRET) or DEFAULT_MESSAGING_APP,
        )
        # Card-header deep-links — only used if explicitly configured. Canvas's
        # native worklists (/panel etc.) redirect to the schedule on a cold URL
        # load (the #terms filter is in-SPA state, not a shareable deep-link),
        # so these default to empty (header not linked) unless a working URL is
        # provided per instance.
        board["panel_links"] = {
            "tasks": self.secrets.get("PANEL_TASKS_URL") or "",
            "refills": self.secrets.get("PANEL_REFILLS_URL") or "",
            "messages": self.secrets.get("PANEL_MESSAGES_URL") or "",
        }
        # "Appointment Prep" → open the Assistant panel (ChatApp) for the patient.
        board["assistant_panel_app"] = (
            self.secrets.get(ASSISTANT_PANEL_SECRET) or DEFAULT_ASSISTANT_PANEL
        )
        return [JSONResponse(board, status_code=HTTPStatus.OK)]


class OutreachRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Records an outreach attempt to a patient's plugin-owned metadata log."""

    PATH = "/app/outreach"

    def post(self) -> list[Response | Effect]:
        """Append an outreach attempt for the given patient."""
        body = self.request.json()
        patient_id = (body.get("patient_id") or "").strip()
        channel = (body.get("channel") or "").strip()
        recipient_type = (body.get("recipient_type") or "").strip()

        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if channel not in OUTREACH_CHANNELS:
            return [JSONResponse({"error": "Invalid channel"}, status_code=HTTPStatus.BAD_REQUEST)]
        if recipient_type not in OUTREACH_RECIPIENTS:
            return [JSONResponse({"error": "Invalid recipient_type"}, status_code=HTTPStatus.BAD_REQUEST)]

        user = _staff_display_name(self.request.headers.get("canvas-logged-in-user-id"))
        effect = record_outreach(
            patient_id,
            channel=channel,
            recipient_type=recipient_type,
            recipient=(body.get("recipient") or "").strip(),
            outcome=(body.get("outcome") or "").strip(),
            note=(body.get("note") or "").strip(),
            user=user,
        )
        return [effect, JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]


class ReadinessOverrideRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Sets or clears a manual 'Mark complete' override for a readiness cell."""

    PATH = "/app/readiness"

    def post(self) -> list[Response | Effect]:
        """Toggle a readiness category's manual completion flag."""
        body = self.request.json()
        patient_id = (body.get("patient_id") or "").strip()
        category = (body.get("category") or "").strip()
        complete = bool(body.get("complete", True))

        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if category not in OVERRIDABLE:
            return [JSONResponse({"error": "Invalid category"}, status_code=HTTPStatus.BAD_REQUEST)]

        effect = set_override(patient_id, category, complete)
        return [effect, JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]


class CreateTaskRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Creates a follow-up task for a patient from the dashboard."""

    PATH = "/app/task"

    def post(self) -> list[Response | Effect]:
        """Create an open task; an optional due date may be supplied (YYYY-MM-DD)."""
        body = self.request.json()
        patient_id = (body.get("patient_id") or "").strip()
        title = (body.get("title") or "").strip()
        due_raw = (body.get("due") or "").strip()

        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not title:
            return [JSONResponse({"error": "A task title is required"}, status_code=HTTPStatus.BAD_REQUEST)]

        due = None
        if due_raw:
            try:
                due = datetime.fromisoformat(due_raw)
            except ValueError:
                return [JSONResponse({"error": "Invalid due date"}, status_code=HTTPStatus.BAD_REQUEST)]

        effect = create_task(
            patient_id,
            title,
            due,
            assignee_id=(body.get("assignee_id") or "").strip() or None,
            team_id=(body.get("team_id") or "").strip() or None,
            priority=(body.get("priority") or "").strip() or None,
        )
        return [effect, JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]


class TaskActionRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Updates an existing task's fields and/or adds a comment, in-dashboard."""

    PATH = "/app/task-action"

    def post(self) -> list[Response | Effect]:
        """Apply field updates and/or a comment to a task assigned to the user/team."""
        body = self.request.json()
        task_id = (body.get("task_id") or "").strip()
        if not task_id:
            return [JSONResponse({"error": "Missing task_id"}, status_code=HTTPStatus.BAD_REQUEST)]

        due_raw = (body.get("due") or "").strip()
        due = None
        if due_raw:
            try:
                due = datetime.fromisoformat(due_raw)
            except ValueError:
                return [JSONResponse({"error": "Invalid due date"}, status_code=HTTPStatus.BAD_REQUEST)]

        effects: list[Response | Effect] = []

        # Field updates (any subset).
        if any(
            (body.get(k) or "").strip()
            for k in ("status", "assignee_id", "team_id", "title", "priority")
        ) or due is not None:
            effects.append(
                update_task(
                    task_id,
                    status=(body.get("status") or "").strip() or None,
                    assignee_id=(body.get("assignee_id") or "").strip() or None,
                    team_id=(body.get("team_id") or "").strip() or None,
                    title=(body.get("title") or "").strip() or None,
                    due=due,
                    priority=(body.get("priority") or "").strip() or None,
                )
            )

        comment = (body.get("comment") or "").strip()
        if comment:
            effects.append(comment_task(task_id, comment))

        if not effects:
            return [JSONResponse({"error": "Nothing to update"}, status_code=HTTPStatus.BAD_REQUEST)]

        effects.append(JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK))
        return effects


class PrepRoute(StaffSessionAuthMixin, SimpleAPIRoute):
    """Stages an 'Appointment Prep' prompt on the patient for the Assistant panel."""

    PATH = "/app/prep"

    def post(self) -> list[Response | Effect]:
        """Write the prep prompt to patient metadata; the Assistant panel consumes it."""
        body = self.request.json()
        patient_id = (body.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]

        prompt = self.secrets.get(ASSISTANT_PROMPT_SECRET) or DEFAULT_ASSISTANT_PROMPT
        effect = stage_prep_prompt(patient_id, prompt)
        return [effect, JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]
