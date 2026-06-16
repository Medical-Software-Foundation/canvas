"""Tests for RxApi."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from rx_status.applications.rx_api import (
    CACHE_RULES_KEY,
    RxApi,
    VALID_DURATION_UNITS,
    VALID_STATUSES,
)


def _make_api(request=None):
    api = RxApi.__new__(RxApi)
    api.request = request or MagicMock()
    return api


def _response_body(responses):
    """Extract the first JSONResponse body for assertions."""
    return responses[0].content if hasattr(responses[0], "content") else responses[0]


class TestValidation:
    def test_status_must_be_valid(self) -> None:
        api = _make_api()

        result = api._validate_rule_body(
            {"status": "bogus", "task_title": "t"}
        )

        assert result == "Invalid or missing 'status'"

    def test_task_title_required(self) -> None:
        api = _make_api()

        result = api._validate_rule_body({"status": "pending"})

        assert result == "'task_title' is required"

    def test_task_title_length_capped(self) -> None:
        api = _make_api()
        long_title = "x" * 300

        result = api._validate_rule_body(
            {"status": "pending", "task_title": long_title}
        )

        assert "255" in result

    def test_duration_value_must_be_int(self) -> None:
        api = _make_api()

        result = api._validate_rule_body(
            {"status": "pending", "task_title": "t", "duration_value": "abc"}
        )

        assert result == "'duration_value' must be an integer"

    def test_duration_value_non_negative(self) -> None:
        api = _make_api()

        result = api._validate_rule_body(
            {"status": "pending", "task_title": "t", "duration_value": -1}
        )

        assert result == "'duration_value' must be zero or greater"

    def test_duration_unit_enum(self) -> None:
        api = _make_api()

        result = api._validate_rule_body(
            {"status": "pending", "task_title": "t", "duration_unit": "w"}
        )

        assert result == "'duration_unit' must be 'h' or 'd'"

    def test_valid_body_returns_none(self) -> None:
        api = _make_api()

        result = api._validate_rule_body(
            {
                "status": "pending",
                "task_title": "Follow up",
                "duration_value": 24,
                "duration_unit": "h",
            }
        )

        assert result is None


class TestTypeFilter:
    @patch("rx_status.applications.rx_api.Prescription")
    def test_new_rx_filter(self, _mock: MagicMock) -> None:
        api = _make_api()
        qs = MagicMock()
        qs.filter.return_value = "filtered"

        result = api._apply_type_filter(qs, "New Rx")

        qs.filter.assert_called_with(is_refill=False, is_adjustment=False)
        assert result == "filtered"

    def test_refill_filter_excludes_responses(self) -> None:
        api = _make_api()
        qs = MagicMock()

        api._apply_type_filter(qs, "Refill")

        qs.filter.assert_called_with(is_refill=True, response_type__isnull=True)

    def test_approve_refill(self) -> None:
        api = _make_api()
        qs = MagicMock()

        api._apply_type_filter(qs, "Approve Refill")

        qs.filter.assert_called_with(is_refill=True, response_type__in=["A", "C"])

    def test_deny_refill(self) -> None:
        api = _make_api()
        qs = MagicMock()

        api._apply_type_filter(qs, "Deny Refill")

        qs.filter.assert_called_with(is_refill=True, response_type__in=["D", "N"])

    def test_adjustment(self) -> None:
        api = _make_api()
        qs = MagicMock()

        api._apply_type_filter(qs, "Adjustment")

        qs.filter.assert_called_with(is_adjustment=True)

    def test_unknown_returns_untouched(self) -> None:
        api = _make_api()
        qs = MagicMock()

        result = api._apply_type_filter(qs, "Unknown")

        qs.filter.assert_not_called()
        assert result is qs

    def test_empty_returns_untouched(self) -> None:
        api = _make_api()
        qs = MagicMock()

        result = api._apply_type_filter(qs, None)

        assert result is qs


class TestDateRangeFilter:
    def test_same_day_date_range_uses_lt_plus_one(self) -> None:
        api = _make_api()
        qs = MagicMock()
        qs.filter.return_value = qs

        api._apply_filters(qs, {"date_to": "2026-04-07"})

        # Last filter call should be written_date__lt with the next day
        from datetime import date
        found = False
        for call in qs.filter.call_args_list:
            kwargs = call.kwargs
            if "written_date__lt" in kwargs:
                assert kwargs["written_date__lt"] == date(2026, 4, 8)
                found = True
        assert found, "Expected written_date__lt filter to be applied"

    def test_malformed_date_is_skipped(self) -> None:
        api = _make_api()
        qs = MagicMock()
        qs.filter.return_value = qs

        result = api._apply_filters(qs, {"date_to": "not-a-date"})

        # No __lt filter applied for malformed date
        for call in qs.filter.call_args_list:
            assert "written_date__lt" not in call.kwargs
        assert result is qs

    def test_date_from_uses_gte(self) -> None:
        api = _make_api()
        qs = MagicMock()
        qs.filter.return_value = qs

        api._apply_filters(qs, {"date_from": "2026-04-01"})

        qs.filter.assert_any_call(written_date__gte="2026-04-01")


class TestSerializePrescription:
    def test_basic_fields(self, mock_prescription: MagicMock) -> None:
        api = _make_api()

        result = api._serialize_prescription(mock_prescription)

        assert result["patient_name"] == "Solomon Test"
        assert result["patient_id"] == "patient-xyz-999"
        assert result["prescriber"] == "Wayne Best"
        assert result["med_name"] == "Lisinopril 10 mg"
        assert result["pharmacy"] == "Test Pharmacy"
        assert result["status"] == "pending"
        assert result["rx_type"] == "New Rx"
        assert result["note_dbid"] == 42

    def test_refill_type(self, mock_prescription: MagicMock) -> None:
        mock_prescription.is_refill = True
        mock_prescription.response_type = None
        api = _make_api()

        result = api._serialize_prescription(mock_prescription)

        assert result["rx_type"] == "Refill"

    def test_approve_refill_type(self, mock_prescription: MagicMock) -> None:
        mock_prescription.is_refill = True
        mock_prescription.response_type = "A"
        api = _make_api()

        result = api._serialize_prescription(mock_prescription)

        assert result["rx_type"] == "Approve Refill"

    def test_deny_refill_type(self, mock_prescription: MagicMock) -> None:
        mock_prescription.is_refill = True
        mock_prescription.response_type = "N"
        api = _make_api()

        result = api._serialize_prescription(mock_prescription)

        assert result["rx_type"] == "Deny Refill"

    def test_adjustment_type(self, mock_prescription: MagicMock) -> None:
        mock_prescription.is_refill = False
        mock_prescription.is_adjustment = True
        api = _make_api()

        result = api._serialize_prescription(mock_prescription)

        assert result["rx_type"] == "Adjustment"

    def test_no_patient(self, mock_prescription: MagicMock) -> None:
        mock_prescription.patient = None
        api = _make_api()

        result = api._serialize_prescription(mock_prescription)

        assert result["patient_name"] == ""
        assert result["patient_id"] == ""

    def test_no_note(self, mock_prescription: MagicMock) -> None:
        mock_prescription.note = None
        api = _make_api()

        result = api._serialize_prescription(mock_prescription)

        assert result["note_dbid"] is None


class TestCreateRule:
    @patch("rx_status.applications.rx_api.get_cache")
    def test_invalid_json_returns_400(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_request.body = "not json"
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        result = api.create_rule()

        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_status.applications.rx_api.get_cache")
    def test_non_object_body_rejected(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_request.body = json.dumps(["array", "not", "object"])
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        result = api.create_rule()

        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_status.applications.rx_api.get_cache")
    def test_invalid_status_returns_400(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_request.body = json.dumps({"status": "bogus", "task_title": "t"})
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        result = api.create_rule()

        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_status.applications.rx_api.get_cache")
    def test_happy_path_appends_rule(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_request.body = json.dumps(
            {
                "status": "pending",
                "task_title": "Follow up",
                "duration_value": 24,
                "duration_unit": "h",
            }
        )
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        result = api.create_rule()

        assert result[0].status_code == HTTPStatus.CREATED
        rules = mock_cache._store[CACHE_RULES_KEY]
        assert len(rules) == 1
        assert rules[0]["status"] == "pending"
        assert rules[0]["duration_value"] == 24

    @patch("rx_status.applications.rx_api.get_cache")
    def test_rule_creation_is_immutable(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        original = [{"id": "r0", "status": "open", "task_title": "x"}]
        mock_cache._store[CACHE_RULES_KEY] = original
        mock_request.body = json.dumps(
            {"status": "pending", "task_title": "Follow up"}
        )
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        api.create_rule()

        assert original == [{"id": "r0", "status": "open", "task_title": "x"}]
        assert len(mock_cache._store[CACHE_RULES_KEY]) == 2


class TestDeleteRule:
    @patch("rx_status.applications.rx_api.get_cache")
    def test_removes_matching_rule(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_cache._store[CACHE_RULES_KEY] = [
            {"id": "r1"},
            {"id": "r2"},
        ]
        mock_request.path_params = {"rule_id": "r1"}
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        result = api.delete_rule()

        assert result[0].status_code == HTTPStatus.OK
        remaining = mock_cache._store[CACHE_RULES_KEY]
        assert len(remaining) == 1
        assert remaining[0]["id"] == "r2"


class TestListRules:
    @patch("rx_status.applications.rx_api.get_cache")
    def test_returns_empty_when_cache_empty(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        result = api.list_rules()

        assert result[0].status_code == HTTPStatus.OK

    @patch("rx_status.applications.rx_api.get_cache")
    def test_parses_json_string_form(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_cache._store[CACHE_RULES_KEY] = json.dumps([{"id": "x"}])
        mock_get_cache.return_value = mock_cache
        api = _make_api(mock_request)

        result = api.list_rules()

        assert result[0].status_code == HTTPStatus.OK


class TestGetCurrentUser:
    @patch("rx_status.applications.rx_api.Staff")
    def test_no_header_returns_empty_user(
        self, mock_staff: MagicMock, mock_request: MagicMock
    ) -> None:
        mock_request.headers = {}
        api = _make_api(mock_request)

        result = api.get_current_user()

        assert result[0].status_code == HTTPStatus.OK
        mock_staff.objects.get.assert_not_called()

    @patch("rx_status.applications.rx_api.Staff")
    @patch("rx_status.applications.rx_api.Prescription")
    def test_looks_up_staff_when_header_present(
        self,
        mock_prescription: MagicMock,
        mock_staff: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        mock_request.headers = {"canvas-logged-in-user-id": "staff-1"}
        staff = MagicMock()
        staff.id = "staff-1"
        staff.first_name = "Wayne"
        staff.last_name = "Best"
        mock_staff.objects.get.return_value = staff
        mock_prescription.objects.filter.return_value.exists.return_value = True

        api = _make_api(mock_request)
        result = api.get_current_user()

        assert result[0].status_code == HTTPStatus.OK
        mock_staff.objects.get.assert_called_once_with(id="staff-1")


class TestConstants:
    def test_valid_statuses_matches_event_map(self) -> None:
        from rx_status.protocols.rx_notifications import EVENT_STATUS_MAP

        assert set(EVENT_STATUS_MAP.values()) == VALID_STATUSES

    def test_valid_duration_units(self) -> None:
        assert VALID_DURATION_UNITS == {"h", "d"}
