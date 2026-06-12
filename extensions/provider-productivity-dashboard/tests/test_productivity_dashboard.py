# Tests for the Provider Productivity Dashboard plugin.
# Run with: uv run pytest

import datetime
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import arrow
import pytest

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.test_utils.factories import (
    NoteFactory,
    NoteStateChangeEventFactory,
    NoteTypeFactory,
    PatientFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.billing import BillingLineItem, BillingLineItemStatus
from canvas_sdk.v1.data.note import NoteStates, NoteTypeCategories

from provider_productivity_dashboard.applications.productivity_dashboard import (
    DME_KEYWORDS,
    EXCLUDED_CATEGORIES,
    OPEN_STATES,
    SIGNED_STATES,
    VISIBLE_STATES,
    ProductivityDashboardApi,
    ProductivityDashboardApplication,
    _format_duration,
    _get_date_range,
    _is_dme_referral,
)


def _mock_visible_note_ids(mock_state_cls: MagicMock, note_ids: list[int], state_events: list | None = None) -> None:
    """Set up CurrentNoteStateEvent mock to support both the visible_note_ids query chain
    and the state_map iteration used in get_patients."""
    visible_qs = MagicMock()
    visible_qs.exclude.return_value = visible_qs
    visible_qs.values_list.return_value = note_ids

    state_events = state_events or []

    def filter_side_effect(**kwargs):
        if "state__in" in kwargs and kwargs["state__in"] == VISIBLE_STATES:
            return visible_qs
        # For state_map iteration in get_patients (note_id__in=...)
        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter(state_events))
        mock_qs.count.return_value = 0
        return mock_qs

    mock_state_cls.objects.filter = MagicMock(side_effect=filter_side_effect)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(period: str = "day", staff_id: str = "staff-001", cpt: str = "") -> MagicMock:
    """Build a mock request object."""
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": staff_id}
    request.query_params = {"period": period, "cpt": cpt}
    return request


def _make_api(
    period: str = "day",
    staff_id: str = "staff-001",
    cpt: str = "",
    provider_id: str = "",
    secrets: dict | None = None,
) -> ProductivityDashboardApi:
    """Instantiate the API handler with a mocked request."""
    api = ProductivityDashboardApi.__new__(ProductivityDashboardApi)
    request = _make_request(period=period, staff_id=staff_id, cpt=cpt)
    if provider_id:
        request.query_params["provider_id"] = provider_id
    api.request = request
    api.secrets = secrets or {}
    return api


# ---------------------------------------------------------------------------
# _is_admin and _resolve_staff_id tests
# ---------------------------------------------------------------------------

class TestResolveStaffId:
    def test_returns_own_id_when_no_override(self):
        api = _make_api(staff_id="staff-001")
        assert api._resolve_staff_id() == "staff-001"

    def test_returns_requested_id_when_provided(self):
        api = _make_api(staff_id="staff-001", provider_id="staff-002")
        assert api._resolve_staff_id() == "staff-002"

    def test_returns_all_when_requested(self):
        api = _make_api(staff_id="staff-001", provider_id="all")
        assert api._resolve_staff_id() == "all"

    def test_get_visible_note_ids_filters_by_provider(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state:
            mock_qs = MagicMock()
            mock_state.objects.filter.return_value = mock_qs
            mock_qs.exclude.return_value = mock_qs
            mock_qs.values_list.return_value = [1, 2]
            result = api._get_visible_note_ids("staff-001", "2026-01-01", "2026-01-02")
            call_kwargs = mock_state.objects.filter.call_args[1]
            assert "note__provider__id" in call_kwargs
            assert call_kwargs["note__provider__id"] == "staff-001"
            assert result == [1, 2]

    def test_get_visible_note_ids_skips_provider_filter_for_all(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state:
            mock_qs = MagicMock()
            mock_state.objects.filter.return_value = mock_qs
            mock_qs.exclude.return_value = mock_qs
            mock_qs.values_list.return_value = [1, 2, 3]
            result = api._get_visible_note_ids("all", "2026-01-01", "2026-01-02")
            call_kwargs = mock_state.objects.filter.call_args[1]
            assert "note__provider__id" not in call_kwargs
            assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_providers tests
# ---------------------------------------------------------------------------

class TestGetProviders:
    def test_returns_all_providers_for_any_user(self):
        api = _make_api(staff_id="staff-003", secrets={})
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Staff"
        ) as mock_staff:
            mock_s = MagicMock()
            mock_s.id = "staff-002"
            mock_s.credentialed_name = "Dr. Smith"
            mock_staff.objects.filter.return_value.order_by.return_value = [mock_s]
            results = api.get_providers()

        import json
        body = json.loads(results[0].content)
        assert body["logged_in_staff_id"] == "staff-003"
        assert len(body["providers"]) == 1
        assert body["providers"][0]["name"] == "Dr. Smith"


# ---------------------------------------------------------------------------
# _get_date_range unit tests
# ---------------------------------------------------------------------------

class TestGetDateRange:
    def test_day_range_covers_today(self):
        start, end = _get_date_range("day")
        now = arrow.now()
        assert start.date() == now.date()
        assert end.date() == now.date()

    def test_week_range_starts_on_monday(self):
        start, end = _get_date_range("week")
        # Monday = weekday 0
        assert start.weekday() == 0

    def test_week_range_ends_today(self):
        start, end = _get_date_range("week")
        now = arrow.now()
        assert end.date() == now.date()

    def test_month_range_starts_on_first(self):
        start, end = _get_date_range("month")
        assert start.day == 1

    def test_month_range_ends_today(self):
        start, end = _get_date_range("month")
        now = arrow.now()
        assert end.date() == now.date()

    def test_unknown_period_defaults_to_day(self):
        start, end = _get_date_range("unknown_period")
        now = arrow.now()
        assert start.date() == now.date()

    def test_quarter_range_starts_on_quarter_first(self):
        start, end = _get_date_range("quarter")
        assert start.month in (1, 4, 7, 10)
        assert start.day == 1

    def test_quarter_range_ends_today(self):
        start, end = _get_date_range("quarter")
        now = arrow.now()
        assert end.date() == now.date()

    def test_year_range_starts_on_jan_first(self):
        start, end = _get_date_range("year")
        assert start.month == 1
        assert start.day == 1

    def test_year_range_ends_today(self):
        start, end = _get_date_range("year")
        now = arrow.now()
        assert end.date() == now.date()

    def test_start_before_end_all_periods(self):
        for period in ("day", "week", "month", "quarter", "year"):
            start, end = _get_date_range(period)
            assert start <= end


# ---------------------------------------------------------------------------
# ProductivityDashboardApplication tests
# ---------------------------------------------------------------------------

class TestProductivityDashboardApplication:
    def test_on_open_returns_launch_modal_effect(self):
        app = ProductivityDashboardApplication.__new__(ProductivityDashboardApplication)
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.render_to_string",
            return_value="<html>dashboard</html>",
        ):
            result = app.on_open()

        # Should return a single effect dict (from .apply())
        assert result is not None
        # The applied effect has a type field
        assert result.type is not None

    def test_on_open_uses_dashboard_template(self):
        app = ProductivityDashboardApplication.__new__(ProductivityDashboardApplication)
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.render_to_string",
        ) as mock_render:
            mock_render.return_value = "<html></html>"
            app.on_open()
            mock_render.assert_called_once_with("templates/dashboard.html")


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_metrics tests
# ---------------------------------------------------------------------------

