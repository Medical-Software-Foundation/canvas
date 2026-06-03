from datetime import date, datetime
from unittest.mock import patch

import patient_visit_summary.services.command_blocks as cb

_CB = "patient_visit_summary.services.command_blocks"


# --- value_to_text ---


class TestValueToText:
    def test_none(self):
        assert cb.value_to_text(None) == ""

    def test_bool_true(self):
        assert cb.value_to_text(True) == "Yes"

    def test_bool_false(self):
        assert cb.value_to_text(False) == "No"

    def test_int(self):
        assert cb.value_to_text(5) == "5"

    def test_float(self):
        assert cb.value_to_text(1.5) == "1.5"

    def test_str_stripped(self):
        assert cb.value_to_text("  hi  ") == "hi"

    def test_datetime(self):
        assert cb.value_to_text(datetime(2025, 4, 24, 10, 30)) == "2025-04-24"

    def test_date(self):
        assert cb.value_to_text(date(2025, 4, 24)) == "2025-04-24"

    def test_dict_input_and_date_differ(self):
        val = {"input": "last year", "date": "2025-04-24"}
        assert cb.value_to_text(val) == "last year (around 2025-04-24)"

    def test_dict_input_equals_date(self):
        val = {"input": "2025-04-24", "date": "2025-04-24"}
        assert cb.value_to_text(val) == "2025-04-24"

    def test_dict_only_input(self):
        assert cb.value_to_text({"input": "soon"}) == "soon"

    def test_dict_only_date(self):
        assert cb.value_to_text({"date": "2025-04-24"}) == "2025-04-24"

    def test_dict_text_key(self):
        assert cb.value_to_text({"text": "Lisinopril"}) == "Lisinopril"

    def test_dict_display_key(self):
        assert cb.value_to_text({"display": "Aspirin"}) == "Aspirin"

    def test_dict_no_renderable_key(self):
        assert cb.value_to_text({"foo": "bar"}) == ""

    def test_list(self):
        assert cb.value_to_text(["a", "", "b"]) == "a, b"

    def test_unrenderable_type(self):
        assert cb.value_to_text(object()) == ""


# --- format_field_label ---


class TestFormatFieldLabel:
    def test_override(self):
        assert cb.format_field_label("today_assessment") == "TODAY'S ASSESSMENT"

    def test_default(self):
        assert cb.format_field_label("ordering_provider") == "ORDERING PROVIDER"


# --- first_text_from_keys / title helpers ---


class TestFirstTextFromKeys:
    def test_first_match(self):
        entry = {"a": "", "b": "found", "c": "later"}
        assert cb.first_text_from_keys(entry, ("a", "b", "c")) == "found"

    def test_none_found(self):
        assert cb.first_text_from_keys({"x": ""}, ("a", "b")) == ""

    def test_medication_title(self):
        assert cb.medication_title({"medication": {"text": "Med"}}) == "Med"

    def test_immunize_title(self):
        assert cb.immunize_title({"vaccine": "Flu"}) == "Flu"

    def test_review_title(self):
        assert cb.review_title({"report": "CBC"}) == "CBC"


# --- condition_text ---


class TestConditionText:
    def test_non_dict(self):
        assert cb.condition_text("plain") == "plain"

    def test_text_and_annotation_code(self):
        val = {"text": "Diabetes", "annotations": ["E1165"]}
        assert cb.condition_text(val) == "Diabetes (E11.65)"

    def test_text_with_dotted_code_unchanged(self):
        val = {"text": "Diabetes", "value": "E11.65"}
        assert cb.condition_text(val) == "Diabetes (E11.65)"

    def test_text_with_value_code_formatted(self):
        val = {"text": "Diabetes", "value": "E1165"}
        assert cb.condition_text(val) == "Diabetes (E11.65)"

    def test_display_fallback(self):
        val = {"display": "Asthma"}
        assert cb.condition_text(val) == "Asthma"

    def test_code_only(self):
        val = {"value": "E1165"}
        assert cb.condition_text(val) == "E11.65"

    def test_empty(self):
        assert cb.condition_text({}) == ""

    def test_blank_annotation_falls_to_value(self):
        val = {"text": "X", "annotations": ["  "], "value": "E1165"}
        assert cb.condition_text(val) == "X (E11.65)"

    def test_non_str_annotation_ignored(self):
        val = {"text": "X", "annotations": [123], "value": "E1165"}
        assert cb.condition_text(val) == "X (E11.65)"


# --- strip_trailing_parens ---


class TestStripTrailingParens:
    def test_strips(self):
        assert cb.strip_trailing_parens("Sage (allergy group)") == "Sage"

    def test_no_parens(self):
        assert cb.strip_trailing_parens("Penicillin") == "Penicillin"

    def test_non_str(self):
        assert cb.strip_trailing_parens(None) == ""

    def test_non_str_truthy_returned(self):
        # non-str but truthy -> `text or ""` returns the value
        assert cb.strip_trailing_parens(5) == 5


# --- truncate ---


class TestTruncate:
    def test_none(self):
        assert cb.truncate(None) == ""

    def test_non_str(self):
        assert cb.truncate(123) == "123"

    def test_empty_after_strip(self):
        assert cb.truncate("   ") == ""

    def test_under_limit(self):
        assert cb.truncate("short") == "short"

    def test_over_limit(self):
        result = cb.truncate("x" * 100, limit=10)
        assert result == "x" * 9 + "…"
        assert len(result) == 10


# --- extra_blocks ---


class TestExtraBlocks:
    def test_non_dict(self):
        assert cb.extra_blocks(["x"], shown_keys=set()) == []

    def test_skips_shown_internal_and_empty(self):
        entry = {
            "shown": "x",
            "id": "abc",
            "_private": "y",
            "skip-this": "z",
            "empty": "",
            "real": "value",
        }
        result = cb.extra_blocks(entry, shown_keys={"shown"})
        assert result == [{"kind": "field", "label": "REAL", "value": "value"}]


# --- compute_bmi ---


class TestComputeBmi:
    def test_valid(self):
        assert cb.compute_bmi({"height": 70, "weight_lbs": 180}) == "25.8"

    def test_with_ozs(self):
        result = cb.compute_bmi({"height": 70, "weight_lbs": 180, "weight_oz": 8})
        assert result.startswith("25.")

    def test_zero_height(self):
        assert cb.compute_bmi({"height": 0, "weight_lbs": 180}) == ""

    def test_zero_weight(self):
        assert cb.compute_bmi({"height": 70, "weight_lbs": 0}) == ""

    def test_invalid_type(self):
        assert cb.compute_bmi({"height": "tall", "weight_lbs": 180}) == ""


