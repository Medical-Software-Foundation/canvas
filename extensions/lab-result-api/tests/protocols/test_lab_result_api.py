from http import HTTPStatus
from unittest.mock import MagicMock, patch, call
import json
import pytest

from lab_result_api.protocols.lab_result_api import LabResultAPI


class TestLabResultAPI:
    """Test suite for LabResultAPI SimpleAPI handler."""

    def test_get_lab_report_success(self, mock_event, mock_request, mock_lab_report):
        """Test successful GET request returns lab report with all data."""
        mock_request.path_params.get.return_value = "lab-report-uuid-789"

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.objects.get.return_value = mock_lab_report

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="lab-report-uuid-789")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            # Verify response
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK

            # Verify response data
            response_data = json.loads(response.content)
            assert response_data["id"] == "lab-report-uuid-789"
            assert response_data["dbid"] == 999
            assert response_data["created"] == "2025-01-15T08:00:00"
            assert response_data["modified"] == "2025-01-15T10:00:00"

            # Verify patient data
            assert response_data["patient"]["id"] == "patient-uuid-111"
            assert response_data["patient"]["first_name"] == "John"
            assert response_data["patient"]["last_name"] == "Doe"
            assert response_data["patient"]["birth_date"] == "1980-05-15"

            # Verify ordering provider data
            assert response_data["ordering_provider"]["id"] == "provider-uuid-456"
            assert response_data["ordering_provider"]["first_name"] == "Jane"
            assert response_data["ordering_provider"]["last_name"] == "Smith"
            assert response_data["ordering_provider"]["npi"] == "1234567890"

            # Verify lab facility data
            assert response_data["lab_facility"]["name"] == "Quest Diagnostics"

            # Verify originator data
            assert response_data["originator"]["id"] == "staff-uuid-222"
            assert response_data["originator"]["first_name"] == "Alice"
            assert response_data["originator"]["last_name"] == "Johnson"
            assert response_data["originator"]["is_staff"] is True

            # Verify lab tests (2 test values)
            assert len(response_data["lab_tests"]) == 2

            # First test with coding
            test1 = response_data["lab_tests"][0]
            assert test1["id"] == "lab-value-uuid-1"
            assert test1["test_name"] == "Hemoglobin A1c"
            assert test1["test_code"] == "4548-4"
            assert test1["coding_system"] == "http://loinc.org"
            assert test1["value"] == "6.5"
            assert test1["units"] == "%"
            assert test1["reference_range"] == "4.0-5.6"
            assert test1["abnormal_flag"] == "high"
            assert test1["observation_status"] == "final"
            assert test1["low_threshold"] == "4.0"
            assert test1["high_threshold"] == "5.6"
            assert test1["comment"] == "Elevated A1c"

            # Second test without coding
            test2 = response_data["lab_tests"][1]
            assert test2["id"] == "lab-value-uuid-2"
            assert "test_name" not in test2
            assert "test_code" not in test2
            assert "coding_system" not in test2
            assert test2["value"] == "110"
            assert test2["units"] == "mg/dL"

    def test_get_lab_report_not_found(self, mock_event, mock_request):
        """Test GET request with non-existent lab report ID returns 404."""
        mock_request.path_params.get.return_value = "non-existent-uuid"

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.DoesNotExist = Exception
            mock_lab_report_class.objects.get.side_effect = mock_lab_report_class.DoesNotExist()

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="non-existent-uuid")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            # Verify response
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.NOT_FOUND

            response_data = json.loads(response.content)
            assert response_data["error"] == "Lab report not found"
            assert response_data["lab_report_id"] == "non-existent-uuid"

    def test_get_lab_report_missing_id(self, mock_event, mock_request):
        """Test GET request without lab_report_id returns 400."""
        mock_request.path_params.get.return_value = None

        handler = LabResultAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.get()

        # Verify mock calls
        assert mock_request.path_params.get.call_args == call("lab_report_id")

        # Verify response
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

        response_data = json.loads(response.content)
        assert response_data["error"] == "Lab report ID is required"

    def test_get_lab_report_no_orders(self, mock_event, mock_request, mock_lab_report):
        """Test lab report with no associated lab orders."""
        mock_request.path_params.get.return_value = "lab-report-uuid-789"

        # Mock empty lab orders
        mock_laborder_set = MagicMock()
        mock_laborder_set.all.return_value = []
        mock_lab_report.laborder_set = mock_laborder_set

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.objects.get.return_value = mock_lab_report

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="lab-report-uuid-789")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            # Verify response
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK

            response_data = json.loads(response.content)
            assert response_data["ordering_provider"] is None
            assert response_data["lab_facility"] is None

    def test_get_lab_report_no_ordering_provider(self, mock_event, mock_request, mock_lab_report):
        """Test lab report with lab order but no ordering provider."""
        mock_request.path_params.get.return_value = "lab-report-uuid-789"

        # Mock lab order without ordering provider
        mock_lab_order = MagicMock()
        mock_lab_order.ordering_provider = None
        mock_lab_order.ontology_lab_partner = "Quest Diagnostics"

        mock_laborder_set = MagicMock()
        mock_laborder_set.all.return_value = [mock_lab_order]
        mock_lab_report.laborder_set = mock_laborder_set

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.objects.get.return_value = mock_lab_report

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="lab-report-uuid-789")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            # Verify response
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK

            response_data = json.loads(response.content)
            assert response_data["ordering_provider"] is None
            assert response_data["lab_facility"]["name"] == "Quest Diagnostics"

    def test_get_lab_report_with_none_values(self, mock_event, mock_request, mock_lab_report):
        """Test lab report serialization handles None values correctly."""
        mock_request.path_params.get.return_value = "lab-report-uuid-789"

        # Set optional fields to None
        mock_lab_report.created = None
        mock_lab_report.modified = None
        mock_lab_report.patient = None
        mock_lab_report.originator = None

        # Empty lab values
        mock_values = MagicMock()
        mock_values.all.return_value = []
        mock_lab_report.values = mock_values

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.objects.get.return_value = mock_lab_report

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="lab-report-uuid-789")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            # Verify response
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK

            response_data = json.loads(response.content)
            assert response_data["created"] is None
            assert response_data["modified"] is None
            assert response_data["patient"] is None
            assert response_data["originator"] is None
            assert response_data["lab_tests"] == []

    def test_get_lab_report_empty_lab_tests(self, mock_event, mock_request, mock_lab_report):
        """Test lab report with no lab test values."""
        mock_request.path_params.get.return_value = "lab-report-uuid-789"

        # Mock empty lab values
        mock_values = MagicMock()
        mock_values.all.return_value = []
        mock_lab_report.values = mock_values

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.objects.get.return_value = mock_lab_report

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="lab-report-uuid-789")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            # Verify response
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK

            response_data = json.loads(response.content)
            assert response_data["lab_tests"] == []

    def test_get_lab_report_provider_without_npi(self, mock_event, mock_request, mock_lab_report):
        """Test lab report with ordering provider that has no NPI attribute."""
        mock_request.path_params.get.return_value = "lab-report-uuid-789"

        # Mock lab order with provider without NPI
        mock_lab_order = MagicMock()
        mock_lab_order.ordering_provider.id = "provider-uuid-456"
        mock_lab_order.ordering_provider.first_name = "Jane"
        mock_lab_order.ordering_provider.last_name = "Smith"
        # Delete npi attribute to simulate provider without NPI
        del mock_lab_order.ordering_provider.npi
        mock_lab_order.ontology_lab_partner = "Quest Diagnostics"

        mock_laborder_set = MagicMock()
        mock_laborder_set.all.return_value = [mock_lab_order]
        mock_lab_report.laborder_set = mock_laborder_set

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.objects.get.return_value = mock_lab_report

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="lab-report-uuid-789")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            # Verify response
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK

            response_data = json.loads(response.content)
            assert response_data["ordering_provider"]["id"] == "provider-uuid-456"
            assert response_data["ordering_provider"]["first_name"] == "Jane"
            assert response_data["ordering_provider"]["last_name"] == "Smith"
            assert response_data["ordering_provider"]["npi"] is None

    def test_serialize_lab_value_all_fields(self, mock_event, mock_request, mock_lab_report, mock_lab_value_with_coding):
        """Test that all lab value fields are correctly serialized."""
        mock_request.path_params.get.return_value = "lab-report-uuid-789"

        # Mock with only one lab value to test all fields
        mock_values = MagicMock()
        mock_values.all.return_value = [mock_lab_value_with_coding]
        mock_lab_report.values = mock_values

        with patch("lab_result_api.protocols.lab_result_api.LabReport") as mock_lab_report_class:
            mock_lab_report_class.objects.get.return_value = mock_lab_report

            handler = LabResultAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.get()

            # Verify mock calls
            assert mock_lab_report_class.objects.get.call_args == call(id="lab-report-uuid-789")
            assert mock_request.path_params.get.call_args == call("lab_report_id")

            response = responses[0]
            response_data = json.loads(response.content)

            # Verify all lab test fields are present
            test = response_data["lab_tests"][0]
            assert test["id"] == "lab-value-uuid-1"
            assert test["value"] == "6.5"
            assert test["units"] == "%"
            assert test["reference_range"] == "4.0-5.6"
            assert test["abnormal_flag"] == "high"
            assert test["observation_status"] == "final"
            assert test["low_threshold"] == "4.0"
            assert test["high_threshold"] == "5.6"
            assert test["comment"] == "Elevated A1c"
            assert test["created"] == "2025-01-15T10:00:00"
            assert test["modified"] == "2025-01-15T10:00:00"
            assert test["test_name"] == "Hemoglobin A1c"
            assert test["test_code"] == "4548-4"
            assert test["coding_system"] == "http://loinc.org"