class TestGetMetrics:
    def _setup_mocks(self, mock_note, mock_billing, mock_state, visible_ids, patients_count=0, cpt_rows=None, signed=0, open_count=0, mock_protocol=None, care_gaps_open=0, care_gaps_closed=0):
        """Set up mocks for the new visible-notes-first query flow."""
        # Step 1: CurrentNoteStateEvent visible_note_ids query
        visible_qs = MagicMock()
        visible_qs.exclude.return_value = visible_qs
        visible_qs.values_list.return_value = visible_ids

        # Step 2+4: Also handle signed/open count queries
        signed_qs = MagicMock()
        signed_qs.count.return_value = signed
        open_qs = MagicMock()
        open_qs.count.return_value = open_count

        call_count = [0]
        def state_filter_side_effect(**kwargs):
            if "state__in" in kwargs and kwargs["state__in"] == VISIBLE_STATES:
                return visible_qs
            call_count[0] += 1
            if call_count[0] == 1:
                return signed_qs
            return open_qs

        mock_state.objects.filter.side_effect = state_filter_side_effect

        # Step 2: Note.objects.filter(dbid__in=visible_ids)
        mock_note_qs = MagicMock()
        mock_note.objects.filter.return_value = mock_note_qs
        # base_notes.exclude(patient__isnull=True) returns the same queryset
        mock_note_qs.exclude.return_value = mock_note_qs
        mock_note_qs.values.return_value.distinct.return_value.count.return_value = patients_count
        mock_note_qs.values_list.return_value.distinct.return_value = ["patient-1"]
        mock_note_qs.__iter__ = MagicMock(return_value=iter([]))

        # Step 3: BillingLineItem
        mock_billing_qs = MagicMock()
        mock_billing.objects.filter.return_value = mock_billing_qs
        mock_billing_qs.values.return_value = mock_billing_qs
        mock_billing_qs.annotate.return_value = mock_billing_qs
        mock_billing_qs.order_by.return_value = cpt_rows or []

        # Step 5: ProtocolCurrent for care gaps
        if mock_protocol is not None:
            protocol_call_count = [0]
            def protocol_filter_side_effect(**kwargs):
                protocol_call_count[0] += 1
                qs = MagicMock()
                if protocol_call_count[0] == 1:
                    qs.count.return_value = care_gaps_open
                else:
                    qs.count.return_value = care_gaps_closed
                return qs
            mock_protocol.objects.filter.side_effect = protocol_filter_side_effect

    def _patch_all(self):
        """Context manager that patches Note, BillingLineItem, CurrentNoteStateEvent, ProtocolCurrent, and NoteStateChangeEvent."""
        from contextlib import contextmanager
        @contextmanager
        def _cm():
            with patch(
                "provider_productivity_dashboard.applications.productivity_dashboard.Note"
            ) as mock_note, patch(
                "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
            ) as mock_billing, patch(
                "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
            ) as mock_state, patch(
                "provider_productivity_dashboard.applications.productivity_dashboard.ProtocolCurrent"
            ) as mock_protocol, patch(
                "provider_productivity_dashboard.applications.productivity_dashboard.NoteStateChangeEvent"
            ) as mock_nsce:
                # Default: no sign events (avg_time_to_close = "—")
                nsce_qs = MagicMock()
                mock_nsce.objects.filter.return_value = nsce_qs
                nsce_qs.select_related.return_value = nsce_qs
                nsce_qs.order_by.return_value = []
                yield mock_note, mock_billing, mock_state, mock_protocol, mock_nsce
        return _cm()

    def test_returns_json_response(self):
        api = _make_api()
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[1, 2, 3], patients_count=3,
                cpt_rows=[{"cpt": "99213", "description": "Office visit", "count": 2}],
                signed=2, open_count=1,
                mock_protocol=mock_protocol)
            results = api.get_metrics()

        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.OK

    def test_metrics_period_day_in_response(self):
        api = _make_api(period="day")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state, visible_ids=[],
                mock_protocol=mock_protocol)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert body["period"] == "day"

    def test_metrics_week_period_passed(self):
        api = _make_api(period="week")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[1, 2, 3, 4, 5], patients_count=5,
                mock_protocol=mock_protocol)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert body["period"] == "week"
        assert body["patients_seen"] == 5

    def test_metrics_includes_notes_total(self):
        api = _make_api(period="day")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[1, 2, 3], patients_count=2,
                signed=2, open_count=1,
                mock_protocol=mock_protocol)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert body["notes_signed"] == 2
        assert body["notes_open"] == 1
        assert body["notes_total"] == 3

    def test_metrics_includes_unsigned_notes_count(self):
        api = _make_api(period="day")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[1, 2, 3], patients_count=2,
                signed=2, open_count=1,
                mock_protocol=mock_protocol)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert "unsigned_notes" in body
        assert body["unsigned_notes"] == 1

    def test_metrics_includes_care_gaps(self):
        api = _make_api(period="day")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[1, 2], patients_count=2,
                mock_protocol=mock_protocol,
                care_gaps_open=5, care_gaps_closed=3)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert body["care_gaps_open"] == 5
        assert body["care_gaps_closed"] == 3

    def test_metrics_care_gaps_zero_when_no_protocols(self):
        api = _make_api(period="day")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[], patients_count=0,
                mock_protocol=mock_protocol,
                care_gaps_open=0, care_gaps_closed=0)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert body["care_gaps_open"] == 0
        assert body["care_gaps_closed"] == 0

    def test_metrics_care_gaps_all_providers_scoped_to_period_patients(self):
        api = _make_api(period="day", provider_id="all")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[1, 2, 3], patients_count=3,
                mock_protocol=mock_protocol,
                care_gaps_open=10, care_gaps_closed=7)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert body["care_gaps_open"] == 10
        assert body["care_gaps_closed"] == 7
        # Even for "all", both care-gap queries are scoped to the patients seen in
        # the period so the counts track the selected time window.
        assert mock_protocol.objects.filter.call_args_list, "ProtocolCurrent was never queried"
        for call in mock_protocol.objects.filter.call_args_list:
            assert "patient__id__in" in call.kwargs

    def test_metrics_avg_time_to_close_dash_when_no_signed(self):
        api = _make_api(period="day")
        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[], patients_count=0,
                mock_protocol=mock_protocol)
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        assert body["avg_time_to_close"] == "\u2014"

    def test_metrics_avg_time_to_close_with_signed_notes(self):
        api = _make_api(period="day")

        # Create mock notes with created timestamps
        mock_note_1 = MagicMock()
        mock_note_1.dbid = 1
        mock_note_1.created = datetime.datetime(2026, 4, 13, 8, 0, tzinfo=datetime.timezone.utc)
        mock_note_2 = MagicMock()
        mock_note_2.dbid = 2
        mock_note_2.created = datetime.datetime(2026, 4, 13, 9, 0, tzinfo=datetime.timezone.utc)

        # Create sign events
        sign_evt_1 = MagicMock()
        sign_evt_1.note_id = 1
        sign_evt_1.created = datetime.datetime(2026, 4, 13, 10, 0, tzinfo=datetime.timezone.utc)  # 2h after note
        sign_evt_2 = MagicMock()
        sign_evt_2.note_id = 2
        sign_evt_2.created = datetime.datetime(2026, 4, 13, 13, 0, tzinfo=datetime.timezone.utc)  # 4h after note

        with self._patch_all() as (mock_note, mock_billing, mock_state, mock_protocol, mock_nsce):
            self._setup_mocks(mock_note, mock_billing, mock_state,
                visible_ids=[1, 2], patients_count=2, signed=2, open_count=0,
                mock_protocol=mock_protocol)
            # Override note iteration to return our mock notes
            mock_note.objects.filter.return_value.__iter__ = MagicMock(return_value=iter([mock_note_1, mock_note_2]))
            # Override NoteStateChangeEvent to return sign events
            nsce_qs = MagicMock()
            mock_nsce.objects.filter.return_value = nsce_qs
            nsce_qs.select_related.return_value = nsce_qs
            nsce_qs.order_by.return_value = [sign_evt_1, sign_evt_2]
            results = api.get_metrics()

        import json
        body = json.loads(results[0].content)
        # Average: (2h + 4h) / 2 = 3h 0m
        assert body["avg_time_to_close"] == "3h 0m"


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_medications tests
# ---------------------------------------------------------------------------