# --- tiny constructors ---


class TestConstructors:
    def test_heading_or_plain_with_title(self):
        assert cb._heading_or_plain("Pre", "T") == {
            "kind": "heading", "prefix": "Pre", "value": "T",
        }

    def test_heading_or_plain_empty(self):
        assert cb._heading_or_plain("Pre", "") == {"kind": "heading_plain", "value": "Pre"}

    def test_joined_list_field(self):
        items = [{"text": "a"}, {"nope": "x"}, {"text": "b"}]
        assert cb._joined_list_field("L", items) == {
            "kind": "field", "label": "L", "value": "a, b",
        }

    def test_joined_list_field_empty_list(self):
        assert cb._joined_list_field("L", []) is None

    def test_joined_list_field_not_list(self):
        assert cb._joined_list_field("L", "nope") is None

    def test_joined_list_field_no_texts(self):
        assert cb._joined_list_field("L", [{"nope": "x"}]) is None

    def test_indications_field(self):
        items = [{"text": "Diabetes", "value": "E1165"}]
        assert cb._indications_field(items) == {
            "kind": "field", "label": "INDICATIONS", "value": "Diabetes (E11.65)",
        }

    def test_indications_field_empty(self):
        assert cb._indications_field([]) is None

    def test_indications_field_not_list(self):
        assert cb._indications_field("nope") is None

    def test_indications_field_no_texts(self):
        assert cb._indications_field([{}]) is None


# --- _blocks_rfv ---


class TestBlocksRfv:
    def test_not_list(self):
        assert cb._blocks_rfv("RFV", "notalist") == []

    def test_dict_with_comment(self):
        data = [{"text": "Cough", "comment": "3 days"}]
        result = cb._blocks_rfv("RFV", data)
        assert result == [
            {"kind": "heading", "prefix": "RFV", "value": "Cough"},
            {"kind": "field", "label": "COMMENT", "value": "3 days"},
        ]

    def test_bare_string(self):
        result = cb._blocks_rfv("RFV", ["Headache"])
        assert result == [{"kind": "heading", "prefix": "RFV", "value": "Headache"}]

    def test_empty_entry_skipped(self):
        assert cb._blocks_rfv("RFV", [{"text": "", "comment": ""}]) == []


# --- _blocks_hpi ---


class TestBlocksHpi:
    def test_with_narrative_and_extra(self):
        data = [{"narrative": "Patient reports pain", "severity": "high"}]
        result = cb._blocks_hpi("HPI", data)
        assert result[0] == {"kind": "heading_plain", "value": "HPI"}
        assert result[1] == {"kind": "body", "value": "Patient reports pain"}
        assert {"kind": "field", "label": "SEVERITY", "value": "high"} in result

    def test_bare_string(self):
        result = cb._blocks_hpi("HPI", ["text item"])
        assert result == [
            {"kind": "heading_plain", "value": "HPI"},
            {"kind": "body", "value": "text item"},
        ]


# --- _blocks_ros_or_exam ---


class TestBlocksRosOrExam:
    def test_with_questions(self):
        data = [{
            "questionnaire": "ROS",
            "questions_and_answers": [{"label": "Fever", "answer": "No"}],
        }]
        result = cb._blocks_ros_or_exam("Review", data)
        assert result == [
            {"kind": "subheading", "prefix": "Review", "value": "ROS", "ts": ""},
            {"kind": "subfield", "label": "Fever", "value": "No"},
        ]

    def test_bare_string(self):
        result = cb._blocks_ros_or_exam("Review", ["plain"])
        assert result == [
            {"kind": "subheading", "prefix": "Review", "value": "plain", "ts": ""},
        ]


# --- _blocks_questionnaire ---


class TestBlocksQuestionnaire:
    def test_full(self):
        data = [{
            "name": "PHQ-9",
            "last_updated": "2025-01-01",
            "result": 12,
            "questions_and_answers": [{"label": "mood", "answer": "low"}],
        }]
        result = cb._blocks_questionnaire("Q", data)
        assert result[0] == {
            "kind": "subheading", "prefix": "Q", "value": "PHQ-9", "ts": "2025-01-01",
        }
        assert result[1] == {"kind": "field", "label": "RESULT", "value": "12"}
        assert result[2] == {"kind": "field", "label": "MOOD", "value": "low"}

    def test_no_result(self):
        data = [{"name": "Q1", "questions_and_answers": []}]
        result = cb._blocks_questionnaire("Q", data)
        assert len(result) == 1


# --- _format_vitals_value & _blocks_vitals ---


class TestVitals:
    def test_bp_with_diastole(self):
        v = {"blood_pressure_diastole": 80}
        assert cb._format_vitals_value(v, "blood_pressure_systole", 120, None, "") == "120/80 mmHg"

    def test_bp_diastole_zero(self):
        v = {"blood_pressure_diastole": 0}
        assert cb._format_vitals_value(v, "blood_pressure_systole", 120, None, "") == "120/0 mmHg"

    def test_bp_without_diastole(self):
        v = {}
        assert cb._format_vitals_value(v, "blood_pressure_systole", 120, None, "") == "120 mmHg"

    def test_weight_with_ozs_and_bmi(self):
        v = {"weight_oz": 8}
        assert cb._format_vitals_value(v, "weight_lbs", 180, "lb", "25.8") == "180 lb 8 oz (BMI: 25.8)"

    def test_weight_without_ozs_no_bmi(self):
        v = {}
        assert cb._format_vitals_value(v, "weight_lbs", 180, "lb", "") == "180 lb"

    def test_unit(self):
        assert cb._format_vitals_value({}, "pulse", 72, "bpm", "") == "72 bpm"

    def test_no_unit(self):
        assert cb._format_vitals_value({}, "note", "ok", None, "") == "ok"

    def test_blocks_vitals_full(self):
        data = [{
            "height": 70,
            "weight_lbs": 180,
            "weight_oz": 0,
            "blood_pressure_systole": 120,
            "blood_pressure_diastole": 80,
            "pulse": 72,
            "extra_field": "X",
        }]
        result = cb._blocks_vitals("Vitals", data)
        assert {"kind": "heading_plain", "value": "Vitals"} in result
        vitals_block = next(b for b in result if b["kind"] == "vitals")
        labels = {i["label"] for i in vitals_block["items"]}
        assert "HEIGHT" in labels and "WEIGHT" in labels and "BLOOD PRESSURE" in labels
        assert {"kind": "field", "label": "EXTRA FIELD", "value": "X"} in result

    def test_blocks_vitals_bmi_not_double_rendered(self):
        # The shared extractor adds a `bmi` key; _blocks_vitals renders BMI inline
        # on the weight line, so it must not also leak out via extra_blocks.
        data = [{"height": 70, "weight_lbs": 180, "weight_oz": 8, "bmi": "25.9"}]
        result = cb._blocks_vitals("Vitals", data)
        assert not any(
            b.get("kind") == "field" and b.get("label") == "BMI" for b in result
        )
        vitals_block = next(b for b in result if b["kind"] == "vitals")
        weight = next(i for i in vitals_block["items"] if i["label"] == "WEIGHT")
        assert "(BMI:" in weight["value"]

    def test_blocks_vitals_no_items(self):
        result = cb._blocks_vitals("Vitals", [{}])
        assert result == [{"kind": "heading_plain", "value": "Vitals"}]

    def test_blocks_vitals_zero_value_included(self):
        result = cb._blocks_vitals("Vitals", [{"pulse": 0}])
        vitals_block = next(b for b in result if b["kind"] == "vitals")
        assert vitals_block["items"] == [{"label": "PULSE RATE", "value": "0 bpm"}]


