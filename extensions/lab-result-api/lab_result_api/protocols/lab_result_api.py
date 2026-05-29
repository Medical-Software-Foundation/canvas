from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPIRoute
from canvas_sdk.v1.data.lab import LabReport, LabValue
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
            lab_report = (
                LabReport.objects
                .with_result_tests_and_values()
                .prefetch_related("tests__values__codings", "values__codings")
                .get(id=lab_report_id, entered_in_error__isnull=True)
            )
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
        lab_order: dict[str, Any] = {}
        lab_partner_name = None

        # Access lab orders through the reverse relationship, skipping any
        # order retracted as entered-in-error so a retracted order is never
        # surfaced as the canonical order block.
        lab_orders = lab_report.laborder_set.select_related("ordering_provider").filter(
            entered_in_error__isnull=True
        )
        if lab_orders:
            first_order = lab_orders[0]
            if first_order.ordering_provider:
                lab_order["ordering_provider"] = {
                    "id": str(first_order.ordering_provider.id),
                    "first_name": first_order.ordering_provider.first_name,
                    "last_name": first_order.ordering_provider.last_name,
                    "npi": first_order.ordering_provider.npi_number,
                }
            lab_partner_name = first_order.ontology_lab_partner
            lab_order["comment"] = first_order.comment
            lab_order["date_ordered"] = first_order.date_ordered.isoformat() if first_order.date_ordered else None
            lab_order["reason_conditions"] = self._serialize_reason_conditions(first_order)


        lab_tests = [
            {
                "id": str(lab_test.id),
                "name": lab_test.ontology_test_name,
                "ontology_test_code": lab_test.ontology_test_code,
                "values": [self._serialize_lab_value(v) for v in lab_test.values.all()],
            }
            for lab_test in lab_report.result_tests
        ]

        # Legacy reports may have LabValues attached directly to the report with no
        # associated LabTest. Surface those separately so consumers still see them.
        unassigned_values = [
            self._serialize_lab_value(v)
            for v in lab_report.values.all()
            if v.test_id is None
        ]

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
            "lab_result": {
                "tests": lab_tests,
                "unassigned_values": unassigned_values,
            },
        }

        return lab_data

    def _serialize_reason_conditions(self, order: Any) -> list[dict[str, Any]]:
        reason_conditions = []
        reasons = order.reasons.filter(entered_in_error__isnull=True).prefetch_related(
            "reason_conditions__condition__codings"
        )
        for reason in reasons:
            for reason_condition in reason.reason_conditions.all():
                condition = reason_condition.condition
                if condition is None or condition.entered_in_error_id is not None:
                    continue
                reason_conditions.append({
                    "id": str(condition.id),
                    "codings": [
                        {"code": c.code, "display": c.display, "system": c.system}
                        for c in condition.codings.all()
                    ],
                })
        return reason_conditions

    def _serialize_lab_value(self, lab_value: LabValue) -> dict[str, Any]:
        value_data = {
            "id": str(lab_value.id),
            "value": lab_value.value,
            "units": lab_value.units,
            "reference_range": "" if lab_value.reference_range.strip() == "-" else lab_value.reference_range,
            "abnormal_flag": bool(lab_value.abnormal_flag),
            "observation_status": lab_value.observation_status,
            "low_threshold": lab_value.low_threshold,
            "high_threshold": lab_value.high_threshold,
            "comment": lab_value.comment,
            "created": lab_value.created.isoformat() if lab_value.created else None,
            "modified": lab_value.modified.isoformat() if lab_value.modified else None,
        }

        coding = lab_value.codings.first()
        if coding is not None:
            value_data["name"] = coding.name
            value_data["code"] = coding.code
            value_data["coding_system"] = coding.system

        return value_data