class TestGetMedications:
    MODULE = "provider_productivity_dashboard.applications.productivity_dashboard"

    def _mock_med_qs(self, mock_med, meds_list):
        mock_qs = MagicMock()
        mock_med.objects.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.order_by.return_value = meds_list
        return mock_qs

    def test_returns_json_response(self):
        api = _make_api(provider_id="all")
        with patch(f"{self.MODULE}.Medication") as mock_med:
            self._mock_med_qs(mock_med, [])
            results = api.get_medications()

        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.OK

    def test_empty_medications(self):
        api = _make_api(provider_id="all")
        with patch(f"{self.MODULE}.Medication") as mock_med:
            self._mock_med_qs(mock_med, [])
            results = api.get_medications()

        import json
        body = json.loads(results[0].content)
        assert body["medications"] == []
        assert body["count"] == 0

    def test_medications_with_data(self):
        api = _make_api(period="week", provider_id="all")

        mock_patient = MagicMock()
        mock_patient.id = "patient-uuid-1"
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Doe"
        mock_patient.nickname = ""

        mock_coding = MagicMock()
        mock_coding.display = "Lisinopril 10mg"

        mock_med_obj = MagicMock()
        mock_med_obj.patient = mock_patient
        mock_med_obj.start_date = datetime.datetime(2026, 4, 11, 14, 0)
        mock_med_obj.codings.all.return_value = [mock_coding]

        with patch(f"{self.MODULE}.Medication") as mock_med:
            self._mock_med_qs(mock_med, [mock_med_obj])
            results = api.get_medications()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert body["medications"][0]["patient_name"] == "Jane Doe"
        assert body["medications"][0]["medication_name"] == "Lisinopril 10mg"
        assert "Apr 11, 2026" in body["medications"][0]["date_prescribed"]

    def test_medications_skips_null_patient(self):
        api = _make_api(provider_id="all")

        mock_med_obj = MagicMock()
        mock_med_obj.patient = None

        with patch(f"{self.MODULE}.Medication") as mock_med:
            self._mock_med_qs(mock_med, [mock_med_obj])
            results = api.get_medications()

        import json
        body = json.loads(results[0].content)
        assert body["medications"] == []

    def test_medications_unknown_when_no_codings(self):
        api = _make_api(provider_id="all")

        mock_patient = MagicMock()
        mock_patient.id = "patient-uuid-1"
        mock_patient.first_name = "John"
        mock_patient.last_name = "Smith"
        mock_patient.nickname = ""

        mock_med_obj = MagicMock()
        mock_med_obj.patient = mock_patient
        mock_med_obj.start_date = datetime.datetime(2026, 4, 11, 14, 0)
        mock_med_obj.codings.all.return_value = []

        with patch(f"{self.MODULE}.Medication") as mock_med:
            self._mock_med_qs(mock_med, [mock_med_obj])
            results = api.get_medications()

        import json
        body = json.loads(results[0].content)
        assert body["medications"][0]["medication_name"] == "Unknown Medication"

    def test_medications_filtered_by_provider(self):
        api = _make_api(provider_id="staff-001")
        with patch(f"{self.MODULE}.Medication") as mock_med, \
             patch(f"{self.MODULE}.CurrentNoteStateEvent") as mock_state, \
             patch(f"{self.MODULE}.Note") as mock_note:
            _mock_visible_note_ids(mock_state, [1])
            mock_note.objects.filter.return_value.values_list.return_value.distinct.return_value = ["patient-1"]
            self._mock_med_qs(mock_med, [])
            results = api.get_medications()

        # Should have filtered by patient__id__in
        call_kwargs = mock_med.objects.filter.call_args[1]
        assert "patient__id__in" in call_kwargs


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_patients tests
# ---------------------------------------------------------------------------