# --- _blocks_assess ---


class TestBlocksAssess:
    def test_full(self):
        data = [{
            "condition": {"text": "Diabetes", "value": "E1165"},
            "background": "bg",
            "status": "active",
            "narrative": "doing well",
            "extra": "Y",
        }]
        result = cb._blocks_assess("A", data)
        assert result[0] == {"kind": "heading", "prefix": "Assessment", "value": "Diabetes (E11.65)"}
        assert {"kind": "field", "label": "BACKGROUND", "value": "bg"} in result
        assert {"kind": "field", "label": "STATUS", "value": "active"} in result
        assert {"kind": "field", "label": "TODAY'S ASSESSMENT", "value": "doing well"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "Y"} in result

    def test_minimal(self):
        result = cb._blocks_assess("A", [{"condition": {"text": "X"}}])
        assert result == [{"kind": "heading", "prefix": "Assessment", "value": "X"}]


# --- _blocks_diagnose ---


class TestBlocksDiagnose:
    def test_nested_data(self):
        data = [{"data": {"diagnose": {"text": "Flu"}, "background": "bg"}}]
        result = cb._blocks_diagnose("D", data)
        assert result[0] == {"kind": "heading", "prefix": "Diagnose", "value": "Flu"}
        assert {"kind": "field", "label": "BACKGROUND", "value": "bg"} in result

    def test_flat(self):
        result = cb._blocks_diagnose("D", [{"diagnose": {"text": "Flu"}}])
        assert result[0] == {"kind": "heading", "prefix": "Diagnose", "value": "Flu"}


# --- _blocks_change_diagnosis ---


class TestBlocksChangeDiagnosis:
    def test_full(self):
        data = [{"data": {
            "condition": {"text": "Old"},
            "new_condition": {"text": "New"},
            "background": "bg",
            "narrative": "n",
        }}]
        result = cb._blocks_change_diagnosis("C", data)
        assert result[0] == {"kind": "heading", "prefix": "Change Diagnosis", "value": "Old"}
        assert {"kind": "field", "label": "NEW DIAGNOSIS", "value": "New"} in result
        assert {"kind": "field", "label": "BACKGROUND", "value": "bg"} in result
        assert {"kind": "field", "label": "TODAY'S ASSESSMENT", "value": "n"} in result

    def test_non_dict_entry(self):
        result = cb._blocks_change_diagnosis("C", ["x"])
        assert result == [{"kind": "heading", "prefix": "Change Diagnosis", "value": ""}]


# --- _blocks_resolve_condition ---


class TestBlocksResolveCondition:
    def test_full(self):
        data = [{"condition": {"text": "Cond"}, "rationale": "resolved"}]
        result = cb._blocks_resolve_condition("R", data)
        assert result[0] == {"kind": "heading", "prefix": "Resolve Condition", "value": "Cond"}
        assert {"kind": "field", "label": "RATIONALE", "value": "resolved"} in result

    def test_non_dict(self):
        result = cb._blocks_resolve_condition("R", [42])
        assert result == [{"kind": "heading", "prefix": "Resolve Condition", "value": ""}]


# --- _blocks_plan ---


class TestBlocksPlan:
    def test_full(self):
        result = cb._blocks_plan("Plan", [{"narrative": "do x", "extra": "Y"}])
        assert result[0] == {"kind": "heading_plain", "value": "Plan"}
        assert {"kind": "body", "value": "do x"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "Y"} in result

    def test_bare(self):
        result = cb._blocks_plan("Plan", ["str plan"])
        assert {"kind": "body", "value": "str plan"} in result


# --- _med_action_row & _blocks_med_action ---


