"""Tests for chart_command_search handlers."""

import json
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from chart_command_search.handlers.search_api import ChartSearchAPI
from chart_command_search.searchers import (
    CATEGORY_SEARCHERS,
    COMMAND_TYPE_LABELS,
    build_command_link,
    build_note_link,
    extract_body_text,
    extract_command_details,
    extract_command_heading,
    fmt_date,
    fmt_datetime,
    make_result,
    match_snippet,
    note_type_name,
    readable_value,
    search_labs,
    search_medications,
    strip_html,
)
from chart_command_search.searchers.constants import _MED_COMMAND_KEYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_obj(**kwargs: Any) -> MagicMock:
    """Create a MagicMock with the given attributes."""
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _get_json(response: Any) -> dict:
    return json.loads(getattr(response, "content"))


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


class TestFmtDate:
    def test_none(self) -> None:
        assert fmt_date(None) == ""

    def test_date(self) -> None:
        assert fmt_date(datetime(2024, 1, 15)) == "2024-01-15T00:00:00+00:00"

    def test_string(self) -> None:
        assert fmt_date("2024-01-15") == "2024-01-15"


class TestFmtDatetime:
    def test_none(self) -> None:
        assert fmt_datetime(None) == ""

    def test_datetime(self) -> None:
        assert fmt_datetime(datetime(2024, 1, 15, 10, 30)) == "2024-01-15T10:30:00+00:00"


class TestStripHtml:
    def test_strips_tags(self) -> None:
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_plain_text(self) -> None:
        assert strip_html("no tags") == "no tags"


class TestMakeResult:
    def test_basic(self) -> None:
        r = make_result(
            category="command",
            type_label="Prescribe",
            summary="Test med",
            details=[{"label": "Sig", "value": "take daily"}],
        )
        assert r["category"] == "command"
        assert r["summary"] == "Test med"

    def test_empty_details_filtered(self) -> None:
        r = make_result(
            category="note",
            type_label="Note",
            summary="",
            details=[{"label": "X", "value": ""}, {"label": "Y", "value": "data"}],
        )
        assert len(r["details"]) == 1


class TestReadableValue:
    def test_string(self) -> None:
        assert readable_value("hello") == "hello"

    def test_list_of_dicts(self) -> None:
        val = [{"text": "A"}, {"text": "B"}]
        assert readable_value(val) == "A, B"

    def test_none(self) -> None:
        assert readable_value(None) == ""


class TestMatchSnippet:
    def test_match(self) -> None:
        text = "a" * 100 + "KEYWORD" + "b" * 100
        snippet = match_snippet("KEYWORD", text)
        assert "KEYWORD" in snippet

    def test_no_match(self) -> None:
        assert match_snippet("missing", "some text") == ""


class TestExtractCommandHeading:
    def test_prescribe(self) -> None:
        data = {"prescribe": {"text": "Lisinopril 10mg"}}
        assert extract_command_heading("prescribe", data) == "Lisinopril 10mg"

    def test_plan(self) -> None:
        data = {"narrative": "Follow up in 2 weeks"}
        assert extract_command_heading("plan", data) == "Follow up in 2 weeks"


class TestExtractCommandDetails:
    def test_prescribe_details(self) -> None:
        data = {
            "prescribe": {"text": "Med"},
            "sig": "take daily",
            "quantity_to_dispense": "30",
        }
        details = extract_command_details("prescribe", data)
        labels = [d["label"] for d in details]
        assert "Sig" in labels


class TestBuildNoteLink:
    def test_builds_link(self) -> None:
        note = _mock_obj(dbid=42)
        link = build_note_link("patient-uuid", note)
        assert link == "/patient/patient-uuid#noteId=42"

    def test_no_dbid(self) -> None:
        note = _mock_obj(dbid=None)
        assert build_note_link("p", note) == ""


class TestBuildCommandLink:
    def test_full_link(self) -> None:
        note = _mock_obj(dbid=10)
        cmd = _mock_obj(
            note=note,
            anchor_object_dbid=99,
            schema_key="prescribe",
        )
        link = build_command_link("patient-uuid", cmd)
        assert "noteId=10" in link
        assert "commandId=99" in link


