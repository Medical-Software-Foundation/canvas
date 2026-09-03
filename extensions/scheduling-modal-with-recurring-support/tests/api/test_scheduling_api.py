from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest
from requests import RequestException

from scheduling_modal_with_recurring_support.api.scheduling_api import (
    PatientStateResult,
    _backend_error_response,
    _fhir_to_local_hhmm,
    _parse_request_duration_minutes,
    _resolve_default_duration_minutes,
    _resolve_patient_state,
    _resolve_recurrence_rule,
)


# ---- Helper: build SchedulingAPI instance ----

def _make_api(
    query_params: dict[str, str] | None = None,
    json_body: dict | None = None,
    secrets: dict[str, str] | None = None,
) -> MagicMock:
    from scheduling_modal_with_recurring_support.api.scheduling_api import SchedulingAPI

    api = MagicMock(spec=SchedulingAPI)
    req = MagicMock()
    req.query_params = query_params or {}
    req.json.return_value = json_body or {}
    api.request = req
    api.secrets = secrets or {}

    api.providers = lambda: SchedulingAPI.providers(api)
    api.patients = lambda: SchedulingAPI.patients(api)
    api.note_types = lambda: SchedulingAPI.note_types(api)
    api.availability = lambda: SchedulingAPI.availability(api)
    api.candidate_times = lambda: SchedulingAPI.candidate_times(api)
    api.candidate_first_dates = lambda: SchedulingAPI.candidate_first_dates(api)
    api.free_slots = lambda: SchedulingAPI.free_slots(api)
    api.availability_window = lambda: SchedulingAPI.availability_window(api)
    api.check_slots = lambda: SchedulingAPI.check_slots(api)
    api.book = lambda: SchedulingAPI.book(api)
    api.verify_booking = lambda: SchedulingAPI.verify_booking(api)
    api.scheduling_ui = lambda: SchedulingAPI.scheduling_ui(api)
    api.available_times = lambda: SchedulingAPI.available_times(api)
    api.canvas_plugin_ui_css = lambda: SchedulingAPI.canvas_plugin_ui_css(api)
    api.canvas_plugin_ui_js = lambda: SchedulingAPI.canvas_plugin_ui_js(api)

    return api


# ---- _fhir_to_local_hhmm ----

from datetime import timezone as _tz


_EDT = _tz(timedelta(hours=-4))
_UTC = _tz.utc


def test_fhir_to_local_naive_iso_returns_as_is() -> None:
    assert _fhir_to_local_hhmm("2026-05-01T10:00:00", _EDT) == "10:00"


def test_fhir_to_local_utc_z_converts_to_edt() -> None:
    assert _fhir_to_local_hhmm("2026-05-01T14:00:00Z", _EDT) == "10:00"


def test_fhir_to_local_utc_offset_converts_to_edt() -> None:
    assert _fhir_to_local_hhmm("2026-05-01T14:30:00+00:00", _EDT) == "10:30"


def test_fhir_to_local_same_tz_no_change() -> None:
    assert _fhir_to_local_hhmm("2026-05-01T10:00:00-04:00", _EDT) == "10:00"


def test_fhir_to_local_different_offset() -> None:
    assert _fhir_to_local_hhmm("2026-05-01T10:00:00-04:00", _UTC) == "14:00"


def test_fhir_to_local_plain_time() -> None:
    assert _fhir_to_local_hhmm("10:00", _EDT) == "10:00"


def test_fhir_to_local_plain_time_with_seconds() -> None:
    assert _fhir_to_local_hhmm("14:30:00", _EDT) == "14:30"


# ---- _resolve_default_duration_minutes and _parse_request_duration_minutes ----


class TestResolveDefaultDurationMinutes:
    def test_returns_60_when_secret_missing(self) -> None:
        assert _resolve_default_duration_minutes({}) == 60

    def test_returns_60_when_secret_empty_string(self) -> None:
        assert _resolve_default_duration_minutes({"DEFAULT_APPOINTMENT_DURATION_MINUTES": ""}) == 60

    def test_returns_60_when_secret_whitespace(self) -> None:
        assert _resolve_default_duration_minutes({"DEFAULT_APPOINTMENT_DURATION_MINUTES": "   "}) == 60

    def test_returns_60_when_secret_non_integer(self) -> None:
        assert _resolve_default_duration_minutes({"DEFAULT_APPOINTMENT_DURATION_MINUTES": "abc"}) == 60

    def test_returns_60_when_secret_below_min(self) -> None:
        assert _resolve_default_duration_minutes({"DEFAULT_APPOINTMENT_DURATION_MINUTES": "4"}) == 60

    def test_returns_60_when_secret_above_max(self) -> None:
        assert _resolve_default_duration_minutes({"DEFAULT_APPOINTMENT_DURATION_MINUTES": "241"}) == 60

    def test_returns_30_when_secret_is_30(self) -> None:
        assert _resolve_default_duration_minutes({"DEFAULT_APPOINTMENT_DURATION_MINUTES": "30"}) == 30

    def test_returns_240_when_secret_is_max(self) -> None:
        assert _resolve_default_duration_minutes({"DEFAULT_APPOINTMENT_DURATION_MINUTES": "240"}) == 240


class TestParseRequestDurationMinutes:
    def test_returns_default_when_value_none(self) -> None:
        assert _parse_request_duration_minutes(None, 45) == 45

    def test_returns_default_when_value_empty_string(self) -> None:
        assert _parse_request_duration_minutes("", 45) == 45

    def test_returns_default_when_value_non_integer(self) -> None:
        assert _parse_request_duration_minutes("abc", 45) == 45

    def test_returns_default_when_value_below_min(self) -> None:
        assert _parse_request_duration_minutes("4", 45) == 45

    def test_returns_default_when_value_above_max(self) -> None:
        assert _parse_request_duration_minutes("241", 45) == 45

    def test_returns_value_when_in_range(self) -> None:
        assert _parse_request_duration_minutes("30", 60) == 30


# ---- _resolve_patient_state ----

def test_resolve_patient_state_with_home_address() -> None:
    mock_patient = MagicMock()
    home = MagicMock()
    home.use = "home"
    home.state_code = "CA"
    mock_patient.addresses.all.return_value = [home]

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
    ) as mock_cls:
        mock_cls.objects.filter.return_value.first.return_value = mock_patient
        result = _resolve_patient_state("patient-123")

    assert result.state == "CA"
    assert result.error == ""


def test_resolve_patient_state_no_patient() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
    ) as mock_cls:
        mock_cls.objects.filter.return_value.first.return_value = None
        result = _resolve_patient_state("missing")

    assert result.state == ""
    assert result.not_found is True
    assert result.error != ""


def test_resolve_patient_state_empty_id() -> None:
    result = _resolve_patient_state("")
    assert result.state == ""
    assert result.not_found is False
    assert result.error != ""


def test_resolve_patient_state_no_address_with_state() -> None:
    mock_patient = MagicMock()
    mock_patient.addresses.all.return_value = []

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
    ) as mock_cls:
        mock_cls.objects.filter.return_value.first.return_value = mock_patient
        result = _resolve_patient_state("p3")

    assert result.state == ""
    assert "no state on file" in result.error


def test_resolve_patient_state_falls_back_to_first_address() -> None:
    mock_patient = MagicMock()
    mock_fallback = MagicMock()
    mock_fallback.use = "billing"
    mock_fallback.state_code = "TX"
    mock_patient.addresses.all.return_value = [mock_fallback]

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
    ) as mock_cls:
        mock_cls.objects.filter.return_value.first.return_value = mock_patient
        result = _resolve_patient_state("p2")

    assert result.state == "TX"
    assert result.error == ""


def test_resolve_patient_state_prefers_home_over_non_home() -> None:
    """A home use address with a state wins over a non home address even when the
    non home one is first in the list."""
    mock_patient = MagicMock()
    billing = MagicMock()
    billing.use = "billing"
    billing.state_code = "TX"
    home = MagicMock()
    home.use = "home"
    home.state_code = "CA"
    mock_patient.addresses.all.return_value = [billing, home]

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
    ) as mock_cls:
        mock_cls.objects.filter.return_value.first.return_value = mock_patient
        result = _resolve_patient_state("p4")

    assert result.state == "CA"


# ---- providers endpoint ----

def test_providers_endpoint_success() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import ProviderSummary

    summaries = [
        ProviderSummary(
            id="s1",
            full_name="Dr. X",
            npi_number="111",
            pct_filled=25.0,
            filled_count=2,
            free_count=6,
            total_count=8,
            has_capacity=True,
            appointments_last_30_days=5,
            upcoming_7_days=2,
            tier="recommended",
        ),
    ]

    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
            return_value=summaries,
        ) as mock_filter,
    ):
        mock_token.return_value = MagicMock(access_token="tok")
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(
            query_params={"patient_id": "p1"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    mock_filter.assert_called_once_with(
        "CA",
        fhir_base_url="https://fumage-test.canvasmedical.com",
        access_token="tok",
        location_id="loc-1",
    )
    assert len(results) == 1


def test_providers_endpoint_state_missing_returns_unfiltered() -> None:
    """When patient has no state on file, return unfiltered providers with state_missing flag."""
    from scheduling_modal_with_recurring_support.services.provider_filter import ProviderSummary

    summaries = [
        ProviderSummary(
            id="s1",
            full_name="Dr. X",
            npi_number="111",
            pct_filled=25.0,
            filled_count=2,
            free_count=6,
            total_count=8,
            has_capacity=True,
            appointments_last_30_days=5,
            upcoming_7_days=2,
            tier="recommended",
        ),
    ]

    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="", error="Patient has no state on file. Pick a state to apply or continue without state filter."),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
            return_value=summaries,
        ) as mock_filter,
    ):
        mock_token.return_value = MagicMock(access_token="tok")
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(
            query_params={"patient_id": "p2"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    # Filter is called with empty state, which licensed_providers_for_state
    # interprets as no license filter.
    mock_filter.assert_called_once_with(
        "",
        fhir_base_url="https://fumage-test.canvasmedical.com",
        access_token="tok",
        location_id="loc-1",
    )
    assert len(results) == 1
    resp = results[0]
    assert resp.status_code == HTTPStatus.OK
    body = json.loads(resp.content)
    assert body["state_missing"] is True
    assert "no state on file" in body["message"]
    assert body["state"] == ""
    assert len(body["providers"]) == 1


def test_providers_endpoint_no_patient_id_returns_400() -> None:
    """An empty patient_id is a hard 400, not a recoverable state diagnostic."""
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
        return_value=PatientStateResult(state="", error="No patient ID provided."),
    ):
        api = _make_api(query_params={"patient_id": ""})
        results = api.providers()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_providers_endpoint_patient_not_found_returns_404() -> None:
    """A missing patient is a hard 404, not a recoverable state diagnostic."""
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
        return_value=PatientStateResult(
            state="",
            error="We could not find that patient. Reopen the modal and try again.",
            not_found=True,
        ),
    ):
        api = _make_api(query_params={"patient_id": "missing"})
        results = api.providers()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.NOT_FOUND


# ---- session state override on /providers ----


def _override_summaries() -> list:
    from scheduling_modal_with_recurring_support.services.provider_filter import ProviderSummary

    return [
        ProviderSummary(
            id="s1",
            full_name="Dr. X",
            npi_number="111",
            pct_filled=25.0,
            filled_count=2,
            free_count=6,
            total_count=8,
            has_capacity=True,
            appointments_last_30_days=5,
            upcoming_7_days=2,
            tier="recommended",
        ),
    ]