class TestMedAction:
    def test_med_action_row_full(self):
        entry = {
            "days_supply": 30,
            "quantity_to_dispense": 90,
            "type_to_dispense": {"text": "tablet"},
            "refills": 2,
        }
        row = cb._med_action_row(entry)
        assert row == {"kind": "vitals", "items": [
            {"label": "DAYS SUPPLY", "value": "30"},
            {"label": "QUANTITY TO DISPENSE", "value": "90 × tablet"},
            {"label": "REFILLS", "value": "2"},
        ]}

    def test_med_action_row_zeros(self):
        entry = {"days_supply": 0, "quantity_to_dispense": 0, "refills": 0}
        row = cb._med_action_row(entry)
        labels = [i["label"] for i in row["items"]]
        assert labels == ["DAYS SUPPLY", "QUANTITY TO DISPENSE", "REFILLS"]
        qty = next(i for i in row["items"] if i["label"] == "QUANTITY TO DISPENSE")
        assert qty["value"] == "0"

    def test_med_action_row_none(self):
        assert cb._med_action_row({}) is None

    def test_blocks_med_action_full(self):
        data = [{
            "prescribe": {"text": "DrugA"},
            "change_medication_to": {"text": "DrugB"},
            "indications": [{"text": "Pain"}],
            "sig": "1 daily",
            "days_supply": 30,
            "substitutions": "allowed",
            "pharmacy": "CVS",
            "prescriber": "Dr X",
            "supervising_provider": "Dr Y",
            "note_to_pharmacist": "hi",
            "extra": "Z",
        }]
        result = cb._blocks_med_action("Med", data)
        assert {"kind": "field", "label": "CHANGE FROM", "value": "DrugA"} in result
        assert {"kind": "field", "label": "INDICATIONS", "value": "Pain"} in result
        assert {"kind": "field", "label": "SIG", "value": "1 daily"} in result
        assert {"kind": "field", "label": "SUBSTITUTIONS ALLOWED", "value": "Allowed"} in result
        assert {"kind": "field", "label": "PHARMACY", "value": "CVS"} in result
        assert {"kind": "field", "label": "PRESCRIBER", "value": "Dr X"} in result
        assert {"kind": "field", "label": "SUPERVISING PROVIDER", "value": "Dr Y"} in result
        assert {"kind": "field", "label": "NOTE TO PHARMACIST", "value": "hi"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "Z"} in result

    def test_blocks_med_action_non_dict_skipped(self):
        assert cb._blocks_med_action("Med", ["x"]) == []

    def test_blocks_med_action_no_change_from_when_same(self):
        data = [{
            "prescribe": {"text": "DrugA"},
            "change_medication_to": {"text": "DrugA"},
        }]
        result = cb._blocks_med_action("Med", data)
        assert not any(b.get("label") == "CHANGE FROM" for b in result)


# --- _blocks_refer ---


class TestBlocksRefer:
    def test_full(self):
        data = [{
            "refer_to": {"text": "Cardiology"},
            "indications": [{"text": "Chest pain"}],
            "clinical_question": "why?",
            "priority": "urgent",
            "notes_to_specialist": "see soon",
            "include_visit_note": True,
            "internal_comment": "ic",
            "documents_to_include": [{"text": "doc1"}],
            "linked_items": [{"text": "link1"}],
            "extra": "E",
        }]
        result = cb._blocks_refer("Refer", data)
        assert result[0] == {"kind": "heading", "prefix": "Referral", "value": "Cardiology"}
        assert {"kind": "field", "label": "INDICATIONS", "value": "Chest pain"} in result
        assert {"kind": "field", "label": "CLINICAL QUESTION", "value": "why?"} in result
        assert {"kind": "field", "label": "PRIORITY", "value": "urgent"} in result
        assert {"kind": "field", "label": "NOTES TO SPECIALIST", "value": "see soon"} in result
        assert {"kind": "field", "label": "INCLUDE VISIT NOTE", "value": "Yes"} in result
        assert {"kind": "field", "label": "INTERNAL COMMENT", "value": "ic"} in result
        assert {"kind": "field", "label": "DOCUMENTS TO INCLUDE", "value": "doc1"} in result
        assert {"kind": "field", "label": "LINKED ITEMS", "value": "link1"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "E"} in result

    def test_include_visit_note_false(self):
        data = [{"refer_to": "X", "include_visit_note": False}]
        result = cb._blocks_refer("Refer", data)
        assert {"kind": "field", "label": "INCLUDE VISIT NOTE", "value": "No"} in result

    def test_non_dict(self):
        assert cb._blocks_refer("Refer", ["x"]) == []


# --- _blocks_lab_order ---


class TestBlocksLabOrder:
    def test_full_with_aoe(self):
        data = [{
            "lab_partner": "Quest",
            "tests": [{"text": "CBC", "value": "100"}],
            "ordering_provider": {"text": "Dr X"},
            "diagnosis": [{"text": "Anemia"}],
            "fasting_status": True,
            "aoes|100": "answer text",
            "aoes|999": "",
            "comment": "c",
            "extra": "E",
        }]
        result = cb._blocks_lab_order("Lab", data)
        assert result[0] == {"kind": "heading", "prefix": "Lab Order", "value": "Quest"}
        assert {"kind": "field", "label": "TESTS", "value": "CBC"} in result
        assert {"kind": "field", "label": "ORDERING PROVIDER", "value": "Dr X"} in result
        assert {"kind": "field", "label": "INDICATIONS", "value": "Anemia"} in result
        assert {"kind": "field", "label": "FASTING REQUIRED", "value": "Yes"} in result
        assert {"kind": "field", "label": "(CBC) NEW QUESTION", "value": "answer text"} in result
        assert {"kind": "field", "label": "COMMENT", "value": "c"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "E"} in result

    def test_aoe_without_test_text(self):
        data = [{"lab_partner": "Q", "tests": [], "aoes|abc": "ans"}]
        result = cb._blocks_lab_order("Lab", data)
        assert {"kind": "field", "label": "NEW QUESTION", "value": "ans"} in result

    def test_aoe_no_pipe_code(self):
        # key starts with "aoes|" so split always has parts; cover branch with bare "aoes|"
        data = [{"lab_partner": "Q", "tests": [], "aoes|": "ans"}]
        result = cb._blocks_lab_order("Lab", data)
        assert {"kind": "field", "label": "NEW QUESTION", "value": "ans"} in result

    def test_fasting_false(self):
        data = [{"lab_partner": "Q", "fasting_status": False}]
        result = cb._blocks_lab_order("Lab", data)
        assert {"kind": "field", "label": "FASTING REQUIRED", "value": "No"} in result

    def test_no_lab_partner_plain_heading(self):
        result = cb._blocks_lab_order("Lab", [{"tests": []}])
        assert result[0] == {"kind": "heading_plain", "value": "Lab Order"}

    def test_tests_not_list(self):
        data = [{"lab_partner": "Q", "tests": "nope"}]
        result = cb._blocks_lab_order("Lab", data)
        assert result[0]["value"] == "Q"

    def test_non_dict(self):
        assert cb._blocks_lab_order("Lab", ["x"]) == []


# --- _blocks_imaging_order ---


