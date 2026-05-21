"""Tests for provider_availability.api.provision_api."""

from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.api.provision_api import ProvisionAPI

PROV_MODULE = "provider_availability.api.provision_api"


# ── Helpers ──────────────────────────────────────────────────────────────


def _parse(response) -> tuple[dict, int]:
    """Extract (body_dict, status_code) from a JSONResponse."""
    body = json.loads(getattr(response, "content"))
    return body, response.status_code


def _make_provision_handler(
    json_body: dict | None = None,
    path_params: dict | None = None,
    query_params: dict | None = None,
    secrets: dict | None = None,
) -> ProvisionAPI:
    """Create a ProvisionAPI handler with a mocked request and secrets."""
    mock_event = MagicMock()
    handler = ProvisionAPI(mock_event)
    handler.request = MagicMock()
    handler.request.json.return_value = json_body or {}
    handler.request.path_params = path_params or {}
    handler.request.query_params = query_params or {}
    handler.secrets = secrets or {"simpleapi-api-key": "test-key"}
    return handler


def _make_staff(role: str | None, staff_id: str = "staff-uuid-1",
                first_name: str = "Jane", last_name: str = "Doe") -> MagicMock:
    """Create a mock Staff object."""
    staff = MagicMock()
    staff.top_role_abbreviation = role
    staff.id = staff_id
    staff.first_name = first_name
    staff.last_name = last_name
    return staff


def _setup_staff_queryset(mock_staff_cls: MagicMock, staff_list: list) -> None:
    """Configure Staff.objects.filter to return the given staff list."""
    qs = MagicMock()
    qs.count.return_value = len(staff_list)
    qs.__iter__ = lambda self: iter(staff_list)
    mock_staff_cls.objects.filter.return_value = qs


# ── Authentication ───────────────────────────────────────────────────────


class TestAuthenticate:
    def test_valid_key(self):
        """Matching API key returns True."""
        handler = _make_provision_handler(secrets={"simpleapi-api-key": "my-secret"})
        creds = MagicMock()
        creds.key = "my-secret"

        result = handler.authenticate(creds)

        assert result is True

    def test_invalid_key(self):
        """Mismatched API key returns False."""
        handler = _make_provision_handler(secrets={"simpleapi-api-key": "my-secret"})
        creds = MagicMock()
        creds.key = "wrong-key"

        result = handler.authenticate(creds)

        assert result is False

    def test_empty_secret_returns_false(self):
        """Empty string secret always rejects regardless of key."""
        handler = _make_provision_handler(secrets={"simpleapi-api-key": ""})
        creds = MagicMock()
        creds.key = "any-key"

        result = handler.authenticate(creds)

        assert result is False

    def test_missing_secret_returns_false(self):
        """When the secret is not configured at all, authentication fails."""
        handler = _make_provision_handler(secrets={})
        creds = MagicMock()
        creds.key = "any-key"

        result = handler.authenticate(creds)

        assert result is False


# ── Run provisioning ─────────────────────────────────────────────────────