def test_providers_endpoint_applies_session_state_override() -> None:
    """A patient with no state on file (no address) is unblocked. The state passed
    on the query filters the list and is reported back, never persisted."""
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="", error="This patient has no state on file."),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
            return_value=_override_summaries(),
        ) as mock_filter,
    ):
        mock_token.return_value = MagicMock(access_token="tok")
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(
            query_params={"patient_id": "p1", "state": "CA"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    # The override drives the license filter even though the patient has no
    # resolved state and no address.
    mock_filter.assert_called_once_with(
        "CA",
        fhir_base_url="https://fumage-test.canvasmedical.com",
        access_token="tok",
        location_id="loc-1",
    )
    resp = results[0]
    assert resp.status_code == HTTPStatus.OK
    body = json.loads(resp.content)
    assert body["state"] == "CA"
    assert body["state_missing"] is False


def test_providers_endpoint_override_wins_over_state_on_file() -> None:
    """A patient who already has a state on file is still overridable. The state
    passed on the query drives the license filter even when it differs from the
    resolved state, so a traveling patient can be booked in another state. The
    override is reported back and never persisted."""
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="TN", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
            return_value=_override_summaries(),
        ) as mock_filter,
    ):
        mock_token.return_value = MagicMock(access_token="tok")
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(
            query_params={"patient_id": "p1", "state": "CA"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    mock_filter.assert_called_once_with(
        "CA",
        fhir_base_url="https://fumage-test.canvasmedical.com",
        access_token="tok",
        location_id="loc-1",
    )
    body = json.loads(results[0].content)
    assert body["state"] == "CA"
    assert body["state_missing"] is False


def test_providers_endpoint_lowercase_override_normalised() -> None:
    """A lowercase override is normalised to uppercase before filtering."""
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="", error="no state"),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
            return_value=_override_summaries(),
        ) as mock_filter,
    ):
        mock_token.return_value = MagicMock(access_token="tok")
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(
            query_params={"patient_id": "p1", "state": "ca"},
            secrets={"CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com"},
        )
        results = api.providers()

    assert mock_filter.call_args.args[0] == "CA"
    assert results[0].status_code == HTTPStatus.OK


def test_providers_endpoint_ignores_invalid_state_override() -> None:
    """A malformed override is ignored and the flow falls back to the unfiltered
    list with the state_missing flag, rather than wedging on a bad value."""
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="", error="This patient has no state on file."),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
            return_value=_override_summaries(),
        ) as mock_filter,
    ):
        mock_token.return_value = MagicMock(access_token="tok")
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(
            query_params={"patient_id": "p1", "state": "California"},
            secrets={"CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com"},
        )
        results = api.providers()

    assert mock_filter.call_args.args[0] == ""
    body = json.loads(results[0].content)
    assert body["state_missing"] is True


# ---- patients endpoint ----


def test_patients_search_returns_results() -> None:
    mock_patient = MagicMock()
    mock_patient.id = "p-abc"
    mock_patient.first_name = "John"
    mock_patient.last_name = "Doe"
    mock_patient.birth_date = date(1990, 5, 15)
    home = MagicMock()
    home.use = "home"
    home.state_code = "CA"
    mock_patient.addresses.all.return_value = [home]

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
    ) as mock_cls:
        mock_qs = MagicMock()
        mock_qs.__getitem__ = MagicMock(return_value=[mock_patient])
        mock_cls.objects.filter.return_value.prefetch_related.return_value = mock_qs

        api = _make_api(query_params={"q": "John"})
        results = api.patients()

    assert len(results) == 1
    body = json.loads(results[0].content)
    assert body["patients"][0]["state_code"] == "CA"


def test_patients_search_includes_empty_state_code_when_no_address() -> None:
    """A patient with no address on file returns an empty state_code so the
    modal opens the state dropdown empty rather than prefilling a stale value."""
    mock_patient = MagicMock()
    mock_patient.id = "p-def"
    mock_patient.first_name = "Jane"
    mock_patient.last_name = "Roe"
    mock_patient.birth_date = None
    mock_patient.addresses.all.return_value = []

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
    ) as mock_cls:
        mock_qs = MagicMock()
        mock_qs.__getitem__ = MagicMock(return_value=[mock_patient])
        mock_cls.objects.filter.return_value.prefetch_related.return_value = mock_qs

        api = _make_api(query_params={"q": "Jane"})
        results = api.patients()

    body = json.loads(results[0].content)
    assert body["patients"][0]["state_code"] == ""


def test_patients_search_short_query_returns_empty() -> None:
    api = _make_api(query_params={"q": "J"})
    results = api.patients()

    assert len(results) == 1
    resp = results[0]
    assert resp.status_code == HTTPStatus.OK


def test_patients_search_missing_query_returns_empty() -> None:
    api = _make_api(query_params={})
    results = api.patients()

    assert len(results) == 1


# ---- note-types endpoint ----

def test_note_types_returns_scheduleable_encounter_types() -> None:
    mock_nt = MagicMock()
    mock_nt.id = "a1b2c3d4-0000-0000-0000-000000000042"
    mock_nt.name = "Office Visit"

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.NoteType"
    ) as mock_nt_cls:
        mock_nt_cls.objects.filter.return_value = [mock_nt]
        api_inst = _make_api()
        results = api_inst.note_types()

    mock_nt_cls.objects.filter.assert_called_once_with(
        category="encounter",
        is_scheduleable=True,
    )
    assert len(results) == 1


class TestNoteTypesReturnsDefaultDuration:
    def test_returns_60_when_secret_empty(self) -> None:
        with patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.NoteType"
        ) as mock_nt_cls:
            mock_nt_cls.objects.filter.return_value = []
            api_inst = _make_api(secrets={})
            results = api_inst.note_types()

        body = json.loads(results[0].content)
        assert body["default_duration_minutes"] == 60

    def test_returns_30_when_secret_is_30(self) -> None:
        with patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.NoteType"
        ) as mock_nt_cls:
            mock_nt_cls.objects.filter.return_value = []
            api_inst = _make_api(secrets={"DEFAULT_APPOINTMENT_DURATION_MINUTES": "30"})
            results = api_inst.note_types()

        body = json.loads(results[0].content)
        assert body["default_duration_minutes"] == 30

    def test_returns_60_when_secret_invalid(self) -> None:
        with patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.NoteType"
        ) as mock_nt_cls:
            mock_nt_cls.objects.filter.return_value = []
            api_inst = _make_api(secrets={"DEFAULT_APPOINTMENT_DURATION_MINUTES": "abc"})
            results = api_inst.note_types()

        body = json.loads(results[0].content)
        assert body["default_duration_minutes"] == 60


# ---- availability endpoint ----

def test_availability_endpoint_missing_params() -> None:
    api = _make_api(query_params={"provider_id": "s1"})
    results = api.availability()
    assert len(results) == 1


def test_availability_endpoint_provider_not_found() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None
        api = _make_api(query_params={
            "provider_id": "s-missing",
            "start_date": "2025-03-03",
        })
        results = api.availability()

    assert len(results) == 1


def test_availability_rejects_past_start_date() -> None:
    mock_staff = MagicMock()
    mock_staff.npi_number = "111"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 22),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(query_params={
            "provider_id": "s1",
            "cadence": "weekly",
            "start_date": "2026-04-20",
            "occurrences": "4",
        })
        results = api.availability()

    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_availability_returns_slot_times() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        RecurrenceAnalysis,
        SlotAvailability,
    )

    mock_staff = MagicMock()
    mock_staff.npi_number = "111"

    mock_analysis = RecurrenceAnalysis(
        slots=[
            SlotAvailability(
                occurrence_date=date(2026, 5, 1),
                available_times=[
                    FreeSlot(start="2026-05-01T09:00:00", end="2026-05-01T09:30:00"),
                    FreeSlot(start="2026-05-01T10:00:00", end="2026-05-01T10:30:00"),
                ],
                is_available=True,
            ),
            SlotAvailability(
                occurrence_date=date(2026, 5, 8),
                available_times=[],
                is_available=False,
            ),
        ],
        available_count=1,
        total_count=2,
        availability_pct=50.0,
    )

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.analyse_recurrence",
            return_value=mock_analysis,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "cadence": "weekly",
                "start_date": "2026-05-01",
                "occurrences": "2",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.availability()

    assert len(results) == 1


# ---- candidate-times endpoint ----


def test_candidate_times_returns_aggregated_payload() -> None:
    from scheduling_modal_with_recurring_support.services.availability import CandidateTimeAggregate

    mock_staff = MagicMock()
    mock_staff.id = "s1"
    mock_aggregates = [
        CandidateTimeAggregate(hhmm="09:00", available_count=3, total_count=4, availability_pct=75.0),
        CandidateTimeAggregate(hhmm="10:00", available_count=4, total_count=4, availability_pct=100.0),
    ]

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.aggregate_by_candidate_time",
            return_value=mock_aggregates,
        ) as mock_agg,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "cadence": "weekly",
                "start_date": "2026-05-04",
                "occurrences": "4",
                "tz_offset": "240",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.candidate_times()

    assert len(results) == 1
    body = results[0].content
    import json
    data = json.loads(body)
    assert data["date"] == "2026-05-04"
    assert len(data["candidate_times"]) == 2
    assert data["candidate_times"][0] == {
        "hhmm": "09:00",
        "available_count": 3,
        "total_count": 4,
        "availability_pct": 75.0,
    }
    assert data["candidate_times"][1]["hhmm"] == "10:00"
    mock_agg.assert_called_once()
    kwargs = mock_agg.call_args.kwargs
    rule = kwargs["rule"]
    assert rule.interval.value == 1
    assert rule.interval.unit.value == "week"
    assert rule.end.count == 4
    assert kwargs["start_date"] == date(2026, 5, 4)
    assert kwargs["tz_offset_minutes"] == 240


def test_candidate_times_rejects_missing_provider_id() -> None:
    api = _make_api(query_params={"start_date": "2026-05-04"})
    results = api.candidate_times()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


# ---- check-slots endpoint ----

_CHECK_SLOTS_SECRETS = {
    "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
    "CANVAS_OAUTH_CLIENT_ID": "cid",
    "CANVAS_OAUTH_CLIENT_SECRET": "cs",
}


def _check_slots_setup(slot_avail, booked_times=None):
    """Context manager helper for check-slots tests.

    The handler prefills a date keyed memo via `_prefill_memo_for_range`, so
    this helper writes the supplied SlotAvailability into the memo for every
    requested date. booked_times: list of UTC datetimes that the DB says are
    already booked. Pass [] or omit for no conflicts.
    """
    from contextlib import contextmanager

    def _fake_prefill(memo, fhir_base_url, access_token, schedule_id, dates, *args, **kwargs):
        for d in dates:
            memo[d] = slot_avail

    @contextmanager
    def ctx():
        mock_staff = MagicMock()
        with (
            patch(
                "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
            ) as mock_staff_cls,
            patch(
                "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
            ) as mock_token,
            patch(
                "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
                return_value="sched-1",
            ),
            patch(
                "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
                side_effect=_fake_prefill,
            ),
            patch(
                "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
            ) as mock_appt_model,
        ):
            mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
            mock_token.return_value = MagicMock(access_token="tok")
            mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = booked_times or []
            yield
    return ctx()


def _parse_check_slots_response(results):
    import json
    resp = results[0]
    return resp.status_code, json.loads(resp.content)