class TestBlocksImagingOrder:
    def test_full(self):
        data = [{
            "image": {"text": "X-Ray"},
            "indications": [{"text": "Fracture"}],
            "priority": "urgent",
            "additional_details": "detail",
            "imaging_center": {"text": "Center"},
            "ordering_provider": {"text": "Dr X"},
            "comment": "c",
            "linked_items": [{"text": "L1"}],
            "extra": "E",
        }]
        result = cb._blocks_imaging_order("Img", data)
        assert result[0] == {"kind": "heading", "prefix": "Image", "value": "X-Ray"}
        assert {"kind": "field", "label": "INDICATIONS", "value": "Fracture"} in result
        assert {"kind": "field", "label": "PRIORITY", "value": "urgent"} in result
        assert {"kind": "field", "label": "ADDITIONAL ORDER DETAILS", "value": "detail"} in result
        assert {"kind": "field", "label": "IMAGING CENTER", "value": "Center"} in result
        assert {"kind": "field", "label": "ORDERING PROVIDER", "value": "Dr X"} in result
        assert {"kind": "field", "label": "INTERNAL COMMENT", "value": "c"} in result
        assert {"kind": "field", "label": "LINKED ITEMS", "value": "L1"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "E"} in result

    def test_non_dict(self):
        assert cb._blocks_imaging_order("Img", ["x"]) == []


# --- _blocks_review ---


class TestBlocksReview:
    def test_full(self):
        data = [{
            "report": "CBC",
            "message_to_patient": "all good",
            "communication_method": {"text": "phone"},
            "linked_items": [{"text": "L1"}],
            "internal_comment": "ic",
            "extra": "E",
        }]
        result = cb._blocks_review("Review", data)
        assert result[0] == {"kind": "heading", "prefix": "Review", "value": "CBC"}
        assert {"kind": "field", "label": "PATIENT MESSAGE", "value": "all good"} in result
        assert {"kind": "field", "label": "PATIENT COMMUNICATION", "value": "phone"} in result
        assert {"kind": "field", "label": "LINKED ITEMS", "value": "L1"} in result
        assert {"kind": "field", "label": "INTERNAL COMMENT", "value": "ic"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "E"} in result

    def test_non_dict(self):
        assert cb._blocks_review("Review", [1]) == []


# --- _blocks_medication_statement ---


class TestBlocksMedicationStatement:
    def test_with_med_and_sig(self):
        data = [{"medication": {"text": "Med"}, "sig": "daily", "extra": "E"}]
        result = cb._blocks_medication_statement("MS", data)
        assert result[0] == {"kind": "heading", "prefix": "Medication Statement", "value": "Med"}
        assert {"kind": "field", "label": "SIG", "value": "daily"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "E"} in result

    def test_fdbmedid_fallback(self):
        result = cb._blocks_medication_statement("MS", [{"fdbMedId": "FDB1"}])
        assert result[0]["value"] == "FDB1"

    def test_non_dict(self):
        assert cb._blocks_medication_statement("MS", [None]) == []


# --- _blocks_remove_allergy ---


class TestBlocksRemoveAllergy:
    def test_narrative(self):
        data = [{"allergy": {"text": "Penicillin"}, "narrative": "no longer"}]
        result = cb._blocks_remove_allergy("RA", data)
        assert result[0] == {"kind": "heading", "prefix": "Remove Allergy", "value": "Penicillin"}
        assert {"kind": "field", "label": "RATIONALE", "value": "no longer"} in result

    def test_rationale_fallback(self):
        result = cb._blocks_remove_allergy("RA", [{"allergy": "X", "rationale": "r"}])
        assert {"kind": "field", "label": "RATIONALE", "value": "r"} in result

    def test_non_dict(self):
        assert cb._blocks_remove_allergy("RA", [1]) == []


# --- _family_history_name & _blocks_family_history ---


class TestFamilyHistory:
    def test_name_dict(self):
        assert cb._family_history_name({"condition": {"text": "Cancer", "value": "C00"}}) == "Cancer (C00)"

    def test_name_str(self):
        assert cb._family_history_name({"fh": "Diabetes"}) == "Diabetes"

    def test_name_none(self):
        assert cb._family_history_name({"other": "x"}) == ""

    def test_name_empty_value_skipped(self):
        assert cb._family_history_name({"family_history": "", "fh": "Found"}) == "Found"

    def test_blocks_full(self):
        data = [{"condition": {"text": "Cancer"}, "relative": "Mother", "note": "n", "extra": "E"}]
        result = cb._blocks_family_history("FH", data)
        assert result[0] == {"kind": "heading", "prefix": "Family History", "value": "Cancer"}
        assert {"kind": "field", "label": "RELATIVE", "value": "Mother"} in result
        assert {"kind": "field", "label": "NOTE", "value": "n"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "E"} in result

    def test_blocks_non_dict(self):
        assert cb._blocks_family_history("FH", [1]) == []


# --- _blocks_immunization_statement ---


class TestBlocksImmunizationStatement:
    def test_full(self):
        data = [{
            "vaccine": "Flu",
            "approximate_date": {"input": "last year"},
            "comments": "c",
            "extra": "E",
        }]
        result = cb._blocks_immunization_statement("IS", data)
        assert result[0] == {"kind": "heading", "prefix": "Immunization Statement", "value": "Flu"}
        assert {"kind": "field", "label": "APPROXIMATE DATE OF IMMUNIZATION", "value": "last year"} in result
        assert {"kind": "field", "label": "COMMENT", "value": "c"} in result
        assert {"kind": "field", "label": "EXTRA", "value": "E"} in result

    def test_date_and_comment_fallbacks(self):
        data = [{"vaccine": "Flu", "date": "2025-01-01", "comment": "cc"}]
        result = cb._blocks_immunization_statement("IS", data)
        assert {"kind": "field", "label": "APPROXIMATE DATE OF IMMUNIZATION", "value": "2025-01-01"} in result
        assert {"kind": "field", "label": "COMMENT", "value": "cc"} in result

    def test_date_value_to_text_empty_uses_str(self):
        data = [{"vaccine": "Flu", "approximate_date": 12345}]
        result = cb._blocks_immunization_statement("IS", data)
        assert {"kind": "field", "label": "APPROXIMATE DATE OF IMMUNIZATION", "value": "12345"} in result

    def test_non_dict(self):
        assert cb._blocks_immunization_statement("IS", [1]) == []

    def test_cpt_and_cvx_in_heading(self):
        data = [{"statement": {
            "text": "LAIV3 VACCINE LIVE FOR INTRANASAL USE",
            "extra": {"coding": [
                {"code": "90660", "system": "http://www.ama-assn.org/go/cpt"},
                {"code": "111", "system": "http://hl7.org/fhir/sid/cvx"},
            ]},
        }}]
        result = cb._blocks_immunization_statement("IS", data)
        assert result[0] == {
            "kind": "heading", "prefix": "Immunization Statement",
            "value": "LAIV3 VACCINE LIVE FOR INTRANASAL USE (CPT 90660, CVX 111)",
        }


