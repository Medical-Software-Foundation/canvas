"""Render the 'Patient Info' custom section.

Surfaces the four fields clinicians and staff most often copy out of a chart -
patient name, date of birth, primary phone number, and home address - each
with a one-click copy button. Rows are only included when the underlying
field is populated; otherwise the row is omitted from the rendered HTML.
"""

import base64

from canvas_sdk.effects.patient_chart_summary_custom_section import (
    PatientChartSummaryCustomSection,
)
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.common import (
    AddressState,
    AddressUse,
    ContactPointState,
    ContactPointSystem,
)
from canvas_sdk.v1.data.patient import Patient

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


def _format_phone(patient: Patient) -> dict | None:
    """Build the Phone row.

    Display: NANP-formatted "(555) 123-4567" when the raw value parses as a
    10-digit US number (an 11-digit number whose leading digit is 1 is
    accepted and stripped). Otherwise the raw value is shown verbatim.

    Copy payload: digits only, e.g. "5551234567". When the raw value has no
    numeric digits at all, the row is omitted.
    """
    phone = (
        patient.telecom.filter(
            system=ContactPointSystem.PHONE,
            state=ContactPointState.ACTIVE,
        )
        .order_by("rank")
        .first()
    )
    if phone is None or not phone.value:
        return None

    digits = "".join(c for c in phone.value if c.isdigit())
    if not digits:
        return None

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) == 10:
        display = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    else:
        display = phone.value.strip()

    return {"label": "Phone", "display": display, "copy": digits}


def _format_address(patient: Patient) -> dict | None:
    """Build the Address row in multi-line USPS format.

    Prefers home addresses; falls back to the first active address. Returns
    None when no active address is on file or when all the address parts are
    blank.
    """
    addresses = patient.addresses.filter(state=AddressState.ACTIVE)
    address = addresses.filter(use=AddressUse.HOME).first() or addresses.first()
    if address is None:
        return None

    line1 = (address.line1 or "").strip()
    line2 = (address.line2 or "").strip()
    city = (address.city or "").strip()
    state_code = (address.state_code or "").strip()
    postal_code = (address.postal_code or "").strip()

    csz_parts = []
    if city and state_code:
        csz_parts.append(f"{city}, {state_code}")
    elif city:
        csz_parts.append(city)
    elif state_code:
        csz_parts.append(state_code)
    if postal_code:
        csz_parts.append(postal_code)
    csz = " ".join(csz_parts)

    lines = [piece for piece in (line1, line2, csz) if piece]
    if not lines:
        return None

    text = "\n".join(lines)
    return {"label": "Address", "display": text, "copy": text}


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
            _format_phone(patient),
            _format_address(patient),
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
