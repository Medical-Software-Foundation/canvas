"""Tests for the NoteProductionDashboardAPI SimpleAPI handler.

Covers:
  - Time window math (_window) for daily / weekly (Sun/Mon) / monthly
  - /providers endpoint: count aggregation, sorting, empty period
  - /providers/<id>/notes endpoint: row shape, CPT joining, RFV fallback,
    provider credentials suffix
  - HTML /dashboard endpoint: returns 200, contains key UI elements
  - Auth: StaffSessionAuthMixin is applied (configuration check)
"""

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# ── helpers imported directly ─────────────────────────────────────────────────
from note_production_dashboard.handlers.dashboard_api import (
    NoteProductionDashboardAPI,
    SimpleAPI,
    StaffSessionAuthMixin,
    _build_provider_counts_result,
    _format_dos,
    _patient_display_name,
    _provider_display_name,
    _render_dashboard_html,
    _rfv_text,
    _window,
)

# ── conftest helpers ──────────────────────────────────────────────────────────
from tests.conftest import make_command, make_note, make_staff, make_state_event


# ── helper: patch settings with a SimpleNamespace so TIME_ZONE is readable ──


def _settings_ns(tz: str = "UTC") -> SimpleNamespace:
    return SimpleNamespace(TIME_ZONE=tz)


# ─────────────────────────────────────────────────────────────────────────────
# Time-window math
# ─────────────────────────────────────────────────────────────────────────────