# --- _blocks_surgical_history ---


class TestBlocksSurgicalHistory:
    def test_dict_name(self):
        data = [{"past_surgical_history": {"text": "Appendectomy"}, "approximate_date": "2020", "comment": "c"}]
        result = cb._blocks_surgical_history("SH", data)
        assert result[0] == {"kind": "heading", "prefix": "Past Surgical History", "value": "Appendectomy"}
        assert {"kind": "field", "label": "APPROXIMATE DATE", "value": "2020"} in result
        assert {"kind": "field", "label": "COMMENT", "value": "c"} in result

    def test_str_name(self):
        result = cb._blocks_surgical_history("SH", [{"past_surgical_history": "X"}])
        assert result[0]["value"] == "X"

    def test_approx_str_fallback(self):
        data = [{"past_surgical_history": "X", "approximate_date": 99}]
        result = cb._blocks_surgical_history("SH", data)
        assert {"kind": "field", "label": "APPROXIMATE DATE", "value": "99"} in result

    def test_non_dict(self):
        assert cb._blocks_surgical_history("SH", [1]) == []


# --- _blocks_medical_history ---


class TestBlocksMedicalHistory:
    def test_full(self):
        data = [{
            "past_medical_history": {"text": "HTN"},
            "approximate_start_date": "2018",
            "approximate_end_date": "2020",
            "show_on_condition_list": True,
            "comments": "c",
        }]
        result = cb._blocks_medical_history("MH", data)
        assert result[0] == {"kind": "heading", "prefix": "Past Medical History", "value": "HTN"}
        assert {"kind": "field", "label": "APPROXIMATE START DATE", "value": "2018"} in result
        assert {"kind": "field", "label": "APPROXIMATE END DATE", "value": "2020"} in result
        assert {"kind": "field", "label": "SHOW ON CONDITION LIST", "value": "Yes"} in result
        assert {"kind": "field", "label": "COMMENTS", "value": "c"} in result

    def test_show_false_str_name(self):
        data = [{"past_medical_history": "X", "show_on_condition_list": False}]
        result = cb._blocks_medical_history("MH", data)
        assert {"kind": "field", "label": "SHOW ON CONDITION LIST", "value": "No"} in result

    def test_date_str_fallbacks(self):
        data = [{"past_medical_history": "X", "approximate_start_date": 1, "approximate_end_date": 2}]
        result = cb._blocks_medical_history("MH", data)
        assert {"kind": "field", "label": "APPROXIMATE START DATE", "value": "1"} in result
        assert {"kind": "field", "label": "APPROXIMATE END DATE", "value": "2"} in result

    def test_non_dict(self):
        assert cb._blocks_medical_history("MH", [1]) == []


# --- _blocks_perform ---


class TestBlocksPerform:
    def test_full(self):
        result = cb._blocks_perform("P", [{"perform": {"text": "Proc"}, "notes": "n"}])
        assert result[0] == {"kind": "heading", "prefix": "Perform", "value": "Proc"}
        assert {"kind": "field", "label": "NOTES", "value": "n"} in result

    def test_non_dict(self):
        assert cb._blocks_perform("P", [1]) == []

    def test_cpt_code_in_heading(self):
        data = [{"perform": {
            "text": "Biopsy floor mouth (CPT: 41108)",
            "extra": {"coding": [
                {"code": "41108", "system": "http://www.ama-assn.org/go/cpt"},
            ]},
        }}]
        result = cb._blocks_perform("P", data)
        assert result[0] == {
            "kind": "heading", "prefix": "Perform", "value": "Biopsy floor mouth (CPT 41108)",
        }


# --- _blocks_immunize ---


class TestBlocksImmunize:
    def test_full(self):
        data = [{
            "vaccine": "Flu",
            "lot_number": "L1",
            "manufacturer": {"text": "Pfizer"},
            "expiration_date": "2026-01-01",
            "sig": "1 dose",
            "vis_consent": True,
            "given_by": {"text": "Nurse"},
        }]
        result = cb._blocks_immunize("Imm", data)
        assert result[0] == {"kind": "heading", "prefix": "Immunize", "value": "Flu"}
        assert {"kind": "field", "label": "LOT NUMBER", "value": "L1"} in result
        assert {"kind": "field", "label": "MANUFACTURER", "value": "Pfizer"} in result
        assert {"kind": "field", "label": "EXPIRATION DATE", "value": "2026-01-01"} in result
        assert {"kind": "field", "label": "SIG", "value": "1 dose"} in result
        assert {"kind": "field", "label": "VIS CONSENT", "value": "Yes"} in result
        assert {"kind": "field", "label": "GIVEN BY", "value": "Nurse"} in result

    def test_fallbacks_and_consent_given_str(self):
        data = [{
            "vaccine": "Flu",
            "manufacturer": 5,
            "exp_date_original": 999,
            "sig_original": "sigo",
            "consent_given": "verbal",
        }]
        result = cb._blocks_immunize("Imm", data)
        assert {"kind": "field", "label": "MANUFACTURER", "value": "5"} in result
        assert {"kind": "field", "label": "EXPIRATION DATE", "value": "999"} in result
        assert {"kind": "field", "label": "SIG", "value": "sigo"} in result
        assert {"kind": "field", "label": "VIS CONSENT", "value": "verbal"} in result

    def test_consent_false_bool(self):
        result = cb._blocks_immunize("Imm", [{"vaccine": "F", "vis_consent": False}])
        assert {"kind": "field", "label": "VIS CONSENT", "value": "No"} in result

    def test_non_dict(self):
        assert cb._blocks_immunize("Imm", [1]) == []

    def test_cpt_and_cvx_in_heading(self):
        data = [{"coding": {
            "text": "DTaP-Hib vaccine (CPT: 90721)",
            "extra": {"coding": [
                {"code": "90721", "system": "http://www.ama-assn.org/go/cpt"},
                {"code": "50", "system": "http://hl7.org/fhir/sid/cvx"},
            ]},
        }}]
        result = cb._blocks_immunize("Imm", data)
        assert result[0] == {
            "kind": "heading", "prefix": "Immunize",
            "value": "DTaP-Hib vaccine (CPT 90721, CVX 50)",
        }


