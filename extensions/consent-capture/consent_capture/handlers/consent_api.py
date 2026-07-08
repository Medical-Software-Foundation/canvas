"""Endpoint that records an accepted consent via the Canvas FHIR API.

Called by the consent modal's "Accept" button. Builds a documentation PDF naming
the logged-in staff member who collected the verbal consent, then creates a FHIR
Consent (status active, effective today, no expiration) with the PDF attached as
the source attachment.
"""

import re
from datetime import datetime, timezone
from http import HTTPStatus

# Matches an ISO calendar date (YYYY-MM-DD) sent by the browser.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

from canvas_sdk.clients.canvas_fhir import CanvasFhir
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data import Patient, Staff

from logger import log

from consent_capture.constants import parse_statement
from consent_capture.fhir import build_consent_payload
from consent_capture.pdf import generate_consent_pdf_base64


def _clean_time(value):
    """Sanitize a browser-supplied local time like '2:32 PM' for display."""
    if not value:
        return ""
    allowed = set("0123456789: APMapm")
    cleaned = "".join(ch for ch in value.strip() if ch in allowed).strip()
    return cleaned[:12]


def _clean_text(value, limit=80):
    """Trim free text and drop control characters for safe display."""
    if not value:
        return ""
    cleaned = "".join(ch for ch in str(value) if ch == " " or ch.isprintable())
    return cleaned.strip()[:limit]


def _consented_by(body):
    """Return (label, error). label is who consented, e.g. 'Patient' or
    'Jane Doe (Daughter)'. error is a user-facing string or None."""
    who = (body.get("consent_by") or "patient").strip().lower()
    if who != "representative":
        return "Patient", None
    name = _clean_text(body.get("representative_name"))
    if not name:
        return None, "Please enter the representative's name."
    relationship = _clean_text(body.get("representative_relationship"), limit=60)
    if relationship:
        return "%s (%s)" % (name, relationship), None
    return name, None


def _full_name(first, last, fallback):
    name = ("%s %s" % (first or "", last or "")).strip()
    return name or fallback


def _resolve_patient(patient_id):
    """Return (full_name, date_of_birth_iso) or None if the patient isn't found."""
    row = (
        Patient.objects.filter(id=patient_id)
        .values_list("first_name", "last_name", "birth_date")
        .first()
    )
    if not row:
        return None
    name = _full_name(row[0], row[1], "(name unavailable)")
    dob = row[2].isoformat() if row[2] else ""
    return name, dob


def _resolve_staff(staff_id):
    if not staff_id:
        return "Unknown"
    row = (
        Staff.objects.filter(id=staff_id)
        .values_list("first_name", "last_name")
        .first()
    )
    if not row:
        return "Unknown"
    return _full_name(row[0], row[1], "Unknown")


class ConsentApi(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = "/consent"

    @api.post("/collect")
    def collect(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        patient_id = body.get("patient_id")

        # Authoritative identity of the collector: the logged-in staff session.
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")

        system = self.secrets.get("CONSENT_SYSTEM", "")
        code = self.secrets.get("CONSENT_CODE", "")
        display = self.secrets.get("CONSENT_DISPLAY", "")
        client_id = self.secrets.get("CANVAS_FHIR_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_FHIR_CLIENT_SECRET", "")

        if not patient_id:
            return [self._error("No patient was identified for this consent.")]
        if not code:
            return [
                self._error(
                    "This plugin isn't fully configured yet — the consent code "
                    "is missing. Please contact your administrator."
                )
            ]
        if not client_id or not client_secret:
            return [
                self._error(
                    "This plugin isn't fully configured yet — the Canvas FHIR "
                    "credentials are missing. Please contact your administrator."
                )
            ]

        patient = _resolve_patient(patient_id)
        if patient is None:
            return [self._error("We couldn't find this patient's record.")]
        patient_name, patient_dob = patient

        staff_name = _resolve_staff(staff_id)

        # Use the end user's LOCAL calendar date (sent by the browser) so the
        # consent date reflects the user's day, not UTC — which could otherwise
        # roll a late-evening consent onto the next/previous day. Fall back to the
        # server's UTC date only if the browser didn't send a valid date.
        local_date = (body.get("local_date") or "").strip()
        if _DATE_RE.match(local_date):
            today = local_date
        else:
            today = datetime.now(timezone.utc).date().isoformat()

        # Local wall-clock time (from the browser) for the footer timestamp.
        local_time = _clean_time(body.get("local_time"))

        # Who is giving consent: the patient or an authorized representative.
        consented_by, who_error = _consented_by(body)
        if who_error:
            return [self._error(who_error)]

        pdf_b64 = generate_consent_pdf_base64(
            title=display or code,
            patient_name=patient_name,
            patient_dob=patient_dob,
            staff_name=staff_name,
            date=today,
            statement_paragraphs=parse_statement(self.secrets.get("CONSENT_STATEMENT", "")),
            time=local_time,
            consented_by=consented_by,
        )

        payload = build_consent_payload(
            system=system,
            code=code,
            display=display,
            patient_id=patient_id,
            pdf_base64=pdf_b64,
            today=today,
        )

        try:
            client = CanvasFhir(client_id, client_secret)
            client.create("Consent", payload)
        except Exception as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            # Canvas returns 201 with an empty body on a successful Consent
            # create, which makes the client's JSON parse raise a ValueError even
            # though the write succeeded. Treat 2xx (or an empty-body parse error
            # with no HTTP response) as success; only real 4xx/5xx or connection
            # failures are errors.
            if status is not None and status < 400:
                log.info(
                    "ConsentApi: consent created (HTTP %s, empty body) for "
                    "patient %s" % (status, patient_id)
                )
            elif status is None and isinstance(exc, ValueError):
                log.info(
                    "ConsentApi: consent created (empty response body) for "
                    "patient %s" % patient_id
                )
            else:
                detail = getattr(response, "text", str(exc))
                log.error(
                    "ConsentApi: FHIR Consent create failed (HTTP %s) for "
                    "patient %s: %s" % (status, patient_id, detail)
                )
                return [
                    self._error(
                        "We couldn't save the consent. If this keeps happening, "
                        "please contact your administrator."
                    )
                ]

        log.info(
            "ConsentApi: recorded consent %s for patient %s, collected by %s"
            % (code, patient_id, staff_name)
        )
        return [
            JSONResponse(
                {
                    "ok": True,
                    "preview": {
                        "title": display or code,
                        "patient_name": patient_name,
                        "patient_dob": patient_dob,
                        "consented_by": consented_by,
                        "collected_by": staff_name,
                        "date": today,
                        "time": local_time,
                    },
                },
                status_code=HTTPStatus.OK,
            )
        ]

    def _error(self, message):
        return JSONResponse(
            {"ok": False, "error": message},
            status_code=HTTPStatus.OK,
        )
