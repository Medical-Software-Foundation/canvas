"""Render the 'Last Reviewed' custom section.

For each chart section that supports the "Mark as Reviewed" workflow, find the
most recent committed ChartSectionReview command and report when it was
reviewed and by whom. Sections never reviewed for this patient are surfaced
explicitly so missing reviews are obvious.
"""

import base64
from datetime import datetime

import arrow
from canvas_sdk.effects.patient_chart_summary_custom_section import (
    PatientChartSummaryCustomSection,
)
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import NoteStates

from last_reviewed.handlers.section_config import SECTION_KEY


# (display label, value as it appears in Command.data["section"]).
# Values come from canvas_sdk.commands.commands.chart_section_review.ChartSectionReviewCommand.Sections.
_SECTIONS = [
    ("Conditions", "conditions"),
    ("Medications", "medications"),
    ("Allergies", "allergies"),
    ("Immunizations", "immunizations"),
    ("Surgical History", "surgical_history"),
    ("Family History", "family_histories"),
]


_ICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
    b'<g fill="none" stroke="#2c3e50" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
    b'<rect x="9" y="8" width="30" height="34" rx="3"/>'
    b'<rect x="18" y="4" width="12" height="6" rx="1.5" fill="#2c3e50"/>'
    b'<path d="M16 24 l5 5 l11 -11"/>'
    b'<path d="M16 36 h12"/>'
    b"</g></svg>"
)
_ICON_URL = "data:image/svg+xml;base64," + base64.b64encode(_ICON_SVG).decode("ascii")


def _committer_name(user) -> str | None:
    if user is None or not user.is_staff:
        return None
    try:
        staff = user.staff
    except Exception:
        return None
    if staff is None:
        return None
    name = f"{staff.first_name} {staff.last_name}".strip()
    return name or None


def _format_row(label: str, command: Command | None) -> dict:
    if command is None:
        return {"label": label, "reviewed": False}
    when: datetime = command.created
    return {
        "label": label,
        "reviewed": True,
        "relative": arrow.get(when).humanize(),
        "absolute": arrow.get(when).format("YYYY-MM-DD HH:mm ZZZ"),
        "reviewer": _committer_name(command.committer),
    }


class LastReviewedSectionContent(PatientChartSummaryCustomSectionHandler):
    """Renders the 'Last Reviewed' section for the current patient."""

    SECTION_KEY = SECTION_KEY

    def handle(self):
        patient_id = self.event.target.id

        # Canvas's "Mark as reviewed" workflow commits the chartSectionReview
        # command into a small standalone note. When a clinician deletes the
        # review, the Command row is left untouched (state stays 'committed',
        # entered_in_error stays null) and the parent note is moved to the
        # DELETED state instead. To honor "rolled back" reviews we have to
        # exclude commands whose note is currently deleted.
        commands = (
            Command.objects.filter(
                patient__id=patient_id,
                schema_key="chartSectionReview",
                state="committed",
                entered_in_error__isnull=True,
            )
            .exclude(note__current_state__state=NoteStates.DELETED)
            .select_related("committer")
            .order_by("-created")
        )

        wanted = {value for _, value in _SECTIONS}
        latest: dict[str, Command] = {}
        for command in commands.iterator():
            section_value = (command.data or {}).get("section")
            if section_value in wanted and section_value not in latest:
                latest[section_value] = command
            if len(latest) == len(wanted):
                break

        rows = [_format_row(label, latest.get(value)) for label, value in _SECTIONS]
        styles = render_to_string("static/section.css")
        script = render_to_string("static/section.js")
        html = render_to_string(
            "static/section.html",
            {"rows": rows, "styles": styles, "script": script},
        )

        return [
            PatientChartSummaryCustomSection(
                content=html,
                icon_url=_ICON_URL,
            ).apply()
        ]
