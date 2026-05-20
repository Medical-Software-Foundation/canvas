from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock

from chart_command_search.searchers.command_helpers import (
    extract_code,
    extract_command_details,
    extract_command_heading,
    readable_value,
)
from chart_command_search.searchers.helpers import (
    build_command_link,
    extract_body_text,
    fmt_date,
    match_snippet,
    note_type_name,
    parse_multi,
    resolve_command_query,
    staff_name,
)


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


class TestParseMulti:
    def test_all_returns_empty(self) -> None:
        assert parse_multi("all") == set()

    def test_empty_returns_empty(self) -> None:
        assert parse_multi("") == set()

    def test_single(self) -> None:
        assert parse_multi("active") == {"active"}

    def test_comma_separated(self) -> None:
        assert parse_multi("active,pending") == {"active", "pending"}

    def test_whitespace_trimmed(self) -> None:
        assert parse_multi(" a , b , c ") == {"a", "b", "c"}


class TestResolveCommandQuery:
    def test_abbreviation_match(self) -> None:
        q, matched = resolve_command_query("hpi")
        assert q == "hpi"
        assert "hpi" in matched

    def test_label_match(self) -> None:
        q, matched = resolve_command_query("prescribe")
        assert "prescribe" in matched

    def test_no_match(self) -> None:
        q, matched = resolve_command_query("zzzznotacommand")
        assert matched == set()

    def test_partial_label_match(self) -> None:
        q, matched = resolve_command_query("allergy")
        assert "allergy" in matched


class TestFmtDate:
    def test_date_only_object(self) -> None:
        d = date(2024, 3, 15)
        result = fmt_date(d)
        assert result == "Mar 15, 2024"

    def test_datetime_with_tz(self) -> None:
        from zoneinfo import ZoneInfo

        dt = datetime(2024, 3, 15, 10, 30, tzinfo=ZoneInfo("US/Eastern"))
        result = fmt_date(dt)
        assert "2024-03-15" in result

    def test_datetime_naive(self) -> None:
        dt = datetime(2024, 3, 15, 10, 30)
        result = fmt_date(dt)
        assert "2024-03-15" in result
        assert "+00:00" in result


class TestStaffName:
    def test_full_name(self) -> None:
        staff = _mock_obj(first_name="Jane", last_name="Doe")
        assert staff_name(staff) == "Jane Doe"

    def test_first_only(self) -> None:
        staff = _mock_obj(first_name="Jane", last_name="")
        assert staff_name(staff) == "Jane"

    def test_last_only(self) -> None:
        staff = _mock_obj(first_name="", last_name="Doe")
        assert staff_name(staff) == "Doe"


class TestNoteTypeName:
    def test_display_preferred(self) -> None:
        note = _mock_obj(note_type_version=_mock_obj(display="Office Visit", name="OV"))
        assert note_type_name(note) == "Office Visit"

    def test_name_fallback(self) -> None:
        note = _mock_obj(note_type_version=_mock_obj(display="", name="Office Visit"))
        assert note_type_name(note) == "Office Visit"

    def test_no_ntv(self) -> None:
        note = _mock_obj(note_type_version=None)
        assert note_type_name(note) == ""


class TestExtractBodyText:
    def test_none(self) -> None:
        assert extract_body_text(None) == ""

    def test_not_a_list(self) -> None:
        assert extract_body_text("string") == ""

    def test_empty_list(self) -> None:
        assert extract_body_text([]) == ""

    def test_text_items(self) -> None:
        body = [
            {"type": "text", "value": "First paragraph."},
            {"type": "text", "value": "Second paragraph."},
        ]
        assert extract_body_text(body) == "First paragraph. Second paragraph."

    def test_non_text_items_skipped(self) -> None:
        body = [
            {"type": "image", "value": "data:image/png..."},
            {"type": "text", "value": "Visible text"},
        ]
        assert extract_body_text(body) == "Visible text"

    def test_empty_text_values_skipped(self) -> None:
        body = [
            {"type": "text", "value": ""},
            {"type": "text", "value": "   "},
            {"type": "text", "value": "Content"},
        ]
        assert extract_body_text(body) == "Content"

    def test_non_string_value_skipped(self) -> None:
        body = [{"type": "text", "value": 123}]
        assert extract_body_text(body) == ""


class TestMatchSnippet:
    def test_empty_query(self) -> None:
        assert match_snippet("", "some text") == ""

    def test_empty_text(self) -> None:
        assert match_snippet("query", "") == ""

    def test_match_at_start(self) -> None:
        snippet = match_snippet("Hello", "Hello world")
        assert "Hello" in snippet

    def test_match_in_middle_with_ellipsis(self) -> None:
        text = "a" * 50 + "KEYWORD" + "b" * 50
        snippet = match_snippet("KEYWORD", text)
        assert "KEYWORD" in snippet
        assert snippet.startswith("...")


