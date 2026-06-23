import base64
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import arrow

from provider_productivity_compensation.applications import productivity_dashboard as pd
from provider_productivity_compensation.applications.productivity_dashboard import (
    ProductivityDashboardApplication,
)


# ---------------------------------------------------------------------------
# _get_pay_period
# ---------------------------------------------------------------------------
class TestGetPayPeriod:
    def test_first_half_of_month(self):
        """A date on or before the 15th yields the 1st-15th period."""
        ref = arrow.get("2026-06-10T09:30:00")
        start, end = pd._get_pay_period(ref)

        assert start.day == 1
        assert (start.hour, start.minute, start.second) == (0, 0, 0)
        assert end.day == 15
        assert (end.hour, end.minute) == (23, 59)
        assert start.month == end.month == 6

    def test_boundary_day_15_is_first_half(self):
        """The 15th itself belongs to the first half."""
        ref = arrow.get("2026-06-15T23:00:00")
        start, end = pd._get_pay_period(ref)

        assert (start.day, end.day) == (1, 15)

    def test_second_half_of_month(self):
        """A date after the 15th yields the 16th-end-of-month period."""
        ref = arrow.get("2026-06-20T09:30:00")
        start, end = pd._get_pay_period(ref)

        assert start.day == 16
        assert (start.hour, start.minute, start.second) == (0, 0, 0)
        assert end.day == 30  # June has 30 days
        assert (end.hour, end.minute) == (23, 59)

    def test_second_half_february(self):
        """End-of-month is computed correctly for a 28-day month."""
        ref = arrow.get("2026-02-20T00:00:00")
        start, end = pd._get_pay_period(ref)

        assert start.day == 16
        assert end.day == 28


# ---------------------------------------------------------------------------
# _get_date_range
# ---------------------------------------------------------------------------
class TestGetDateRange:
    def test_day_period_spans_a_single_day(self):
        start, end = pd._get_date_range("day", tz="UTC")
        assert start <= end
        assert start.hour == 0 and start.minute == 0
        assert end.hour == 23 and end.minute == 59
        assert start.date() == end.date()

    def test_week_period_starts_on_monday(self):
        start, end = pd._get_date_range("week", tz="UTC")
        # arrow floor("week") is Monday (weekday() == 0)
        assert start.weekday() == 0
        assert start <= end

    def test_month_period_starts_on_first(self):
        start, end = pd._get_date_range("month", tz="UTC")
        assert start.day == 1
        assert start <= end

    def test_unknown_period_falls_back_to_day(self):
        start, end = pd._get_date_range("nonsense", tz="UTC")
        assert start.date() == end.date()
        assert start.hour == 0 and end.hour == 23

    def test_this_pay_period(self):
        start, end = pd._get_date_range("this_pay_period", tz="UTC")
        # Start is either the 1st or the 16th
        assert start.day in (1, 16)
        assert start <= end

    def test_last_pay_period_precedes_this_pay_period(self):
        last_start, last_end = pd._get_date_range("last_pay_period", tz="UTC")
        this_start, _ = pd._get_date_range("this_pay_period", tz="UTC")
        assert last_end < this_start
        assert last_start.day in (1, 16)

    def test_custom_range_uses_supplied_dates(self):
        start, end = pd._get_date_range(
            "custom", start_date="2025-01-05", end_date="2025-01-20", tz="UTC"
        )
        assert start.year == 2025 and start.month == 1 and start.day == 5
        assert start.hour == 0 and start.minute == 0
        assert end.day == 20
        assert end.hour == 23 and end.minute == 59

    def test_custom_without_dates_falls_through_to_day(self):
        """period='custom' but missing dates is treated as the default (day)."""
        start, end = pd._get_date_range("custom", tz="UTC")
        assert start.date() == end.date()

    def test_custom_with_invalid_dates_falls_through(self):
        """Unparseable custom dates fall back rather than raising."""
        start, end = pd._get_date_range(
            "custom", start_date="not-a-date", end_date="also-bad", tz="UTC"
        )
        assert start.date() == end.date()

    def test_invalid_timezone_falls_back_to_server_default(self):
        """An invalid tz string must not raise."""
        start, end = pd._get_date_range("day", tz="Not/AZone")
        assert start <= end