class TestGetPatients:
    def _mock_note_qs(self, mock_note, notes_list):
        """Set up the Note queryset mock chain, returning notes_list as the iterable."""
        mock_qs = MagicMock()
        mock_note.objects.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = notes_list
        return mock_qs

    def test_returns_json_response(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ):
            _mock_visible_note_ids(mock_state, [])
            self._mock_note_qs(mock_note, [])
            results = api.get_patients()

        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.OK

    def test_empty_notes_list(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ):
            _mock_visible_note_ids(mock_state, [])
            self._mock_note_qs(mock_note, [])
            results = api.get_patients()

        import json
        body = json.loads(results[0].content)
        assert body["notes"] == []

    def test_notes_list_with_data(self):
        api = _make_api(period="week")
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ) as mock_billing:
            mock_patient = MagicMock()
            mock_patient.id = "patient-uuid-1"
            mock_patient.first_name = "Jane"
            mock_patient.last_name = "Doe"
            mock_patient.nickname = ""

            mock_note_obj = MagicMock()
            mock_note_obj.patient = mock_patient
            mock_note_obj.dbid = 1
            mock_note_obj.datetime_of_service = datetime.datetime(2026, 3, 23, 10, 0)

            mock_state_event = MagicMock()
            mock_state_event.note_id = 1
            mock_state_event.state = NoteStates.NEW

            _mock_visible_note_ids(mock_state, [1], state_events=[mock_state_event])
            self._mock_note_qs(mock_note, [mock_note_obj])

            mock_billing_qs = MagicMock()
            mock_billing.objects.filter.return_value = mock_billing_qs
            mock_billing_qs.values_list.return_value = [(1, "99213")]

            results = api.get_patients()

        import json
        body = json.loads(results[0].content)
        assert len(body["notes"]) == 1
        assert body["notes"][0]["patient_name"] == "Jane Doe"
        assert body["notes"][0]["status"] == "Open"
        assert body["notes"][0]["cpts"] == ["99213"]
        assert "patient-uuid-1" in body["notes"][0]["chart_link"]

    def test_notes_skips_none_patient(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ):
            mock_note_obj = MagicMock()
            mock_note_obj.patient = None
            mock_note_obj.dbid = 1
            _mock_visible_note_ids(mock_state, [1])
            self._mock_note_qs(mock_note, [mock_note_obj])
            results = api.get_patients()

        import json
        body = json.loads(results[0].content)
        assert body["notes"] == []

    def test_notes_period_in_response(self):
        api = _make_api(period="month")
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ):
            _mock_visible_note_ids(mock_state, [])
            self._mock_note_qs(mock_note, [])
            results = api.get_patients()

        import json
        body = json.loads(results[0].content)
        assert body["period"] == "month"


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_cpt_patients tests
# ---------------------------------------------------------------------------

