"""Tests for intake_api: pure helpers and the IntakeAPI handler."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from api.intake_api import (
    IntakeAPI,
    filter_rows_by_licensed_states,
    get_licensed_states,
    humanize_pending,
    sort_rows,
)


def _make_api():
    """Build an IntakeAPI bypassing the canvas_sdk SimpleAPI __init__."""
    api_obj = IntakeAPI.__new__(IntakeAPI)
    api_obj.request = MagicMock()
    api_obj.secrets = {}
    return api_obj


def _row(*, name="Patient", state="CA", seconds=3600):
    return {
        "patient_id": f"id-{name}",
        "patient_name": name,
        "state": state,
        "time_pending_seconds": seconds,
        "time_pending_display": humanize_pending(timedelta(seconds=seconds)),
        "note_url": "https://example.canvasmedical.com/patient/id#noteId=1",
        "note_dbid": 1,
    }


class TestFilterRowsByLicensedStates:
    def test_none_returns_all_rows_unfiltered(self):
        rows = [_row(state="CA"), _row(state="NY"), _row(state=None)]
        assert filter_rows_by_licensed_states(rows, None) == rows

    def test_empty_set_filters_everything_out(self):
        rows = [_row(state="CA"), _row(state="NY")]
        assert filter_rows_by_licensed_states(rows, set()) == []

    def test_keeps_only_matching_states(self):
        rows = [_row(name="A", state="CA"), _row(name="B", state="NY"), _row(name="C", state="TX")]
        result = filter_rows_by_licensed_states(rows, {"CA", "TX"})
        assert [r["patient_name"] for r in result] == ["A", "C"]

    def test_excludes_rows_with_no_state_when_filtering(self):
        rows = [_row(name="A", state="CA"), _row(name="B", state=None)]
        result = filter_rows_by_licensed_states(rows, {"CA"})
        assert [r["patient_name"] for r in result] == ["A"]

    def test_state_match_is_exact_not_substring(self):
        rows = [_row(name="A", state="CA"), _row(name="B", state="CAL")]
        result = filter_rows_by_licensed_states(rows, {"CA"})
        assert [r["patient_name"] for r in result] == ["A"]


class TestSortRows:
    def test_default_sort_is_oldest_pending_first(self):
        rows = [_row(name="A", seconds=60), _row(name="B", seconds=3600), _row(name="C", seconds=300)]
        result = sort_rows(rows, sort_by="", sort_dir="")
        assert [r["patient_name"] for r in result] == ["B", "C", "A"]

    def test_sort_by_patient_asc(self):
        rows = [_row(name="Charlie"), _row(name="alice"), _row(name="Bob")]
        result = sort_rows(rows, sort_by="patient", sort_dir="asc")
        assert [r["patient_name"] for r in result] == ["alice", "Bob", "Charlie"]

    def test_sort_by_patient_desc(self):
        rows = [_row(name="Charlie"), _row(name="alice"), _row(name="Bob")]
        result = sort_rows(rows, sort_by="patient", sort_dir="desc")
        assert [r["patient_name"] for r in result] == ["Charlie", "Bob", "alice"]

    def test_sort_by_state_asc(self):
        rows = [_row(name="A", state="TX"), _row(name="B", state="CA"), _row(name="C", state="NY")]
        result = sort_rows(rows, sort_by="state", sort_dir="asc")
        assert [r["state"] for r in result] == ["CA", "NY", "TX"]

    def test_sort_by_time_pending_desc_is_oldest_first(self):
        rows = [_row(name="A", seconds=60), _row(name="B", seconds=3600)]
        result = sort_rows(rows, sort_by="time_pending", sort_dir="desc")
        assert [r["patient_name"] for r in result] == ["B", "A"]

    def test_sort_by_time_pending_asc_is_newest_first(self):
        rows = [_row(name="A", seconds=60), _row(name="B", seconds=3600)]
        result = sort_rows(rows, sort_by="time_pending", sort_dir="asc")
        assert [r["patient_name"] for r in result] == ["A", "B"]


class TestHumanizePending:
    def test_minutes_only(self):
        assert humanize_pending(timedelta(minutes=5)) == "5m"

    def test_hours_and_minutes(self):
        assert humanize_pending(timedelta(hours=2, minutes=14)) == "2h 14m"

    def test_days_and_hours(self):
        assert humanize_pending(timedelta(days=3, hours=7)) == "3d 7h"

    def test_zero(self):
        assert humanize_pending(timedelta()) == "0m"

    def test_negative_clamped_to_zero(self):
        assert humanize_pending(timedelta(seconds=-300)) == "0m"


class TestGetLicensedStates:
    @patch("api.intake_api.StaffLicense")
    def test_returns_set_of_state_codes(self, mock_license_cls):
        chain = mock_license_cls.objects.filter.return_value.exclude.return_value
        chain.values_list.return_value = ["CA", "NY", "TX"]
        mock_license_cls.LicenseType.STATE_LICENSE = "STATE"
        today = date(2026, 5, 13)

        result = get_licensed_states("staff-1", today)

        assert result == {"CA", "NY", "TX"}
        mock_license_cls.objects.filter.assert_called_once_with(
            staff__id="staff-1",
            license_type="STATE",
            expiration_date__gte=today,
            state__isnull=False,
        )
        mock_license_cls.objects.filter.return_value.exclude.assert_called_once_with(state="")
        chain.values_list.assert_called_once_with("state", flat=True)

    @patch("api.intake_api.StaffLicense")
    def test_returns_none_when_no_active_licenses(self, mock_license_cls):
        chain = mock_license_cls.objects.filter.return_value.exclude.return_value
        chain.values_list.return_value = []

        result = get_licensed_states("staff-1", date(2026, 5, 13))

        assert result is None


class TestIntakeNoteTypes:
    def test_parses_comma_separated(self):
        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "New Patient Intake, Follow-up Intake"}
        assert api_obj._intake_note_types() == ["New Patient Intake", "Follow-up Intake"]

    def test_strips_surrounding_quotes(self):
        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": '"Intake, Other"'}
        assert api_obj._intake_note_types() == ["Intake", "Other"]

    def test_missing_secret_returns_empty(self):
        api_obj = _make_api()
        api_obj.secrets = {}
        assert api_obj._intake_note_types() == []

    def test_empty_string_returns_empty(self):
        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": ""}
        assert api_obj._intake_note_types() == []


class TestInstanceUrl:
    def test_strips_trailing_slash(self):
        api_obj = _make_api()
        api_obj.secrets = {"CANVAS_INSTANCE_URL": "https://x.canvasmedical.com/"}
        assert api_obj._instance_url() == "https://x.canvasmedical.com"

    def test_strips_quotes(self):
        api_obj = _make_api()
        api_obj.secrets = {"CANVAS_INSTANCE_URL": '"https://x.canvasmedical.com"'}
        assert api_obj._instance_url() == "https://x.canvasmedical.com"

    def test_missing_returns_empty(self):
        api_obj = _make_api()
        api_obj.secrets = {}
        assert api_obj._instance_url() == ""


class TestShellContext:
    @patch("api.intake_api.Staff")
    def test_returns_first_and_last_name(self, mock_staff_cls):
        mock_staff_cls.objects.values.return_value.get.return_value = {
            "first_name": "Allison",
            "last_name": "Smith",
        }
        api_obj = _make_api()
        api_obj.request.headers = {"canvas-logged-in-user-id": "staff-1"}

        ctx = api_obj._shell_context()

        assert ctx == {"first_name": "Allison", "last_name": "Smith"}
        mock_staff_cls.objects.values.assert_called_once_with("first_name", "last_name")
        mock_staff_cls.objects.values.return_value.get.assert_called_once_with(id="staff-1")


class TestBuildPendingIntakeRows:
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_empty_when_no_note_types_configured(self, mock_addr, mock_note):
        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "", "CANVAS_INSTANCE_URL": "https://x"}

        result = api_obj._build_pending_intake_rows()

        assert result == []
        mock_note.objects.filter.assert_not_called()
        mock_addr.objects.filter.assert_not_called()

    @patch("api.intake_api.Prefetch")
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_builds_row_with_home_state_and_absolute_deep_link(self, mock_addr, mock_note, mock_prefetch):
        patient = MagicMock()
        patient.id = "pt-1"
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        home = MagicMock()
        home.state_code = "ca"
        patient.home_addresses_cache = [home]

        note = MagicMock()
        note.patient = patient
        note.dbid = 42
        note.created = datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)

        chain = mock_note.objects.filter.return_value.select_related.return_value
        chain.prefetch_related.return_value = [note]

        api_obj = _make_api()
        api_obj.secrets = {
            "INTAKE_NOTE_TYPES": "New Patient Intake",
            "CANVAS_INSTANCE_URL": "https://example.canvasmedical.com",
        }

        rows = api_obj._build_pending_intake_rows()

        assert len(rows) == 1
        row = rows[0]
        assert row["patient_id"] == "pt-1"
        assert row["patient_name"] == "Jane Doe"
        assert row["state"] == "CA"
        assert row["note_dbid"] == 42
        assert row["note_url"] == "https://example.canvasmedical.com/patient/pt-1#noteId=42"
        assert row["time_pending_display"].startswith("2h")
        assert 8800 < row["time_pending_seconds"] < 9200
        mock_note.objects.filter.return_value.select_related.assert_called_once_with("patient")

    @patch("api.intake_api.Prefetch")
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_skips_notes_with_no_patient(self, mock_addr, mock_note, mock_prefetch):
        note = MagicMock()
        note.patient = None
        chain = mock_note.objects.filter.return_value.select_related.return_value
        chain.prefetch_related.return_value = [note]

        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "Intake", "CANVAS_INSTANCE_URL": ""}

        rows = api_obj._build_pending_intake_rows()

        assert rows == []

    @patch("api.intake_api.Prefetch")
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_state_is_none_when_patient_has_no_home_address(self, mock_addr, mock_note, mock_prefetch):
        patient = MagicMock()
        patient.id = "pt-1"
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        patient.home_addresses_cache = []
        note = MagicMock()
        note.patient = patient
        note.dbid = 1
        note.created = datetime.now(timezone.utc) - timedelta(minutes=15)

        chain = mock_note.objects.filter.return_value.select_related.return_value
        chain.prefetch_related.return_value = [note]

        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "Intake", "CANVAS_INSTANCE_URL": ""}

        rows = api_obj._build_pending_intake_rows()

        assert rows[0]["state"] is None

    @patch("api.intake_api.Prefetch")
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_converts_non_datetime_created_via_arrow(self, mock_addr, mock_note, mock_prefetch):
        patient = MagicMock()
        patient.id = "pt-1"
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        patient.home_addresses_cache = []
        note = MagicMock()
        note.patient = patient
        note.dbid = 1
        # Non-datetime value triggers the arrow.get(...).datetime branch
        note.created = "2026-05-13T10:00:00+00:00"
        chain = mock_note.objects.filter.return_value.select_related.return_value
        chain.prefetch_related.return_value = [note]

        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "Intake", "CANVAS_INSTANCE_URL": ""}

        rows = api_obj._build_pending_intake_rows()

        assert len(rows) == 1
        assert rows[0]["time_pending_seconds"] > 0

    @patch("api.intake_api.Prefetch")
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_note_url_falls_back_to_relative_path_without_instance_url(self, mock_addr, mock_note, mock_prefetch):
        patient = MagicMock()
        patient.id = "pt-9"
        patient.first_name = "A"
        patient.last_name = "B"
        patient.home_addresses_cache = []
        note = MagicMock()
        note.patient = patient
        note.dbid = 9
        note.created = datetime.now(timezone.utc) - timedelta(minutes=5)
        chain = mock_note.objects.filter.return_value.select_related.return_value
        chain.prefetch_related.return_value = [note]

        api_obj = _make_api()
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "Intake", "CANVAS_INSTANCE_URL": ""}

        rows = api_obj._build_pending_intake_rows()

        assert rows[0]["note_url"] == "/patient/pt-9#noteId=9"


class TestIndexEndpoint:
    @patch("api.intake_api.HTMLResponse")
    @patch("api.intake_api.render_to_string")
    @patch("api.intake_api.Staff")
    def test_renders_index_with_staff_name(self, mock_staff, mock_render, mock_html_response):
        mock_staff.objects.values.return_value.get.return_value = {
            "first_name": "A", "last_name": "B",
        }
        mock_render.return_value = "<html/>"
        mock_html_response.return_value = "html-resp"

        api_obj = _make_api()
        api_obj.request.headers = {"canvas-logged-in-user-id": "staff-1"}

        result = api_obj.index()

        assert result == ["html-resp"]
        mock_render.assert_called_once_with(
            "static/index.html", {"first_name": "A", "last_name": "B"}
        )


class TestStaticAssetEndpoints:
    @patch("api.intake_api.Response")
    @patch("api.intake_api.render_to_string")
    def test_get_css(self, mock_render, mock_response):
        mock_render.return_value = "body{}"
        mock_response.return_value = "css-resp"
        api_obj = _make_api()

        result = api_obj.get_css()

        assert result == ["css-resp"]
        mock_render.assert_called_once_with("static/styles.css")

    @patch("api.intake_api.Response")
    @patch("api.intake_api.render_to_string")
    def test_get_scripts(self, mock_render, mock_response):
        mock_render.return_value = "console.log()"
        mock_response.return_value = "js-resp"
        api_obj = _make_api()

        result = api_obj.get_scripts()

        assert result == ["js-resp"]
        mock_render.assert_called_once_with("static/scripts.js")


class TestGetTableEndpoint:
    @patch("api.intake_api.HTMLResponse")
    @patch("api.intake_api.render_to_string")
    @patch("api.intake_api.get_licensed_states")
    @patch("api.intake_api.Prefetch")
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_renders_with_license_filter_banner(
        self, mock_addr, mock_note, mock_prefetch, mock_get_states, mock_render, mock_html_response
    ):
        mock_get_states.return_value = {"CA"}
        chain = mock_note.objects.filter.return_value.select_related.return_value
        chain.prefetch_related.return_value = []
        mock_render.return_value = "<table/>"
        mock_html_response.return_value = "ok"

        api_obj = _make_api()
        api_obj.request.headers = {"canvas-logged-in-user-id": "staff-1"}
        api_obj.request.query_params = {"sort_by": "patient", "sort_dir": "asc"}
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "Intake", "CANVAS_INSTANCE_URL": ""}

        result = api_obj.get_table()

        assert result == ["ok"]
        template_name, ctx = mock_render.call_args.args
        assert template_name == "static/table.html"
        assert ctx["sort_by"] == "patient"
        assert ctx["sort_dir"] == "asc"
        assert ctx["has_license_filter"] is True
        assert ctx["licensed_states"] == ["CA"]
        assert ctx["total_count"] == 0

    @patch("api.intake_api.HTMLResponse")
    @patch("api.intake_api.render_to_string")
    @patch("api.intake_api.get_licensed_states")
    @patch("api.intake_api.Prefetch")
    @patch("api.intake_api.Note")
    @patch("api.intake_api.PatientAddress")
    def test_defaults_to_desc_sort_and_shows_unfiltered_banner(
        self, mock_addr, mock_note, mock_prefetch, mock_get_states, mock_render, mock_html_response
    ):
        mock_get_states.return_value = None
        chain = mock_note.objects.filter.return_value.select_related.return_value
        chain.prefetch_related.return_value = []
        mock_render.return_value = "<table/>"
        mock_html_response.return_value = "ok"

        api_obj = _make_api()
        api_obj.request.headers = {"canvas-logged-in-user-id": "staff-1"}
        api_obj.request.query_params = {}
        api_obj.secrets = {"INTAKE_NOTE_TYPES": "Intake", "CANVAS_INSTANCE_URL": ""}

        api_obj.get_table()

        _, ctx = mock_render.call_args.args
        assert ctx["sort_by"] == ""
        assert ctx["sort_dir"] == "desc"
        assert ctx["has_license_filter"] is False
        assert ctx["licensed_states"] == []