def test_check_slots_missing_params() -> None:
    api = _make_api(json_body={"provider_id": "", "slots": []})
    results = api.check_slots()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_check_slots_provider_not_found() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None
        api = _make_api(
            json_body={"provider_id": "s-missing", "slots": [{"date": "2026-05-01", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()
    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_check_slots_slot_is_free_in_fhir() -> None:
    """Requested time exists in FHIR free slots and no ORM conflict -> is_free=True.
    A free row returns the full day's free list, the requested time included."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[
            FreeSlot(start="2026-05-01T10:00:00", end="2026-05-01T10:30:00"),
            FreeSlot(start="2026-05-01T11:00:00", end="2026-05-01T11:30:00"),
        ],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    status, body = _parse_check_slots_response(results)
    assert status == HTTPStatus.OK
    assert body["free_count"] == 1
    assert body["results"][0]["is_free"] is True
    alt_starts = [a["start"] for a in body["results"][0]["available_times"]]
    assert "2026-05-01T10:00:00" in alt_starts
    assert "2026-05-01T11:00:00" in alt_starts
    assert len(body["results"][0]["available_times"]) == 2


def test_check_slots_time_not_in_fhir_shows_alternatives() -> None:
    """Requested time NOT in FHIR free slots -> is_free=False, alternatives listed WITHOUT the requested time."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[
            FreeSlot(start="2026-05-01T11:00:00", end="2026-05-01T11:30:00"),
            FreeSlot(start="2026-05-01T14:00:00", end="2026-05-01T14:30:00"),
        ],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    status, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is False
    assert len(body["results"][0]["available_times"]) == 2
    alt_starts = [a["start"] for a in body["results"][0]["available_times"]]
    assert "2026-05-01T11:00:00" in alt_starts
    assert "2026-05-01T14:00:00" in alt_starts


def test_check_slots_fhir_free_but_orm_conflict_excludes_requested_time() -> None:
    """FHIR says 10am is free, but ORM has existing appointment -> is_free=False.
    Alternatives must NOT include the 10am slot that is already booked."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[
            FreeSlot(start="2026-05-01T10:00:00-04:00", end="2026-05-01T10:30:00-04:00"),
            FreeSlot(start="2026-05-01T11:00:00-04:00", end="2026-05-01T11:30:00-04:00"),
            FreeSlot(start="2026-05-01T14:00:00-04:00", end="2026-05-01T14:30:00-04:00"),
        ],
        is_available=True,
    )

    # Slot is 10:00 EDT (UTC-4 = tz_offset 240) → 14:00 UTC
    booked = [datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)]
    with _check_slots_setup(avail, booked_times=booked):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}], "tz_offset": 240},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    status, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is False
    alt_starts = [a["start"] for a in body["results"][0]["available_times"]]
    assert "2026-05-01T10:00:00-04:00" not in alt_starts
    assert "2026-05-01T11:00:00-04:00" in alt_starts
    assert "2026-05-01T14:00:00-04:00" in alt_starts
    assert len(alt_starts) == 2


def test_check_slots_no_fhir_availability_empty_alternatives() -> None:
    """FHIR has no free slots at all -> is_free=False, alternatives empty."""
    from scheduling_modal_with_recurring_support.services.availability import SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[],
        is_available=False,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    status, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is False
    assert body["results"][0]["available_times"] == []


def test_check_slots_invalid_date_returns_not_free() -> None:
    """Invalid date string -> gracefully returns is_free=False with empty alternatives."""
    from scheduling_modal_with_recurring_support.services.availability import SlotAvailability

    avail = SlotAvailability(occurrence_date=date(2026, 5, 1), available_times=[], is_available=False)

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "not-a-date", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    status, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is False
    assert body["results"][0]["available_times"] == []


def test_check_slots_multiple_slots_mixed_results() -> None:
    """Multiple slots: one free, one taken. Counts reflect correctly."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail_may1 = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[FreeSlot(start="2026-05-01T10:00:00", end="2026-05-01T10:30:00")],
        is_available=True,
    )
    avail_may8 = SlotAvailability(
        occurrence_date=date(2026, 5, 8),
        available_times=[FreeSlot(start="2026-05-08T11:00:00", end="2026-05-08T11:30:00")],
        is_available=True,
    )

    def fake_prefill(memo, fhir_base_url, access_token, schedule_id, dates, *args, **kwargs):
        if date(2026, 5, 1) in dates:
            memo[date(2026, 5, 1)] = avail_may1
        if date(2026, 5, 8) in dates:
            memo[date(2026, 5, 8)] = avail_may8

    mock_staff = MagicMock()
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
            side_effect=fake_prefill,
        ),
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel") as mock_appt_model,
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [
                    {"date": "2026-05-01", "start_time": "10:00"},
                    {"date": "2026-05-08", "start_time": "10:00"},
                ],
            },
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    status, body = _parse_check_slots_response(results)
    assert body["total_count"] == 2
    assert body["free_count"] == 1
    assert body["results"][0]["is_free"] is True
    assert body["results"][1]["is_free"] is False
    assert len(body["results"][1]["available_times"]) == 1


def test_check_slots_fhir_edt_offset_matches_edt_user() -> None:
    """FHIR returns '10:00:00-04:00' (EDT). User in EDT requested '10:00'. Should match.
    The free row returns the day's full free list, both EDT slots included."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 12),
        available_times=[
            FreeSlot(start="2026-05-12T10:00:00-04:00", end="2026-05-12T10:30:00-04:00"),
            FreeSlot(start="2026-05-12T11:00:00-04:00", end="2026-05-12T11:30:00-04:00"),
        ],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-12", "start_time": "10:00"}], "tz_offset": 240},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is True
    assert len(body["results"][0]["available_times"]) == 2


def test_check_slots_fhir_utc_converts_to_edt_user() -> None:
    """FHIR returns '14:00:00Z' (UTC). User in EDT (tz_offset=240) requested '10:00'.
    14:00 UTC = 10:00 EDT. Should match and be free, and the free row returns that
    slot in its available_times."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 12),
        available_times=[
            FreeSlot(start="2026-05-12T14:00:00Z", end="2026-05-12T14:30:00Z"),
        ],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-12", "start_time": "10:00"}], "tz_offset": 240},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is True
    assert len(body["results"][0]["available_times"]) == 1
    assert body["results"][0]["available_times"][0]["start"] == "2026-05-12T14:00:00Z"


def test_check_slots_eest_user_12pm_matches_booked_slot() -> None:
    """User in EEST (tz_offset=-120) requests '12:00'. FHIR has free slot at
    06:00 EDT (=12:00 EEST). This correctly matches.
    But if no free slot at 06:00 EDT (it's booked), it should show not free."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 12),
        available_times=[
            FreeSlot(start="2026-05-12T07:10:00-04:00", end="2026-05-12T07:30:00-04:00"),
            FreeSlot(start="2026-05-12T09:00:00-04:00", end="2026-05-12T09:20:00-04:00"),
        ],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-12", "start_time": "12:00"}], "tz_offset": -120},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is False
    assert len(body["results"][0]["available_times"]) == 2


def test_check_slots_fhir_utc_not_matching_edt_user_shows_alternatives() -> None:
    """FHIR returns '14:00:00Z' (UTC = 10:00 EDT) and '15:00:00Z' (UTC = 11:00 EDT).
    User in EDT requests '09:00'. Neither matches. Alternatives shown."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 12),
        available_times=[
            FreeSlot(start="2026-05-12T14:00:00Z", end="2026-05-12T14:30:00Z"),
            FreeSlot(start="2026-05-12T15:00:00Z", end="2026-05-12T15:30:00Z"),
        ],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-12", "start_time": "09:00"}], "tz_offset": 240},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is False
    assert len(body["results"][0]["available_times"]) == 2


def test_check_slots_free_slot_returns_full_day_times() -> None:
    """When the slot IS free, available_times carries the full day's free list so
    the time picker paints from the first response. The requested time is included."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[
            FreeSlot(start="2026-05-01T10:00:00", end="2026-05-01T10:30:00"),
            FreeSlot(start="2026-05-01T11:00:00", end="2026-05-01T11:30:00"),
            FreeSlot(start="2026-05-01T14:00:00", end="2026-05-01T14:30:00"),
        ],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["is_free"] is True
    alt_starts = [a["start"] for a in body["results"][0]["available_times"]]
    assert "2026-05-01T10:00:00" in alt_starts
    assert len(body["results"][0]["available_times"]) == 3


def test_check_slots_forwards_tz_offset_to_memo_prefill() -> None:
    """check_slots must bucket availability by the local date. It forwards the
    request tz_offset into _prefill_memo_for_range, the same offset every other
    consumer uses, so an evening time like 22:30 is judged against its local day
    and not the UTC day it spills into. Omitting the offset was the bug, the
    memo bucketed by UTC and the row was checked against the wrong day."""
    from scheduling_modal_with_recurring_support.services.availability import SlotAvailability

    captured: dict[str, int] = {}

    def _capture_prefill(
        memo, fhir_base_url, access_token, schedule_id, dates,
        duration_minutes=30, tz_offset_minutes=0,
    ):
        captured["tz_offset_minutes"] = tz_offset_minutes
        for d in dates:
            memo[d] = SlotAvailability(occurrence_date=d, available_times=[], is_available=False)

    mock_staff = MagicMock()
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
            side_effect=_capture_prefill,
        ),
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel") as mock_appt_model,
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []
        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [{"date": "2026-05-12", "start_time": "22:30"}],
                "tz_offset": 240,
            },
            secrets=_CHECK_SLOTS_SECRETS,
        )
        api.check_slots()

    assert captured["tz_offset_minutes"] == 240


# ---- check-slots per occurrence reason ----


def test_check_slots_reason_free_when_slot_open() -> None:
    """A free time with no booking reads reason 'free'."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[FreeSlot(start="2026-05-01T10:00:00", end="2026-05-01T10:30:00")],
        is_available=True,
    )

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["reason"] == "free"
    assert body["results"][0]["is_free"] is True


def test_check_slots_reason_outside_hours_when_closed() -> None:
    """A closed day, no FHIR slot and no booking, reads reason 'outside_hours'."""
    from scheduling_modal_with_recurring_support.services.availability import SlotAvailability

    avail = SlotAvailability(occurrence_date=date(2026, 5, 1), available_times=[], is_available=False)

    with _check_slots_setup(avail):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}]},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["reason"] == "outside_hours"
    assert body["results"][0]["is_free"] is False


