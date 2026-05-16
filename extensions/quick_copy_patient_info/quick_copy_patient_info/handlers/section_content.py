"""Render the 'Patient Info' custom section.

Surfaces the four fields clinicians and staff most often copy out of a
chart - patient name, date of birth, preferred pharmacy name, and primary
insurance payer name - each with a one-click copy button. Rows are only
included when the underlying field is populated; otherwise the row is
omitted from the rendered HTML.
"""

import base64

from canvas_sdk.effects.patient_chart_summary_custom_section import (
    PatientChartSummaryCustomSection,
)
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.patient import Patient


# Canvas sandbox does not allow importing the CoverageRank / CoverageStack /
# CoverageState enum classes themselves (only the Coverage and Transactor
# models are on the allowlist). The ORM accepts the underlying values
# directly, so we filter against the literal strings and ints. The values
# come from canvas_sdk.v1.data.coverage and are stable:
#   - CoverageRank.PRIMARY    = 1
#   - CoverageStack.IN_USE    = "IN_USE"
#   - CoverageState.ACTIVE    = "active"
_COVERAGE_RANK_PRIMARY = 1
_COVERAGE_STACK_IN_USE = "IN_USE"
_COVERAGE_STATE_ACTIVE = "active"

from quick_copy_patient_info.handlers.section_config import SECTION_KEY


_ICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
    b'<g fill="none" stroke="#2c3e50" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
    b'<rect x="7" y="11" width="34" height="26" rx="3"/>'
    b'<circle cx="18" cy="22" r="4" fill="#2c3e50" stroke="none"/>'
    b'<path d="M11 33 c2 -4 12 -4 14 0"/>'
    b'<path d="M28 19 h8"/>'
    b'<path d="M28 25 h8"/>'
    b'<path d="M28 31 h5"/>'
    b"</g></svg>"
)
_ICON_URL = "data:image/svg+xml;base64," + base64.b64encode(_ICON_SVG).decode("ascii")


def _format_name(patient: Patient) -> dict | None:
    """Build the Name row, or None when both first and last are blank."""
    first = (patient.first_name or "").strip()
    last = (patient.last_name or "").strip()
    full = " ".join(p for p in (first, last) if p)
    if not full:
        return None
    return {"label": "Name", "display": full, "copy": full}


def _format_dob(patient: Patient) -> dict | None:
    """Build the DOB row in MM/DD/YYYY, or None when birth_date is missing."""
    birth_date = patient.birth_date
    if not birth_date:
        return None
    text = birth_date.strftime("%m/%d/%Y")
    return {"label": "DOB", "display": text, "copy": text}


def _format_pharmacy(patient: Patient) -> dict | None:
    """Build the Pharmacy row from the patient's preferred pharmacy setting.

    The setting is stored as a JSON dict (or a list of dicts where one is
    marked default). The Patient model's `preferred_pharmacy` property
    handles both shapes and returns the dict that represents the default.
    The pharmacy name lives under `organization_name`.
    """
    pharmacy = patient.preferred_pharmacy
    if not pharmacy:
        return None
    name = (pharmacy.get("organization_name") or "").strip()
    if not name:
        return None
    return {"label": "Pharmacy", "display": name, "copy": name}


def _format_insurance(patient: Patient) -> dict | None:
    """Build the Insurance row from the patient's primary active coverage.

    "Primary" means `coverage_rank=1`. We additionally filter on
    `state=active` and `stack=IN_USE` because the Canvas UI's "Remove"
    action sets `stack=REMOVED` without touching `state`, so a state-only
    filter would surface coverages that have been removed from the chart.
    The displayed and copied value is the payer name (`issuer.name`).
    """
    coverage = (
        patient.coverages.filter(
            state=_COVERAGE_STATE_ACTIVE,
            stack=_COVERAGE_STACK_IN_USE,
            coverage_rank=_COVERAGE_RANK_PRIMARY,
        )
        .select_related("issuer")
        .first()
    )
    if coverage is None or coverage.issuer is None:
        return None
    name = (coverage.issuer.name or "").strip()
    if not name:
        return None
    return {"label": "Insurance", "display": name, "copy": name}


class QuickCopyPatientInfoSectionContent(PatientChartSummaryCustomSectionHandler):
    """Renders the 'Patient Info' section for the current patient."""

    SECTION_KEY = SECTION_KEY

    def handle(self):
        patient_id = self.event.target.id

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return []

        candidates = (
            _format_name(patient),
            _format_dob(patient),
            _format_pharmacy(patient),
            _format_insurance(patient),
        )
        rows = [row for row in candidates if row is not None]

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