class TestBuildCommandLink:
    def test_note_only(self) -> None:
        cmd = _mock_obj(
            note=_mock_obj(dbid=10),
            anchor_object_dbid=None,
            schema_key="prescribe",
        )
        link = build_command_link("patient-1", cmd)
        assert link == "/patient/patient-1#noteId=10"
        assert "commandId" not in link

    def test_no_note(self) -> None:
        cmd = _mock_obj(note=None, anchor_object_dbid=None, schema_key="")
        assert build_command_link("patient-1", cmd) == ""

    def test_no_schema_key(self) -> None:
        cmd = _mock_obj(
            note=_mock_obj(dbid=10),
            anchor_object_dbid=99,
            schema_key="",
        )
        link = build_command_link("patient-1", cmd)
        assert link == "/patient/patient-1#noteId=10"


class TestReadableValue:
    def test_bool_true(self) -> None:
        assert readable_value(True) == "Yes"

    def test_bool_false(self) -> None:
        assert readable_value(False) == "No"

    def test_int(self) -> None:
        assert readable_value(42) == "42"

    def test_float(self) -> None:
        assert readable_value(3.14) == "3.14"

    def test_long_string_no_spaces(self) -> None:
        assert readable_value("a" * 101) == ""

    def test_long_string_with_spaces(self) -> None:
        val = "word " * 25
        assert readable_value(val) == val.strip()

    def test_list_of_strings(self) -> None:
        assert readable_value(["one", "two", "three"]) == "one, two, three"

    def test_dict_with_text(self) -> None:
        assert readable_value({"text": "Hello"}) == "Hello"

    def test_dict_with_label(self) -> None:
        assert readable_value({"label": "Label"}) == "Label"

    def test_dict_with_display(self) -> None:
        assert readable_value({"display": "Display"}) == "Display"

    def test_dict_with_date_fallback(self) -> None:
        assert readable_value({"date": "2024-01-01"}) == "2024-01-01"

    def test_dict_with_input_fallback(self) -> None:
        assert readable_value({"input": "user input"}) == "user input"

    def test_dict_with_value_fallback(self) -> None:
        assert readable_value({"value": "val"}) == "val"

    def test_dict_empty_returns_empty(self) -> None:
        assert readable_value({}) == ""

    def test_other_type(self) -> None:
        assert readable_value(object()) != ""


class TestExtractCode:
    def test_value(self) -> None:
        assert extract_code({"value": "12345"}) == "12345"

    def test_code(self) -> None:
        assert extract_code({"code": "ICD10"}) == "ICD10"

    def test_empty(self) -> None:
        assert extract_code({}) == ""


class TestExtractCommandHeading:
    def test_empty_data(self) -> None:
        assert extract_command_heading("prescribe", None) == ""

    def test_empty_dict(self) -> None:
        assert extract_command_heading("prescribe", {}) == ""

    def test_plan_narrative(self) -> None:
        data = {"narrative": "Follow up in 2 weeks with labs"}
        assert extract_command_heading("plan", data) == "Follow up in 2 weeks with labs"

    def test_plan_long_narrative_truncated(self) -> None:
        data = {"narrative": "x" * 200}
        result = extract_command_heading("plan", data)
        assert result.endswith("...")
        assert len(result) <= 154

    def test_hpi(self) -> None:
        data = {"narrative": "Patient reports improvement"}
        assert extract_command_heading("hpi", data) == "Patient reports improvement"

    def test_reason_for_visit_coding_text(self) -> None:
        data = {"coding": {"text": "Annual exam", "value": "Z00.00"}}
        result = extract_command_heading("reasonForVisit", data)
        assert "Annual exam" in result
        assert "Z00.00" in result

    def test_reason_for_visit_coding_text_only(self) -> None:
        data = {"coding": {"text": "Annual exam"}}
        assert extract_command_heading("reasonForVisit", data) == "Annual exam"

    def test_reason_for_visit_comment_fallback(self) -> None:
        data = {"coding": {}, "comment": "General checkup"}
        assert extract_command_heading("reasonForVisit", data) == "General checkup"

    def test_task(self) -> None:
        data = {"title": "Follow up with patient"}
        assert extract_command_heading("task", data) == "Follow up with patient"

    def test_questionnaire(self) -> None:
        data = {"questionnaire": {"text": "PHQ-9"}}
        assert extract_command_heading("questionnaire", data) == "PHQ-9"

    def test_ros(self) -> None:
        data = {"questionnaire": {"text": "ROS Form"}}
        assert extract_command_heading("ros", data) == "ROS Form"

    def test_exam(self) -> None:
        data = {"questionnaire": {"extra": {"name": "Physical Exam Form"}}}
        assert extract_command_heading("exam", data) == "Physical Exam Form"

    def test_questionnaire_string(self) -> None:
        data = {"questionnaire": "Simple string value"}
        assert extract_command_heading("questionnaire", data) == "Simple string value"

    def test_lab_order(self) -> None:
        data = {"tests": [{"text": "CBC"}, {"text": "BMP"}]}
        assert extract_command_heading("labOrder", data) == "CBC, BMP"

    def test_lab_order_empty_tests(self) -> None:
        data = {"tests": []}
        assert extract_command_heading("labOrder", data) == ""

    def test_diagnose_with_code(self) -> None:
        data = {"diagnose": {"text": "Hypertension", "value": "I10"}}
        result = extract_command_heading("diagnose", data)
        assert "Hypertension" in result
        assert "I10" in result

    def test_nested_key_string_value(self) -> None:
        data = {"instruct": "Take medication with food"}
        assert extract_command_heading("instruct", data) == "Take medication with food"

    def test_allergy(self) -> None:
        data = {"allergy": {"text": "Penicillin"}}
        assert extract_command_heading("allergy", data) == "Penicillin"


