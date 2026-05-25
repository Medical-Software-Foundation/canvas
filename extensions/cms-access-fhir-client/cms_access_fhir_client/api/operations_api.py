"""Internal API endpoints invoked by the chart-button modals.

Routes:
    GET  /eligibility          — renders eligibility check modal (HTML)
    POST /eligibility          — submits $check-eligibility to CMS
    GET  /align                — renders align modal (HTML)
    POST /align                — submits $align to CMS
    GET  /unalign              — renders unalign modal (HTML)
    POST /unalign              — submits $unalign to CMS

Authentication: StaffSessionAuthMixin — all routes require a logged-in Canvas staff session.
"""
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from logger import log

from cms_access_fhir_client.cms_client import align, check_eligibility, unalign
from cms_access_fhir_client.coverage_lookup import get_active_medicare_part_b_coverage
from cms_access_fhir_client.models import ACCESSAlignment
from cms_access_fhir_client.models.access_alignment import CustomPatient


_ELIGIBILITY_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         padding: 24px; max-width: 480px; margin: auto; }}
  h2 {{ margin-bottom: 16px; }}
  .result {{ margin-top: 16px; padding: 12px; border-radius: 4px; }}
  .ok {{ background: #dcfce7; color: #16a34a; }}
  .err {{ background: #fee2e2; color: #dc2626; }}
  button {{ padding: 8px 16px; background: #2563eb; color: white;
            border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
  button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
</style>
</head>
<body>
  <h2>Check ACCESS Eligibility</h2>
  <p>Patient ID: <code>{patient_id}</code></p>
  <button id="btn" onclick="checkEligibility()">Check Eligibility</button>
  <div id="result"></div>
  <script>
    async function checkEligibility() {{
      const btn = document.getElementById('btn');
      const result = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Checking...';
      try {{
        const resp = await fetch('/plugin-io/api/cms_access_fhir_client/eligibility', {{
          method: 'POST',
          credentials: 'include',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{patient_id: '{patient_id}'}})
        }});
        const data = await resp.json();
        result.className = 'result ' + (resp.ok ? 'ok' : 'err');
        result.textContent = resp.ok
          ? 'Status: ' + data.status
          : 'Error: ' + (data.error || resp.status);
      }} catch (e) {{
        result.className = 'result err';
        result.textContent = 'Request failed: ' + e.message;
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Check Eligibility';
      }}
    }}
  </script>
</body></html>"""

_ALIGN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         padding: 24px; max-width: 480px; margin: auto; }}
  h2 {{ margin-bottom: 16px; }}
  label {{ display: block; margin-bottom: 4px; font-weight: 500; }}
  select, textarea {{ width: 100%; margin-bottom: 12px; padding: 6px;
                      border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }}
  textarea {{ height: 80px; resize: vertical; }}
  .result {{ margin-top: 16px; padding: 12px; border-radius: 4px; }}
  .ok {{ background: #dcfce7; color: #16a34a; }}
  .err {{ background: #fee2e2; color: #dc2626; }}
  button {{ padding: 8px 16px; background: #16a34a; color: white;
            border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
  button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
</style>
</head>
<body>
  <h2>Enroll in ACCESS</h2>
  <form id="form" onsubmit="submitAlign(event)">
    <label for="track">Track</label>
    <select id="track" required>
      <option value="">Select track...</option>
      <option value="eCKM">eCKM — Enhanced Kidney Care Model</option>
      <option value="CKM">CKM — Kidney Care Model</option>
      <option value="MSK">MSK — Musculoskeletal</option>
      <option value="BH">BH — Behavioral Health</option>
    </select>
    <label for="justification">Clinical Justification</label>
    <textarea id="justification" required placeholder="Enter clinical justification..."></textarea>
    <button type="submit" id="btn">Submit Enrollment</button>
  </form>
  <div id="result"></div>
  <script>
    async function submitAlign(e) {{
      e.preventDefault();
      const btn = document.getElementById('btn');
      const result = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Submitting...';
      try {{
        const resp = await fetch('/plugin-io/api/cms_access_fhir_client/align', {{
          method: 'POST',
          credentials: 'include',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            patient_id: '{patient_id}',
            track: document.getElementById('track').value,
            clinical_justification: document.getElementById('justification').value,
          }})
        }});
        const data = await resp.json();
        result.className = 'result ' + (resp.ok ? 'ok' : 'err');
        result.textContent = resp.ok
          ? 'Enrollment submitted. Status: ' + data.status
          : 'Error: ' + (data.error || resp.status);
      }} catch (e) {{
        result.className = 'result err';
        result.textContent = 'Request failed: ' + e.message;
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Submit Enrollment';
      }}
    }}
  </script>
</body></html>"""

_UNALIGN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         padding: 24px; max-width: 480px; margin: auto; }}
  h2 {{ margin-bottom: 16px; }}
  label {{ display: block; margin-bottom: 4px; font-weight: 500; }}
  select {{ width: 100%; margin-bottom: 12px; padding: 6px;
            border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }}
  .result {{ margin-top: 16px; padding: 12px; border-radius: 4px; }}
  .ok {{ background: #dcfce7; color: #16a34a; }}
  .err {{ background: #fee2e2; color: #dc2626; }}
  button {{ padding: 8px 16px; background: #dc2626; color: white;
            border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
  button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
</style>
</head>
<body>
  <h2>Unalign from ACCESS</h2>
  <form id="form" onsubmit="submitUnalign(event)">
    <label for="reason">Reason for Unalignment</label>
    <select id="reason" required>
      <option value="">Select reason...</option>
      <option value="patient-request">Patient Request</option>
      <option value="provider-decision">Provider Decision</option>
      <option value="care-completed">Care Completed</option>
      <option value="other">Other</option>
    </select>
    <button type="submit" id="btn">Submit Unalignment</button>
  </form>
  <div id="result"></div>
  <script>
    async function submitUnalign(e) {{
      e.preventDefault();
      const btn = document.getElementById('btn');
      const result = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Submitting...';
      try {{
        const resp = await fetch('/plugin-io/api/cms_access_fhir_client/unalign', {{
          method: 'POST',
          credentials: 'include',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            patient_id: '{patient_id}',
            reason_code: document.getElementById('reason').value,
          }})
        }});
        const data = await resp.json();
        result.className = 'result ' + (resp.ok ? 'ok' : 'err');
        result.textContent = resp.ok
          ? 'Unalignment submitted.'
          : 'Error: ' + (data.error || resp.status);
      }} catch (e) {{
        result.className = 'result err';
        result.textContent = 'Request failed: ' + e.message;
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Submit Unalignment';
      }}
    }}
  </script>
</body></html>"""


def _build_patient_resource(patient, mbi: str) -> dict:
    """Build a FHIR Patient resource embedding the MBI for transmission to CMS.

    None-valued top-level fields are stripped to avoid FHIR validator rejections.
    """
    resource: dict = {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "http://hl7.org/fhir/sid/us-mbi",
                "value": mbi,
            }
        ],
        "name": [{"family": patient.last_name, "given": [patient.first_name]}],
    }
    birth_date = getattr(patient, "birth_date", None)
    if birth_date is not None:
        resource["birthDate"] = birth_date.isoformat()
    return resource


class AccessOperationsApi(StaffSessionAuthMixin, SimpleAPI):
    """Internal endpoints invoked by the chart-button modals.

    All routes are gated on a Canvas staff session via StaffSessionAuthMixin.
    """

    @api.get("/eligibility")
    def eligibility_modal(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        return [HTMLResponse(_ELIGIBILITY_HTML.format(patient_id=patient_id))]

    @api.post("/eligibility")
    def submit_eligibility(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
        if coverage is None:
            return [
                JSONResponse(
                    {"error": "Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        patient_resource = _build_patient_resource(patient, mbi=coverage.id_number)
        result = check_eligibility(self.secrets, patient_resource=patient_resource)

        status = _extract_eligibility_status(result)
        alignment, _ = ACCESSAlignment.objects.get_or_create(
            patient=patient,
            track="",
            defaults={"status": status},
        )
        alignment.status = status
        alignment.last_eligibility_check_at = _utcnow()

        if result.get("status_code") == 202:
            content_location = result.get("content_location")
            if content_location:
                alignment.submission_status_url = content_location
                alignment.submission_state = ACCESSAlignment.SUB_STATE_IN_PROGRESS
                alignment.submission_op = ACCESSAlignment.SUB_OP_ELIGIBILITY
                alignment.submission_started_at = _utcnow()
                alignment.poll_attempts = 0

        alignment.save()

        return [JSONResponse({"status": alignment.status}, status_code=HTTPStatus.OK)]

    @api.get("/align")
    def align_modal(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        return [HTMLResponse(_ALIGN_HTML.format(patient_id=patient_id))]

    @api.post("/align")
    def submit_align(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id")
        track = body.get("track")
        clinical_justification = body.get("clinical_justification")

        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not track:
            return [JSONResponse({"error": "Missing track"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not clinical_justification:
            return [JSONResponse({"error": "Missing clinical_justification"}, status_code=HTTPStatus.BAD_REQUEST)]

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
        if coverage is None:
            return [
                JSONResponse(
                    {"error": "Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        patient_resource = _build_patient_resource(patient, mbi=coverage.id_number)
        status_code, content_location, _ = align(
            self.secrets,
            patient_resource=patient_resource,
            track=track,
            clinical_justification=clinical_justification,
        )

        alignment, _ = ACCESSAlignment.objects.get_or_create(
            patient=patient,
            track=track,
            defaults={"status": ACCESSAlignment.STATUS_PENDING},
        )
        alignment.status = ACCESSAlignment.STATUS_PENDING
        alignment.clinical_justification = clinical_justification

        if status_code == 202 and content_location:
            alignment.submission_status_url = content_location
            alignment.submission_state = ACCESSAlignment.SUB_STATE_IN_PROGRESS
            alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN
            alignment.submission_started_at = _utcnow()
            alignment.poll_attempts = 0

        alignment.save()
        log.info(f"[cms-access] Align submitted for patient {patient_id}, track {track}")

        return [JSONResponse({"status": alignment.status}, status_code=HTTPStatus.ACCEPTED)]

    @api.get("/unalign")
    def unalign_modal(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        return [HTMLResponse(_UNALIGN_HTML.format(patient_id=patient_id))]

    @api.post("/unalign")
    def submit_unalign(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id")
        reason_code = body.get("reason_code")

        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not reason_code:
            return [JSONResponse({"error": "Missing reason_code"}, status_code=HTTPStatus.BAD_REQUEST)]

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
        if coverage is None:
            return [
                JSONResponse(
                    {"error": "Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        alignment = (
            ACCESSAlignment.objects.filter(
                patient=patient,
                status=ACCESSAlignment.STATUS_ALIGNED,
            )
            .order_by("-updated_at")
            .first()
        )

        if not alignment:
            return [
                JSONResponse(
                    {"error": "No active alignment found for this patient"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        alignment_id = alignment.alignment_id
        if not alignment_id:
            return [
                JSONResponse(
                    {"error": "Alignment record is missing alignment_id"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        status_code, content_location, _ = unalign(
            self.secrets,
            alignment_id=alignment_id,
            reason_code=reason_code,
        )

        alignment.unalignment_reason = reason_code
        if status_code == 202 and content_location:
            alignment.submission_status_url = content_location
            alignment.submission_state = ACCESSAlignment.SUB_STATE_IN_PROGRESS
            alignment.submission_op = ACCESSAlignment.SUB_OP_UNALIGN
            alignment.submission_started_at = _utcnow()
            alignment.poll_attempts = 0
        else:
            alignment.status = ACCESSAlignment.STATUS_UNALIGNED

        alignment.save()
        log.info(f"[cms-access] Unalign submitted for patient {patient_id}")

        return [JSONResponse({"status": alignment.status}, status_code=HTTPStatus.ACCEPTED)]


def _extract_eligibility_status(result: dict) -> str:
    """Parse a CMS check-eligibility Parameters response into an ACCESSAlignment status string."""
    for param in result.get("parameter", []):
        if param.get("name") == "status":
            code = param.get("valueCode", "")
            if code == "eligible":
                return ACCESSAlignment.STATUS_ELIGIBLE
            if code == "ineligible":
                return ACCESSAlignment.STATUS_INELIGIBLE
            if code == "already-aligned":
                return ACCESSAlignment.STATUS_ALREADY_ALIGNED
    return ACCESSAlignment.STATUS_ERROR


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