class TestCategorySearchers:
    def test_all_registered(self) -> None:
        expected = {
            "commands", "appointments", "letters", "messages", "notes", "labs",
        }
        assert set(CATEGORY_SEARCHERS.keys()) == expected

    def test_callable(self) -> None:
        for name, fn in CATEGORY_SEARCHERS.items():
            assert callable(fn), f"{name} is not callable"


# ---------------------------------------------------------------------------
# search_appointments tests
# ---------------------------------------------------------------------------


class TestSearchAppointmentsStatusLabels:
    """Test that appointment status labels reflect raw DB status (no promotion logic)."""

    @patch("chart_command_search.searchers.appointments.NoteType")
    @patch("chart_command_search.searchers.appointments.Note")
    @patch("chart_command_search.searchers.appointments.Appointment")
    def test_shows_raw_status_label(
        self, mock_appt_cls: Any, mock_note_cls: Any, mock_nt_cls: Any
    ) -> None:
        # Appointments display their raw DB status directly — no promotion
        # to "Completed" based on note lock state.
        note = _mock_obj(
            dbid=1,
            provider=None,
            note_type_version=None,
            current_state=None,
            body=None,
        )
        note.commands.all.return_value = []

        appt = _mock_obj(
            status="confirmed",
            provider=None,
            duration_minutes=30,
            comment="",
            description="Visit",
            note_type_id=None,
            note_id=1,
            start_time=datetime(2024, 1, 15, 10, 0),
        )

        # Create a proper mock chain for the queryset
        qs_mock = MagicMock()
        qs_mock.filter.return_value = qs_mock
        qs_mock.order_by.return_value.__getitem__ = lambda self, s: [appt]

        def filter_side_effect(*args: Any, **kwargs: Any) -> Any:
            # First call: Q(...), entered_in_error__isnull=True
            if "entered_in_error__isnull" in kwargs:
                chain_mock = MagicMock()
                chain_mock.select_related.return_value.distinct.return_value = qs_mock
                return chain_mock
            # This shouldn't be reached in these specific tests
            return MagicMock()

        mock_appt_cls.objects.filter.side_effect = filter_side_effect

        mock_nt_cls.objects.filter.return_value = []

        note_qs = mock_note_cls.objects.filter.return_value
        note_qs.select_related.return_value.prefetch_related.return_value = [note]

        results = CATEGORY_SEARCHERS["appointments"]("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["state"] == "Confirmed"
        assert results[0]["state_class"] == "confirmed"

    @patch("chart_command_search.searchers.appointments.NoteType")
    @patch("chart_command_search.searchers.appointments.Note")
    @patch("chart_command_search.searchers.appointments.Appointment")
    def test_roomed_status_shows_roomed_label(
        self, mock_appt_cls: Any, mock_note_cls: Any, mock_nt_cls: Any
    ) -> None:
        # An in-progress appointment with status "roomed" should display
        # "Roomed" — the raw DB value, regardless of any note state.
        note = _mock_obj(
            dbid=1,
            provider=None,
            note_type_version=None,
            current_state=None,
            body=None,
        )
        note.commands.all.return_value = []

        appt = _mock_obj(
            status="roomed",
            provider=None,
            duration_minutes=30,
            comment="",
            description="Visit",
            note_type_id=None,
            note_id=1,
            start_time=datetime(2024, 1, 15, 10, 0),
        )

        # Create a proper mock chain for the queryset
        qs_mock = MagicMock()
        qs_mock.filter.return_value = qs_mock
        qs_mock.order_by.return_value.__getitem__ = lambda self, s: [appt]

        def filter_side_effect(*args: Any, **kwargs: Any) -> Any:
            # First call: Q(...), entered_in_error__isnull=True
            if "entered_in_error__isnull" in kwargs:
                chain_mock = MagicMock()
                chain_mock.select_related.return_value.distinct.return_value = qs_mock
                return chain_mock
            # This shouldn't be reached in these specific tests
            return MagicMock()

        mock_appt_cls.objects.filter.side_effect = filter_side_effect

        mock_nt_cls.objects.filter.return_value = []

        note_qs = mock_note_cls.objects.filter.return_value
        note_qs.select_related.return_value.prefetch_related.return_value = [note]

        results = CATEGORY_SEARCHERS["appointments"]("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["state"] == "Roomed"
        assert results[0]["state_class"] == "roomed"

    @patch("chart_command_search.searchers.appointments.NoteType")
    @patch("chart_command_search.searchers.appointments.Note")
    @patch("chart_command_search.searchers.appointments.Appointment")
    def test_terminal_statuses_keep_original_label(
        self, mock_appt_cls: Any, mock_note_cls: Any, mock_nt_cls: Any
    ) -> None:
        # Terminal statuses (noshowed, cancelled, exited) display their raw DB
        # labels directly — no special promotion logic.
        note = _mock_obj(
            dbid=1,
            provider=None,
            note_type_version=None,
            current_state=None,
            body=None,
        )
        note.commands.all.return_value = []

        for terminal_status, expected_label in [
            ("exited", "Exited"),
            ("noshowed", "No-showed"),
            ("cancelled", "Cancelled"),
        ]:
            appt = _mock_obj(
                status=terminal_status,
                provider=None,
                duration_minutes=30,
                comment="",
                description="Visit",
                note_type_id=None,
                note_id=1,
                start_time=datetime(2024, 1, 15, 10, 0),
            )

            # Create a proper mock chain for the queryset
            qs_mock = MagicMock()
            qs_mock.filter.return_value = qs_mock
            qs_mock.order_by.return_value.__getitem__ = lambda self, s: [appt]

            def filter_side_effect(*args: Any, **kwargs: Any) -> Any:
                # First call: Q(...), entered_in_error__isnull=True
                if "entered_in_error__isnull" in kwargs:
                    chain_mock = MagicMock()
                    chain_mock.select_related.return_value.distinct.return_value = qs_mock
                    return chain_mock
                # This shouldn't be reached in these specific tests
                return MagicMock()

            mock_appt_cls.objects.filter.side_effect = filter_side_effect
            mock_nt_cls.objects.filter.return_value = []

            note_qs = mock_note_cls.objects.filter.return_value
            note_qs.select_related.return_value.prefetch_related.return_value = [note]

            results = CATEGORY_SEARCHERS["appointments"]("patient-1", "", "")
            assert len(results) == 1, f"Expected 1 result for {terminal_status}"
            assert results[0]["state"] == expected_label, (
                f"Expected '{expected_label}' for terminal status '{terminal_status}', "
                f"got '{results[0]['state']}'"
            )


# ---------------------------------------------------------------------------
# search_labs tests
# ---------------------------------------------------------------------------


class TestSearchLabs:
    @patch("chart_command_search.searchers.labs.LabValue")
    @patch("chart_command_search.searchers.labs.LabTest")
    @patch("chart_command_search.searchers.labs.LabReview")
    @patch("chart_command_search.searchers.labs.LabReport")
    def test_basic_lab_search(
        self,
        mock_report_cls: Any,
        mock_review_cls: Any,
        mock_test_cls: Any,
        mock_value_cls: Any,
    ) -> None:
        report = _mock_obj(
            dbid=10,
            custom_document_name="CBC Panel",
            requisition_number="REQ-001",
            date_performed=datetime(2024, 3, 1),
            transmission_type="HL7",
        )

        qs = mock_report_cls.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [report]

        review = _mock_obj(lab_report_id=10, status="completed")
        mock_review_cls.objects.filter.return_value = [review]

        test_obj = _mock_obj(
            dbid=20,
            lab_report_id=10,
            ontology_test_name="Complete Blood Count",
            status="RE",
            lab_order=None,
        )
        mock_test_cls.objects.filter.return_value.select_related.return_value = [
            test_obj
        ]

        mock_value_cls.objects.filter.return_value = []

        results = search_labs("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["category"] == "lab"
        assert results[0]["summary"] == "CBC Panel"
        assert results[0]["state"] == "Reviewed"
        assert results[0]["state_class"] == "completed"

    @patch("chart_command_search.searchers.labs.LabValue")
    @patch("chart_command_search.searchers.labs.LabTest")
    @patch("chart_command_search.searchers.labs.LabReview")
    @patch("chart_command_search.searchers.labs.LabReport")
    def test_abnormal_flag(
        self,
        mock_report_cls: Any,
        mock_review_cls: Any,
        mock_test_cls: Any,
        mock_value_cls: Any,
    ) -> None:
        report = _mock_obj(
            dbid=10,
            custom_document_name="",
            requisition_number="",
            date_performed=datetime(2024, 3, 1),
            transmission_type="",
        )

        qs = mock_report_cls.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [report]

        mock_review_cls.objects.filter.return_value = []

        test_obj = _mock_obj(
            dbid=20,
            lab_report_id=10,
            ontology_test_name="Glucose",
            status="RE",
            lab_order=None,
        )
        mock_test_cls.objects.filter.return_value.select_related.return_value = [
            test_obj
        ]

        value = _mock_obj(lab_test_id=20, abnormal_flag="H")
        mock_value_cls.objects.filter.return_value = [value]

        results = search_labs("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["state"] == "Abnormal"
        assert results[0]["state_class"] == "cancelled"
        # Summary should fall back to test name when no custom_document_name
        assert results[0]["summary"] == "Glucose"

    @patch("chart_command_search.searchers.labs.LabValue")
    @patch("chart_command_search.searchers.labs.LabTest")
    @patch("chart_command_search.searchers.labs.LabReview")
    @patch("chart_command_search.searchers.labs.LabReport")
    def test_text_search(
        self,
        mock_report_cls: Any,
        mock_review_cls: Any,
        mock_test_cls: Any,
        mock_value_cls: Any,
    ) -> None:
        report1 = _mock_obj(
            dbid=10,
            custom_document_name="CBC",
            requisition_number="",
            date_performed=datetime(2024, 3, 1),
            transmission_type="",
        )
        report2 = _mock_obj(
            dbid=11,
            custom_document_name="Lipid Panel",
            requisition_number="",
            date_performed=datetime(2024, 3, 2),
            transmission_type="",
        )

        qs = mock_report_cls.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [report1, report2]

        mock_review_cls.objects.filter.return_value = []
        mock_test_cls.objects.filter.return_value.select_related.return_value = []
        mock_value_cls.objects.filter.return_value = []

        results = search_labs("patient-1", "CBC", "")
        assert len(results) == 1
        assert results[0]["summary"] == "CBC"

    @patch("chart_command_search.searchers.labs.LabValue")
    @patch("chart_command_search.searchers.labs.LabTest")
    @patch("chart_command_search.searchers.labs.LabReview")
    @patch("chart_command_search.searchers.labs.LabReport")
    def test_status_filter_reviewed(
        self,
        mock_report_cls: Any,
        mock_review_cls: Any,
        mock_test_cls: Any,
        mock_value_cls: Any,
    ) -> None:
        report = _mock_obj(
            dbid=10,
            custom_document_name="Panel",
            requisition_number="",
            date_performed=datetime(2024, 3, 1),
            transmission_type="",
        )

        qs = mock_report_cls.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [report]

        # No review → not reviewed → should be excluded by "reviewed" filter
        mock_review_cls.objects.filter.return_value = []
        mock_test_cls.objects.filter.return_value.select_related.return_value = []
        mock_value_cls.objects.filter.return_value = []

        results = search_labs("patient-1", "", "reviewed")
        assert len(results) == 0

    @patch("chart_command_search.searchers.labs.LabValue")
    @patch("chart_command_search.searchers.labs.LabTest")
    @patch("chart_command_search.searchers.labs.LabReview")
    @patch("chart_command_search.searchers.labs.LabReport")
    def test_empty_results(
        self,
        mock_report_cls: Any,
        mock_review_cls: Any,
        mock_test_cls: Any,
        mock_value_cls: Any,
    ) -> None:
        qs = mock_report_cls.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: []

        results = search_labs("patient-1", "", "")
        assert results == []


# ---------------------------------------------------------------------------
# search_medications tests
# ---------------------------------------------------------------------------


class TestSearchMedications:
    """Medication search now queries Commands with medication schema keys."""

    def _make_med_command(self, **overrides: Any) -> MagicMock:
        """Create a mock Command for a medication command."""
        note = _mock_obj(
            dbid=overrides.pop("note_dbid", 1),
            datetime_of_service=overrides.pop("dos", datetime(2024, 1, 15)),
            note_type_version=None,
        )
        defaults: dict[str, Any] = {
            "schema_key": "prescribe",
            "state": "committed",
            "entered_in_error": False,
            "note": note,
            "anchor_object_dbid": 99,
            "data": {"prescribe": {"text": "Lisinopril 10mg"}},
        }
        defaults.update(overrides)
        return _mock_obj(**defaults)

    @patch("chart_command_search.searchers.commands.Prescription", None)
    @patch("chart_command_search.searchers.commands.Command")
    def test_basic_med_command_search(self, mock_cmd_cls: Any) -> None:
        cmd = self._make_med_command()
        qs = mock_cmd_cls.objects.filter.return_value.exclude.return_value
        # search_medications calls filter(...).select_related(...)
        qs2 = mock_cmd_cls.objects.filter.return_value
        qs2.select_related.return_value.filter.return_value = qs2.select_related.return_value
        qs2.select_related.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: [cmd]
        )

        results = search_medications("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["category"] == "command"
        assert results[0]["summary"] == "Lisinopril 10mg"
        assert results[0]["state"] == "Committed"
        assert results[0]["state_class"] == "committed"

    @patch("chart_command_search.searchers.commands.Prescription")
    @patch("chart_command_search.searchers.commands.Command")
    def test_prescription_status_badge(
        self, mock_cmd_cls: Any, mock_rx_cls: Any
    ) -> None:
        cmd = self._make_med_command(note_dbid=10)
        qs = mock_cmd_cls.objects.filter.return_value
        qs.select_related.return_value.filter.return_value = qs.select_related.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: [cmd]
        )

        rx = _mock_obj(note_id=10, status="ultimately-accepted")
        mock_rx_cls.objects.filter.return_value = [rx]

        results = search_medications("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["state"] == "Accepted"
        assert results[0]["state_class"] == "completed"

    @patch("chart_command_search.searchers.commands.Prescription", None)
    @patch("chart_command_search.searchers.commands.Command")
    def test_fallback_uncommitted(self, mock_cmd_cls: Any) -> None:
        cmd = self._make_med_command(state="uncommitted")
        qs = mock_cmd_cls.objects.filter.return_value
        qs.select_related.return_value.filter.return_value = qs.select_related.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: [cmd]
        )

        results = search_medications("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["state"] == "Uncommitted"
        assert results[0]["state_class"] == "uncommitted"

    @patch("chart_command_search.searchers.commands.Prescription", None)
    @patch("chart_command_search.searchers.commands.Command")
    def test_empty_results(self, mock_cmd_cls: Any) -> None:
        qs = mock_cmd_cls.objects.filter.return_value
        qs.select_related.return_value.filter.return_value = qs.select_related.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: []
        )

        results = search_medications("patient-1", "", "")
        assert results == []

    @patch("chart_command_search.searchers.commands.Prescription")
    @patch("chart_command_search.searchers.commands.Command")
    def test_error_badge(self, mock_cmd_cls: Any, mock_rx_cls: Any) -> None:
        cmd = self._make_med_command(note_dbid=10)
        qs = mock_cmd_cls.objects.filter.return_value
        qs.select_related.return_value.filter.return_value = qs.select_related.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: [cmd]
        )

        rx = _mock_obj(note_id=10, status="error")
        mock_rx_cls.objects.filter.return_value = [rx]

        results = search_medications("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["state"] == "Error"
        assert results[0]["state_class"] == "cancelled"


class TestCommandsExcludesMedKeys:
    """Commands search should exclude medication and lab order command schema keys."""

    @patch("chart_command_search.searchers.commands.Command")
    def test_exclude_called(self, mock_cmd_cls: Any) -> None:
        qs = mock_cmd_cls.objects.filter.return_value
        qs.exclude.return_value = qs
        qs.select_related.return_value = qs
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: []

        CATEGORY_SEARCHERS["commands"]("patient-1", "", "")

        # Verify .exclude was called with med command keys only (labOrder is back in generic commands)
        mock_cmd_cls.objects.filter.return_value.exclude.assert_called_once()
        call_kwargs = mock_cmd_cls.objects.filter.return_value.exclude.call_args
        assert set(call_kwargs.kwargs["schema_key__in"]) == _MED_COMMAND_KEYS