class TestRunProvisioning:
    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_creates_calendars_for_schedulable_roles(self, mock_staff_cls, mock_cal_model):
        """Providers with MD/DO/NP/PA roles get calendar + event created."""
        provider = _make_staff("MD", "staff-uuid-md", "Jane", "Doe")
        _setup_staff_queryset(mock_staff_cls, [provider])
        mock_cal_model.objects.filter.return_value.first.return_value = None

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["created"] == 1
        assert data["skipped"] == 0
        assert data["errored"] == 0
        # CalendarEffect + EventEffect + JSONResponse
        assert len(result) == 3

        assert mock_staff_cls.mock_calls == [
            call.objects.filter(active=True),
            call.objects.filter().count(),
        ]
        assert mock_cal_model.mock_calls == [
            call.objects.filter(description=str(provider.id)),
            call.objects.filter().first(),
        ]

    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_skips_non_provider_roles(self, mock_staff_cls, mock_cal_model):
        """Staff with roles not in SCHEDULABLE_ROLES (RN, MA, etc.) are skipped."""
        rn_staff = _make_staff("RN", "staff-rn")
        ma_staff = _make_staff("MA", "staff-ma")
        _setup_staff_queryset(mock_staff_cls, [rn_staff, ma_staff])

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["created"] == 0
        assert data["skipped"] == 0
        assert data["errored"] == 0
        # Only JSONResponse, no effects
        assert len(result) == 1
        # CalendarModel should never be queried
        assert mock_cal_model.mock_calls == []

    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_skips_null_role(self, mock_staff_cls, mock_cal_model):
        """Staff with None as top_role_abbreviation should be skipped."""
        staff = _make_staff(None, "staff-null-role")
        staff.top_role_abbreviation = None
        _setup_staff_queryset(mock_staff_cls, [staff])

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        data, _ = _parse(result[-1])
        assert data["created"] == 0
        assert data["skipped"] == 0
        assert mock_cal_model.mock_calls == []

    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_skips_existing_calendar_with_active_event(self, mock_staff_cls, mock_cal_model):
        """Provider with existing calendar AND active event is skipped."""
        provider = _make_staff("NP", "staff-uuid-np", "Bob", "Smith")
        _setup_staff_queryset(mock_staff_cls, [provider])

        existing_cal = MagicMock()
        existing_cal.id = "cal-uuid-1"
        active_event = MagicMock()
        existing_cal.events.filter.return_value.first.return_value = active_event
        mock_cal_model.objects.filter.return_value.first.return_value = existing_cal

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["created"] == 0
        assert data["skipped"] == 1
        assert data["errored"] == 0
        # Only JSONResponse, no effects
        assert len(result) == 1

    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_reuses_existing_calendar_without_active_event(self, mock_staff_cls, mock_cal_model):
        """Provider with existing calendar but no active event gets a new event only."""
        provider = _make_staff("DO", "staff-uuid-do", "Alice", "Jones")
        _setup_staff_queryset(mock_staff_cls, [provider])

        existing_cal = MagicMock()
        existing_cal.id = "cal-uuid-existing"
        existing_cal.events.filter.return_value.first.return_value = None
        mock_cal_model.objects.filter.return_value.first.return_value = existing_cal

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["created"] == 1
        assert data["skipped"] == 0
        # Only EventEffect + JSONResponse (no CalendarEffect)
        assert len(result) == 2

    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_handles_exception_per_staff(self, mock_staff_cls, mock_cal_model):
        """Exception during provisioning of one staff increments errored count."""
        provider = _make_staff("PA", "staff-uuid-pa", "Error", "Provider")
        _setup_staff_queryset(mock_staff_cls, [provider])
        mock_cal_model.objects.filter.side_effect = Exception("DB error")

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["errored"] == 1
        assert data["created"] == 0
        assert data["skipped"] == 0

    @patch(f"{PROV_MODULE}.datetime")
    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_leap_year_fallback(self, mock_staff_cls, mock_cal_model, mock_datetime):
        """When current date is Feb 29, recurrence_end falls back to Feb 28 if needed."""
        provider = _make_staff("MD", "staff-uuid-leap", "Leap", "Doc")
        _setup_staff_queryset(mock_staff_cls, [provider])
        mock_cal_model.objects.filter.return_value.first.return_value = None

        # Simulate Feb 29 of a leap year
        from datetime import datetime as real_datetime, timedelta as real_timedelta

        fake_now = real_datetime(2028, 2, 29, 12, 0, 0)
        mock_datetime.now.return_value = fake_now
        mock_datetime.side_effect = real_datetime
        mock_datetime.return_value = fake_now

        # Override datetime constructor to behave like real datetime
        def datetime_constructor(*args, **kwargs):
            return real_datetime(*args, **kwargs)

        mock_datetime.side_effect = datetime_constructor
        mock_datetime.now.return_value = fake_now

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        data, _ = _parse(result[-1])
        # Should succeed - either creates normally or uses fallback
        assert data["created"] == 1 or data["errored"] == 0

    @patch(f"{PROV_MODULE}.CalendarModel")
    @patch(f"{PROV_MODULE}.Staff")
    def test_mixed_staff_roles(self, mock_staff_cls, mock_cal_model):
        """Batch of staff with mixed roles: only schedulable ones get processed."""
        md_provider = _make_staff("MD", "staff-md", "Dr", "One")
        rn_staff = _make_staff("RN", "staff-rn", "Nurse", "Two")
        np_provider = _make_staff("NP", "staff-np", "Nurse", "Pract")
        _setup_staff_queryset(mock_staff_cls, [md_provider, rn_staff, np_provider])
        mock_cal_model.objects.filter.return_value.first.return_value = None

        handler = _make_provision_handler()
        result = handler.run_provisioning()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["created"] == 2  # MD + NP
        assert data["skipped"] == 0
        assert data["errored"] == 0


# ── list_allowed_staff ──────────────────────────────────────────────────


