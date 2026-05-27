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
from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update
from cms_access_fhir_client.modal_html import ALIGN_HTML, ELIGIBILITY_HTML, UNALIGN_HTML
from cms_access_fhir_client.models import ACCESSAlignment
from cms_access_fhir_client.models.access_alignment import CustomPatient


def _get_payer_id(coverage, secrets: dict) -> str | None:
    """Resolve the CMS payerID for a Coverage record.

    Lookup order:
    1. coverage.issuer.payer_id — the Transactor identifier, preferred when populated.
    2. ACCESS_DEFAULT_PAYER_ID secret — escape hatch when Transactor.payer_id is empty.
    3. Returns None if both are absent, signalling fail-closed to the caller.
    """
    payer_id = getattr(coverage.issuer, "payer_id", None)
    if payer_id:
        return payer_id
    default = secrets.get("ACCESS_DEFAULT_PAYER_ID", "")
    if default:
        return default
    return None


class AccessOperationsApi(StaffSessionAuthMixin, SimpleAPI):
    """Internal endpoints invoked by the chart-button modals.

    All routes are gated on a Canvas staff session via StaffSessionAuthMixin.
    """

    @api.get("/eligibility")
    def eligibility_modal(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        return [HTMLResponse(ELIGIBILITY_HTML.replace("__PATIENT_ID__", patient_id))]

    @api.post("/eligibility")
    def submit_eligibility(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id")
        track = body.get("track")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not track:
            return [JSONResponse({"error": "Missing track"}, status_code=HTTPStatus.BAD_REQUEST)]

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

        payer_id = _get_payer_id(coverage, self.secrets)
        if not payer_id:
            return [
                JSONResponse(
                    {"error": "Cannot determine payerID — populate Transactor.payer_id on the Medicare Part B payer or set ACCESS_DEFAULT_PAYER_ID secret"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        try:
            result = check_eligibility(
                self.secrets,
                mbi=coverage.id_number,
                payer_id=payer_id,
                track=track,
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] $check-eligibility failed for patient {patient.id}: {exc}")
            alignment, _ = ACCESSAlignment.objects.get_or_create(
                patient=patient,
                track=track,
                defaults={"status": ACCESSAlignment.STATUS_ERROR},
            )
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = str(exc)
            alignment.last_eligibility_check_at = _utcnow()
            alignment.save()
            return [
                broadcast_alignment_update(str(patient.id)),
                JSONResponse(
                    {"error": f"CMS request failed: {exc}", "status": alignment.status},
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

        status = _extract_eligibility_status(result)
        alignment, _ = ACCESSAlignment.objects.get_or_create(
            patient=patient,
            track=track,
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

        return [
            broadcast_alignment_update(str(patient.id)),
            JSONResponse({"status": alignment.status}, status_code=HTTPStatus.OK),
        ]

    @api.get("/align")
    def align_modal(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        return [HTMLResponse(ALIGN_HTML.replace("__PATIENT_ID__", patient_id))]

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

        payer_id = _get_payer_id(coverage, self.secrets)
        if not payer_id:
            return [
                JSONResponse(
                    {"error": "Cannot determine payerID — populate Transactor.payer_id on the Medicare Part B payer or set ACCESS_DEFAULT_PAYER_ID secret"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        try:
            status_code, content_location, _ = align(
                self.secrets,
                mbi=coverage.id_number,
                payer_id=payer_id,
                track=track,
                clinical_justification=clinical_justification,
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] $align failed for patient {patient.id}: {exc}")
            alignment, _ = ACCESSAlignment.objects.get_or_create(
                patient=patient,
                track=track,
                defaults={"status": ACCESSAlignment.STATUS_ERROR},
            )
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = str(exc)
            alignment.clinical_justification = clinical_justification
            alignment.save()
            return [
                broadcast_alignment_update(str(patient.id)),
                JSONResponse(
                    {"error": f"CMS request failed: {exc}", "status": alignment.status},
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

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

        return [
            broadcast_alignment_update(str(patient.id)),
            JSONResponse({"status": alignment.status}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.get("/unalign")
    def unalign_modal(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        return [HTMLResponse(UNALIGN_HTML.replace("__PATIENT_ID__", patient_id))]

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

        payer_id = _get_payer_id(coverage, self.secrets)
        if not payer_id:
            return [
                JSONResponse(
                    {"error": "Cannot determine payerID — populate Transactor.payer_id on the Medicare Part B payer or set ACCESS_DEFAULT_PAYER_ID secret"},
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

        try:
            status_code, content_location, _ = unalign(
                self.secrets,
                mbi=coverage.id_number,
                payer_id=payer_id,
                track=alignment.track,
                alignment_id=alignment_id,
                reason_code=reason_code,
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] $unalign failed for patient {patient.id}: {exc}")
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = str(exc)
            alignment.save()
            return [
                broadcast_alignment_update(str(patient.id)),
                JSONResponse(
                    {"error": f"CMS request failed: {exc}", "status": alignment.status},
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

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

        return [
            broadcast_alignment_update(str(patient.id)),
            JSONResponse({"status": alignment.status}, status_code=HTTPStatus.ACCEPTED),
        ]


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