class TestWindow:
    """_window() returns correct [start, end) edges in the instance timezone."""

    def test_daily_start_end(self) -> None:
        """Daily window is today 00:00 → tomorrow 00:00 local."""
        import arrow as real_arrow

        fixed = real_arrow.Arrow(2025, 4, 27, 14, 30, 0, tzinfo="America/Chicago")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("America/Chicago"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("daily", "sunday")

            assert start == fixed.floor("day").datetime
            assert end == fixed.floor("day").shift(days=1).datetime
            assert mock_arrow.mock_calls == [call.now("America/Chicago")]

    def test_monthly_start_end(self) -> None:
        """Monthly window is 1st of month 00:00 → 1st of next month 00:00 local."""
        import arrow as real_arrow

        fixed = real_arrow.Arrow(2025, 4, 15, 10, 0, 0, tzinfo="America/Chicago")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("America/Chicago"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("monthly", "sunday")

            assert start == fixed.floor("month").datetime
            assert end == fixed.floor("month").shift(months=1).datetime
            assert mock_arrow.mock_calls == [call.now("America/Chicago")]

    def test_weekly_sunday_start_on_sunday(self) -> None:
        """Weekly/Sun: when today is Sunday, week starts today."""
        import arrow as real_arrow

        # 2025-04-27 is a Sunday (arrow weekday=6)
        fixed = real_arrow.Arrow(2025, 4, 27, 14, 0, 0, tzinfo="America/Chicago")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("America/Chicago"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("weekly", "sunday")

            # days_back = (6 - 6) % 7 = 0 → same day (Sunday)
            expected_start = fixed.shift(days=0).floor("day")
            assert start == expected_start.datetime
            assert end == expected_start.shift(weeks=1).datetime
            assert mock_arrow.mock_calls == [call.now("America/Chicago")]

    def test_weekly_sunday_start_mid_week(self) -> None:
        """Weekly/Sun mid-week: rolls back to the most-recent Sunday."""
        import arrow as real_arrow

        # 2025-04-30 is a Wednesday (arrow weekday=2)
        # days_back = (2 - 6) % 7 = 3 → back to Sun Apr 27
        fixed = real_arrow.Arrow(2025, 4, 30, 10, 0, 0, tzinfo="America/Chicago")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("America/Chicago"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("weekly", "sunday")

            expected_start = fixed.shift(days=-3).floor("day")
            assert start == expected_start.datetime
            assert end == expected_start.shift(weeks=1).datetime
            assert mock_arrow.mock_calls == [call.now("America/Chicago")]

    def test_weekly_monday_start_on_sunday(self) -> None:
        """Weekly/Mon: when today is Sunday, rolls back 6 days to the previous Monday."""
        import arrow as real_arrow

        # 2025-04-27 is Sunday (weekday=6); anchor=0 (Mon)
        # days_back = (6 - 0) % 7 = 6 → Mon Apr 21
        fixed = real_arrow.Arrow(2025, 4, 27, 14, 0, 0, tzinfo="America/Chicago")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("America/Chicago"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("weekly", "monday")

            expected_start = fixed.shift(days=-6).floor("day")
            assert start == expected_start.datetime
            assert end == expected_start.shift(weeks=1).datetime
            assert mock_arrow.mock_calls == [call.now("America/Chicago")]

    def test_weekly_monday_start_on_monday(self) -> None:
        """Weekly/Mon: when today is Monday, week starts today."""
        import arrow as real_arrow

        # 2025-04-28 is Monday (weekday=0)
        fixed = real_arrow.Arrow(2025, 4, 28, 9, 0, 0, tzinfo="America/Chicago")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("America/Chicago"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("weekly", "monday")

            expected_start = fixed.shift(days=0).floor("day")
            assert start == expected_start.datetime
            assert end == expected_start.shift(weeks=1).datetime
            assert mock_arrow.mock_calls == [call.now("America/Chicago")]

    def test_unknown_period_defaults_to_daily(self) -> None:
        """Unknown period string falls through to the daily branch."""
        import arrow as real_arrow

        fixed = real_arrow.Arrow(2025, 4, 27, 12, 0, 0, tzinfo="UTC")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("bogus", "sunday")

            assert start == fixed.floor("day").datetime
            assert end == fixed.floor("day").shift(days=1).datetime
            assert mock_arrow.mock_calls == [call.now("UTC")]

    def test_monthly_crosses_year_boundary(self) -> None:
        """Monthly window for December correctly wraps to January of next year."""
        import arrow as real_arrow

        fixed = real_arrow.Arrow(2025, 12, 15, 12, 0, 0, tzinfo="UTC")

        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ), patch(
            "note_production_dashboard.handlers.dashboard_api.arrow"
        ) as mock_arrow:
            mock_arrow.now.return_value = fixed

            start, end = _window("monthly", "sunday")

            assert start == fixed.floor("month").datetime
            assert end == fixed.floor("month").shift(months=1).datetime
            # End should be Jan 1, 2026
            assert end.year == 2026
            assert end.month == 1
            assert mock_arrow.mock_calls == [call.now("UTC")]


# ─────────────────────────────────────────────────────────────────────────────
# Helper function unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProviderDisplayName:
    def test_with_credentials(self) -> None:
        staff = make_staff(
            first_name="Jane",
            last_name="Smith",
            credentialed_name="Jane Smith, MD",
        )
        assert _provider_display_name(staff) == "Jane Smith, MD"

    def test_without_credentials_same_as_name(self) -> None:
        """When credentialed_name equals plain name, no suffix is added."""
        staff = make_staff(
            first_name="Jane",
            last_name="Smith",
            credentialed_name="Jane Smith",
        )
        assert _provider_display_name(staff) == "Jane Smith"

    def test_no_credentialed_name_attr(self) -> None:
        """Falls back gracefully when credentialed_name attribute is absent."""
        staff = SimpleNamespace(first_name="Bob", last_name="Jones")
        assert _provider_display_name(staff) == "Bob Jones"


class TestPatientDisplayName:
    def test_last_first_format(self) -> None:
        patient = SimpleNamespace(first_name="John", last_name="Doe")
        assert _patient_display_name(patient) == "Doe, John"

    def test_only_last_name(self) -> None:
        patient = SimpleNamespace(first_name="", last_name="Doe")
        assert _patient_display_name(patient) == "Doe"

    def test_only_first_name(self) -> None:
        patient = SimpleNamespace(first_name="John", last_name="")
        assert _patient_display_name(patient) == "John"

    def test_neither_name(self) -> None:
        patient = SimpleNamespace(first_name="", last_name="")
        assert _patient_display_name(patient) == ""

    def test_none_patient(self) -> None:
        assert _patient_display_name(None) == ""

    def test_strips_whitespace(self) -> None:
        patient = SimpleNamespace(first_name="  John  ", last_name="  Doe  ")
        assert _patient_display_name(patient) == "Doe, John"


class TestRfvText:
    def test_structured_display_preferred(self) -> None:
        cmd = make_command(
            "reasonForVisit",
            {"coding": {"display": "Chest pain", "text": "Other"}, "comment": "Ignored"},
        )
        note = make_note(rfv_commands=[cmd])
        note.rfv_commands_prefetched = [cmd]
        assert _rfv_text(note) == "Chest pain"

    def test_structured_text_fallback(self) -> None:
        cmd = make_command(
            "reasonForVisit",
            {"coding": {"display": None, "text": "Accident-prone"}, "comment": ""},
        )
        note = make_note(rfv_commands=[cmd])
        note.rfv_commands_prefetched = [cmd]
        assert _rfv_text(note) == "Accident-prone"

    def test_unstructured_comment(self) -> None:
        cmd = make_command(
            "reasonForVisit",
            {"coding": {}, "comment": "Fatigue and weakness"},
        )
        note = make_note(rfv_commands=[cmd])
        note.rfv_commands_prefetched = [cmd]
        assert _rfv_text(note) == "Fatigue and weakness"

    def test_em_dash_when_no_rfv_commands(self) -> None:
        note = make_note(rfv_commands=[])
        note.rfv_commands_prefetched = []
        assert _rfv_text(note) == "—"

    def test_em_dash_when_coding_and_comment_empty(self) -> None:
        cmd = make_command("reasonForVisit", {"coding": {}, "comment": ""})
        note = make_note(rfv_commands=[cmd])
        note.rfv_commands_prefetched = [cmd]
        assert _rfv_text(note) == "—"

    def test_earliest_rfv_selected_by_dbid(self) -> None:
        """When multiple RFV commands exist, the one with the lowest dbid wins."""
        cmd_high = make_command(
            "reasonForVisit",
            {"coding": {"display": "First (high dbid)"}, "comment": ""},
            dbid=10,
        )
        cmd_low = make_command(
            "reasonForVisit",
            {"coding": {"display": "Second (low dbid)"}, "comment": ""},
            dbid=5,
        )
        note = make_note(rfv_commands=[cmd_high, cmd_low])
        note.rfv_commands_prefetched = [cmd_high, cmd_low]
        # dbid=5 (cmd_low) should win
        assert _rfv_text(note) == "Second (low dbid)"

    def test_non_rfv_commands_ignored(self) -> None:
        """Commands with other schema_keys do not produce RFV text."""
        cmd = make_command("diagnose", {"coding": {"display": "Diabetes"}}, dbid=1)
        note = make_note(rfv_commands=[])
        note.rfv_commands_prefetched = []
        # commands.all() returns non-rfv cmd, but prefetched list is empty
        assert _rfv_text(note) == "—"


class TestFormatDos:
    def test_formats_in_utc(self) -> None:
        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ):
            dos = dt.datetime(2025, 4, 27, 9, 30, tzinfo=dt.timezone.utc)
            assert _format_dos(dos) == "04/27 09:30"

    def test_formats_in_local_timezone(self) -> None:
        """A UTC time is shown in the local timezone."""
        with patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("America/New_York"),
        ):
            # 14:00 UTC = 10:00 AM EDT (UTC-4 in April)
            dos = dt.datetime(2025, 4, 27, 14, 0, tzinfo=dt.timezone.utc)
            result = _format_dos(dos)
            assert result == "04/27 10:00"


# ─────────────────────────────────────────────────────────────────────────────
# /providers endpoint
# ─────────────────────────────────────────────────────────────────────────────


class TestProvidersEndpoint:
    """Tests for NoteProductionDashboardAPI.providers_list."""

    def _make_api(self, query_params: dict[str, str]) -> NoteProductionDashboardAPI:
        api: NoteProductionDashboardAPI = NoteProductionDashboardAPI.__new__(
            NoteProductionDashboardAPI
        )
        api.request = SimpleNamespace(
            query_params=query_params,
            path_params={},
            headers={},
        )
        return api

    def _fixed_window(self) -> tuple[dt.datetime, dt.datetime]:
        return (
            dt.datetime(2025, 4, 27, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2025, 4, 28, 0, 0, tzinfo=dt.timezone.utc),
        )

    def test_calls_helper_with_validated_window_and_returns_result(self) -> None:
        """The endpoint passes the validated window to _fetch_provider_counts and serializes its return value."""
        api = self._make_api({"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()
        helper_result = [
            {"provider_id": "p-b", "name": "Bob Baker", "count": 3},
            {"provider_id": "p-a", "name": "Alice Adams", "count": 1},
        ]

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_provider_counts"
        ) as mock_counts:
            mock_window.return_value = fw
            mock_counts.return_value = helper_result

            responses = api.providers_list()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_counts.mock_calls == [call(fw[0], fw[1])]

        import json

        assert json.loads(responses[0].content) == helper_result

    def test_empty_period_returns_empty_list(self) -> None:
        """When the helper returns [], the endpoint returns []."""
        api = self._make_api({"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_provider_counts"
        ) as mock_counts:
            mock_window.return_value = fw
            mock_counts.return_value = []

            responses = api.providers_list()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_counts.mock_calls == [call(fw[0], fw[1])]

        import json

        assert json.loads(responses[0].content) == []

    def test_invalid_period_coerced_to_daily(self) -> None:
        """Unknown period param is rejected; daily is used instead."""
        api = self._make_api({"period": "yearly", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_provider_counts"
        ) as mock_counts:
            mock_window.return_value = fw
            mock_counts.return_value = []

            api.providers_list()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_counts.mock_calls == [call(fw[0], fw[1])]

    def test_invalid_week_start_coerced_to_sunday(self) -> None:
        """Unknown week_start param is rejected; sunday is used instead."""
        api = self._make_api({"period": "weekly", "week_start": "friday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_provider_counts"
        ) as mock_counts:
            mock_window.return_value = fw
            mock_counts.return_value = []

            api.providers_list()

            assert mock_window.mock_calls == [call("weekly", "sunday")]
            assert mock_counts.mock_calls == [call(fw[0], fw[1])]


class TestBuildProviderCountsResult:
    """Tests for the pure result-building helper used by _fetch_provider_counts."""

    def test_empty_inputs_return_empty_list(self) -> None:
        assert _build_provider_counts_result({}, {}) == []

    def test_sort_by_count_desc(self) -> None:
        counts = {"p-b": 3, "p-a": 1}
        staff = {
            "p-a": make_staff("p-a", "Alice", "Adams"),
            "p-b": make_staff("p-b", "Bob", "Baker"),
        }
        result = _build_provider_counts_result(counts, staff)
        assert [r["provider_id"] for r in result] == ["p-b", "p-a"]
        assert [r["count"] for r in result] == [3, 1]

    def test_sort_tie_breaks_by_name_asc(self) -> None:
        counts = {"p-z": 2, "p-a": 2}
        staff = {
            "p-z": make_staff("p-z", "Zara", "Zoller"),
            "p-a": make_staff("p-a", "Aaron", "Able"),
        }
        result = _build_provider_counts_result(counts, staff)
        assert [r["name"] for r in result] == ["Aaron Able", "Zara Zoller"]

    def test_credentialed_name_used_when_present(self) -> None:
        counts = {"p-1": 5}
        staff = {"p-1": make_staff("p-1", "Jane", "Smith", credentialed_name="Jane Smith, MD")}
        result = _build_provider_counts_result(counts, staff)
        assert result[0]["name"] == "Jane Smith, MD"

    def test_missing_staff_record_yields_empty_name(self) -> None:
        """If a provider_id from the count query has no matching Staff row,
        the result row still appears with an empty name (defensive — should
        be rare since the count query already filters provider__isnull=False).
        """
        counts = {"p-orphan": 4}
        staff: dict[str, object] = {}
        result = _build_provider_counts_result(counts, staff)
        assert result == [{"provider_id": "p-orphan", "name": "", "count": 4}]


# ─────────────────────────────────────────────────────────────────────────────
# /providers/<id>/notes endpoint
# ─────────────────────────────────────────────────────────────────────────────


class TestProviderNotesEndpoint:
    """Tests for NoteProductionDashboardAPI.provider_notes."""

    def _make_api(
        self, provider_id: str, query_params: dict[str, str]
    ) -> NoteProductionDashboardAPI:
        api: NoteProductionDashboardAPI = NoteProductionDashboardAPI.__new__(
            NoteProductionDashboardAPI
        )
        api.request = SimpleNamespace(
            query_params=query_params,
            path_params={"provider_id": provider_id},
            headers={},
        )
        return api

    def _fixed_window(self) -> tuple[dt.datetime, dt.datetime]:
        return (
            dt.datetime(2025, 4, 27, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2025, 4, 28, 0, 0, tzinfo=dt.timezone.utc),
        )

    def test_basic_row_shape(self) -> None:
        """Each row has patient, datetime_of_service, cpt, note_type, rfv."""
        dos = dt.datetime(2025, 4, 27, 9, 30, tzinfo=dt.timezone.utc)
        cmd = make_command(
            "reasonForVisit",
            {"coding": {"display": "Chest pain"}, "comment": ""},
        )
        note = make_note(
            "n1",
            provider_id="p-1",
            patient_first="John",
            patient_last="Doe",
            datetime_of_service=dos,
            note_type_name="Office Visit",
            cpt_codes=["99213"],
            rfv_commands=[cmd],
        )
        events = [make_state_event(note)]

        api = self._make_api("p-1", {"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch, patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ):
            mock_window.return_value = fw
            mock_fetch.return_value = events

            responses = api.provider_notes()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_fetch.mock_calls == [
                call(fw[0], fw[1], provider_id="p-1")
            ]

        import json

        rows = json.loads(responses[0].content)
        assert len(rows) == 1
        row = rows[0]
        assert row["patient"] == "Doe, John"
        assert row["datetime_of_service"] == "04/27 09:30"
        assert row["cpt"] == "99213"
        assert row["note_type"] == "Office Visit"
        assert row["rfv"] == "Chest pain"

    def test_cpt_codes_joined_with_comma(self) -> None:
        """Multiple CPT codes are comma-joined in the row."""
        dos = dt.datetime(2025, 4, 27, 9, 30, tzinfo=dt.timezone.utc)
        note = make_note(
            "n1",
            provider_id="p-1",
            cpt_codes=["99213", "90834"],
            datetime_of_service=dos,
        )
        events = [make_state_event(note)]

        api = self._make_api("p-1", {"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch, patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ):
            mock_window.return_value = fw
            mock_fetch.return_value = events

            responses = api.provider_notes()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_fetch.mock_calls == [
                call(fw[0], fw[1], provider_id="p-1")
            ]

        import json

        rows = json.loads(responses[0].content)
        assert rows[0]["cpt"] == "99213, 90834"

    def test_rfv_em_dash_when_no_commands(self) -> None:
        """Notes with no RFV command render an em-dash."""
        dos = dt.datetime(2025, 4, 27, 9, 30, tzinfo=dt.timezone.utc)
        note = make_note("n1", provider_id="p-1", rfv_commands=[], datetime_of_service=dos)
        events = [make_state_event(note)]

        api = self._make_api("p-1", {"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch, patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ):
            mock_window.return_value = fw
            mock_fetch.return_value = events

            responses = api.provider_notes()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_fetch.mock_calls == [
                call(fw[0], fw[1], provider_id="p-1")
            ]

        import json

        rows = json.loads(responses[0].content)
        assert rows[0]["rfv"] == "—"

    def test_rfv_unstructured_comment(self) -> None:
        """Unstructured RFV (no coding display/text) falls back to comment."""
        dos = dt.datetime(2025, 4, 27, 9, 30, tzinfo=dt.timezone.utc)
        cmd = make_command("reasonForVisit", {"coding": {}, "comment": "Back pain"})
        note = make_note("n1", provider_id="p-1", rfv_commands=[cmd], datetime_of_service=dos)
        events = [make_state_event(note)]

        api = self._make_api("p-1", {"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch, patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ):
            mock_window.return_value = fw
            mock_fetch.return_value = events

            responses = api.provider_notes()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_fetch.mock_calls == [
                call(fw[0], fw[1], provider_id="p-1")
            ]

        import json

        rows = json.loads(responses[0].content)
        assert rows[0]["rfv"] == "Back pain"

    def test_empty_notes_returns_empty_list(self) -> None:
        """When no notes exist for provider, the endpoint returns []."""
        api = self._make_api("p-1", {"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch:
            mock_window.return_value = fw
            mock_fetch.return_value = []

            responses = api.provider_notes()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_fetch.mock_calls == [
                call(fw[0], fw[1], provider_id="p-1")
            ]

        import json

        assert json.loads(responses[0].content) == []

    def test_invalid_period_coerced_to_daily(self) -> None:
        """Unknown period in /notes endpoint defaults to daily."""
        api = self._make_api("p-1", {"period": "century", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch:
            mock_window.return_value = fw
            mock_fetch.return_value = []

            api.provider_notes()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_fetch.mock_calls == [call(fw[0], fw[1], provider_id="p-1")]

    def test_invalid_week_start_coerced_to_sunday(self) -> None:
        """Unknown week_start in /notes endpoint defaults to sunday."""
        api = self._make_api("p-1", {"period": "weekly", "week_start": "saturday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch:
            mock_window.return_value = fw
            mock_fetch.return_value = []

            api.provider_notes()

            assert mock_window.mock_calls == [call("weekly", "sunday")]
            assert mock_fetch.mock_calls == [call(fw[0], fw[1], provider_id="p-1")]

    def test_notes_sorted_by_datetime_of_service_desc(self) -> None:
        """Notes are returned in reverse chronological order."""
        dos_early = dt.datetime(2025, 4, 27, 8, 0, tzinfo=dt.timezone.utc)
        dos_late = dt.datetime(2025, 4, 27, 14, 0, tzinfo=dt.timezone.utc)

        note_early = make_note("n1", provider_id="p-1", datetime_of_service=dos_early)
        note_late = make_note("n2", provider_id="p-1", datetime_of_service=dos_late)
        events = [make_state_event(note_early), make_state_event(note_late)]

        api = self._make_api("p-1", {"period": "daily", "week_start": "sunday"})
        fw = self._fixed_window()

        with patch(
            "note_production_dashboard.handlers.dashboard_api._window"
        ) as mock_window, patch(
            "note_production_dashboard.handlers.dashboard_api._fetch_locked_state_events"
        ) as mock_fetch, patch(
            "note_production_dashboard.handlers.dashboard_api.settings",
            _settings_ns("UTC"),
        ):
            mock_window.return_value = fw
            mock_fetch.return_value = events

            responses = api.provider_notes()

            assert mock_window.mock_calls == [call("daily", "sunday")]
            assert mock_fetch.mock_calls == [
                call(fw[0], fw[1], provider_id="p-1")
            ]

        import json

        rows = json.loads(responses[0].content)
        assert rows[0]["note_id"] == "n2"  # latest first
        assert rows[1]["note_id"] == "n1"


# ─────────────────────────────────────────────────────────────────────────────
# /dashboard HTML endpoint
# ─────────────────────────────────────────────────────────────────────────────


class TestDashboardHtmlEndpoint:
    def _make_api(self, query_params: dict[str, str]) -> NoteProductionDashboardAPI:
        api: NoteProductionDashboardAPI = NoteProductionDashboardAPI.__new__(
            NoteProductionDashboardAPI
        )
        api.request = SimpleNamespace(
            query_params=query_params,
            path_params={},
            headers={},
        )
        return api

    def test_returns_200(self) -> None:
        """GET /dashboard returns HTTP 200."""
        from http import HTTPStatus

        api = self._make_api({"period": "daily", "week_start": "sunday"})
        responses = api.dashboard_page()
        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.OK

    def test_html_contains_period_toggles(self) -> None:
        """HTML page contains Daily / Weekly / Monthly toggle buttons."""
        api = self._make_api({})
        html = api.dashboard_page()[0].content.decode("utf-8")
        assert "Daily" in html
        assert "Weekly" in html
        assert "Monthly" in html

    def test_html_contains_week_start_toggles(self) -> None:
        """HTML page contains Sun / Mon week-start toggles."""
        api = self._make_api({})
        html = api.dashboard_page()[0].content.decode("utf-8")
        assert "Sun" in html
        assert "Mon" in html

    def test_html_contains_plugin_api_url(self) -> None:
        """HTML embeds the correct API base path for data fetches."""
        api = self._make_api({})
        html = api.dashboard_page()[0].content.decode("utf-8")
        assert "/plugin-io/api/note_production_dashboard/" in html

    def test_invalid_query_params_default_gracefully(self) -> None:
        """Unknown query params are safely ignored (no 500)."""
        from http import HTTPStatus

        api = self._make_api({"period": "century", "week_start": "friday"})
        assert api.dashboard_page()[0].status_code == HTTPStatus.OK

    def test_credentials_same_origin_in_js(self) -> None:
        """JS fetch calls use 'same-origin' so the session cookie travels."""
        api = self._make_api({})
        html = api.dashboard_page()[0].content.decode("utf-8")
        assert "same-origin" in html

    def test_empty_state_text_in_html(self) -> None:
        """HTML contains the empty-state message path that JS injects."""
        api = self._make_api({})
        html = api.dashboard_page()[0].content.decode("utf-8")
        assert "No locked notes in this period" in html


# ─────────────────────────────────────────────────────────────────────────────
# Auth: class hierarchy configuration
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthConfiguration:
    def test_api_inherits_staff_session_mixin(self) -> None:
        """NoteProductionDashboardAPI must inherit StaffSessionAuthMixin for auth."""
        assert issubclass(NoteProductionDashboardAPI, StaffSessionAuthMixin)
        assert issubclass(NoteProductionDashboardAPI, SimpleAPI)

    def test_application_is_application_subclass(self) -> None:
        """NoteProductionDashboardApp must subclass Application."""
        from canvas_sdk.handlers.application import Application

        from note_production_dashboard.applications.dashboard_app import (
            NoteProductionDashboardApp,
        )

        assert issubclass(NoteProductionDashboardApp, Application)


# ─────────────────────────────────────────────────────────────────────────────
# _render_dashboard_html (unit)
# ─────────────────────────────────────────────────────────────────────────────


class TestRenderDashboardHtml:
    def test_cache_bust_token_in_output(self) -> None:
        """Cache-bust token appears in the rendered HTML."""
        html = _render_dashboard_html("daily", "sunday", "12345")
        assert "12345" in html

    def test_week_start_seeded_in_js(self) -> None:
        """The JS init seeds weekStart from the server-rendered value."""
        html = _render_dashboard_html("weekly", "monday", "99")
        assert "monday" in html

    def test_period_seeded_in_js(self) -> None:
        """The JS init seeds period from the server-rendered value."""
        html = _render_dashboard_html("monthly", "sunday", "99")
        assert "monthly" in html

    def test_html_is_a_string(self) -> None:
        """Function returns a non-empty string."""
        result = _render_dashboard_html("daily", "sunday", "tok")
        assert isinstance(result, str)
        assert len(result) > 100