def test_check_slots_reason_booked_when_time_taken() -> None:
    """FHIR never offered the time because it is taken,
    and the DB shows an appointment there, so the row reads reason 'booked'
    rather than 'outside_hours'."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    # Provider works that day, FHIR offers 11:00 and 14:00 but not 10:00.
    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[
            FreeSlot(start="2026-05-01T11:00:00", end="2026-05-01T11:30:00"),
            FreeSlot(start="2026-05-01T14:00:00", end="2026-05-01T14:30:00"),
        ],
        is_available=True,
    )

    # Requested 10:00 in UTC (tz_offset 0) is booked in the DB.
    booked = [datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)]
    with _check_slots_setup(avail, booked_times=booked):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}], "tz_offset": 0},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["reason"] == "booked"
    assert body["results"][0]["is_free"] is False
    # The other free times that day still surface as alternatives.
    alt_starts = [a["start"] for a in body["results"][0]["available_times"]]
    assert "2026-05-01T11:00:00" in alt_starts
    assert "2026-05-01T14:00:00" in alt_starts


def test_check_slots_reason_booked_on_fhir_free_race() -> None:
    """A time FHIR offered free that the DB shows as just taken reads reason
    'booked' and never free, preserving the existing double book guard."""
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[
            FreeSlot(start="2026-05-01T10:00:00", end="2026-05-01T10:30:00"),
            FreeSlot(start="2026-05-01T11:00:00", end="2026-05-01T11:30:00"),
        ],
        is_available=True,
    )

    booked = [datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)]
    with _check_slots_setup(avail, booked_times=booked):
        api = _make_api(
            json_body={"provider_id": "s1", "slots": [{"date": "2026-05-01", "start_time": "10:00"}], "tz_offset": 0},
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    _, body = _parse_check_slots_response(results)
    assert body["results"][0]["reason"] == "booked"
    assert body["results"][0]["is_free"] is False
    assert body["free_count"] == 0


# ---- book endpoint ----

def test_book_missing_required_fields() -> None:
    api = _make_api(json_body={"patient_id": "", "provider_id": ""})
    results = api.book()
    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_book_no_appointments() -> None:
    api = _make_api(json_body={
        "patient_id": "p1",
        "provider_id": "s1",
        "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
        "appointments": [],
    })
    results = api.book()
    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_book_provider_not_found() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None
        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s-missing",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_book_single_appointment() -> None:
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    mock_appt_instance = MagicMock()
    mock_appt_instance.create.return_value = MagicMock()

    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect",
            return_value=mock_appt_instance,
        ) as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.bust_filled_pct"
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.values_list.return_value = []

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [
                {"date": "2026-05-01", "start_time": "09:00"},
            ],
        })
        results = api.book()

    mock_appt_cls.assert_called_once_with(
        appointment_note_type_id=note_type_id,
        patient_id="p1",
        provider_id="s1",
        start_time=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        duration_minutes=60,
        practice_location_id="loc-1",
    )
    assert len(results) == 2


def test_book_multiple_appointments() -> None:
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    mock_appt_instance = MagicMock()
    mock_appt_instance.create.return_value = MagicMock()

    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect",
            return_value=mock_appt_instance,
        ) as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.bust_filled_pct"
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.values_list.return_value = []

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [
                {"date": "2026-05-01", "start_time": "09:00"},
                {"date": "2026-05-08", "start_time": "14:30"},
            ],
        })
        results = api.book()

    assert mock_appt_cls.call_count == 2
    first_call, second_call = mock_appt_cls.call_args_list

    assert first_call == call(
        appointment_note_type_id=note_type_id,
        patient_id="p1",
        provider_id="s1",
        start_time=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        duration_minutes=60,
        practice_location_id="loc-1",
    )
    assert second_call == call(
        appointment_note_type_id=note_type_id,
        patient_id="p1",
        provider_id="s1",
        start_time=datetime(2026, 5, 8, 14, 30, tzinfo=timezone.utc),
        duration_minutes=60,
        practice_location_id="loc-1",
    )
    # JSONResponse + 2 effects
    assert len(results) == 3


def test_book_rejects_double_booking() -> None:
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        # Appointment is 10:00 with no tz_offset (UTC). Range query returns it as booked.
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = [
            datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
        ]

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [
                {"date": "2026-05-01", "start_time": "10:00"},
            ],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.CONFLICT
    body = json.loads(resp.content)
    assert "Some times were just booked" in body["error"]
    assert isinstance(body["conflicts"], list)
    assert body["conflicts"] == [{"date": "2026-05-01", "start_time": "10:00"}]


def test_book_conflicts_echo_only_the_taken_occurrences() -> None:
    """A partial conflict echoes the client's own values for the taken
    occurrences only, so the frontend can match them back to rows."""
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        # Only the second occurrence is taken. tz_offset -120 means UTC+2,
        # so 12:00 local is 10:00 UTC.
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = [
            datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        ]

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "tz_offset": -120,
            "appointments": [
                {"date": "2026-05-01", "start_time": "12:00"},
                {"date": "2026-05-08", "start_time": "12:00"},
            ],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.CONFLICT
    body = json.loads(resp.content)
    assert body["conflicts"] == [{"date": "2026-05-08", "start_time": "12:00"}]


def test_book_rejects_past_appointment() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 22, 15, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [
                {"date": "2026-04-22", "start_time": "09:00"},
            ],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_book_rejects_invalid_date() -> None:
    mock_staff = MagicMock()

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [
                {"date": "not-a-date", "start_time": "09:00"},
            ],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_book_rejects_invalid_time() -> None:
    mock_staff = MagicMock()

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [
                {"date": "2026-05-01", "start_time": "garbage"},
            ],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_book_rejects_missing_appointment_fields() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [
                {"date": "2026-05-01"},
            ],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST


# ---- book endpoint timezone matrix ----


def _book_with_tz(
    tz_offset: int | None,
    appt_date: str,
    appt_time: str,
    now: datetime,
    conflict_exists: bool = False,
) -> tuple[MagicMock, list]:
    """Run /book with a given tz_offset and return (mock_appt_cls, results)."""
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    mock_appt_instance = MagicMock()
    mock_appt_instance.create.return_value = MagicMock()
    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"

    body: dict = {
        "patient_id": "p1",
        "provider_id": "s1",
        "note_type_id": note_type_id,
        "appointments": [{"date": appt_date, "start_time": appt_time}],
    }
    if tz_offset is not None:
        body["tz_offset"] = tz_offset

    # Compute the UTC datetime the production code will derive so the mock
    # returns it from values_list when conflict_exists=True.
    effective_offset = tz_offset if tz_offset is not None else 0
    client_tz = timezone(timedelta(minutes=-effective_offset))
    appt_dt_local = datetime.combine(
        date.fromisoformat(appt_date),
        datetime.strptime(appt_time, "%H:%M").time(),
        tzinfo=client_tz,
    )
    appt_dt_utc = appt_dt_local.astimezone(timezone.utc)
    booked_starts = [appt_dt_utc] if conflict_exists else []

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect",
            return_value=mock_appt_instance,
        ) as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=now,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.bust_filled_pct"
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = booked_starts

        api = _make_api(json_body=body)
        results = api.book()

    return mock_appt_cls, results


def test_book_tz_offset_zero_produces_utc() -> None:
    """tz_offset=0 produces a UTC datetime equal to the input wall clock."""
    mock_appt_cls, results = _book_with_tz(
        tz_offset=0,
        appt_date="2026-05-01",
        appt_time="09:00",
        now=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
    )
    mock_appt_cls.assert_called_once()
    assert mock_appt_cls.call_args.kwargs["start_time"] == datetime(
        2026, 5, 1, 9, 0, tzinfo=timezone.utc
    )


def test_book_tz_offset_positive_300_us_eastern() -> None:
    """tz_offset=300 (US Eastern winter, west of UTC) shifts 09:00 local to 14:00 UTC."""
    mock_appt_cls, results = _book_with_tz(
        tz_offset=300,
        appt_date="2026-05-01",
        appt_time="09:00",
        now=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
    )
    mock_appt_cls.assert_called_once()
    assert mock_appt_cls.call_args.kwargs["start_time"] == datetime(
        2026, 5, 1, 14, 0, tzinfo=timezone.utc
    )


def test_book_tz_offset_negative_540_tokyo() -> None:
    """tz_offset=-540 (Tokyo, east of UTC) shifts 09:00 local to 00:00 UTC same day."""
    mock_appt_cls, results = _book_with_tz(
        tz_offset=-540,
        appt_date="2026-05-01",
        appt_time="09:00",
        now=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
    )
    mock_appt_cls.assert_called_once()
    assert mock_appt_cls.call_args.kwargs["start_time"] == datetime(
        2026, 5, 1, 0, 0, tzinfo=timezone.utc
    )


def test_book_conflict_check_uses_converted_utc() -> None:
    """Conflict filter sees the converted UTC datetime, not naive local."""
    mock_appt_cls, results = _book_with_tz(
        tz_offset=300,
        appt_date="2026-05-01",
        appt_time="09:00",
        now=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        conflict_exists=True,
    )
    resp = results[0]
    assert resp.status_code == HTTPStatus.CONFLICT


def test_book_past_guard_respects_timezone() -> None:
    """A wall clock that maps to a UTC moment in the past is rejected."""
    mock_appt_cls, results = _book_with_tz(
        tz_offset=300,
        appt_date="2026-05-01",
        appt_time="09:00",
        now=datetime(2026, 5, 1, 14, 30, tzinfo=timezone.utc),
    )
    resp = results[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    mock_appt_cls.assert_not_called()


def test_book_missing_tz_offset_defaults_to_zero() -> None:
    """No tz_offset in body behaves as tz_offset=0 for backward compatibility."""
    mock_appt_cls, results = _book_with_tz(
        tz_offset=None,
        appt_date="2026-05-01",
        appt_time="09:00",
        now=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
    )
    mock_appt_cls.assert_called_once()
    assert mock_appt_cls.call_args.kwargs["start_time"] == datetime(
        2026, 5, 1, 9, 0, tzinfo=timezone.utc
    )


def test_book_busts_filled_pct_cache_for_provider() -> None:
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    mock_appt_instance = MagicMock()
    mock_appt_instance.create.return_value = MagicMock()

    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect",
            return_value=mock_appt_instance,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.bust_filled_pct"
        ) as mock_bust,
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.values_list.return_value = []

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [
                {"date": "2026-05-01", "start_time": "09:00"},
            ],
        })
        api.book()

    mock_bust.assert_called_once_with("s1")


# ---- /book/validate endpoint ----

def _make_validate_api(json_body: dict | None = None) -> MagicMock:
    from scheduling_modal_with_recurring_support.api.scheduling_api import SchedulingAPI
    api = _make_api(json_body=json_body)
    api.validate_booking = lambda: SchedulingAPI.validate_booking(api)
    return api


def test_validate_missing_required_fields() -> None:
    api = _make_validate_api(json_body={"patient_id": "", "provider_id": ""})
    results = api.validate_booking()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_validate_no_appointments() -> None:
    api = _make_validate_api(json_body={
        "patient_id": "p1",
        "provider_id": "s1",
        "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
        "appointments": [],
    })
    results = api.validate_booking()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_validate_provider_not_found() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None
        api = _make_validate_api(json_body={
            "patient_id": "p1",
            "provider_id": "s-missing",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        })
        results = api.validate_booking()
    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_validate_success_returns_count() -> None:
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.values_list.return_value = []

        api = _make_validate_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [
                {"date": "2026-05-01", "start_time": "09:00"},
                {"date": "2026-05-08", "start_time": "09:00"},
                {"date": "2026-05-15", "start_time": "09:00"},
            ],
        })
        results = api.validate_booking()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.OK
    body = json.loads(results[0].content)
    assert body == {"ok": True, "checked": 3}


def test_validate_emits_no_effects() -> None:
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect"
        ) as mock_appt_cls,
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.values_list.return_value = []

        api = _make_validate_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        })
        results = api.validate_booking()

    mock_appt_cls.assert_not_called()
    assert len(results) == 1


def test_validate_conflict_returns_409() -> None:
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        # Appointment is 09:00 with no tz_offset (UTC). Range query returns it as booked.
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = [
            datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
        ]

        api = _make_validate_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        })
        results = api.validate_booking()

    assert results[0].status_code == HTTPStatus.CONFLICT
    body = json.loads(results[0].content)
    assert "error" in body
    assert body["conflicts"] == [{"date": "2026-05-01", "start_time": "09:00"}]


# ---- B1, pre flight NPI guard ----


def test_book_rejects_provider_without_npi() -> None:
    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"
    mock_staff = MagicMock()
    mock_staff.npi_number = ""
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect"
        ) as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        })
        results = api.book()

    resp = results[0]
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    body = json.loads(resp.content)
    assert "NPI" in body["error"]
    # The guard fires before any effect is built.
    mock_appt_cls.assert_not_called()


def test_validate_rejects_provider_without_npi() -> None:
    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"
    mock_staff = MagicMock()
    mock_staff.npi_number = "   "  # whitespace only is treated as blank
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_validate_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        })
        results = api.validate_booking()

    resp = results[0]
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    body = json.loads(resp.content)
    assert "NPI" in body["error"]


def test_book_allows_provider_with_npi() -> None:
    note_type_id = "a1b2c3d4-0000-0000-0000-000000000042"
    mock_staff = MagicMock()
    mock_staff.npi_number = "1234567890"
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    mock_appt_instance = MagicMock()
    mock_appt_instance.create.return_value = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect",
            return_value=mock_appt_instance,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.bust_filled_pct"
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": note_type_id,
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        })
        results = api.book()

    assert results[0].status_code == HTTPStatus.CREATED


# ---- B2, /book/verify endpoint ----


def _make_verify_api(json_body: dict | None = None) -> MagicMock:
    from scheduling_modal_with_recurring_support.api.scheduling_api import SchedulingAPI
    api = _make_api(json_body=json_body)
    api.verify_booking = lambda: SchedulingAPI.verify_booking(api)
    return api


def test_verify_missing_params_returns_400() -> None:
    api = _make_verify_api(json_body={"provider_id": "", "appointments": []})
    results = api.verify_booking()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_verify_non_numeric_tz_returns_400() -> None:
    api = _make_verify_api(json_body={
        "provider_id": "s1",
        "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
        "tz_offset": "abc",
    })
    results = api.verify_booking()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_verify_all_present() -> None:
    booked = [
        datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 8, 9, 0, tzinfo=timezone.utc),
    ]
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
    ) as mock_appt_model:
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = booked
        api = _make_verify_api(json_body={
            "provider_id": "s1",
            "appointments": [
                {"date": "2026-05-01", "start_time": "09:00"},
                {"date": "2026-05-08", "start_time": "09:00"},
            ],
            "tz_offset": 0,
        })
        results = api.verify_booking()

    body = json.loads(results[0].content)
    assert body["all_present"] is True
    assert body["missing"] == []
    assert len(body["present"]) == 2


def test_verify_some_missing() -> None:
    # Only the first requested time reads back as booked.
    booked = [datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)]
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
    ) as mock_appt_model:
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = booked
        api = _make_verify_api(json_body={
            "provider_id": "s1",
            "appointments": [
                {"date": "2026-05-01", "start_time": "09:00"},
                {"date": "2026-05-08", "start_time": "09:00"},
            ],
            "tz_offset": 0,
        })
        results = api.verify_booking()

    body = json.loads(results[0].content)
    assert body["all_present"] is False
    assert body["present"] == [{"date": "2026-05-01", "start_time": "09:00"}]
    assert body["missing"] == [{"date": "2026-05-08", "start_time": "09:00"}]


def test_verify_unparseable_pair_counted_missing() -> None:
    booked = [datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)]
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
    ) as mock_appt_model:
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = booked
        api = _make_verify_api(json_body={
            "provider_id": "s1",
            "appointments": [
                {"date": "2026-05-01", "start_time": "09:00"},
                {"date": "not-a-date", "start_time": "09:00"},
            ],
            "tz_offset": 0,
        })
        results = api.verify_booking()

    body = json.loads(results[0].content)
    assert body["all_present"] is False
    assert body["present"] == [{"date": "2026-05-01", "start_time": "09:00"}]
    assert body["missing"] == [{"date": "not-a-date", "start_time": "09:00"}]


def test_verify_excludes_cancelled_statuses() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
    ) as mock_appt_model:
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []
        api = _make_verify_api(json_body={
            "provider_id": "s1",
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
            "tz_offset": 0,
        })
        api.verify_booking()

    exclude_kwargs = mock_appt_model.objects.filter.return_value.exclude.call_args.kwargs
    assert sorted(exclude_kwargs["status__in"]) == sorted(_CANCELLED_STATUSES)


# ---- candidate-first-dates endpoint ----


_CFD_SECRETS = {
    "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
    "CANVAS_OAUTH_CLIENT_ID": "cid",
    "CANVAS_OAUTH_CLIENT_SECRET": "cs",
}


def _cfd_aggregate(first_date_str: str, available: int, total: int, occurrences: list[str]):
    from scheduling_modal_with_recurring_support.services.availability import FirstDateAggregate

    return FirstDateAggregate(
        first_date=date.fromisoformat(first_date_str),
        occurrence_dates=[date.fromisoformat(d) for d in occurrences],
        available_count=available,
        total_count=total,
        availability_pct=round((available / total * 100) if total else 0.0, 1),
    )


def test_candidate_first_dates_returns_payload_with_canonical_recurrence() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    aggregates = [
        _cfd_aggregate("2026-05-04", 3, 3, ["2026-05-04", "2026-05-11", "2026-05-18"]),
        _cfd_aggregate("2026-05-05", 2, 3, ["2026-05-05", "2026-05-12", "2026-05-19"]),
    ]

    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.aggregate_by_first_date",
            return_value=aggregates,
        ) as mock_agg,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "recurrence": {
                    "interval": {"value": 1, "unit": "week"},
                    "end": {"kind": "count", "count": 3},
                },
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
                "tz_offset": 240,
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()

    assert len(results) == 1
    body = json.loads(results[0].content)
    assert body["search_window"] == {"start": "2026-05-04", "end": "2026-05-31"}
    assert body["candidates"] == [
        {
            "first_date": "2026-05-04",
            "available_count": 3,
            "total_count": 3,
            "availability_pct": 100.0,
            "occurrence_dates": ["2026-05-04", "2026-05-11", "2026-05-18"],
        },
        {
            "first_date": "2026-05-05",
            "available_count": 2,
            "total_count": 3,
            "availability_pct": 66.7,
            "occurrence_dates": ["2026-05-05", "2026-05-12", "2026-05-19"],
        },
    ]

    assert body["basis"] == "single_provider"
    mock_agg.assert_called_once()
    kwargs = mock_agg.call_args.kwargs
    rule = kwargs["rule"]
    assert rule.interval.value == 1
    assert rule.interval.unit.value == "week"
    assert rule.end.count == 3
    assert kwargs["window_start"] == date(2026, 5, 4)
    assert kwargs["window_end"] == date(2026, 5, 31)


def _coverage(first_date_str: str, covering: int, candidate: int):
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        FirstDateCoverage,
    )

    return FirstDateCoverage(
        first_date=date.fromisoformat(first_date_str),
        covering_count=covering,
        candidate_count=candidate,
    )


def test_candidate_first_dates_provider_agnostic_returns_coverage() -> None:
    """With a patient_id and no provider_id the endpoint takes the provider
    agnostic basis, counting how many candidate providers can cover the series
    from each day."""
    from scheduling_modal_with_recurring_support.api.scheduling_api import (
        PatientStateResult,
    )

    coverage = [
        _coverage("2026-05-04", 3, 5),
        _coverage("2026-05-05", 1, 5),
    ]

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.providers_covering_series_by_first_date",
            return_value=coverage,
        ) as mock_cov,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            json_body={
                "patient_id": "p1",
                "recurrence": {
                    "interval": {"value": 1, "unit": "week"},
                    "end": {"kind": "count", "count": 3},
                },
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
                "tz_offset": 240,
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()

    body = json.loads(results[0].content)
    assert body["basis"] == "series_coverage"
    assert body["state"] == "CA"
    assert body["state_missing"] is False
    assert body["candidates"] == [
        {"first_date": "2026-05-04", "covering_count": 3, "candidate_count": 5},
        {"first_date": "2026-05-05", "covering_count": 1, "candidate_count": 5},
    ]
    kwargs = mock_cov.call_args.kwargs
    assert kwargs["window_start"] == date(2026, 5, 4)
    assert kwargs["tz_offset_minutes"] == 240


def test_candidate_first_dates_provider_agnostic_patient_not_found_404() -> None:
    from scheduling_modal_with_recurring_support.api.scheduling_api import (
        PatientStateResult,
    )

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="", error="no patient", not_found=True),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        api = _make_api(
            json_body={
                "patient_id": "ghost",
                "cadence": "weekly",
                "occurrences": 3,
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()

    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_candidate_first_dates_provider_agnostic_missing_state_flags_and_runs() -> None:
    """A patient with no state on file falls through to the unfiltered
    candidate set with a state_missing flag rather than failing."""
    from scheduling_modal_with_recurring_support.api.scheduling_api import (
        PatientStateResult,
    )

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="", error="no state on file"),
        ),
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.providers_covering_series_by_first_date",
            return_value=[_coverage("2026-05-04", 0, 0)],
        ) as mock_cov,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            json_body={
                "patient_id": "p1",
                "cadence": "weekly",
                "occurrences": 3,
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()

    body = json.loads(results[0].content)
    assert body["state_missing"] is True
    assert body["message"] == "no state on file"
    # The empty state still drives the unfiltered scoring call.
    assert mock_cov.call_args.args[0] == ""


def test_candidate_first_dates_accepts_legacy_cadence_body() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.aggregate_by_first_date",
            return_value=[],
        ) as mock_agg,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "cadence": "biweekly",
                "occurrences": 6,
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-18",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()

    assert results[0].status_code == HTTPStatus.OK
    rule = mock_agg.call_args.kwargs["rule"]
    assert rule.interval.value == 2
    assert rule.interval.unit.value == "week"
    assert rule.end.count == 6


def test_candidate_first_dates_empty_candidates_is_200() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.aggregate_by_first_date",
            return_value=[],
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "cadence": "weekly",
                "occurrences": 4,
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()

    assert results[0].status_code == HTTPStatus.OK
    body = json.loads(results[0].content)
    assert body["candidates"] == []


def test_candidate_first_dates_provider_not_found_returns_404() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None

        api = _make_api(
            json_body={
                "provider_id": "missing",
                "cadence": "weekly",
                "occurrences": 4,
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()

    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_candidate_first_dates_missing_provider_id_returns_400() -> None:
    api = _make_api(
        json_body={
            "cadence": "weekly",
            "occurrences": 4,
            "search_window_start": "2026-05-04",
            "search_window_end": "2026-05-31",
        },
        secrets=_CFD_SECRETS,
    )
    results = api.candidate_first_dates()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_first_dates_missing_window_returns_400() -> None:
    api = _make_api(
        json_body={
            "provider_id": "s1",
            "cadence": "weekly",
            "occurrences": 4,
        },
        secrets=_CFD_SECRETS,
    )
    results = api.candidate_first_dates()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_first_dates_window_end_before_start_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(
            json_body={
                "provider_id": "s1",
                "cadence": "weekly",
                "occurrences": 4,
                "search_window_start": "2026-05-10",
                "search_window_end": "2026-05-04",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_first_dates_window_in_past_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 5, 10),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(
            json_body={
                "provider_id": "s1",
                "cadence": "weekly",
                "occurrences": 4,
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-09",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_first_dates_window_exceeds_cap_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(
            json_body={
                "provider_id": "s1",
                "cadence": "weekly",
                "occurrences": 4,
                "search_window_start": "2026-05-01",
                "search_window_end": "2026-09-01",  # 123 days, > 90 cap
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_first_dates_invalid_recurrence_shape_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "recurrence": {"interval": {"value": "not-an-int", "unit": "week"}},
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_first_dates_neither_recurrence_nor_cadence_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-31",
            },
            secrets=_CFD_SECRETS,
        )
        results = api.candidate_first_dates()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_first_dates_fhir_call_count_uses_range_prefill() -> None:
    """Performance smoke. Walk a 14 day window with a daily count 7 rule and
    assert the slot HTTP calls collapse to a single range Slot call covering
    the union of occurrence dates. Without range prefill each candidate
    would issue 7 calls for a total of 98.
    """
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = {"entry": [{"resource": {"id": "Location.1-Staff.s1"}}]}

    slot_calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        slot_calls.append(url)
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"total": 0, "entry": []}
        return resp

    mock_http.get.side_effect = fake_get

    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability.Http",
            return_value=mock_http,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "recurrence": {
                    "interval": {"value": 1, "unit": "day"},
                    "end": {"kind": "count", "count": 7},
                },
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-17",
            },
            secrets=_CFD_SECRETS,
        )
        api.candidate_first_dates()

    # 14 candidate first dates, each spans 7 days, union of occurrence dates
    # is May 4 through May 23. The range prefill collapses that union into
    # one Slot call.
    assert len(slot_calls) == 1
    assert "_count=500" in slot_calls[0]
    # Window padded one day each side of the occurrence union for boundary slots.
    assert "start=2026-05-03" in slot_calls[0]
    assert "end=2026-05-24" in slot_calls[0]


# ---- free-slots endpoint ----


_FS_SECRETS = {
    "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
    "CANVAS_OAUTH_CLIENT_ID": "cid",
    "CANVAS_OAUTH_CLIENT_SECRET": "cs",
}


def test_free_slots_returns_slots_ordered_by_start_with_grouping_keys() -> None:
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot

    mock_staff = MagicMock()
    mock_staff.id = "s1"
    yielded = [
        FreeSlot(start="2026-05-04T09:00:00-04:00", end="2026-05-04T10:00:00-04:00"),
        FreeSlot(start="2026-05-04T11:00:00-04:00", end="2026-05-04T12:00:00-04:00"),
        FreeSlot(start="2026-05-06T08:00:00-04:00", end="2026-05-06T09:00:00-04:00"),
    ]

    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.iter_free_slots",
            return_value=iter(yielded),
        ) as mock_iter,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-10",
                "tz_offset": "240",
                "limit": "10",
            },
            secrets=_FS_SECRETS,
        )
        results = api.free_slots()

    assert len(results) == 1
    body = json.loads(results[0].content)
    assert body["search_window"] == {"start": "2026-05-04", "end": "2026-05-10"}
    assert body["truncated"] is False
    assert body["slots"] == [
        {
            "date": "2026-05-04",
            "hhmm": "09:00",
            "start": "2026-05-04T09:00:00-04:00",
            "end": "2026-05-04T10:00:00-04:00",
        },
        {
            "date": "2026-05-04",
            "hhmm": "11:00",
            "start": "2026-05-04T11:00:00-04:00",
            "end": "2026-05-04T12:00:00-04:00",
        },
        {
            "date": "2026-05-06",
            "hhmm": "08:00",
            "start": "2026-05-06T08:00:00-04:00",
            "end": "2026-05-06T09:00:00-04:00",
        },
    ]
    kwargs = mock_iter.call_args.kwargs
    assert kwargs["window_start"] == date(2026, 5, 4)
    assert kwargs["window_end"] == date(2026, 5, 10)
    # limit + 1 is passed so the endpoint can detect truncation.
    assert kwargs["limit"] == 11


def test_free_slots_truncated_when_limit_reached() -> None:
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot

    mock_staff = MagicMock()
    mock_staff.id = "s1"
    # Yield limit + 1 entries so the endpoint sees the overflow and trims.
    yielded = [
        FreeSlot(start=f"2026-05-04T0{i}:00:00-04:00", end=f"2026-05-04T0{i+1}:00:00-04:00")
        for i in range(3)
    ]

    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.iter_free_slots",
            return_value=iter(yielded),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-10",
                "limit": "2",
            },
            secrets=_FS_SECRETS,
        )
        results = api.free_slots()

    body = json.loads(results[0].content)
    assert body["truncated"] is True
    assert len(body["slots"]) == 2


def test_free_slots_default_limit_is_25() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.iter_free_slots",
            return_value=iter([]),
        ) as mock_iter,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-10",
            },
            secrets=_FS_SECRETS,
        )
        api.free_slots()

    # Default limit is 25, the endpoint passes limit + 1 to the iterator to
    # detect truncation.
    assert mock_iter.call_args.kwargs["limit"] == 26


def test_free_slots_limit_capped_at_100() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.iter_free_slots",
            return_value=iter([]),
        ) as mock_iter,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-10",
                "limit": "500",
            },
            secrets=_FS_SECRETS,
        )
        api.free_slots()

    assert mock_iter.call_args.kwargs["limit"] == 101


def test_free_slots_provider_not_found_returns_404() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None

        api = _make_api(
            query_params={
                "provider_id": "missing",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-10",
            },
            secrets=_FS_SECRETS,
        )
        results = api.free_slots()
    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_free_slots_missing_provider_id_returns_400() -> None:
    api = _make_api(
        query_params={
            "search_window_start": "2026-05-04",
            "search_window_end": "2026-05-10",
        },
        secrets=_FS_SECRETS,
    )
    results = api.free_slots()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_free_slots_window_in_past_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 5, 10),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-09",
            },
            secrets=_FS_SECRETS,
        )
        results = api.free_slots()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_free_slots_window_exceeds_cap_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-09-04",  # > 90 days
            },
            secrets=_FS_SECRETS,
        )
        results = api.free_slots()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_free_slots_empty_yields_empty_list_and_truncated_false() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with (
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.Staff") as mock_staff_cls,
        patch("scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token") as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.iter_free_slots",
            return_value=iter([]),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-04",
                "search_window_end": "2026-05-10",
            },
            secrets=_FS_SECRETS,
        )
        results = api.free_slots()

    body = json.loads(results[0].content)
    assert body["slots"] == []
    assert body["truncated"] is False


# ---- availability-window endpoint ----

_AVW_SECRETS = {
    "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
    "CANVAS_OAUTH_CLIENT_ID": "cid",
    "CANVAS_OAUTH_CLIENT_SECRET": "cs",
}


def test_availability_window_missing_params() -> None:
    api = _make_api(query_params={"provider_id": "s1"})
    results = api.availability_window()
    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_availability_window_provider_not_found() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None
        api = _make_api(query_params={
            "provider_id": "missing",
            "window_start": "2026-05-04",
            "window_end": "2026-05-10",
        })
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_availability_window_invalid_date_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(query_params={
            "provider_id": "s1",
            "window_start": "not-a-date",
            "window_end": "2026-05-10",
        })
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_availability_window_inverted_window_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(query_params={
            "provider_id": "s1",
            "window_start": "2026-05-10",
            "window_end": "2026-05-04",
        })
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_availability_window_too_long_returns_400() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        api = _make_api(query_params={
            "provider_id": "s1",
            "window_start": "2026-05-04",
            "window_end": "2026-06-01",
        })
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_availability_window_invalid_tz_offset_returns_400() -> None:
    api = _make_api(query_params={
        "provider_id": "s1",
        "window_start": "2026-05-04",
        "window_end": "2026-05-10",
        "tz_offset": "not-an-int",
    })
    results = api.availability_window()
    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_availability_window_clamps_past_window_start_to_today() -> None:
    """Past dates inside the requested window are accepted on the request
    boundary, the handler clamps window_start to today before sending to
    Fumage. Verify lookup_window receives the clamped date.
    """
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    captured: dict = {}

    def fake_lookup_window(**kwargs):
        captured.update(kwargs)
        return {}

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.lookup_window",
            side_effect=fake_lookup_window,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 5, 5),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "window_start": "2026-05-01",
                "window_end": "2026-05-10",
                "tz_offset": "240",
            },
            secrets=_AVW_SECRETS,
        )
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.OK
    assert captured["window_start"] == date(2026, 5, 5)
    assert captured["window_end"] == date(2026, 5, 10)
    assert captured["tz_offset_minutes"] == 240

    body = json.loads(results[0].content)
    assert body["window"]["start"] == "2026-05-05"
    assert body["window"]["end"] == "2026-05-10"


def test_availability_window_returns_bucketed_payload() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    bucketed = {
        "2026-05-04": [
            {"hhmm": "09:00", "start": "2026-05-04T09:00:00-04:00", "end": "2026-05-04T10:00:00-04:00"},
            {"hhmm": "10:00", "start": "2026-05-04T10:00:00-04:00", "end": "2026-05-04T11:00:00-04:00"},
        ],
        "2026-05-05": [
            {"hhmm": "13:00", "start": "2026-05-05T13:00:00-04:00", "end": "2026-05-05T14:00:00-04:00"},
        ],
    }

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.lookup_window",
            return_value=bucketed,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "window_start": "2026-05-04",
                "window_end": "2026-05-10",
                "tz_offset": "240",
            },
            secrets=_AVW_SECRETS,
        )
        results = api.availability_window()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.OK
    body = json.loads(results[0].content)
    assert body["by_date"] == bucketed
    assert body["window"] == {"start": "2026-05-04", "end": "2026-05-10"}
    assert body["booked_by_date"] == {}


def test_availability_window_returns_booked_times_bucketed_by_local_date() -> None:
    """Booked appointments come back bucketed by local date and hhmm so a
    moved occurrence can tell a taken time from a closed one."""
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    # 14:00 UTC on 2026-05-04 is 10:00 in EDT (tz_offset 240, UTC-4).
    booked = [datetime(2026, 5, 4, 14, 0, tzinfo=timezone.utc)]

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.lookup_window",
            return_value={},
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 28),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = booked

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "window_start": "2026-05-04",
                "window_end": "2026-05-10",
                "tz_offset": "240",
            },
            secrets=_AVW_SECRETS,
        )
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.OK
    body = json.loads(results[0].content)
    assert body["booked_by_date"] == {"2026-05-04": ["10:00"]}


def test_availability_window_window_entirely_in_the_past_returns_empty() -> None:
    """If every day in the requested window is in the past, clamp pushes
    window_start past window_end. The handler short circuits to an empty
    by_date payload without making a Fumage call.
    """
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.lookup_window"
        ) as mock_lookup,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 5, 20),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "window_start": "2026-05-04",
                "window_end": "2026-05-10",
            },
            secrets=_AVW_SECRETS,
        )
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.OK
    body = json.loads(results[0].content)
    assert body["by_date"] == {}
    mock_lookup.assert_not_called()


# ---- availability_window backend error ----


def test_availability_window_backend_error_returns_502() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("backend down"),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "window_start": "2026-05-04",
                "window_end": "2026-05-10",
            },
            secrets=_AVW_SECRETS,
        )
        results = api.availability_window()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


# ---- static asset endpoints ----


def test_canvas_plugin_ui_css_returns_css_response() -> None:
    api = _make_api()
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.render_to_string",
        return_value="body {}",
    ):
        results = api.canvas_plugin_ui_css()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.OK
    assert results[0].headers.get("Content-Type") == "text/css"


def test_canvas_plugin_ui_js_returns_js_response() -> None:
    api = _make_api()
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.render_to_string",
        return_value="// js",
    ):
        results = api.canvas_plugin_ui_js()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.OK
    assert results[0].headers.get("Content-Type") == "application/javascript"


# ---- scheduling_ui endpoint ----


def test_scheduling_ui_no_patient_id_returns_html() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.render_to_string",
        return_value="<html></html>",
    ):
        api = _make_api(query_params={})
        results = api.scheduling_ui()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.OK


def test_scheduling_ui_with_patient_id_resolves_state_and_name() -> None:
    mock_patient = MagicMock()
    mock_patient.first_name = "Jane"
    mock_patient.last_name = "Doe"
    mock_address = MagicMock()
    mock_address.state_code = "NY"
    mock_patient.addresses.filter.return_value.first.return_value = mock_address

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
        ) as mock_patient_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.render_to_string",
            return_value="<html></html>",
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 5, 1),
        ),
    ):
        mock_patient_cls.objects.filter.return_value.first.return_value = mock_patient

        api = _make_api(query_params={"patient_id": "p1"})
        results = api.scheduling_ui()

    assert results[0].status_code == HTTPStatus.OK


# ---- providers backend error ----


def test_providers_backend_error_returns_502() -> None:
    mock_patient = MagicMock()
    mock_address = MagicMock()
    mock_address.state_code = "CA"
    mock_patient.addresses.filter.return_value.first.return_value = mock_address

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
        ) as mock_patient_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("oauth failed"),
        ),
    ):
        mock_patient_cls.objects.filter.return_value.first.return_value = mock_patient

        api = _make_api(
            query_params={"patient_id": "p1"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


def test_providers_connection_error_returns_502() -> None:
    # Fumage fully unreachable. requests raises a RequestException
    # (ConnectionError, Timeout) rather than the RuntimeError/ValueError that a
    # bad response raises. This is the network failure that escaped the old
    # catch and surfaced as a raw 500. It must route to the clean 502 banner.
    mock_patient = MagicMock()
    mock_address = MagicMock()
    mock_address.state_code = "CA"
    mock_patient.addresses.filter.return_value.first.return_value = mock_address

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Patient"
        ) as mock_patient_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RequestException("connection refused"),
        ),
    ):
        mock_patient_cls.objects.filter.return_value.first.return_value = mock_patient

        api = _make_api(
            query_params={"patient_id": "p1"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


# ---- availability endpoint error cases ----


def test_availability_parse_error_returns_400() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "cadence": "weekly",
                "start_date": "not-a-date",
                "occurrences": "12",
            },
        )
        results = api.availability()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_availability_backend_error_returns_502() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("backend down"),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "cadence": "weekly",
                "start_date": "2026-05-01",
                "occurrences": "4",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.availability()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


# ---- available_times endpoint ----


def test_available_times_missing_params_returns_400() -> None:
    api = _make_api(query_params={"provider_id": "s1"})
    results = api.available_times()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_available_times_provider_not_found_returns_404() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None

        api = _make_api(query_params={"provider_id": "s1", "date": "2026-05-01"})
        results = api.available_times()

    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_available_times_invalid_date_returns_400() -> None:
    mock_staff = MagicMock()

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(query_params={"provider_id": "s1", "date": "not-a-date"})
        results = api.available_times()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_available_times_backend_error_returns_502() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("backend down"),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={"provider_id": "s1", "date": "2026-05-01"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.available_times()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


def test_available_times_success_returns_times() -> None:
    from scheduling_modal_with_recurring_support.services.availability import FreeSlot, SlotAvailability

    mock_staff = MagicMock()
    mock_staff.id = "s1"

    mock_slot_avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[
            FreeSlot(start="2026-05-01T13:00:00Z", end="2026-05-01T13:30:00Z"),
        ],
        is_available=True,
    )

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._check_slot",
            return_value=mock_slot_avail,
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={"provider_id": "s1", "date": "2026-05-01", "tz_offset": "0"},
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.available_times()

    assert results[0].status_code == HTTPStatus.OK
    body = json.loads(results[0].content)
    assert body["date"] == "2026-05-01"
    assert len(body["times"]) == 1


# ---- candidate_times error cases ----


def test_candidate_times_provider_not_found_returns_404() -> None:
    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = None

        api = _make_api(
            query_params={"provider_id": "s1", "start_date": "2026-05-01"},
        )
        results = api.candidate_times()

    assert results[0].status_code == HTTPStatus.NOT_FOUND


def test_candidate_times_parse_error_returns_400() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "start_date": "not-a-date",
                "cadence": "weekly",
                "occurrences": "4",
            },
        )
        results = api.candidate_times()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_times_past_start_date_returns_400() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 6, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "start_date": "2026-05-01",
                "cadence": "weekly",
                "occurrences": "4",
            },
        )
        results = api.candidate_times()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_candidate_times_backend_error_returns_502() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("backend down"),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "start_date": "2026-05-01",
                "cadence": "weekly",
                "occurrences": "4",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.candidate_times()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


# ---- candidate_first_dates backend error ----


def test_candidate_first_dates_backend_error_returns_502() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("backend down"),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "search_window_start": "2026-05-01",
                "search_window_end": "2026-05-31",
                "cadence": "weekly",
                "occurrences": 4,
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.candidate_first_dates()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


# ---- free_slots additional error cases ----


def test_free_slots_invalid_limit_returns_400() -> None:
    api = _make_api(
        query_params={
            "provider_id": "s1",
            "search_window_start": "2026-05-01",
            "search_window_end": "2026-05-07",
            "limit": "abc",
        },
    )
    results = api.free_slots()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(results[0].content)
    assert "limit" in body["error"].lower()


def test_free_slots_inverted_window_returns_400() -> None:
    mock_staff = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-10",
                "search_window_end": "2026-05-01",
            },
        )
        results = api.free_slots()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_free_slots_invalid_date_string_returns_400() -> None:
    mock_staff = MagicMock()

    with patch(
        "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
    ) as mock_staff_cls:
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "not-a-date",
                "search_window_end": "2026-05-07",
            },
        )
        results = api.free_slots()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST


def test_free_slots_backend_error_returns_502() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("backend down"),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 4, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            query_params={
                "provider_id": "s1",
                "search_window_start": "2026-05-01",
                "search_window_end": "2026-05-07",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.free_slots()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


# ---- check_slots additional error cases ----


def test_check_slots_acquire_token_error_returns_502() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RuntimeError("token error"),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [{"date": "2026-05-01", "start_time": "09:00"}],
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.check_slots()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


def test_check_slots_per_slot_check_error_returns_502() -> None:
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
            side_effect=RuntimeError("fhir error"),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [{"date": "2026-05-01", "start_time": "09:00"}],
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.check_slots()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


def test_check_slots_connection_error_returns_502() -> None:
    # check-slots is the live FHIR availability guard that runs immediately
    # before booking. When Fumage is unreachable the schedule resolution call
    # raises a RequestException. It must route to the clean 502 banner rather
    # than a raw 500 so the booking path fails cleanly.
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token",
            side_effect=RequestException("connection refused"),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [{"date": "2026-05-01", "start_time": "09:00"}],
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage.test",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.check_slots()

    assert results[0].status_code == HTTPStatus.BAD_GATEWAY


# ---- _resolve_recurrence_rule ----


def test_resolve_recurrence_rule_non_integer_occurrences_raises() -> None:
    from scheduling_modal_with_recurring_support.services.recurrence import RecurrenceValidationError

    with pytest.raises(RecurrenceValidationError, match="occurrences must be an integer"):
        _resolve_recurrence_rule({"cadence": "weekly", "occurrences": "not-a-number"})


# ---- _backend_error_response ----


def test_backend_error_response_generic_runtime_error_returns_502() -> None:
    with patch("scheduling_modal_with_recurring_support.api.scheduling_api.log"):
        result = _backend_error_response(RuntimeError("some failure"))

    assert result.status_code == HTTPStatus.BAD_GATEWAY
    body = json.loads(result.content)
    assert "backend" in body["error"].lower()


def test_backend_error_response_fhir_schedule_not_found_returns_422() -> None:
    exc = ValueError("No FHIR Schedule found for provider abc")
    with patch("scheduling_modal_with_recurring_support.api.scheduling_api.log"):
        result = _backend_error_response(exc)

    assert result.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    body = json.loads(result.content)
    assert "administrator" in body["error"].lower()


# ---- tz_offset parsing consistency ----
#
# Five endpoints parse tz_offset with a bare int() and surface a 500 on a
# non numeric value. The fix wraps each site with try except returning a 400
# that mirrors the message already used by /availability-window at line 814.


_TZ_OFFSET_BAD_MESSAGE = "We could not read your time zone. Refresh the modal."


def test_available_times_rejects_non_numeric_tz_offset() -> None:
    api = _make_api(
        query_params={
            "provider_id": "s1",
            "date": "2026-05-01",
            "tz_offset": "foo",
        },
    )
    results = api.available_times()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(results[0].content)
    assert body["error"] == _TZ_OFFSET_BAD_MESSAGE


def test_candidate_times_rejects_non_numeric_tz_offset() -> None:
    api = _make_api(
        query_params={
            "provider_id": "s1",
            "start_date": "2026-05-04",
            "cadence": "weekly",
            "occurrences": "4",
            "tz_offset": "foo",
        },
    )
    results = api.candidate_times()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(results[0].content)
    assert body["error"] == _TZ_OFFSET_BAD_MESSAGE


def test_free_slots_rejects_non_numeric_tz_offset() -> None:
    api = _make_api(
        query_params={
            "provider_id": "s1",
            "search_window_start": "2026-05-01",
            "search_window_end": "2026-05-08",
            "tz_offset": "foo",
        },
    )
    results = api.free_slots()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(results[0].content)
    assert body["error"] == _TZ_OFFSET_BAD_MESSAGE


def test_check_slots_rejects_non_numeric_tz_offset() -> None:
    api = _make_api(
        json_body={
            "provider_id": "s1",
            "slots": [{"date": "2026-05-01", "start_time": "09:00"}],
            "tz_offset": "foo",
        },
    )
    results = api.check_slots()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(results[0].content)
    assert body["error"] == _TZ_OFFSET_BAD_MESSAGE


def test_book_rejects_non_numeric_tz_offset() -> None:
    api = _make_api(
        json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "nt1",
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
            "tz_offset": "foo",
        },
    )
    results = api.book()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(results[0].content)
    assert body["error"] == _TZ_OFFSET_BAD_MESSAGE


# ---- /check-slots FHIR fan out ----
#
# /check-slots used to call `_check_slot` once per slot. For a twelve
# occurrence recurrence that was twelve sequential FHIR round trips. The fix
# collects the union of dates, calls `_prefill_memo_for_range` once, and
# reads each slot from the memo. Tests pin the new shape.


def test_check_slots_uses_single_prefill_for_multiple_dates() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        SlotAvailability,
    )

    free_at_10 = [FreeSlot(start="2026-05-01T10:00:00Z", end="2026-05-01T11:00:00Z")]
    free_at_09 = [FreeSlot(start="2026-05-08T09:00:00Z", end="2026-05-08T10:00:00Z")]

    def fake_prefill(memo, fhir_base_url, access_token, schedule_id, dates, *args, **kwargs):
        if date(2026, 5, 1) in dates:
            memo[date(2026, 5, 1)] = SlotAvailability(
                occurrence_date=date(2026, 5, 1),
                available_times=free_at_10,
                is_available=True,
            )
        if date(2026, 5, 8) in dates:
            memo[date(2026, 5, 8)] = SlotAvailability(
                occurrence_date=date(2026, 5, 8),
                available_times=free_at_09,
                is_available=True,
            )

    mock_staff = MagicMock()
    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
            side_effect=fake_prefill,
        ) as mock_prefill,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._check_slot",
        ) as mock_check_slot,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [
                    {"date": "2026-05-01", "start_time": "10:00"},
                    {"date": "2026-05-01", "start_time": "11:00"},
                    {"date": "2026-05-08", "start_time": "09:00"},
                ],
                "tz_offset": 0,
            },
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    # Single prefill call covers both dates. _check_slot is no longer used.
    assert mock_prefill.call_count == 1
    passed_dates = mock_prefill.call_args.args[4]
    assert passed_dates == {date(2026, 5, 1), date(2026, 5, 8)}
    assert mock_check_slot.call_count == 0

    # Response shape is preserved.
    status, body = _parse_check_slots_response(results)
    assert status == HTTPStatus.OK
    assert len(body["results"]) == 3
    by_key = {(r["date"], r["start_time"]): r for r in body["results"]}
    assert by_key[("2026-05-01", "10:00")]["is_free"] is True
    assert by_key[("2026-05-01", "11:00")]["is_free"] is False
    assert by_key[("2026-05-08", "09:00")]["is_free"] is True


def test_check_slots_same_date_duplicates_call_prefill_once() -> None:
    """Twelve occurrences on the same date trigger one prefill, not twelve calls."""
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        SlotAvailability,
    )

    free_at_10 = [FreeSlot(start="2026-05-01T10:00:00Z", end="2026-05-01T11:00:00Z")]

    def fake_prefill(memo, fhir_base_url, access_token, schedule_id, dates, *args, **kwargs):
        memo[date(2026, 5, 1)] = SlotAvailability(
            occurrence_date=date(2026, 5, 1),
            available_times=free_at_10,
            is_available=True,
        )

    mock_staff = MagicMock()
    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
            side_effect=fake_prefill,
        ) as mock_prefill,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._check_slot",
        ) as mock_check_slot,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [
                    {"date": "2026-05-01", "start_time": "10:00"} for _ in range(12)
                ],
                "tz_offset": 0,
            },
            secrets=_CHECK_SLOTS_SECRETS,
        )
        api.check_slots()

    assert mock_prefill.call_count == 1
    assert mock_prefill.call_args.args[4] == {date(2026, 5, 1)}
    assert mock_check_slot.call_count == 0


# ---- Cancelled appointment exclusion in conflict checks ----
#
# The conflict queries in _validate_booking_request and /check-slots Pass 2
# were filtering by provider and time window without excluding rows that
# moved to status `cancelled` or `entered_in_error`. The capacity helper
# already excluded those statuses, so the fix brings the booking path in
# line with the rest of the codebase.


_CANCELLED_STATUSES = ["cancelled", "entered_in_error"]


def test_book_conflict_check_excludes_cancelled_statuses() -> None:
    """The filter chain on _validate_booking_request must exclude cancelled rows."""
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    mock_appt_instance = MagicMock()
    mock_appt_instance.create.return_value = MagicMock()

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect",
            return_value=mock_appt_instance,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.bust_filled_pct"
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        # A cancelled row sits at the same UTC start_time. The .exclude chain
        # must drop it so the booking proceeds.
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [
                {"date": "2026-05-01", "start_time": "10:00"},
            ],
        })
        results = api.book()

    # Pin the exclude call shape.
    exclude_kwargs = mock_appt_model.objects.filter.return_value.exclude.call_args.kwargs
    assert sorted(exclude_kwargs["status__in"]) == sorted(_CANCELLED_STATUSES)

    # The booking should succeed (201) once the cancelled row is excluded.
    resp = results[0]
    assert resp.status_code == HTTPStatus.CREATED


def test_check_slots_pass2_excludes_cancelled_statuses() -> None:
    """The Pass 2 query in /check-slots must exclude cancelled rows."""
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        SlotAvailability,
    )

    fhir_avail = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[FreeSlot(start="2026-05-01T10:00:00Z", end="2026-05-01T11:00:00Z")],
        is_available=True,
    )

    def fake_prefill(memo, fhir_base_url, access_token, schedule_id, dates, *args, **kwargs):
        for d in dates:
            memo[d] = fhir_avail

    # Inline setup mirrors _check_slots_setup but customises the
    # AppointmentModel chain so the test can assert .exclude was called.
    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
            side_effect=fake_prefill,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
    ):
        mock_staff = MagicMock()
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(
            json_body={
                "provider_id": "s1",
                "slots": [{"date": "2026-05-01", "start_time": "10:00"}],
                "tz_offset": 0,
            },
            secrets=_CHECK_SLOTS_SECRETS,
        )
        results = api.check_slots()

    # The exclude chain must drop cancelled and entered_in_error rows.
    exclude_call = mock_appt_model.objects.filter.return_value.exclude.call_args
    assert exclude_call is not None, "/check-slots Pass 2 must call .exclude on the conflict query"
    assert sorted(exclude_call.kwargs["status__in"]) == sorted(_CANCELLED_STATUSES)

    # The slot should still report free because the only matching row is cancelled.
    body = json.loads(results[0].content)
    assert body["results"][0]["is_free"] is True


def test_validate_booking_rejects_non_numeric_tz_offset() -> None:
    from scheduling_modal_with_recurring_support.api.scheduling_api import (
        SchedulingAPI,
        _validate_booking_request,
    )

    api = _make_api(
        json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "nt1",
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
            "tz_offset": "foo",
        },
    )
    api.validate_booking = lambda: SchedulingAPI.validate_booking(api)
    results = api.validate_booking()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(results[0].content)
    assert body["error"] == _TZ_OFFSET_BAD_MESSAGE


# ---- /book and /book/validate honour duration_minutes ----


def _exercise_book(body_overrides, secrets):
    """Run /book with the given body overrides and secrets, capture the
    AppointmentEffect kwargs (specifically duration_minutes) that the handler
    passed.
    """
    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"
    mock_appt_instance = MagicMock()
    mock_appt_instance.create.return_value = MagicMock()

    body = {
        "patient_id": "p1",
        "provider_id": "s1",
        "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
        "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
    }
    body.update(body_overrides)

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentEffect",
            return_value=mock_appt_instance,
        ) as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.bust_filled_pct"
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.values_list.return_value = []

        api = _make_api(json_body=body, secrets=secrets)
        api.book()

    return mock_appt_cls.call_args.kwargs["duration_minutes"]


def test_book_writes_appointment_effect_with_request_duration() -> None:
    assert _exercise_book({"duration_minutes": 30}, {}) == 30


def test_book_falls_back_to_secret_when_body_missing_duration() -> None:
    assert _exercise_book({}, {"DEFAULT_APPOINTMENT_DURATION_MINUTES": "45"}) == 45


def test_book_falls_back_to_60_when_secret_and_body_missing() -> None:
    assert _exercise_book({}, {}) == 60


def test_book_falls_back_when_body_duration_invalid() -> None:
    body_overrides = {"duration_minutes": "abc"}
    secrets = {"DEFAULT_APPOINTMENT_DURATION_MINUTES": "45"}
    assert _exercise_book(body_overrides, secrets) == 45


def test_book_validate_accepts_duration_in_body() -> None:
    from scheduling_modal_with_recurring_support.api.scheduling_api import SchedulingAPI

    mock_staff = MagicMock()
    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.AppointmentModel"
        ) as mock_appt_model,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location
        mock_appt_model.objects.filter.return_value.exclude.return_value.values_list.return_value = []

        api = _make_api(json_body={
            "patient_id": "p1",
            "provider_id": "s1",
            "note_type_id": "a1b2c3d4-0000-0000-0000-000000000042",
            "appointments": [{"date": "2026-05-01", "start_time": "09:00"}],
            "duration_minutes": 30,
        })
        api.validate_booking = lambda: SchedulingAPI.validate_booking(api)
        results = api.validate_booking()

    assert len(results) == 1
    assert results[0].status_code == HTTPStatus.OK


# ---- slot endpoints honour duration_minutes ----

_DUR_SECRETS_BASE = {
    "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
    "CANVAS_OAUTH_CLIENT_ID": "cid",
    "CANVAS_OAUTH_CLIENT_SECRET": "cs",
}


def _exercise_availability_window(duration_value, secrets):
    """Run /availability-window with the given duration query param and secrets,
    capture the duration_minutes that landed on the inner lookup_window call.
    """
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    captured: dict = {}

    def fake_lookup_window(**kwargs):
        captured.update(kwargs)
        return {}

    qp = {
        "provider_id": "s1",
        "window_start": "2026-05-04",
        "window_end": "2026-05-10",
        "tz_offset": "0",
    }
    if duration_value is not None:
        qp["duration_minutes"] = duration_value

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.lookup_window",
            side_effect=fake_lookup_window,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 5, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        api = _make_api(query_params=qp, secrets=secrets)
        api.availability_window()

    return captured["duration_minutes"]


def test_availability_window_passes_request_duration_to_lookup() -> None:
    assert _exercise_availability_window("30", dict(_DUR_SECRETS_BASE)) == 30


def test_availability_window_falls_back_to_secret_when_request_missing() -> None:
    secrets = dict(_DUR_SECRETS_BASE, DEFAULT_APPOINTMENT_DURATION_MINUTES="45")
    assert _exercise_availability_window(None, secrets) == 45


def test_availability_window_falls_back_to_60_when_secret_and_request_missing() -> None:
    assert _exercise_availability_window(None, dict(_DUR_SECRETS_BASE)) == 60


def _exercise_check_slots(duration_value, secrets):
    """Run /check-slots and capture the duration_minutes that landed on the
    inner _prefill_memo_for_range call.
    """
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    captured: dict = {}

    def fake_prefill(memo, fhir_base_url, access_token, schedule_id, dates, duration_minutes=60, *args, **kwargs):
        captured["duration_minutes"] = duration_minutes

    body = {
        "provider_id": "s1",
        "slots": [{"date": "2026-05-04", "start_time": "09:00"}],
        "tz_offset": 0,
    }
    if duration_value is not None:
        body["duration_minutes"] = duration_value

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value="sched-1",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
            side_effect=fake_prefill,
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        api = _make_api(json_body=body, secrets=secrets)
        api.check_slots()

    return captured["duration_minutes"]


def test_check_slots_passes_request_duration_to_inner_helper() -> None:
    assert _exercise_check_slots(30, dict(_DUR_SECRETS_BASE)) == 30


def test_check_slots_falls_back_to_secret_when_request_missing() -> None:
    secrets = dict(_DUR_SECRETS_BASE, DEFAULT_APPOINTMENT_DURATION_MINUTES="45")
    assert _exercise_check_slots(None, secrets) == 45


def test_check_slots_falls_back_to_60_when_secret_and_request_missing() -> None:
    assert _exercise_check_slots(None, dict(_DUR_SECRETS_BASE)) == 60


def _exercise_candidate_first_dates(duration_value, secrets):
    """Run /candidate-first-dates and capture the duration_minutes that landed
    on the inner aggregate_by_first_date call.
    """
    mock_staff = MagicMock()
    mock_staff.id = "s1"

    captured: dict = {}

    def fake_aggregate(**kwargs):
        captured.update(kwargs)
        return []

    body = {
        "provider_id": "s1",
        "search_window_start": "2026-05-04",
        "search_window_end": "2026-05-10",
        "cadence": "weekly",
        "occurrences": 1,
    }
    if duration_value is not None:
        body["duration_minutes"] = duration_value

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.aggregate_by_first_date",
            side_effect=fake_aggregate,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 5, 1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.first.return_value = mock_staff
        mock_token.return_value = MagicMock(access_token="tok")
        api = _make_api(json_body=body, secrets=secrets)
        api.candidate_first_dates()

    return captured["duration_minutes"]


def test_candidate_first_dates_passes_request_duration_to_inner_helper() -> None:
    assert _exercise_candidate_first_dates(30, dict(_DUR_SECRETS_BASE)) == 30


def test_candidate_first_dates_falls_back_to_secret_when_request_missing() -> None:
    secrets = dict(_DUR_SECRETS_BASE, DEFAULT_APPOINTMENT_DURATION_MINUTES="45")
    assert _exercise_candidate_first_dates(None, secrets) == 45


def test_candidate_first_dates_falls_back_to_60_when_secret_and_request_missing() -> None:
    assert _exercise_candidate_first_dates(None, dict(_DUR_SECRETS_BASE)) == 60


# ---- /providers date aware ranking branch ----


def test_providers_endpoint_ranks_by_series_when_start_date_given() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        ProviderSeriesSummary,
    )

    ranked = [
        ProviderSeriesSummary(
            id="s1",
            full_name="Dr. Open",
            npi_number="111",
            series_available_count=5,
            series_total_count=5,
            best_hhmm="09:00",
            has_capacity=True,
            tier="recommended",
        ),
        ProviderSeriesSummary(
            id="s2",
            full_name="Dr. Closed",
            npi_number="222",
            series_available_count=0,
            series_total_count=5,
            best_hhmm="",
            has_capacity=False,
            tier="other",
        ),
    ]

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.providers_ranked_by_series_availability",
            return_value=ranked,
        ) as mock_ranked,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
        ) as mock_load,
    ):
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "patient_id": "p1",
                "start_date": "2099-01-05",
                "cadence": "weekly",
                "occurrences": "5",
                "duration_minutes": "60",
                "tz_offset": "240",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    # The date aware path is taken, the load path is never touched.
    mock_ranked.assert_called_once()
    assert mock_ranked.call_args.args[0] == "CA"
    assert mock_ranked.call_args.kwargs["duration_minutes"] == 60
    assert mock_ranked.call_args.kwargs["tz_offset_minutes"] == 240
    mock_load.assert_not_called()

    body = json.loads(results[0].content)
    assert body["ranking_basis"] == "series"
    assert [p["id"] for p in body["providers"]] == ["s1", "s2"]
    assert body["providers"][0]["series_available_count"] == 5
    assert body["providers"][0]["best_hhmm"] == "09:00"
    assert "pct_filled" not in body["providers"][0]


def test_providers_endpoint_ranks_with_canonical_recurrence_param() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        ProviderSeriesSummary,
    )
    from scheduling_modal_with_recurring_support.services.recurrence import (
        RecurrenceUnit,
        Weekday,
    )

    ranked = [
        ProviderSeriesSummary(
            id="s1",
            full_name="Dr. Open",
            npi_number="111",
            series_available_count=4,
            series_total_count=6,
            best_hhmm="10:00",
            has_capacity=True,
            tier="recommended",
        ),
    ]

    # A custom every-two-weeks-on-Mon-and-Wed rule cannot be expressed as a
    # legacy cadence string, so it arrives as the canonical JSON shape.
    recurrence = {
        "interval": {"value": 2, "unit": "week"},
        "end": {"kind": "count", "count": 6},
        "weekdays": ["MO", "WE"],
    }

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.providers_ranked_by_series_availability",
            return_value=ranked,
        ) as mock_ranked,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
        ) as mock_load,
    ):
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "patient_id": "p1",
                "start_date": "2099-01-05",
                "recurrence": json.dumps(recurrence),
                "duration_minutes": "45",
                "tz_offset": "300",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    mock_ranked.assert_called_once()
    mock_load.assert_not_called()
    passed_rule = mock_ranked.call_args.kwargs["rule"]
    assert passed_rule.interval.value == 2
    assert passed_rule.interval.unit == RecurrenceUnit.WEEK
    assert passed_rule.weekdays == (Weekday.MO, Weekday.WE)
    assert mock_ranked.call_args.kwargs["duration_minutes"] == 45

    body = json.loads(results[0].content)
    assert body["ranking_basis"] == "series"
    assert body["providers"][0]["series_available_count"] == 4


def test_providers_endpoint_ranked_rejects_past_start_date() -> None:
    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.providers_ranked_by_series_availability",
        ) as mock_ranked,
    ):
        api = _make_api(
            query_params={
                "patient_id": "p1",
                "start_date": "2000-01-01",
                "cadence": "weekly",
                "occurrences": "5",
            },
            secrets={"CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com"},
        )
        results = api.providers()

    assert results[0].status_code == HTTPStatus.BAD_REQUEST
    mock_ranked.assert_not_called()


def test_providers_endpoint_load_basis_when_no_start_date() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import ProviderSummary

    summaries = [
        ProviderSummary(
            id="s1",
            full_name="Dr. X",
            npi_number="111",
            pct_filled=25.0,
            filled_count=2,
            free_count=6,
            total_count=8,
            has_capacity=True,
            appointments_last_30_days=5,
            upcoming_7_days=2,
            tier="recommended",
        ),
    ]

    mock_location = MagicMock()
    mock_location.id = "loc-1"

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.PracticeLocation"
        ) as mock_loc_cls,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.licensed_providers_for_state",
            return_value=summaries,
        ),
    ):
        mock_token.return_value = MagicMock(access_token="tok")
        mock_loc_cls.objects.filter.return_value.first.return_value = mock_location

        api = _make_api(
            query_params={"patient_id": "p1"},
            secrets={"CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com"},
        )
        results = api.providers()

    body = json.loads(results[0].content)
    assert body["ranking_basis"] == "load"


def test_providers_ranked_passes_now_to_scorer() -> None:
    """The date aware provider ranking forwards the request clock so the card
    open label drops slots elapsed today."""
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        ProviderSeriesSummary,
    )

    fixed_now = datetime(2026, 6, 24, 20, 0, tzinfo=timezone.utc)
    ranked = [
        ProviderSeriesSummary(
            id="s1",
            full_name="Dr. Open",
            npi_number="111",
            series_available_count=0,
            series_total_count=1,
            best_hhmm="",
            has_capacity=False,
            tier="other",
        ),
    ]

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.providers_ranked_by_series_availability",
            return_value=ranked,
        ) as mock_ranked,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=fixed_now,
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=fixed_now.date(),
        ),
    ):
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(
            query_params={
                "patient_id": "p1",
                "start_date": "2026-06-24",
                "cadence": "single",
                "occurrences": "1",
                "duration_minutes": "60",
                "tz_offset": "240",
            },
            secrets={
                "CANVAS_FHIR_BASE_URL": "https://fumage-test.canvasmedical.com",
                "CANVAS_OAUTH_CLIENT_ID": "cid",
                "CANVAS_OAUTH_CLIENT_SECRET": "cs",
            },
        )
        results = api.providers()

    mock_ranked.assert_called_once()
    assert mock_ranked.call_args.kwargs["now"] == fixed_now
    body = json.loads(results[0].content)
    assert body["providers"][0]["series_available_count"] == 0


def test_candidate_first_dates_agnostic_passes_now_to_coverage() -> None:
    """The provider agnostic calendar badge forwards the request clock so a
    today cell drops to zero once its slots elapse."""
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        FirstDateCoverage,
    )

    fixed_now = datetime(2026, 6, 24, 20, 0, tzinfo=timezone.utc)
    coverage = [
        FirstDateCoverage(
            first_date=date(2026, 6, 24), covering_count=0, candidate_count=2
        ),
    ]

    with (
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._resolve_patient_state",
            return_value=PatientStateResult(state="CA", error=""),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.acquire_token"
        ) as mock_token,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api.providers_covering_series_by_first_date",
            return_value=coverage,
        ) as mock_cover,
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._today",
            return_value=date(2026, 6, 24),
        ),
        patch(
            "scheduling_modal_with_recurring_support.api.scheduling_api._now",
            return_value=fixed_now,
        ),
    ):
        mock_token.return_value = MagicMock(access_token="tok")

        api = _make_api(json_body={
            "patient_id": "p1",
            "recurrence": {
                "interval": {"value": 1, "unit": "week"},
                "end": {"kind": "count", "count": 1},
            },
            "search_window_start": "2026-06-24",
            "search_window_end": "2026-06-24",
            "tz_offset": 240,
        })
        results = api.candidate_first_dates()

    mock_cover.assert_called_once()
    assert mock_cover.call_args.kwargs["now"] == fixed_now
    body = json.loads(results[0].content)
    assert body["candidates"][0]["covering_count"] == 0
