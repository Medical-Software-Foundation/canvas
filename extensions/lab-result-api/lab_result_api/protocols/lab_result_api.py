from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPIRoute
from canvas_sdk.v1.data.lab import LabReport
from logger import log


class LabResultAPI(APIKeyAuthMixin, SimpleAPIRoute):
    """
    SimpleAPI endpoint that returns lab result data with test values.

    GET /lab-result/<lab_report_id> - Returns comprehensive lab result data including
    ordering provider, lab facility, and all individual test results.
    """

    PATH = "/lab-result/<lab_report_id>"

    def get(self) -> list[Response | Effect]:
        """
        Retrieve a lab report by ID with all related data.

        Returns:
            - Lab report metadata
            - Ordering provider information
            - Lab facility details
            - Patient demographics
            - All lab test values with results, units, and reference ranges
        """
        lab_report_id = self.request.path_params.get("lab_report_id")

        if not lab_report_id:
            return [
                JSONResponse(
                    {"error": "Lab report ID is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            lab_report = LabReport.objects.get(id=lab_report_id)
        except LabReport.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Lab report not found", "lab_report_id": lab_report_id},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        lab_data = self._serialize_lab_report(lab_report)
        log.info(f"Lab report data retrieved: {lab_report_id}")
        return [JSONResponse(lab_data, status_code=HTTPStatus.OK)]

    def _serialize_lab_report(self, lab_report: LabReport) -> dict[str, Any]:
        """
        Serialize lab report with all related data.
        """
        # Get ordering provider and lab facility from related lab orders
        lab_order = {}
        lab_partner_name = None

        # Access lab orders through the reverse relationship
        lab_orders = lab_report.laborder_set.all()
        if lab_orders:
            first_order = lab_orders[0]
            if first_order.ordering_provider:
                lab_order["ordering_provider"] = {
                    "id": str(first_order.ordering_provider.id),
                    "first_name": first_order.ordering_provider.first_name,
                    "last_name": first_order.ordering_provider.last_name,
                    "npi": first_order.ordering_provider.npi if hasattr(first_order.ordering_provider, 'npi') else None,
                }
            lab_partner_name = first_order.ontology_lab_partner
            lab_order["comment"] = first_order.comment
            lab_order["date_ordered"] = first_order.date_ordered.isoformat() if first_order.date_ordered else None
            

        lab_tests = []
        for lab_test in lab_report.tests.all():
            lab_tests.append({
                "id": str(lab_test.id),
                "name": lab_test.ontology_test_name,
                "code": lab_test.ontology_test_code,
            })

        # Serialize lab values (individual test results)
        lab_values = []
        for lab_value in lab_report.values.all():
            test_data = {
                "id": str(lab_value.id),
                "value": lab_value.value,
                "units": lab_value.units,
                "reference_range": lab_value.reference_range,
                "abnormal_flag": lab_value.abnormal_flag,
                "observation_status": lab_value.observation_status,
                "low_threshold": lab_value.low_threshold,
                "high_threshold": lab_value.high_threshold,
                "comment": lab_value.comment,
                "created": lab_value.created.isoformat() if lab_value.created else None,
                "modified": lab_value.modified.isoformat() if lab_value.modified else None,
            }

            # Add test name from codings if available
            if lab_value.codings.exists():
                coding = lab_value.codings.first()
                test_data["name"] = coding.name
                test_data["code"] = coding.code
                test_data["coding_system"] = coding.system

            lab_values.append(test_data)

        lab_data = {
            "id": str(lab_report.id),
            "dbid": lab_report.dbid,
            "created": lab_report.created.isoformat() if lab_report.created else None,
            "modified": lab_report.modified.isoformat() if lab_report.modified else None,
            "patient": {
                "id": str(lab_report.patient.id),
                "first_name": lab_report.patient.first_name,
                "last_name": lab_report.patient.last_name,
                "birth_date": lab_report.patient.birth_date.isoformat() if lab_report.patient.birth_date else None,
            } if lab_report.patient else None,
            "lab_order": lab_order,
            "lab_facility": {
                "name": lab_partner_name,
            } if lab_partner_name else None,
            "lab_tests": lab_tests,
            "lab_values": lab_values,
        }

        return lab_data