class TestGetCptPatients:
    def _mock_billing_qs(self, mock_billing, items_list):
        mock_qs = MagicMock()
        mock_billing.objects.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = items_list
        return mock_qs

    def test_returns_json_response(self):
        api = _make_api(cpt="99213")
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ) as mock_billing:
            _mock_visible_note_ids(mock_state, [])
            self._mock_billing_qs(mock_billing, [])
            results = api.get_cpt_patients()

        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.OK

    def test_empty_results(self):
        api = _make_api(cpt="99213")
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ) as mock_billing:
            _mock_visible_note_ids(mock_state, [])
            self._mock_billing_qs(mock_billing, [])
            results = api.get_cpt_patients()

        import json
        body = json.loads(results[0].content)
        assert body["patients"] == []
        assert body["cpt"] == "99213"

    def test_returns_patient_data(self):
        api = _make_api(period="week", cpt="99213")

        mock_patient = MagicMock()
        mock_patient.id = "patient-uuid-2"
        mock_patient.first_name = "John"
        mock_patient.last_name = "Smith"
        mock_patient.nickname = ""

        mock_note = MagicMock()
        mock_note.patient = mock_patient
        mock_note.dbid = 555
        mock_note.datetime_of_service = datetime.datetime(2026, 3, 20, 14, 30)

        mock_item = MagicMock()
        mock_item.note = mock_note

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ) as mock_billing:
            _mock_visible_note_ids(mock_state, [1])
            self._mock_billing_qs(mock_billing, [mock_item])
            results = api.get_cpt_patients()

        import json
        body = json.loads(results[0].content)
        assert len(body["patients"]) == 1
        assert body["patients"][0]["patient_name"] == "John Smith"
        # CPT patient link opens the specific note via the chart fragment.
        assert body["patients"][0]["chart_link"] == "/patient/patient-uuid-2#noteId=555"
        assert body["period"] == "week"

    def test_returns_patient_with_nickname(self):
        api = _make_api(cpt="99214")

        mock_patient = MagicMock()
        mock_patient.id = "patient-uuid-3"
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Doe"
        mock_patient.nickname = "JD"

        mock_note = MagicMock()
        mock_note.patient = mock_patient
        mock_note.datetime_of_service = datetime.datetime(2026, 3, 23, 9, 0)

        mock_item = MagicMock()
        mock_item.note = mock_note

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ) as mock_billing:
            _mock_visible_note_ids(mock_state, [1])
            self._mock_billing_qs(mock_billing, [mock_item])
            results = api.get_cpt_patients()

        import json
        body = json.loads(results[0].content)
        assert body["patients"][0]["patient_name"] == "Jane (JD) Doe"

    def test_skips_item_with_no_patient(self):
        api = _make_api(cpt="99213")

        mock_note = MagicMock()
        mock_note.patient = None

        mock_item = MagicMock()
        mock_item.note = mock_note

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ) as mock_billing:
            _mock_visible_note_ids(mock_state, [1])
            self._mock_billing_qs(mock_billing, [mock_item])
            results = api.get_cpt_patients()

        import json
        body = json.loads(results[0].content)
        assert body["patients"] == []

    def test_skips_item_with_no_note(self):
        api = _make_api(cpt="99213")

        mock_item = MagicMock()
        mock_item.note = None

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.BillingLineItem"
        ) as mock_billing:
            _mock_visible_note_ids(mock_state, [1])
            self._mock_billing_qs(mock_billing, [mock_item])
            results = api.get_cpt_patients()

        import json
        body = json.loads(results[0].content)
        assert body["patients"] == []


# ---------------------------------------------------------------------------
# Constants correctness
# ---------------------------------------------------------------------------

class TestConstants:
    def test_signed_states_includes_locked_relocked_and_sgn(self):
        assert NoteStates.LOCKED in SIGNED_STATES
        assert NoteStates.RELOCKED in SIGNED_STATES
        assert "SGN" in SIGNED_STATES

    def test_open_states_includes_new_and_unlocked(self):
        assert NoteStates.NEW in OPEN_STATES
        assert NoteStates.UNLOCKED in OPEN_STATES

    def test_excluded_categories_has_message_and_letter(self):
        assert NoteTypeCategories.MESSAGE in EXCLUDED_CATEGORIES
        assert NoteTypeCategories.LETTER in EXCLUDED_CATEGORIES

    def test_signed_and_open_states_are_disjoint(self):
        assert not set(SIGNED_STATES) & set(OPEN_STATES)


# ---------------------------------------------------------------------------
# _format_duration tests
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_days_and_hours(self):
        delta = datetime.timedelta(days=3, hours=4)
        assert _format_duration(delta) == "3d 4h"

    def test_hours_and_minutes(self):
        delta = datetime.timedelta(hours=12, minutes=30)
        assert _format_duration(delta) == "12h 30m"

    def test_minutes_only(self):
        delta = datetime.timedelta(minutes=45)
        assert _format_duration(delta) == "45m"

    def test_zero_duration(self):
        delta = datetime.timedelta(0)
        assert _format_duration(delta) == "0m"

    def test_negative_duration(self):
        delta = datetime.timedelta(seconds=-100)
        assert _format_duration(delta) == "0m"

    def test_one_day_zero_hours(self):
        delta = datetime.timedelta(days=1)
        assert _format_duration(delta) == "1d 0h"


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_unsigned_notes tests
# ---------------------------------------------------------------------------

