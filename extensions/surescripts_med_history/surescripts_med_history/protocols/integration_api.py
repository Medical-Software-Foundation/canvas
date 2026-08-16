from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPI, api
from canvas_sdk.v1.data.patient import Patient

from logger import log

from surescripts_med_history.models import MedicationDismissal


class DismissalsIntegrationApi(APIKeyAuthMixin, SimpleAPI):
    """API-key-authenticated endpoints for other plugins to read/write medication dismissals.

    The chart-UI dismiss path (MedHistoryRequestApi.dismiss) stays on
    staff-session auth — this is the inter-plugin surface. Callers supply
    the dismissed_by attribution since there's no logged-in staff session
    on a server-to-server call.

    URL from another plugin:
        https://<instance>.canvasmedical.com/plugin-io/api/surescripts_med_history/integration/dismissals
    Authorization header: the value of secret `simpleapi-api-key`.
    """

    PREFIX = "/integration"

    @api.get("/dismissals")
    def list_dismissals(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id", "")
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient_dbid = Patient.objects.values_list("dbid", flat=True).get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Patient not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        dismissals = MedicationDismissal.objects.filter(
            patient_id=patient_dbid
        ).order_by("-dismissed_at")

        payload = [
            {
                "group_key": d.group_key,
                "drug_description": d.drug_description,
                "dismissed_by": d.dismissed_by,
                "dismissed_by_id": d.dismissed_by_id,
                "dismissed_at": d.dismissed_at.isoformat() if d.dismissed_at else "",
            }
            for d in dismissals
        ]
        return [JSONResponse({"dismissals": payload}, status_code=HTTPStatus.OK)]

    @api.post("/dismissals")
    def create_dismissal(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id", "")
        group_key = body.get("group_key", "")
        dismissed_by = body.get("dismissed_by", "")
        dismissed_by_id = body.get("dismissed_by_id", "")
        drug_description = body.get("drug_description", "") or ""

        missing = [
            name
            for name, value in (
                ("patient_id", patient_id),
                ("group_key", group_key),
                ("dismissed_by", dismissed_by),
                ("dismissed_by_id", dismissed_by_id),
            )
            if not value
        ]
        if missing:
            return [
                JSONResponse(
                    {"error": "Missing required fields: %s" % ", ".join(missing)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient_dbid = Patient.objects.values_list("dbid", flat=True).get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Patient not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        MedicationDismissal.objects.update_or_create(
            patient_id=patient_dbid,
            group_key=group_key,
            defaults={
                "drug_description": drug_description,
                "dismissed_by": dismissed_by,
                "dismissed_by_id": dismissed_by_id,
            },
        )
        log.info(
            "Integration dismiss: patient %s group %s by %s (%s)"
            % (patient_id, group_key, dismissed_by, dismissed_by_id)
        )
        return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]