class TestExtractCommandDetails:
    def test_empty_data(self) -> None:
        assert extract_command_details("prescribe", {}) == []

    def test_none_data(self) -> None:
        assert extract_command_details("prescribe", None) == []

    def test_prescribe_details(self) -> None:
        data = {
            "prescribe": {"text": "Lisinopril"},
            "sig": "take daily",
            "days_supply": "30",
            "quantity_to_dispense": "30",
            "type_to_dispense": "tablets",
            "refills": "3",
        }
        details = extract_command_details("prescribe", data)
        labels = {d["label"] for d in details}
        assert "Sig" in labels
        assert "Days supply" in labels
        assert "Quantity to dispense" in labels
        assert "Refills" in labels

    def test_qty_with_type(self) -> None:
        data = {
            "prescribe": {"text": "Med"},
            "quantity_to_dispense": "30",
            "type_to_dispense": "tablets",
        }
        details = extract_command_details("prescribe", data)
        qty = [d for d in details if d["label"] == "Quantity to dispense"]
        assert qty[0]["value"] == "30 tablets"

    def test_qty_without_type(self) -> None:
        data = {
            "prescribe": {"text": "Med"},
            "quantity_to_dispense": "30",
        }
        details = extract_command_details("prescribe", data)
        qty = [d for d in details if d["label"] == "Quantity to dispense"]
        assert qty[0]["value"] == "30"

    def test_remaining_keys_included(self) -> None:
        data = {
            "allergy": {"text": "Penicillin"},
            "severity": "severe",
            "narrative": "Rash",
            "custom_field": "extra data",
        }
        details = extract_command_details("allergy", data)
        labels = {d["label"] for d in details}
        assert "Custom Field" in labels

    def test_questionnaire_with_questions(self) -> None:
        data = {
            "questionnaire": {
                "text": "PHQ-9",
                "extra": {
                    "questions": [
                        {"pk": "q1", "label": "Feeling down?"},
                        {"pk": "q2", "label": "Sleep issues?"},
                    ],
                },
            },
            "skip-q1": "yes",
            "question-q1": "Most days",
            "skip-q2": "no",
            "question-q2": "Never",
        }
        details = extract_command_details("questionnaire", data)
        assert len(details) == 1
        assert details[0]["label"] == "Feeling down?"
        assert details[0]["value"] == "Most days"

    def test_skip_data_keys_excluded(self) -> None:
        data = {
            "allergy": {"text": "Penicillin"},
            "id": "12345",
            "uuid": "abc-def",
            "severity": "mild",
        }
        details = extract_command_details("allergy", data)
        labels = {d["label"] for d in details}
        assert "Id" not in labels
        assert "Uuid" not in labels
        assert "Severity" in labels

    def test_vitals_details(self) -> None:
        data = {
            "blood_pressure_systole": "120",
            "blood_pressure_diastole": "80",
            "pulse": "72",
        }
        details = extract_command_details("vitals", data)
        labels = {d["label"] for d in details}
        assert "Blood pressure systolic" in labels
        assert "Blood pressure diastolic" in labels
        assert "Pulse" in labels