# ---------------------------------------------------------------------------
# ProductivityDashboardApi._compute_earnings
# ---------------------------------------------------------------------------
class TestComputeEarnings:
    def test_sums_known_rates(self, make_api):
        api = make_api()
        schedule = {"99213": 100.0, "99214": 150.0}
        assert api._compute_earnings(["99213", "99214"], schedule) == 250.0

    def test_unknown_codes_contribute_zero(self, make_api):
        api = make_api()
        schedule = {"99213": 100.0}
        assert api._compute_earnings(["99213", "00000"], schedule) == 100.0

    def test_repeated_codes_counted_each_time(self, make_api):
        api = make_api()
        schedule = {"99213": 100.0}
        assert api._compute_earnings(["99213", "99213"], schedule) == 200.0

    def test_empty_list_is_zero(self, make_api):
        api = make_api()
        assert api._compute_earnings([], {"99213": 100.0}) == 0.0

    def test_result_is_rounded(self, make_api):
        api = make_api()
        schedule = {"a": 10.111, "b": 20.222}
        assert api._compute_earnings(["a", "b"], schedule) == 30.33


# ---------------------------------------------------------------------------
# ProductivityDashboardApi._is_compensation_superuser
# ---------------------------------------------------------------------------
class TestIsCompensationSuperuser:
    def test_no_secret_is_not_superuser(self, make_api):
        api = make_api(secrets={}, headers={"canvas-logged-in-user-id": "staff-1"})
        assert api._is_compensation_superuser() is False

    def test_matching_id_is_superuser(self, make_api):
        api = make_api(
            secrets={"COMPENSATION_SUPERUSER_IDS": "staff-1,staff-2"},
            headers={"canvas-logged-in-user-id": "staff-2"},
        )
        assert api._is_compensation_superuser() is True

    def test_non_matching_id_is_not_superuser(self, make_api):
        api = make_api(
            secrets={"COMPENSATION_SUPERUSER_IDS": "staff-1,staff-2"},
            headers={"canvas-logged-in-user-id": "staff-9"},
        )
        assert api._is_compensation_superuser() is False

    def test_whitespace_and_blanks_are_tolerated(self, make_api):
        api = make_api(
            secrets={"COMPENSATION_SUPERUSER_IDS": " staff-1 , , staff-2 "},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        assert api._is_compensation_superuser() is True


# ---------------------------------------------------------------------------
# ProductivityDashboardApi._resolve_staff_id
# ---------------------------------------------------------------------------
class TestResolveStaffId:
    def test_anyone_can_request_another_provider(self, make_api):
        api = make_api(
            secrets={},  # not a superuser — still allowed to view others
            headers={"canvas-logged-in-user-id": "staff-1"},
            query_params={"provider_id": "staff-other"},
        )
        assert api._resolve_staff_id() == "staff-other"

    def test_without_requested_gets_own_id(self, make_api):
        api = make_api(
            secrets={},
            headers={"canvas-logged-in-user-id": "staff-1"},
            query_params={},
        )
        assert api._resolve_staff_id() == "staff-1"


# ---------------------------------------------------------------------------
# ProductivityDashboardApi._get_fee_schedule
# ---------------------------------------------------------------------------
class TestGetFeeSchedule:
    def test_no_provider_map_returns_none(self, make_api):
        api = make_api(secrets={})
        assert api._get_fee_schedule("staff-1") is None

    def test_staff_not_resolvable_returns_none(self, make_api):
        api = make_api(
            secrets={
                "PROVIDER_FEE_SCHEDULE_MAP": '{"Jane Doe NP": "CA18"}',
                "FEE_SCHEDULE_RATES": '{"CA18": {"99213": 100.0}}',
            }
        )
        with patch.object(pd, "Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = None
            assert api._get_fee_schedule("staff-unknown") is None

    def test_name_not_in_map_returns_none(self, make_api):
        api = make_api(
            secrets={
                "PROVIDER_FEE_SCHEDULE_MAP": '{"Jane Doe NP": "CA18"}',
                "FEE_SCHEDULE_RATES": '{"CA18": {"99213": 100.0}}',
            }
        )
        staff_obj = MagicMock()
        staff_obj.credentialed_name = "Someone Else MD"
        with patch.object(pd, "Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = staff_obj
            assert api._get_fee_schedule("staff-1") is None

    def test_happy_path_returns_schedule(self, make_api):
        api = make_api(
            secrets={
                "PROVIDER_FEE_SCHEDULE_MAP": '{"Jane Doe NP": "CA18"}',
                "FEE_SCHEDULE_RATES": '{"CA18": {"99213": 100.0}}',
            }
        )
        staff_obj = MagicMock()
        staff_obj.credentialed_name = "Jane Doe NP"
        with patch.object(pd, "Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = staff_obj
            assert api._get_fee_schedule("staff-1") == {"99213": 100.0}

    def test_plan_missing_from_rates_returns_none(self, make_api):
        api = make_api(
            secrets={
                "PROVIDER_FEE_SCHEDULE_MAP": '{"Jane Doe NP": "CA18"}',
                "FEE_SCHEDULE_RATES": '{"OTHER": {"99213": 100.0}}',
            }
        )
        staff_obj = MagicMock()
        staff_obj.credentialed_name = "Jane Doe NP"
        with patch.object(pd, "Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = staff_obj
            assert api._get_fee_schedule("staff-1") is None

    def test_malformed_json_returns_none(self, make_api):
        api = make_api(secrets={"PROVIDER_FEE_SCHEDULE_MAP": "{not valid json"})
        assert api._get_fee_schedule("staff-1") is None


# ---------------------------------------------------------------------------
# ProductivityDashboardApi._should_show_earnings
# ---------------------------------------------------------------------------
class TestShouldShowEarnings:
    def test_own_data_with_schedule_shows(self, make_api):
        api = make_api(headers={"canvas-logged-in-user-id": "staff-1"})
        api._get_fee_schedule = lambda sid: {"99213": 100.0}
        assert api._should_show_earnings("staff-1") is True

    def test_own_data_without_schedule_hidden(self, make_api):
        api = make_api(headers={"canvas-logged-in-user-id": "staff-1"})
        api._get_fee_schedule = lambda sid: None
        assert api._should_show_earnings("staff-1") is False

    def test_superuser_viewing_other_with_schedule_shows(self, make_api):
        api = make_api(
            secrets={"COMPENSATION_SUPERUSER_IDS": "staff-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        api._get_fee_schedule = lambda sid: {"99213": 100.0}
        assert api._should_show_earnings("staff-2") is True

    def test_non_superuser_viewing_other_hidden(self, make_api):
        api = make_api(
            secrets={},  # not a superuser
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        api._get_fee_schedule = lambda sid: {"99213": 100.0}
        assert api._should_show_earnings("staff-2") is False


# ---------------------------------------------------------------------------
# ProductivityDashboardApplication.on_open
# ---------------------------------------------------------------------------
class TestOnOpen:
    def test_launches_full_page_modal(self):
        app = ProductivityDashboardApplication.__new__(ProductivityDashboardApplication)
        with patch.object(pd, "render_to_string", return_value="<html></html>") as mock_render, \
             patch.object(pd, "LaunchModalEffect") as mock_modal:
            mock_modal.TargetType.PAGE = "PAGE"
            mock_modal.return_value.apply.return_value = "effect"

            result = app.on_open()

            assert result == "effect"
            assert mock_render.mock_calls == [call("templates/dashboard.html")]
            assert mock_modal.mock_calls == [
                call(content="<html></html>", target="PAGE", title="Provider Productivity Dashboard"),
                call().apply(),
            ]


# ---------------------------------------------------------------------------
# ProductivityDashboardApi._get_visible_note_ids
# ---------------------------------------------------------------------------
class TestGetVisibleNoteIds:
    def test_always_filters_by_provider(self, make_api):
        api = make_api()
        with patch.object(pd, "CurrentNoteStateEvent") as mock_cnse:
            chain = mock_cnse.objects.filter.return_value.values_list
            chain.return_value = [1, 2, 3]
            result = api._get_visible_note_ids("staff-1", "start", "end")

            assert result == [1, 2, 3]
            kwargs = mock_cnse.objects.filter.call_args.kwargs
            assert kwargs["note__provider__id"] == "staff-1"
            assert kwargs["note__note_type_version__is_billable"] is True


# ---------------------------------------------------------------------------
# ProductivityDashboardApi._note_permalink / _base_url
# ---------------------------------------------------------------------------
class TestNotePermalink:
    def test_builds_absolute_permalink(self, make_api):
        api = make_api(headers={"host": "ex.canvasmedical.com"})
        note = MagicMock(dbid=459)
        with patch.object(pd, "ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first.return_value = MagicMock(dbid=90)
            token = base64.b64encode(b"Note:90:459").decode()
            assert api._note_permalink(note) == f"https://ex.canvasmedical.com/permalinks/v1/{token}"

    def test_prefers_forwarded_host_and_proto(self, make_api):
        api = make_api(headers={
            "host": "internal",
            "x-forwarded-host": "public.canvasmedical.com",
            "x-forwarded-proto": "https",
        })
        note = MagicMock(dbid=1)
        with patch.object(pd, "ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first.return_value = MagicMock(dbid=7)
            assert api._note_permalink(note).startswith("https://public.canvasmedical.com/permalinks/v1/")

    def test_relative_when_host_missing(self, make_api):
        api = make_api(headers={})
        note = MagicMock(dbid=5)
        with patch.object(pd, "ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first.return_value = MagicMock(dbid=90)
            token = base64.b64encode(b"Note:90:5").decode()
            assert api._note_permalink(note) == f"/permalinks/v1/{token}"

    def test_falls_back_to_noteid_when_content_type_unresolved(self, make_api):
        """No ContentType row -> degrade to the chart URL + noteId query param."""
        api = make_api(headers={"host": "ex.canvasmedical.com"})
        note = MagicMock(dbid=5)
        note.patient.id = "pat-1"
        note.id = "note-uuid"
        with patch.object(pd, "ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first.return_value = None
            assert api._note_permalink(note) == "https://ex.canvasmedical.com/patient/pat-1?noteId=note-uuid"

    def test_falls_back_when_content_type_unimportable(self, make_api):
        """Older runtime where the ContentType import was sandbox-blocked (None)."""
        api = make_api(headers={"host": "ex.canvasmedical.com"})
        note = MagicMock(dbid=5)
        note.patient.id = "pat-1"
        note.id = "note-uuid"
        with patch.object(pd, "ContentType", None):
            assert api._note_permalink(note) == "https://ex.canvasmedical.com/patient/pat-1?noteId=note-uuid"


# ---------------------------------------------------------------------------
# API endpoints (ORM managers patched, JSONResponse reduced to its payload)
# ---------------------------------------------------------------------------
def _identity_json_response(payload, status_code=None):
    return payload


class TestGetProviders:
    def test_returns_full_provider_list_to_anyone(self, make_api):
        api = make_api(
            secrets={},  # not a superuser — still gets the list
            headers={"canvas-logged-in-user-id": "staff-9"},
        )
        staff = MagicMock()
        staff.id = "staff-2"
        staff.credentialed_name = "Jane Doe NP"
        with patch.object(pd, "JSONResponse", side_effect=_identity_json_response), \
             patch.object(pd, "Staff") as mock_staff:
            mock_staff.objects.filter.return_value.prefetch_related.return_value.order_by.return_value = [staff]
            [payload] = api.get_providers()

            assert "is_admin" not in payload
            assert payload["logged_in_staff_id"] == "staff-9"
            assert payload["providers"] == [{"id": "staff-2", "name": "Jane Doe NP"}]


class TestGetMetrics:
    def test_summary_payload(self, make_api):
        api = make_api(query_params={"period": "day"})
        api._resolve_staff_id = lambda: "staff-1"
        api._get_visible_note_ids = lambda sid, s, e: [10, 11]
        api._should_show_earnings = lambda sid: False

        billing_rows = [
            {"cpt": "99213", "description": "Office visit", "count": 2},
            {"cpt": "99214", "description": "Office visit, complex", "count": 1},
        ]
        with patch.object(pd, "JSONResponse", side_effect=_identity_json_response), \
             patch.object(pd, "BillingLineItem") as mock_bli, \
             patch.object(pd, "CurrentNoteStateEvent") as mock_cnse:
            mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value = billing_rows
            mock_cnse.objects.filter.return_value.count.return_value = 1

            [payload] = api.get_metrics()

            assert payload["encounters"] == 2
            assert payload["cpt_total"] == 3
            assert payload["notes_signed"] == 1
            assert payload["notes_open"] == 1
            assert payload["notes_total"] == 2
            assert payload["show_earnings"] is False
            assert payload["amount_earned"] == 0.0
            assert payload["cpt_codes"][0]["cpt"] == "99213"
            assert payload["cpt_codes"][0]["amount_earned"] == 0.0


class TestGetPatients:
    def test_note_rows(self, make_api):
        api = make_api(
            query_params={"period": "day"},
            headers={"host": "ex.canvasmedical.com"},
        )
        api._resolve_staff_id = lambda: "staff-1"
        api._get_visible_note_ids = lambda sid, s, e: [10]
        api._should_show_earnings = lambda sid: False

        note = MagicMock()
        note.dbid = 10
        note.datetime_of_service = datetime(2026, 6, 22, 15, 0, tzinfo=timezone.utc)
        note.patient.id = "pat-1"
        note.patient.first_name = "John"
        note.patient.last_name = "Smith"
        note.patient.nickname = ""

        with patch.object(pd, "JSONResponse", side_effect=_identity_json_response), \
             patch.object(pd, "Note") as mock_note, \
             patch.object(pd, "CurrentNoteStateEvent") as mock_cnse, \
             patch.object(pd, "BillingLineItem") as mock_bli, \
             patch.object(pd, "ContentType") as mock_ct:
            mock_note.objects.filter.return_value.select_related.return_value.order_by.return_value = [note]
            mock_cnse.objects.filter.return_value.values_list.return_value = [(10, pd.SIGNED_STATES[0])]
            mock_bli.objects.filter.return_value.values_list.return_value = [(10, "99213")]
            mock_ct.objects.filter.return_value.first.return_value = MagicMock(dbid=90)

            [payload] = api.get_patients()

            assert payload["show_earnings"] is False
            row = payload["notes"][0]
            assert row["patient_name"] == "John Smith"
            assert row["patient_id"] == "pat-1"
            assert row["status"] == "Signed"
            assert row["cpts"] == ["99213"]
            token = base64.b64encode(b"Note:90:10").decode()
            assert row["chart_link"] == f"https://ex.canvasmedical.com/permalinks/v1/{token}"


class TestGetCptPatients:
    def test_patients_for_cpt(self, make_api):
        api = make_api(
            query_params={"period": "day", "cpt": "99213"},
            headers={"host": "ex.canvasmedical.com"},
        )
        api._resolve_staff_id = lambda: "staff-1"
        api._get_visible_note_ids = lambda sid, s, e: [10]
        api._should_show_earnings = lambda sid: False

        item = MagicMock()
        item.note.dbid = 459
        item.note.datetime_of_service = datetime(2026, 6, 22, 15, 0, tzinfo=timezone.utc)
        item.note.patient.id = "pat-1"
        item.note.patient.first_name = "Jane"
        item.note.patient.last_name = "Roe"
        item.note.patient.nickname = "JR"

        with patch.object(pd, "JSONResponse", side_effect=_identity_json_response), \
             patch.object(pd, "BillingLineItem") as mock_bli, \
             patch.object(pd, "ContentType") as mock_ct:
            mock_bli.objects.filter.return_value.select_related.return_value.order_by.return_value = [item]
            mock_ct.objects.filter.return_value.first.return_value = MagicMock(dbid=90)

            [payload] = api.get_cpt_patients()

            assert payload["cpt"] == "99213"
            row = payload["patients"][0]
            assert row["patient_name"] == "Jane (JR) Roe"
            assert row["patient_id"] == "pat-1"
            token = base64.b64encode(b"Note:90:459").decode()
            assert row["chart_link"] == f"https://ex.canvasmedical.com/permalinks/v1/{token}"
            assert row["amount_earned"] == 0.0