class TestGetUnsignedNotes:
    def _mock_note_qs(self, mock_note, notes_list):
        mock_qs = MagicMock()
        mock_note.objects.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = notes_list
        return mock_qs

    def test_returns_json_response(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state:
            visible_qs = MagicMock()
            visible_qs.exclude.return_value = visible_qs
            visible_qs.values_list.return_value = []

            open_qs = MagicMock()
            open_qs.values_list.return_value = []

            call_count = [0]
            def filter_side_effect(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return visible_qs
                return open_qs
            mock_state.objects.filter = MagicMock(side_effect=filter_side_effect)

            self._mock_note_qs(mock_note, [])
            results = api.get_unsigned_notes()

        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.OK

    def test_empty_unsigned_notes(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state:
            visible_qs = MagicMock()
            visible_qs.exclude.return_value = visible_qs
            visible_qs.values_list.return_value = []

            open_qs = MagicMock()
            open_qs.values_list.return_value = []

            call_count = [0]
            def filter_side_effect(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return visible_qs
                return open_qs
            mock_state.objects.filter = MagicMock(side_effect=filter_side_effect)

            self._mock_note_qs(mock_note, [])
            results = api.get_unsigned_notes()

        import json
        body = json.loads(results[0].content)
        assert body["notes"] == []
        assert body["count"] == 0

    def test_unsigned_notes_with_data(self):
        api = _make_api(period="week")

        mock_patient = MagicMock()
        mock_patient.id = "patient-uuid-1"
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Doe"
        mock_patient.nickname = ""

        mock_provider = MagicMock()
        mock_provider.credentialed_name = "Dr. Smith"

        mock_note_obj = MagicMock()
        mock_note_obj.patient = mock_patient
        mock_note_obj.provider = mock_provider
        mock_note_obj.dbid = 1
        mock_note_obj.id = "note-uuid-1"
        mock_note_obj.created = datetime.datetime(2026, 4, 10, 8, 0, tzinfo=datetime.timezone.utc)
        mock_note_obj.datetime_of_service = datetime.datetime(2026, 4, 10, 8, 0)

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.arrow"
        ) as mock_arrow:
            mock_now = MagicMock()
            mock_now.datetime = datetime.datetime(2026, 4, 13, 12, 0, tzinfo=datetime.timezone.utc)
            mock_arrow.now.return_value = mock_now
            mock_arrow.get = arrow.get

            visible_qs = MagicMock()
            visible_qs.exclude.return_value = visible_qs
            visible_qs.values_list.return_value = [1]

            open_qs = MagicMock()
            open_qs.values_list.return_value = [1]

            call_count = [0]
            def filter_side_effect(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return visible_qs
                return open_qs
            mock_state.objects.filter = MagicMock(side_effect=filter_side_effect)

            mock_note_qs = MagicMock()
            mock_note.objects.filter.return_value = mock_note_qs
            mock_note_qs.select_related.return_value = mock_note_qs
            mock_note_qs.order_by.return_value = [mock_note_obj]

            results = api.get_unsigned_notes()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert len(body["notes"]) == 1
        assert body["notes"][0]["patient_name"] == "Jane Doe"
        assert body["notes"][0]["provider_name"] == "Dr. Smith"
        assert "time_open" in body["notes"][0]
        # Unsigned-note link opens the specific note via the chart fragment.
        assert body["notes"][0]["chart_link"] == "/patient/patient-uuid-1#noteId=1"

    def test_unsigned_notes_skips_none_patient(self):
        api = _make_api()
        mock_note_obj = MagicMock()
        mock_note_obj.patient = None
        mock_note_obj.dbid = 1
        mock_note_obj.created = datetime.datetime(2026, 4, 10, 8, 0, tzinfo=datetime.timezone.utc)

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.arrow"
        ) as mock_arrow:
            mock_now = MagicMock()
            mock_now.datetime = datetime.datetime(2026, 4, 13, 12, 0, tzinfo=datetime.timezone.utc)
            mock_arrow.now.return_value = mock_now

            visible_qs = MagicMock()
            visible_qs.exclude.return_value = visible_qs
            visible_qs.values_list.return_value = [1]

            open_qs = MagicMock()
            open_qs.values_list.return_value = [1]

            call_count = [0]
            def filter_side_effect(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return visible_qs
                return open_qs
            mock_state.objects.filter = MagicMock(side_effect=filter_side_effect)

            mock_note_qs = MagicMock()
            mock_note.objects.filter.return_value = mock_note_qs
            mock_note_qs.select_related.return_value = mock_note_qs
            mock_note_qs.order_by.return_value = [mock_note_obj]

            results = api.get_unsigned_notes()

        import json
        body = json.loads(results[0].content)
        assert body["notes"] == []


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_care_gaps_closed tests
# ---------------------------------------------------------------------------

class TestGetCareGapsClosed:
    def _mock_protocol_qs(self, mock_protocol, protocols_list):
        mock_qs = MagicMock()
        mock_protocol.objects.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = protocols_list
        return mock_qs

    def test_returns_json_response(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.ProtocolCurrent"
        ) as mock_protocol, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note:
            _mock_visible_note_ids(mock_state, [])
            mock_note.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = []
            self._mock_protocol_qs(mock_protocol, [])
            results = api.get_care_gaps_closed()

        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.OK

    def test_empty_care_gaps(self):
        api = _make_api()
        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.ProtocolCurrent"
        ) as mock_protocol, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note:
            _mock_visible_note_ids(mock_state, [])
            mock_note.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = []
            self._mock_protocol_qs(mock_protocol, [])
            results = api.get_care_gaps_closed()

        import json
        body = json.loads(results[0].content)
        assert body["gaps"] == []
        assert body["count"] == 0

    def test_care_gaps_with_data(self):
        api = _make_api(period="week")

        mock_patient = MagicMock()
        mock_patient.id = "patient-uuid-1"
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Doe"
        mock_patient.nickname = ""

        mock_protocol_obj = MagicMock()
        mock_protocol_obj.patient = mock_patient
        mock_protocol_obj.title = "Annual Wellness Visit"
        mock_protocol_obj.modified = datetime.datetime(2026, 4, 11, 14, 0, tzinfo=datetime.timezone.utc)

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.ProtocolCurrent"
        ) as mock_protocol, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note:
            _mock_visible_note_ids(mock_state, [1])
            mock_note.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = ["patient-uuid-1"]
            self._mock_protocol_qs(mock_protocol, [mock_protocol_obj])
            results = api.get_care_gaps_closed()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert len(body["gaps"]) == 1
        assert body["gaps"][0]["patient_name"] == "Jane Doe"
        assert body["gaps"][0]["protocol_title"] == "Annual Wellness Visit"
        assert "Apr 11, 2026" in body["gaps"][0]["date_resolved"]

    def test_care_gaps_skips_none_patient(self):
        api = _make_api()

        mock_protocol_obj = MagicMock()
        mock_protocol_obj.patient = None
        mock_protocol_obj.title = "Some Protocol"
        mock_protocol_obj.modified = datetime.datetime(2026, 4, 11, 14, 0, tzinfo=datetime.timezone.utc)

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.ProtocolCurrent"
        ) as mock_protocol, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note:
            _mock_visible_note_ids(mock_state, [1])
            mock_note.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = ["patient-uuid-1"]
            self._mock_protocol_qs(mock_protocol, [mock_protocol_obj])
            results = api.get_care_gaps_closed()

        import json
        body = json.loads(results[0].content)
        assert body["gaps"] == []

    def test_all_providers_scoped_to_period_patients(self):
        api = _make_api(provider_id="all")

        with patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.ProtocolCurrent"
        ) as mock_protocol, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.CurrentNoteStateEvent"
        ) as mock_state, patch(
            "provider_productivity_dashboard.applications.productivity_dashboard.Note"
        ) as mock_note:
            _mock_visible_note_ids(mock_state, [1, 2])
            mock_note.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = ["patient-uuid-1"]
            self._mock_protocol_qs(mock_protocol, [])
            results = api.get_care_gaps_closed()

        assert results[0].status_code == HTTPStatus.OK
        # Even for "all", the closed-gaps list is scoped to patients seen in the
        # period so it matches the summary-card count.
        call_kwargs = mock_protocol.objects.filter.call_args[1]
        assert "patient__id__in" in call_kwargs


