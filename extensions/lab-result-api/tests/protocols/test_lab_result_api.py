import json
from http import HTTPStatus
from typing import Any, Callable
from unittest.mock import MagicMock, call, patch

import pytest

from lab_result_api.protocols.lab_result_api import LabResultAPI


def _invoke_get(
    handler: LabResultAPI,
    mock_request: MagicMock,
    lab_report: MagicMock | None = None,
    raises: type[BaseException] | None = None,
) -> tuple[list[Any], MagicMock]:
    """Patch LabReport with the prefetch chain and invoke handler.get()."""
    with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
        # Production chain: LabReport.objects.with_result_tests_and_values()
        #   .prefetch_related(...).get(id=...)
        query_chain = (
            mock_lab_report_class.objects
            .with_result_tests_and_values.return_value
            .prefetch_related.return_value
        )
        if raises is not None:
            mock_lab_report_class.DoesNotExist = raises
            query_chain.get.side_effect = raises()
        else:
            query_chain.get.return_value = lab_report
        handler.request = mock_request
        responses = handler.get()
        return responses, mock_lab_report_class


class TestPathParamValidation:
    def test_missing_lab_report_id_returns_400(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = None
        handler = LabResultAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.get()

        assert mock_request.path_params.get.mock_calls == [call("lab_report_id")]
        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert json.loads(responses[0].content) == {"error": "Lab report ID is required"}


class TestLookup:
    def test_lab_report_not_found_returns_404(
        self, mock_event: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "missing-id"
        handler = LabResultAPI(event=mock_event)

        responses, mock_lab_report_class = _invoke_get(
            handler, mock_request, raises=Exception
        )

        assert mock_request.path_params.get.mock_calls == [call("lab_report_id")]
        assert mock_lab_report_class.objects.with_result_tests_and_values.mock_calls == [
            call(),
            call().prefetch_related("tests__values__codings", "values__codings"),
            call().prefetch_related("tests__values__codings", "values__codings").get(
                id="missing-id", entered_in_error__isnull=True
            ),
        ]
        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.NOT_FOUND
        assert json.loads(responses[0].content) == {
            "error": "Lab report not found",
            "lab_report_id": "missing-id",
        }

    def test_successful_lookup_uses_prefetch_helper(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        handler = LabResultAPI(event=mock_event)

        responses, mock_lab_report_class = _invoke_get(
            handler, mock_request, lab_report=mock_lab_report
        )

        assert mock_request.path_params.get.mock_calls == [call("lab_report_id")]
        # Downstream chained access on the returned report propagates up, so just verify
        # the prefetch helper was constructed, codings were prefetched, and .get() was
        # called with the right id.
        assert mock_lab_report_class.objects.with_result_tests_and_values.mock_calls[:3] == [
            call(),
            call().prefetch_related("tests__values__codings", "values__codings"),
            call().prefetch_related("tests__values__codings", "values__codings").get(
                id="lab-report-uuid-789", entered_in_error__isnull=True
            ),
        ]
        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.OK


class TestReportSerialization:
    def test_full_report_shape(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        handler = LabResultAPI(event=mock_event)

        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["id"] == "lab-report-uuid-789"
        assert data["dbid"] == 999
        assert data["created"] == "2025-01-15T08:00:00"
        assert data["modified"] == "2025-01-15T10:00:00"
        assert data["patient"] == {
            "id": "patient-uuid-111",
            "first_name": "John",
            "last_name": "Doe",
            "birth_date": "1980-05-15",
        }
        assert data["lab_facility"] == {"name": "Quest Diagnostics"}
        assert set(data.keys()) == {
            "id",
            "dbid",
            "created",
            "modified",
            "patient",
            "lab_order",
            "lab_facility",
            "lab_result",
        }

    def test_none_timestamps_serialize_as_null(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_report.created = None
        mock_lab_report.modified = None

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["created"] is None
        assert data["modified"] is None

    def test_missing_patient_serializes_as_null(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_report.patient = None

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["patient"] is None

    def test_patient_without_birth_date(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_report.patient.birth_date = None

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["patient"]["birth_date"] is None


class TestLabOrderBlock:
    def test_no_lab_orders_yields_empty_lab_order_and_null_facility(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_report.laborder_set.select_related.return_value.filter.return_value = []

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_order"] == {}
        assert data["lab_facility"] is None

    def test_lab_order_without_provider_omits_provider(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_order: MagicMock,
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_order.ordering_provider = None

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert "ordering_provider" not in data["lab_order"]
        assert data["lab_order"]["comment"] == "Routine check"

    def test_lab_order_includes_provider_partner_and_dates(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        handler = LabResultAPI(event=mock_event)

        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_order"]["ordering_provider"] == {
            "id": "provider-uuid-456",
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
        }
        assert data["lab_order"]["comment"] == "Routine check"
        assert data["lab_order"]["date_ordered"] == "2025-01-14T09:00:00"
        assert data["lab_facility"] == {"name": "Quest Diagnostics"}
        # Retracted orders must be excluded so an entered-in-error order is never
        # surfaced as the canonical order block.
        mock_lab_report.laborder_set.select_related.assert_called_once_with("ordering_provider")
        mock_lab_report.laborder_set.select_related.return_value.filter.assert_called_once_with(
            entered_in_error__isnull=True
        )

    def test_lab_order_with_no_date_ordered(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_order: MagicMock,
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_order.date_ordered = None

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_order"]["date_ordered"] is None

    def test_empty_lab_partner_yields_null_facility(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_order: MagicMock,
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_order.ontology_lab_partner = ""

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_facility"] is None


class TestReasonConditions:
    def test_no_reasons_yields_empty_list(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        handler = LabResultAPI(event=mock_event)

        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_order"]["reason_conditions"] == []

    def test_reason_conditions_serialize_active_conditions(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_order: MagicMock,
        make_reason_with_conditions: Callable[..., MagicMock],
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        reason = make_reason_with_conditions(
            [
                (
                    "condition-uuid-1",
                    [("E11.9", "Type 2 diabetes mellitus", "ICD-10")],
                    None,
                ),
            ]
        )
        mock_lab_order.reasons.filter.return_value.prefetch_related.return_value = [reason]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        # Retracted order reasons are excluded before prefetching their conditions.
        mock_lab_order.reasons.filter.assert_called_once_with(entered_in_error__isnull=True)
        mock_lab_order.reasons.filter.return_value.prefetch_related.assert_called_once_with(
            "reason_conditions__condition__codings"
        )
        assert data["lab_order"]["reason_conditions"] == [
            {
                "id": "condition-uuid-1",
                "codings": [
                    {
                        "code": "E11.9",
                        "display": "Type 2 diabetes mellitus",
                        "system": "ICD-10",
                    }
                ],
            }
        ]

    def test_entered_in_error_conditions_are_skipped(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_order: MagicMock,
        make_reason_with_conditions: Callable[..., MagicMock],
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        reason = make_reason_with_conditions(
            [
                ("good-condition", [("A00", "Cholera", "ICD-10")], None),
                ("bad-condition", [("B00", "Herpes", "ICD-10")], "user-uuid"),
            ]
        )
        mock_lab_order.reasons.filter.return_value.prefetch_related.return_value = [reason]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert [rc["id"] for rc in data["lab_order"]["reason_conditions"]] == [
            "good-condition"
        ]

    def test_null_condition_is_skipped(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_order: MagicMock,
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        rc = MagicMock()
        rc.condition = None
        reason = MagicMock()
        reason.reason_conditions.all.return_value = [rc]
        mock_lab_order.reasons.filter.return_value.prefetch_related.return_value = [reason]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_order"]["reason_conditions"] == []


class TestLabResultBlock:
    def test_tests_nest_values_under_each_test(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        handler = LabResultAPI(event=mock_event)

        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        tests = data["lab_result"]["tests"]
        assert len(tests) == 1
        assert tests[0]["id"] == "lab-test-uuid-1"
        assert tests[0]["name"] == "Hemoglobin A1c"
        assert tests[0]["ontology_test_code"] == "4548-4"
        assert len(tests[0]["values"]) == 1
        assert tests[0]["values"][0]["value"] == "6.5"

    def test_unassigned_values_only_include_values_without_a_test(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        make_lab_value: Callable[..., MagicMock],
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        attached = make_lab_value(id="attached", test_id="lab-test-uuid-1")
        orphan = make_lab_value(id="orphan", value="9.9", test_id=None)
        mock_lab_report.values.all.return_value = [attached, orphan]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        unassigned = data["lab_result"]["unassigned_values"]
        assert [v["id"] for v in unassigned] == ["orphan"]
        assert unassigned[0]["value"] == "9.9"

    def test_empty_tests_and_no_unassigned_values(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_report.result_tests = []
        mock_lab_report.values.all.return_value = []

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_result"] == {"tests": [], "unassigned_values": []}


class TestLabValueSerialization:
    def test_value_with_coding_includes_name_code_system(
        self, mock_event: MagicMock, mock_request: MagicMock, mock_lab_report: MagicMock
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        handler = LabResultAPI(event=mock_event)

        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)
        value = data["lab_result"]["tests"][0]["values"][0]

        assert value["name"] == "Hemoglobin A1c"
        assert value["code"] == "4548-4"
        assert value["coding_system"] == "http://loinc.org"

    def test_value_without_coding_omits_coding_fields(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_test: MagicMock,
        mock_lab_value_no_coding: MagicMock,
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        mock_lab_test.values.all.return_value = [mock_lab_value_no_coding]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)
        value = data["lab_result"]["tests"][0]["values"][0]

        assert "name" not in value
        assert "code" not in value
        assert "coding_system" not in value

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("-", ""),
            (" - ", ""),
            ("  -  ", ""),
            ("4.0-5.6", "4.0-5.6"),
            ("", ""),
            ("normal", "normal"),
        ],
    )
    def test_reference_range_dash_normalization(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_test: MagicMock,
        make_lab_value: Callable[..., MagicMock],
        raw: str,
        expected: str,
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        lv = make_lab_value(reference_range=raw)
        mock_lab_test.values.all.return_value = [lv]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_result"]["tests"][0]["values"][0]["reference_range"] == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("", False),
            ("H", True),
            ("high", True),
            ("L", True),
        ],
    )
    def test_abnormal_flag_is_boolean(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_test: MagicMock,
        make_lab_value: Callable[..., MagicMock],
        raw: str,
        expected: bool,
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        lv = make_lab_value(abnormal_flag=raw)
        mock_lab_test.values.all.return_value = [lv]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        assert data["lab_result"]["tests"][0]["values"][0]["abnormal_flag"] is expected

    def test_value_with_null_timestamps(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_lab_report: MagicMock,
        mock_lab_test: MagicMock,
        make_lab_value: Callable[..., MagicMock],
    ) -> None:
        mock_request.path_params.get.return_value = "lab-report-uuid-789"
        lv = make_lab_value(created=None, modified=None)
        mock_lab_test.values.all.return_value = [lv]

        handler = LabResultAPI(event=mock_event)
        responses, _ = _invoke_get(handler, mock_request, lab_report=mock_lab_report)
        data = json.loads(responses[0].content)

        v = data["lab_result"]["tests"][0]["values"][0]
        assert v["created"] is None
        assert v["modified"] is None