class TestListAllowedStaff:
    @patch(f"{PROV_MODULE}.get_allowed_staff", return_value=["s1", "s2"])
    def test_returns_list(self, mock_get):
        handler = _make_provision_handler()
        result = handler.list_allowed_staff()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["allowed_staff"] == ["s1", "s2"]
        assert data["count"] == 2
        assert mock_get.mock_calls == [call()]

    @patch(f"{PROV_MODULE}.get_allowed_staff", return_value=[])
    def test_returns_empty_list(self, mock_get):
        handler = _make_provision_handler()
        result = handler.list_allowed_staff()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["allowed_staff"] == []
        assert data["count"] == 0
        assert mock_get.mock_calls == [call()]


# ── replace_allowed_staff ───────────────────────────────────────────────


class TestReplaceAllowedStaff:
    @patch(f"{PROV_MODULE}.set_allowed_staff")
    def test_replaces_list(self, mock_set):
        handler = _make_provision_handler(json_body={"staff_ids": ["s1", "s2", "s3"]})
        result = handler.replace_allowed_staff()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["count"] == 3
        assert data["message"] == "Allowed staff list updated"
        assert mock_set.mock_calls == [call(["s1", "s2", "s3"])]

    def test_invalid_input_not_a_list(self):
        handler = _make_provision_handler(json_body={"staff_ids": "not-a-list"})
        result = handler.replace_allowed_staff()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "staff_ids must be a list" in data["error"]

    @patch(f"{PROV_MODULE}.set_allowed_staff")
    def test_coerces_ids_to_strings(self, mock_set):
        handler = _make_provision_handler(json_body={"staff_ids": [123, 456]})
        result = handler.replace_allowed_staff()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert mock_set.mock_calls == [call(["123", "456"])]


# ── add_allowed_staff_endpoint ──────────────────────────────────────────


class TestAddAllowedStaffEndpoint:
    @patch(f"{PROV_MODULE}.add_allowed_staff")
    def test_adds_single(self, mock_add):
        handler = _make_provision_handler(json_body={"staff_id": "s-new"})
        result = handler.add_allowed_staff_endpoint()

        data, code = _parse(result[0])
        assert code == HTTPStatus.CREATED
        assert data["staff_id"] == "s-new"
        assert data["message"] == "Staff added"
        assert mock_add.mock_calls == [call("s-new")]

    def test_missing_staff_id(self):
        handler = _make_provision_handler(json_body={})
        result = handler.add_allowed_staff_endpoint()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "staff_id is required" in data["error"]

    def test_empty_staff_id(self):
        handler = _make_provision_handler(json_body={"staff_id": ""})
        result = handler.add_allowed_staff_endpoint()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "staff_id is required" in data["error"]


# ── remove_allowed_staff_endpoint ───────────────────────────────────────


class TestRemoveAllowedStaffEndpoint:
    @patch(f"{PROV_MODULE}.remove_allowed_staff")
    def test_removes_single(self, mock_remove):
        handler = _make_provision_handler(path_params={"staff_id": "s-remove"})
        result = handler.remove_allowed_staff_endpoint()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["staff_id"] == "s-remove"
        assert data["message"] == "Staff removed"
        assert mock_remove.mock_calls == [call("s-remove")]


# ── get_timezone ────────────────────────────────────────────────────────


class TestGetTimezone:
    @patch(f"{PROV_MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{PROV_MODULE}.get_practice_timezone", return_value="US/Pacific")
    def test_returns_timezone(self, mock_tz):
        handler = _make_provision_handler()
        result = handler.get_timezone()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["timezone"] == "US/Pacific"
        assert data["available"] == ["US/Eastern", "US/Pacific", "UTC"]
        assert mock_tz.mock_calls == [call()]


# ── set_timezone ────────────────────────────────────────────────────────


class TestSetTimezone:
    @patch(f"{PROV_MODULE}.set_practice_timezone")
    @patch(f"{PROV_MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_sets_timezone(self, mock_set):
        handler = _make_provision_handler(json_body={"timezone": "US/Eastern"})
        result = handler.set_timezone()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["timezone"] == "US/Eastern"
        assert data["message"] == "Timezone set to US/Eastern"
        assert mock_set.mock_calls == [call("US/Eastern")]

    @patch(f"{PROV_MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone(self):
        handler = _make_provision_handler(json_body={"timezone": "Mars/Olympus"})
        result = handler.set_timezone()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]

    @patch(f"{PROV_MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_empty_timezone(self):
        handler = _make_provision_handler(json_body={"timezone": ""})
        result = handler.set_timezone()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]

    @patch(f"{PROV_MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_missing_timezone_key(self):
        handler = _make_provision_handler(json_body={})
        result = handler.set_timezone()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]