# --- _blocks_task ---


class TestBlocksTask:
    def test_full(self):
        data = [{
            "title": "Follow up",
            "assign_to": {"text": "Team A"},
            "due_date": "2025-02-01",
            "comment": "c",
            "labels": ["urgent", ""],
            "linked_items": [{"text": "L1"}],
        }]
        result = cb._blocks_task("T", data)
        assert result[0] == {"kind": "heading", "prefix": "Task", "value": "Follow up"}
        assert {"kind": "field", "label": "ASSIGN TO", "value": "Team A"} in result
        assert {"kind": "field", "label": "DUE DATE", "value": "2025-02-01"} in result
        assert {"kind": "field", "label": "COMMENT", "value": "c"} in result
        assert {"kind": "field", "label": "LABELS", "value": "urgent"} in result
        assert {"kind": "field", "label": "LINKED ITEMS", "value": "L1"} in result

    def test_due_date_str_fallback(self):
        result = cb._blocks_task("T", [{"title": "X", "due_date": 5}])
        assert {"kind": "field", "label": "DUE DATE", "value": "5"} in result

    def test_labels_all_empty(self):
        result = cb._blocks_task("T", [{"title": "X", "labels": ["", None]}])
        assert not any(b.get("label") == "LABELS" for b in result)

    def test_non_dict(self):
        assert cb._blocks_task("T", [1]) == []


# --- _blocks_instruct ---


class TestBlocksInstruct:
    def test_full(self):
        result = cb._blocks_instruct("I", [{"instruct": {"text": "Rest"}, "narrative": "n"}])
        assert result[0] == {"kind": "heading", "prefix": "Instruct", "value": "Rest"}
        assert {"kind": "field", "label": "NARRATIVE", "value": "n"} in result

    def test_non_dict(self):
        assert cb._blocks_instruct("I", [1]) == []


# --- _blocks_goal ---


class TestBlocksGoal:
    def test_goal_str_statement(self):
        data = [{
            "goal_statement": "Lose weight",
            "start_date": "2025-01-01",
            "due_date": "2025-12-31",
            "achievement_status": "in-progress",
            "priority": "high",
            "progress": "on track",
        }]
        result = cb._blocks_goal("G", data)
        assert result[0] == {"kind": "heading", "prefix": "Goal", "value": "Lose weight"}
        assert {"kind": "field", "label": "START DATE", "value": "2025-01-01"} in result
        assert {"kind": "field", "label": "DUE DATE", "value": "2025-12-31"} in result
        assert {"kind": "field", "label": "STATUS", "value": "in-progress"} in result
        assert {"kind": "field", "label": "PRIORITY", "value": "high"} in result
        assert {"kind": "field", "label": "PROGRESS / BARRIERS", "value": "on track"} in result

    def test_update_goal_dict_statement(self):
        data = [{"goal_statement": {"text": "Improve"}}]
        result = cb._blocks_goal("G", data)
        assert result[0] == {"kind": "heading", "prefix": "Update Goal", "value": "Improve"}

    def test_description_fallback(self):
        result = cb._blocks_goal("G", [{"description": "Desc"}])
        assert result[0]["value"] == "Desc"

    def test_non_dict(self):
        assert cb._blocks_goal("G", [1]) == []


# --- _blocks_allergy ---


class TestBlocksAllergy:
    def test_strips_parens(self):
        result = cb._blocks_allergy("A", [{"allergy": "Sage (allergy group)", "reaction": "rash"}])
        assert result[0] == {"kind": "heading", "prefix": "Allergy", "value": "Sage"}
        assert {"kind": "field", "label": "REACTION", "value": "rash"} in result


# --- _blocks_generic ---


class TestBlocksGeneric:
    def test_not_list(self):
        assert cb._blocks_generic("G", "nope") == []

    def test_dict_and_str_items(self):
        result = cb._blocks_generic("G", [{"foo": "bar"}, "body text", ""])
        assert result[0] == {"kind": "heading_plain", "value": "G"}
        assert {"kind": "field", "label": "FOO", "value": "bar"} in result
        assert {"kind": "body", "value": "body text"} in result


# --- title extractors ---


class TestTitleExtractors:
    def test_title_goal(self):
        assert cb._title_goal({"goal_statement": "Lose weight"}) == "Lose weight"

    def test_title_goal_description_fallback(self):
        assert cb._title_goal({"description": "Desc"}) == "Desc"

    def test_title_family_history_dict(self):
        assert cb._title_family_history({"condition": {"text": "Cancer"}}) == "Cancer"

    def test_title_family_history_str(self):
        assert cb._title_family_history({"fh": "Diabetes"}) == "Diabetes"

    def test_title_family_history_empty_then_present(self):
        # first key present but empty text -> condition_text returns "" -> keep looping
        assert cb._title_family_history({"family_history": {}, "fh": "Found"}) == "Found"

    def test_title_family_history_none(self):
        assert cb._title_family_history({"other": "x"}) == ""

    def test_title_generic_direct_str(self):
        assert cb._title_generic({"name": "Joe"}) == "Joe"

    def test_title_generic_direct_dict(self):
        assert cb._title_generic({"text": {"text": "Nested"}}) == "Nested"

    def test_title_generic_scan_dict_values(self):
        assert cb._title_generic({"random": {"display": "Found"}}) == "Found"

    def test_title_generic_none(self):
        assert cb._title_generic({"random": 5}) == ""


# --- build_blocks ---


class TestBuildBlocks:
    def test_empty(self):
        assert cb.build_blocks("D", "rfv", []) == []

    def test_registered_builder(self):
        result = cb.build_blocks("RFV", "rfv", [{"text": "Cough"}])
        assert result == [{"kind": "heading", "prefix": "RFV", "value": "Cough"}]

    def test_unregistered_uses_generic(self):
        result = cb.build_blocks("Custom", "unknown_type", [{"foo": "bar"}])
        assert result[0] == {"kind": "heading_plain", "value": "Custom"}


# --- title_for_entry ---