# ---------------------------------------------------------------------------
# _is_dme_referral tests
# ---------------------------------------------------------------------------

class TestIsDmeReferral:
    def test_detects_dme_keyword(self):
        assert _is_dme_referral("Patient needs DME evaluation") is True

    def test_detects_equipment_keyword(self):
        assert _is_dme_referral("Durable medical equipment for home use") is True

    def test_detects_wheelchair(self):
        assert _is_dme_referral("Order wheelchair for patient") is True

    def test_detects_cpap(self):
        assert _is_dme_referral("CPAP machine fitting") is True

    def test_returns_false_for_regular_referral(self):
        assert _is_dme_referral("Refer to cardiology for evaluation") is False

    def test_returns_false_for_empty_string(self):
        assert _is_dme_referral("") is False

    def test_returns_false_for_none(self):
        assert _is_dme_referral(None) is False

    def test_case_insensitive(self):
        assert _is_dme_referral("WHEELCHAIR needed") is True


# ---------------------------------------------------------------------------
# ProductivityDashboardApi.get_orders tests
# ---------------------------------------------------------------------------

class TestGetOrders:
    MODULE = "provider_productivity_dashboard.applications.productivity_dashboard"

    def _make_mock_patient(self, patient_id="patient-1", first="Jane", last="Doe", nickname=""):
        p = MagicMock()
        p.id = patient_id
        p.first_name = first
        p.last_name = last
        p.nickname = nickname
        return p

    def _make_mock_provider(self, name="Dr. Smith"):
        p = MagicMock()
        p.credentialed_name = name
        return p

    def test_returns_json_response_empty(self):
        api = _make_api()
        with patch(f"{self.MODULE}.LabOrder") as mock_lab, \
             patch(f"{self.MODULE}.ImagingOrder") as mock_img, \
             patch(f"{self.MODULE}.Referral") as mock_ref:
            for m in (mock_lab, mock_img, mock_ref):
                m.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            results = api.get_orders()

        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.OK
        import json
        body = json.loads(results[0].content)
        assert body["orders"] == []
        assert body["count"] == 0

    def test_lab_order_included(self):
        api = _make_api(period="week")
        patient = self._make_mock_patient()
        provider = self._make_mock_provider()

        mock_lab = MagicMock()
        mock_lab.patient = patient
        mock_lab.ordering_provider = provider
        mock_lab.date_ordered = datetime.datetime(2026, 4, 10, 10, 0)
        mock_lab.comment = "Routine labs"
        mock_lab.tests.values_list.return_value = ["CBC", "BMP"]

        with patch(f"{self.MODULE}.LabOrder") as lab_cls, \
             patch(f"{self.MODULE}.ImagingOrder") as img_cls, \
             patch(f"{self.MODULE}.Referral") as ref_cls:
            lab_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = [mock_lab]
            img_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            ref_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            results = api.get_orders()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert body["orders"][0]["order_type"] == "Lab"
        assert body["orders"][0]["description"] == "CBC, BMP"
        assert body["orders"][0]["provider"] == "Dr. Smith"

    def test_imaging_order_included(self):
        api = _make_api(period="week")
        patient = self._make_mock_patient()
        provider = self._make_mock_provider("Dr. Jones")

        mock_img = MagicMock()
        mock_img.patient = patient
        mock_img.ordering_provider = provider
        mock_img.date_time_ordered = datetime.datetime(2026, 4, 11, 9, 0)
        mock_img.imaging = "Chest X-Ray"

        with patch(f"{self.MODULE}.LabOrder") as lab_cls, \
             patch(f"{self.MODULE}.ImagingOrder") as img_cls, \
             patch(f"{self.MODULE}.Referral") as ref_cls:
            lab_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = []
            img_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = [mock_img]
            ref_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            results = api.get_orders()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert body["orders"][0]["order_type"] == "Imaging"
        assert body["orders"][0]["description"] == "Chest X-Ray"

    def test_referral_included(self):
        api = _make_api(period="week")
        patient = self._make_mock_patient()
        provider = self._make_mock_provider()
        mock_note = MagicMock()
        mock_note.provider = provider

        mock_ref = MagicMock()
        mock_ref.patient = patient
        mock_ref.note = mock_note
        mock_ref.notes = "Refer to cardiology"
        mock_ref.date_referred = datetime.datetime(2026, 4, 12, 11, 0)

        with patch(f"{self.MODULE}.LabOrder") as lab_cls, \
             patch(f"{self.MODULE}.ImagingOrder") as img_cls, \
             patch(f"{self.MODULE}.Referral") as ref_cls:
            lab_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = []
            img_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            ref_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = [mock_ref]
            results = api.get_orders()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert body["orders"][0]["order_type"] == "Referral"

    def test_dme_referral_detected(self):
        api = _make_api(period="week")
        patient = self._make_mock_patient()
        mock_note = MagicMock()
        mock_note.provider = self._make_mock_provider()

        mock_ref = MagicMock()
        mock_ref.patient = patient
        mock_ref.note = mock_note
        mock_ref.notes = "Patient needs wheelchair and CPAP"
        mock_ref.date_referred = datetime.datetime(2026, 4, 12, 11, 0)

        with patch(f"{self.MODULE}.LabOrder") as lab_cls, \
             patch(f"{self.MODULE}.ImagingOrder") as img_cls, \
             patch(f"{self.MODULE}.Referral") as ref_cls:
            lab_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = []
            img_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            ref_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = [mock_ref]
            results = api.get_orders()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert body["orders"][0]["order_type"] == "DME"

    def test_type_filter_lab_only(self):
        api = _make_api(period="week")
        api.request.query_params["order_type"] = "lab"
        patient = self._make_mock_patient()
        provider = self._make_mock_provider()

        mock_lab = MagicMock()
        mock_lab.patient = patient
        mock_lab.ordering_provider = provider
        mock_lab.date_ordered = datetime.datetime(2026, 4, 10, 10, 0)
        mock_lab.tests.values_list.return_value = ["CBC"]

        with patch(f"{self.MODULE}.LabOrder") as lab_cls, \
             patch(f"{self.MODULE}.ImagingOrder") as img_cls, \
             patch(f"{self.MODULE}.Referral") as ref_cls:
            lab_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = [mock_lab]
            results = api.get_orders()

        # ImagingOrder and Referral should not have been queried
        img_cls.objects.filter.assert_not_called()
        ref_cls.objects.filter.assert_not_called()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert body["order_type"] == "lab"

    def test_type_filter_dme_excludes_regular_referrals(self):
        api = _make_api(period="week")
        api.request.query_params["order_type"] = "dme"
        patient = self._make_mock_patient()
        mock_note = MagicMock()
        mock_note.provider = self._make_mock_provider()

        regular_ref = MagicMock()
        regular_ref.patient = patient
        regular_ref.note = mock_note
        regular_ref.notes = "Cardiology consult"
        regular_ref.date_referred = datetime.datetime(2026, 4, 12, 11, 0)

        dme_ref = MagicMock()
        dme_ref.patient = patient
        dme_ref.note = mock_note
        dme_ref.notes = "Needs wheelchair"
        dme_ref.date_referred = datetime.datetime(2026, 4, 12, 12, 0)

        with patch(f"{self.MODULE}.LabOrder") as lab_cls, \
             patch(f"{self.MODULE}.ImagingOrder") as img_cls, \
             patch(f"{self.MODULE}.Referral") as ref_cls:
            ref_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = [regular_ref, dme_ref]
            results = api.get_orders()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 1
        assert body["orders"][0]["order_type"] == "DME"

    def test_skips_null_patients(self):
        api = _make_api(period="week")

        mock_lab = MagicMock()
        mock_lab.patient = None

        with patch(f"{self.MODULE}.LabOrder") as lab_cls, \
             patch(f"{self.MODULE}.ImagingOrder") as img_cls, \
             patch(f"{self.MODULE}.Referral") as ref_cls:
            lab_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = [mock_lab]
            img_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            ref_cls.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            results = api.get_orders()

        import json
        body = json.loads(results[0].content)
        assert body["count"] == 0


# ---------------------------------------------------------------------------
# Integration-style tests (use real DB via factories)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIntegration:
    def test_note_factory_creates_note(self):
        """Smoke test: NoteFactory works in this test suite."""
        note = NoteFactory.create()
        assert note.id is not None

    def test_staff_factory_creates_staff(self):
        staff = StaffFactory.create()
        assert staff.id is not None

    def test_patient_factory_creates_patient(self):
        patient = PatientFactory.create()
        assert patient.id is not None

    def test_note_state_change_event_factory(self):
        """NoteStateChangeEventFactory creates event with NEW state by default."""
        event = NoteStateChangeEventFactory.create()
        assert event.state == NoteStates.NEW

    def test_note_type_category_exclusion(self):
        """Notes with MESSAGE or LETTER categories should be filterable."""
        message_type = NoteTypeFactory.create(category=NoteTypeCategories.MESSAGE)
        letter_type = NoteTypeFactory.create(category=NoteTypeCategories.LETTER)
        from canvas_sdk.v1.data.note import NoteType
        qs = NoteType.objects.filter(
            category__in=EXCLUDED_CATEGORIES
        )
        ids = list(qs.values_list("id", flat=True))
        assert message_type.id in ids
        assert letter_type.id in ids