class TestTitleForEntry:
    def test_rfv_dict_text(self):
        assert cb.title_for_entry("rfv", "RFV", {"text": "Cough"}, 0) == "Cough"

    def test_rfv_dict_comment_fallback(self):
        assert cb.title_for_entry("rfv", "RFV", {"comment": "3 days"}, 0) == "3 days"

    def test_rfv_dict_empty_fallback(self):
        assert cb.title_for_entry("rfv", "RFV", {}, 2) == "RFV #3"

    def test_rfv_bare_string(self):
        assert cb.title_for_entry("rfv", "RFV", "Headache", 0) == "Headache"

    def test_rfv_bare_empty_fallback(self):
        assert cb.title_for_entry("rfv", "RFV", "", 0) == "RFV #1"

    def test_non_dict_non_rfv(self):
        assert cb.title_for_entry("hpi", "HPI", "plain", 0) == "plain"

    def test_non_dict_empty_fallback(self):
        assert cb.title_for_entry("hpi", "HPI", "", 1) == "HPI #2"

    def test_vitals_always_fallback(self):
        assert cb.title_for_entry("vitals", "Vitals", {"height": 70}, 0) == "Vitals #1"

    def test_registered_extractor(self):
        assert cb.title_for_entry("task", "Task", {"title": "Follow up"}, 0) == "Follow up"

    def test_extractor_empty_uses_fallback(self):
        assert cb.title_for_entry("task", "Task", {"title": ""}, 0) == "Task #1"

    def test_generic_extractor(self):
        assert cb.title_for_entry("unknown", "X", {"text": "Found"}, 0) == "Found"

    def test_diagnose_extractor_nested(self):
        title = cb.title_for_entry("diagnose", "D", {"data": {"diagnose": {"text": "Flu"}}}, 0)
        assert title == "Flu"


# --- render_blocks / render_blocks_html ---


class TestRender:
    def test_render_blocks_empty(self):
        assert cb.render_blocks([]) == ""

    def test_render_blocks(self):
        blocks = [{"kind": "body", "value": "x"}]
        with patch(f"{_CB}.render_to_string", return_value="<html>") as mock_render:
            result = cb.render_blocks(blocks)
        assert result == "<html>"
        mock_render.assert_called_once_with(
            "templates/command_block.html", context={"blocks": blocks},
        )

    def test_render_blocks_html_empty_data(self):
        with patch(f"{_CB}.render_to_string") as mock_render:
            result = cb.render_blocks_html("D", "rfv", [])
        assert result == ""
        mock_render.assert_not_called()

    def test_render_blocks_html_no_blocks_produced(self):
        # rfv on a list of empties produces no blocks -> "" without rendering
        with patch(f"{_CB}.render_to_string") as mock_render:
            result = cb.render_blocks_html("D", "rfv", [{"text": "", "comment": ""}])
        assert result == ""
        mock_render.assert_not_called()

    def test_render_blocks_html_full(self):
        with patch(f"{_CB}.render_to_string", return_value="<html>out</html>") as mock_render:
            result = cb.render_blocks_html("RFV", "rfv", [{"text": "Cough"}])
        assert result == "<html>out</html>"
        expected_blocks = [{"kind": "heading", "prefix": "RFV", "value": "Cough"}]
        mock_render.assert_called_once_with(
            "templates/command_block.html", context={"blocks": expected_blocks},
        )


# --- enumerate_sections ---


class TestEnumerateSections:
    def test_empty_context(self):
        assert cb.enumerate_sections({}) == []

    def test_builds_section_with_group(self):
        context = {"reasons_for_visit": [{"text": "Cough", "comment": "3 days"}]}
        result = cb.enumerate_sections(context)
        assert len(result) == 1
        section = result[0]
        assert section["key"] == "subjective"
        assert section["title"] == "Subjective"
        group = section["groups"][0]
        assert group["context_key"] == "reasons_for_visit"
        assert group["render_type"] == "rfv"
        entry = group["entries"][0]
        assert entry["title"] == "Cough"
        assert entry["raw"] == {"text": "Cough", "comment": "3 days"}
        assert entry["blocks"][0] == {"kind": "heading", "prefix": "Reason for Visit", "value": "Cough"}

    def test_non_list_data_wrapped(self):
        context = {"plan_commands_data": {"narrative": "do x"}}
        result = cb.enumerate_sections(context)
        group = result[0]["groups"][0]
        assert group["context_key"] == "plan_commands_data"
        assert len(group["entries"]) == 1

    def test_filters_empty_entries(self):
        context = {"reasons_for_visit": [None, {}, ""]}
        # entries filtered to [{}] since {} is falsy and "" falsy and None falsy
        result = cb.enumerate_sections(context)
        assert result == []

    def test_zero_entry_retained(self):
        context = {"reasons_for_visit": [0]}
        result = cb.enumerate_sections(context)
        # 0 == 0 retained; rfv on int 0 -> value_to_text("0") heading
        group = result[0]["groups"][0]
        assert len(group["entries"]) == 1

    def test_custom_sections(self):
        sections = [{
            "key": "k",
            "title": "T",
            "items": [("task_commands_data", "Tasks", "task")],
        }]
        context = {"task_commands_data": [{"title": "Do it"}]}
        result = cb.enumerate_sections(context, sections=sections)
        assert result[0]["key"] == "k"
        assert result[0]["groups"][0]["entries"][0]["title"] == "Do it"


# --- _blocks_billing / _billing_title (patient-facing billed services) ---


class TestBlocksBilling:
    def test_code_description_and_units(self):
        data = [{"code": "99213", "description": "Office visit, established", "units": 1}]
        result = cb._blocks_billing("Billed Services", data)
        assert result[0] == {
            "kind": "heading", "prefix": "Billed Services",
            "value": "Office visit, established (99213)",
        }
        assert {"kind": "field", "label": "UNITS", "value": "1"} in result

    def test_code_only_no_description(self):
        result = cb._blocks_billing("Billed Services", [{"code": "90686", "units": 2}])
        assert result[0] == {"kind": "heading", "prefix": "Billed Services", "value": "90686"}
        assert {"kind": "field", "label": "UNITS", "value": "2"} in result

    def test_no_units_omits_units_field(self):
        result = cb._blocks_billing("Billed Services", [{"code": "90686", "description": "Flu"}])
        assert result == [{"kind": "heading", "prefix": "Billed Services", "value": "Flu (90686)"}]

    def test_empty_title_skipped(self):
        assert cb._blocks_billing("Billed Services", [{"units": 1}]) == []

    def test_non_dict_skipped(self):
        assert cb._blocks_billing("Billed Services", [1, "x"]) == []

    def test_title_description_only(self):
        assert cb._billing_title({"description": "Flu"}) == "Flu"
