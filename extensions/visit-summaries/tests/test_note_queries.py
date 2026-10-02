"""Tests for visit_summaries.helpers.note_queries."""
from unittest.mock import MagicMock, patch

import pytest

from visit_summaries.helpers.note_queries import (
    build_interim_context_for_llm,
    build_note_context_for_llm,
    extract_allergies_from_commands,
    extract_assess_plan_from_commands,
    extract_chief_complaint,
    extract_immunizations_from_commands,
    extract_medications_from_commands,
    extract_orders_from_commands,
    extract_questionnaires_from_commands,
    extract_vitals_from_commands,
    format_service_date,
    get_commands_for_note,
    get_lab_reports_in_range,
    get_most_recent_locked_note,
    has_interim_activity,
)


# ---------------------------------------------------------------------------
# extract_vitals_from_commands
# ---------------------------------------------------------------------------

def _make_cmd(schema_key: str, data: dict) -> MagicMock:
    cmd = MagicMock()
    cmd.schema_key = schema_key
    cmd.data = data
    return cmd


def test_extract_vitals_all_fields():
    commands = [
        _make_cmd(
            "vitals",
            {
                "blood_pressure_systole": 130,
                "blood_pressure_diastole": 85,
                "pulse": 72,
                "oxygen_saturation": 98,
                "weight_lbs": 165,
                "height": 68,
                "bmi": 24.5,
                "body_temperature": 98.6,
            },
        )
    ]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["systolic"] == "130"
    assert vitals["diastolic"] == "85"
    assert vitals["heart_rate"] == "72"
    assert vitals["spo2"] == "98"
    assert vitals["weight"] == "165"
    assert vitals["height"] == "68"
    assert vitals["bmi"] == "24.5"
    assert vitals["temperature"] == "98.6"


def test_extract_vitals_no_vitals_command():
    commands = [_make_cmd("assess", {"icd10_codes": [{"code": "J06.9", "display": "URI"}]})]
    vitals = extract_vitals_from_commands(commands)
    assert all(v is None for v in vitals.values())


def test_extract_vitals_partial_data():
    commands = [_make_cmd("vitals", {"pulse": 60})]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["heart_rate"] == "60"
    assert vitals["systolic"] is None


def test_extract_vitals_heart_rate_fallback():
    """Legacy heart_rate field name still works as fallback."""
    commands = [_make_cmd("vitals", {"heart_rate": 75})]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["heart_rate"] == "75"


# ---------------------------------------------------------------------------
# extract_assess_plan_from_commands
# ---------------------------------------------------------------------------

def test_extract_assess_with_icd10():
    commands = [
        _make_cmd(
            "assess",
            {"icd10_codes": [{"code": "J06.9", "display": "Upper Respiratory Infection"}]},
        )
    ]
    diagnoses, plan_items = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert diagnoses[0]["code"] == "J06.9"
    assert diagnoses[0]["display"] == "Upper Respiratory Infection"
    assert plan_items == []


def test_extract_plan_narrative():
    commands = [_make_cmd("plan", {"narrative": "Rest and fluids for 3 days."})]
    diagnoses, plan_items = extract_assess_plan_from_commands(commands)
    assert diagnoses == []
    assert "Rest and fluids" in plan_items[0]["text"]


def test_extract_instruct_nested_text():
    """Canvas stores instruct text in data['instruct']['text']."""
    commands = [_make_cmd("instruct", {
        "instruct": {
            "text": "Apply ice to lower back for 20 minutes every 2 hours.",
            "extra": {"coding": [{"code": "", "system": "UNSTRUCTURED", "display": "Apply ice to lower back for 20 minutes every 2 hours."}]},
            "value": "Apply ice to lower back for 20 minutes every 2 hours.",
        },
        "narrative": "",
    })]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert "Apply ice" in plan_items[0]["text"]


def test_extract_instruct_comment_fallback():
    """Falls back to comment when instruct.text and coding.display are empty."""
    commands = [_make_cmd("instruct", {
        "instruct": {"text": "", "value": ""},
        "comment": "Drink plenty of water",
    })]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert plan_items[0]["text"] == "Drink plenty of water"


def test_extract_followup_with_date():
    """Canvas followUp command has requested_date and note_type."""
    commands = [_make_cmd("followUp", {
        "reason_for_visit": "Check blood pressure",
        "requested_date": {"input": "2 weeks", "date": "2026-04-16"},
        "note_type": {"text": "Office Visit", "value": "1"},
    })]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert "Follow up in 2 weeks" in plan_items[0]["text"]
    assert "Office Visit" in plan_items[0]["text"]


def test_extract_assess_plan_empty_commands():
    diagnoses, plan_items = extract_assess_plan_from_commands([])
    assert diagnoses == []
    assert plan_items == []


# ---------------------------------------------------------------------------
# extract_chief_complaint
# ---------------------------------------------------------------------------

def test_extract_chief_complaint_rfv():
    """Canvas uses reasonForVisit (camelCase) as schema key."""
    commands = [_make_cmd("reasonForVisit", {"comment": "Sore throat and fever"})]
    result = extract_chief_complaint(commands)
    assert result == "Sore throat and fever"


def test_extract_chief_complaint_rfv_legacy_key():
    """Legacy reason_for_visit key still works as fallback."""
    commands = [_make_cmd("reason_for_visit", {"comment": "Back pain"})]
    result = extract_chief_complaint(commands)
    assert result == "Back pain"


def test_extract_chief_complaint_hpi_fallback():
    """Falls back to HPI when no reason for visit exists."""
    commands = [
        _make_cmd("vitals", {}),
        _make_cmd("hpi", {"narrative": "Patient reports burning sensation"}),
    ]
    result = extract_chief_complaint(commands)
    assert result == "Patient reports burning sensation"


def test_extract_chief_complaint_missing():
    commands = [_make_cmd("vitals", {})]
    result = extract_chief_complaint(commands)
    assert result == ""


# ---------------------------------------------------------------------------
# extract_medications_from_commands
# ---------------------------------------------------------------------------

def test_extract_medications_prescribe():
    """Canvas stores medication name in data['prescribe']['text']."""
    commands = [
        _make_cmd(
            "prescribe",
            {
                "prescribe": {"text": "Amoxicillin 500mg Capsule", "value": "123456"},
                "quantity_to_dispense": "30",
                "sig": "TID x 10 days",
            },
        )
    ]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert meds[0]["name"] == "Amoxicillin 500mg Capsule"
    assert meds[0]["dose"] == "30"
    assert meds[0]["sig"] == "TID x 10 days"


def test_extract_medications_prescribe_value_fallback():
    """Falls back to prescribe.value when text is empty."""
    commands = [
        _make_cmd("prescribe", {"prescribe": {"value": "FDB-789", "text": ""}, "sig": "BID"})
    ]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert meds[0]["name"] == "FDB-789"


def test_extract_medications_empty():
    meds = extract_medications_from_commands([])
    assert meds == []


# ---------------------------------------------------------------------------
# build_note_context_for_llm
# ---------------------------------------------------------------------------

def test_build_note_context_includes_vitals():
    note = MagicMock()
    note.datetime_of_service = "2025-01-15T10:00:00"

    vitals_cmd = _make_cmd("vitals", {"blood_pressure_systole": 120, "blood_pressure_diastole": 80, "pulse": 65})
    assess_cmd = _make_cmd("assess", {"icd10_codes": [{"code": "Z00.0", "display": "General exam"}]})

    with patch(
        "visit_summaries.helpers.note_queries.get_commands_for_note",
        return_value=[vitals_cmd, assess_cmd],
    ):
        context = build_note_context_for_llm(note)

    assert "120/80" in context
    assert "Z00.0" in context
    assert "January 15, 2025" in context


# ---------------------------------------------------------------------------
# get_most_recent_locked_note
# ---------------------------------------------------------------------------

def test_get_most_recent_locked_note_excludes_current():
    mock_note = MagicMock()
    current_note = MagicMock()
    current_note.datetime_of_service = "2025-03-15T09:00:00"

    mock_qs = MagicMock()
    mock_qs.select_related.return_value = mock_qs
    mock_qs.order_by.return_value = mock_qs
    mock_qs.exclude.return_value = mock_qs
    mock_qs.filter.return_value = mock_qs
    mock_qs.first.return_value = mock_note

    # For the current note lookup
    current_qs = MagicMock()
    current_qs.first.return_value = current_note

    with patch("visit_summaries.helpers.note_queries.Note") as MockNote:
        MockNote.objects.filter.side_effect = [mock_qs, current_qs]

        result = get_most_recent_locked_note("patient-xyz", exclude_note_id="note-aaa")

    assert result == mock_note
    mock_qs.exclude.assert_called_once_with(dbid="note-aaa")


def test_get_most_recent_locked_note_no_notes():
    mock_qs = MagicMock()
    mock_qs.select_related.return_value = mock_qs
    mock_qs.order_by.return_value = mock_qs
    mock_qs.first.return_value = None

    with patch("visit_summaries.helpers.note_queries.Note") as MockNote:
        MockNote.objects.filter.return_value = mock_qs

        result = get_most_recent_locked_note("patient-xyz")

    assert result is None


# ---------------------------------------------------------------------------
# build_interim_context_for_llm
# ---------------------------------------------------------------------------

_INTERIM_PATCHES = {
    "visit_summaries.helpers.note_queries.get_lab_reports_in_range": [],
    "visit_summaries.helpers.note_queries.Medication": MagicMock(),
    "visit_summaries.helpers.note_queries.Condition": MagicMock(),
    "visit_summaries.helpers.note_queries.Task": MagicMock(),
    "visit_summaries.helpers.note_queries.Appointment": MagicMock(),
}


def _patch_interim_defaults():
    """Return a contextmanager that patches all interim query dependencies to empty results."""
    from unittest.mock import patch as _patch
    import contextlib

    patches = []
    patches.append(_patch("visit_summaries.helpers.note_queries.get_lab_reports_in_range", return_value=[]))

    for model_path in [
        "visit_summaries.helpers.note_queries.Medication",
        "visit_summaries.helpers.note_queries.Condition",
        "visit_summaries.helpers.note_queries.Task",
        "visit_summaries.helpers.note_queries.Appointment",
    ]:
        mock_model = MagicMock()
        mock_model.objects.filter.return_value.select_related.return_value = []
        mock_model.objects.filter.return_value.prefetch_related.return_value = []
        mock_model.objects.filter.return_value = MagicMock()
        mock_model.objects.filter.return_value.__iter__ = MagicMock(return_value=iter([]))
        patches.append(_patch(model_path, mock_model))

    return contextlib.ExitStack(), patches


def test_build_interim_context_no_labs():
    stack, patches = _patch_interim_defaults()
    with stack:
        for p in patches:
            stack.enter_context(p)
        context = build_interim_context_for_llm("patient-xyz", "2025-01-01", "2025-01-15")

    assert "14 days" in context
    assert "None in this period" in context


def test_build_interim_context_with_labs():
    lab_value = MagicMock()
    lab_value.name = "HbA1c"
    lab_value.value = "7.2"
    lab_value.units = "%"
    lab_value.reference_range = "< 5.7"
    lab_value.abnormal_flag = "H"

    report = MagicMock()
    report.date_performed = "2025-01-10"
    report.values.all.return_value = [lab_value]

    stack, patches = _patch_interim_defaults()
    with stack:
        for p in patches:
            stack.enter_context(p)
        # Override just the lab reports patch
        with patch(
            "visit_summaries.helpers.note_queries.get_lab_reports_in_range",
            return_value=[report],
        ):
            context = build_interim_context_for_llm("patient-xyz", "2025-01-01", "2025-01-15")

    assert "HbA1c" in context
    assert "7.2" in context
    assert "[H]" in context


# ---------------------------------------------------------------------------
# get_commands_for_note
# ---------------------------------------------------------------------------

def test_get_commands_for_note_no_filter():
    note = MagicMock()
    cmd1 = MagicMock()
    note.commands.all.return_value = [cmd1]

    result = get_commands_for_note(note)
    assert result == [cmd1]
    note.commands.all.assert_called_once()


def test_get_commands_for_note_with_schema_keys():
    note = MagicMock()
    qs = MagicMock()
    note.commands.all.return_value = qs
    qs.filter.return_value = [MagicMock()]

    result = get_commands_for_note(note, schema_keys=["vitals", "assess"])
    qs.filter.assert_called_once_with(schema_key__in=["vitals", "assess"])


# ---------------------------------------------------------------------------
# get_lab_reports_in_range
# ---------------------------------------------------------------------------

def test_get_lab_reports_in_range():
    mock_report = MagicMock()
    mock_qs = MagicMock()
    mock_qs.prefetch_related.return_value = mock_qs
    mock_qs.order_by.return_value = [mock_report]

    with patch("visit_summaries.helpers.note_queries.LabReport") as MockLR:
        MockLR.objects.filter.return_value = mock_qs
        result = get_lab_reports_in_range("patient-1", "2025-01-01", "2025-01-31")

    assert result == [mock_report]


# ---------------------------------------------------------------------------
# build_note_context_for_llm (additional branches)
# ---------------------------------------------------------------------------

def test_build_note_context_full_note():
    """Cover all branches: chief complaint, vitals, diagnoses, plan, medications."""
    note = MagicMock()
    note.datetime_of_service = "2025-06-01T09:00:00"

    commands = [
        _make_cmd("reasonForVisit", {"comment": "Headache"}),
        _make_cmd("vitals", {
            "blood_pressure_systole": 140,
            "blood_pressure_diastole": 90,
            "pulse": 88,
            "oxygen_saturation": 96,
            "weight_lbs": 180,
            "height": 70,
            "bmi": 28.5,
            "body_temperature": 99.1,
        }),
        _make_cmd("assess", {"icd10_codes": [{"code": "R51", "display": "Headache"}]}),
        _make_cmd("plan", {"narrative": "Ibuprofen PRN, follow up in 2 weeks"}),
        _make_cmd("prescribe", {
            "prescribe": {"text": "Ibuprofen 400mg Tablet", "value": "55555"},
            "quantity_to_dispense": "30",
            "sig": "Q6H PRN",
        }),
    ]

    with patch(
        "visit_summaries.helpers.note_queries.get_commands_for_note",
        return_value=commands,
    ):
        context = build_note_context_for_llm(note)

    assert "June 1, 2025" in context
    assert "Headache" in context
    assert "140/90" in context
    assert "88 bpm" in context
    assert "96%" in context
    assert "180 lbs" in context
    assert "70 in" in context
    assert "28.5" in context
    assert "99.1" in context
    assert "R51" in context
    assert "Ibuprofen" in context
    assert "follow up in 2 weeks" in context


def test_build_note_context_no_service_date():
    note = MagicMock()
    note.datetime_of_service = None

    mock_cond_qs = MagicMock()
    mock_cond_qs.extra.return_value.prefetch_related.return_value = []

    with (
        patch("visit_summaries.helpers.note_queries.get_commands_for_note", return_value=[]),
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockCond.objects.filter.return_value = mock_cond_qs
        context = build_note_context_for_llm(note)

    assert "Note date:" in context


def test_extract_assess_condition_dict():
    """Canvas stores assess condition as a dict with text and value keys."""
    commands = [_make_cmd("assess", {
        "condition": {"value": 3, "text": "Sleep apnea, unspecified"},
        "status": "stable",
        "narrative": "Continuing CPAP therapy",
    })]
    diagnoses, plan_items = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert diagnoses[0]["display"] == "Sleep apnea, unspecified"
    assert diagnoses[0]["code"] == "3"


def test_extract_assess_condition_scalar_fallback():
    """Scalar condition value still works for backward compatibility."""
    commands = [_make_cmd("assess", {"icd10_codes": [], "condition": "Migraine"})]
    diagnoses, plan_items = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert diagnoses[0]["display"] == "Migraine"
    assert diagnoses[0]["code"] == ""


# ---------------------------------------------------------------------------
# _format_medication_changes
# ---------------------------------------------------------------------------

def test_format_medication_changes_with_data():
    from visit_summaries.helpers.note_queries import _format_medication_changes

    new_med = MagicMock()
    new_med.clinical_quantity_description = "Metformin 500mg"
    new_med.start_date = "2025-01-05"
    new_med.end_date = None

    stopped_med = MagicMock()
    stopped_med.clinical_quantity_description = "Lisinopril 10mg"
    stopped_med.end_date = "2025-01-10"
    stopped_med.start_date = None

    mock_med_cls = MagicMock()
    new_qs = MagicMock()
    new_qs.select_related.return_value = [new_med]
    new_qs.__iter__ = MagicMock(return_value=iter([new_med]))
    stopped_qs = MagicMock()
    stopped_qs.select_related.return_value = [stopped_med]
    stopped_qs.__iter__ = MagicMock(return_value=iter([stopped_med]))

    mock_med_cls.objects.filter.side_effect = [new_qs, stopped_qs]

    with patch("visit_summaries.helpers.note_queries.Medication", mock_med_cls):
        lines = _format_medication_changes("p1", "2025-01-01", "2025-01-15")

    joined = "\n".join(lines)
    assert "NEW: Metformin 500mg" in joined
    assert "STOPPED: Lisinopril 10mg" in joined


# ---------------------------------------------------------------------------
# _format_new_conditions
# ---------------------------------------------------------------------------

def test_format_new_conditions_with_data():
    from visit_summaries.helpers.note_queries import _format_new_conditions

    coding = MagicMock()
    coding.display = "Hypertension"
    coding.code = "I10"

    new_cond = MagicMock()
    new_cond.codings.first.return_value = coding

    resolved_cond = MagicMock()
    resolved_coding = MagicMock()
    resolved_coding.display = "Acute Bronchitis"
    resolved_cond.codings.first.return_value = resolved_coding

    mock_cond_cls = MagicMock()
    # New conditions: .filter(patient__id=...).extra(...).prefetch_related(...)
    new_inner_qs = MagicMock()
    new_final_qs = MagicMock()
    new_final_qs.__iter__ = MagicMock(return_value=iter([new_cond]))
    new_inner_qs.extra.return_value.prefetch_related.return_value = new_final_qs
    # Resolved conditions: .filter(patient__id=..., resolution_date__gte=..., ...).prefetch_related(...)
    resolved_qs = MagicMock()
    resolved_qs.prefetch_related.return_value.__iter__ = MagicMock(return_value=iter([resolved_cond]))

    mock_cond_cls.objects.filter.side_effect = [new_inner_qs, resolved_qs]

    with patch("visit_summaries.helpers.note_queries.Condition", mock_cond_cls):
        lines = _format_new_conditions("p1", "2025-01-01", "2025-01-15")

    joined = "\n".join(lines)
    assert "NEW: Hypertension (I10)" in joined
    assert "RESOLVED: Acute Bronchitis" in joined


# ---------------------------------------------------------------------------
# _format_completed_tasks
# ---------------------------------------------------------------------------

def test_format_completed_tasks_with_data():
    from visit_summaries.helpers.note_queries import _format_completed_tasks

    task = MagicMock()
    task.title = "Annual wellness labs"

    mock_task_cls = MagicMock()
    qs = MagicMock()
    qs.__iter__ = MagicMock(return_value=iter([task]))
    mock_task_cls.objects.filter.return_value = qs

    with patch("visit_summaries.helpers.note_queries.Task", mock_task_cls):
        lines = _format_completed_tasks("p1", "2025-01-01T00:00:00Z", "2025-01-15T00:00:00Z")

    joined = "\n".join(lines)
    assert "Annual wellness labs" in joined


# ---------------------------------------------------------------------------
# _format_other_encounters
# ---------------------------------------------------------------------------

def test_format_other_encounters_with_data():
    from visit_summaries.helpers.note_queries import _format_other_encounters

    provider = MagicMock()
    provider.first_name = "Sarah"
    provider.last_name = "Smith"

    appt = MagicMock()
    appt.start_time = "2025-01-08T14:00:00"
    appt.status = "completed"
    appt.description = "Telehealth follow-up"
    appt.provider = provider

    mock_appt_cls = MagicMock()
    qs = MagicMock()
    qs.select_related.return_value = qs
    qs.__iter__ = MagicMock(return_value=iter([appt]))
    mock_appt_cls.objects.filter.return_value = qs

    with patch("visit_summaries.helpers.note_queries.Appointment", mock_appt_cls):
        lines = _format_other_encounters("p1", "2025-01-01T00:00:00Z", "2025-01-15T00:00:00Z")

    joined = "\n".join(lines)
    assert "Telehealth follow-up" in joined
    assert "Sarah Smith" in joined


def test_extract_medications_no_dose_no_sig():
    """Cover branches where dose and sig are missing."""
    commands = [_make_cmd("prescribe", {"prescribe": {"text": "Aspirin", "value": "111"}})]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert meds[0]["name"] == "Aspirin"
    assert meds[0]["dose"] == ""
    assert meds[0]["sig"] == ""


def test_extract_medications_prescribe_string_fallback():
    """Handles case where prescribe field is a plain string instead of dict."""
    commands = [_make_cmd("prescribe", {"prescribe": "Metformin 500mg"})]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert meds[0]["name"] == "Metformin 500mg"


# ---------------------------------------------------------------------------
# extract_assess_plan_from_commands (diagnose dict format)
# ---------------------------------------------------------------------------

def test_extract_assess_diagnose_dict_with_icd_coding():
    """Cover the diagnose dict format with extra.coding containing ICD codes."""
    commands = [
        _make_cmd("diagnose", {
            "diagnose": {
                "text": "Hypertension",
                "extra": {
                    "coding": [
                        {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10", "display": "Essential hypertension"},
                        {"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertensive disorder"},
                    ]
                }
            }
        })
    ]
    diagnoses, _ = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert diagnoses[0]["code"] == "I10"
    assert diagnoses[0]["display"] == "Essential hypertension"


def test_extract_assess_diagnose_dict_text_fallback():
    """Cover the text fallback when coding list is empty."""
    commands = [
        _make_cmd("diagnose", {
            "diagnose": {
                "text": "Back pain",
                "value": "M54.5",
                "extra": {"coding": []}
            }
        })
    ]
    diagnoses, _ = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert diagnoses[0]["display"] == "Back pain"
    assert diagnoses[0]["code"] == "M54.5"


# ---------------------------------------------------------------------------
# extract_questionnaires_from_commands
# ---------------------------------------------------------------------------

def test_extract_questionnaires_with_options():
    """Cover questionnaire extraction with option label resolution."""
    commands = [
        _make_cmd("questionnaire", {
            "questionnaire": {
                "text": "PHQ-9",
                "extra": {
                    "name": "PHQ-9",
                    "questions": [
                        {
                            "name": "q1",
                            "label": "Little interest",
                            "options": [
                                {"value": "0", "label": "Not at all"},
                                {"value": "1", "label": "Several days"},
                            ]
                        }
                    ]
                }
            },
            "q1": "1",
        })
    ]
    results = extract_questionnaires_from_commands(commands)
    assert len(results) == 1
    assert results[0]["name"] == "PHQ-9"
    assert "Several days" in results[0]["answers"]


def test_extract_questionnaires_no_name_skips():
    """Questionnaire with no name should be skipped."""
    commands = [
        _make_cmd("questionnaire", {
            "questionnaire": {"text": "", "extra": {"name": ""}},
        })
    ]
    results = extract_questionnaires_from_commands(commands)
    assert results == []


def test_extract_questionnaires_no_label():
    """Cover branch where question has no label."""
    commands = [
        _make_cmd("questionnaire", {
            "questionnaire": {
                "text": "Intake",
                "extra": {
                    "name": "Intake",
                    "questions": [
                        {"name": "q1", "label": "", "options": []}
                    ]
                }
            },
            "q1": "yes",
        })
    ]
    results = extract_questionnaires_from_commands(commands)
    assert len(results) == 1
    assert "yes" in results[0]["answers"]


def test_extract_questionnaires_unanswered_skips():
    """Questions with None answer should be skipped."""
    commands = [
        _make_cmd("questionnaire", {
            "questionnaire": {
                "text": "Survey",
                "extra": {
                    "name": "Survey",
                    "questions": [
                        {"name": "q1", "label": "Rating", "options": []}
                    ]
                }
            },
        })
    ]
    results = extract_questionnaires_from_commands(commands)
    assert results == []


# ---------------------------------------------------------------------------
# build_note_context_for_llm (questionnaire and condition fallback branches)
# ---------------------------------------------------------------------------

def test_build_note_context_with_questionnaires():
    """Cover the questionnaire output branch in build_note_context_for_llm."""
    note = MagicMock()
    note.datetime_of_service = "2025-06-01T09:00:00"

    q_cmd = _make_cmd("questionnaire", {
        "questionnaire": {
            "text": "PHQ-9",
            "extra": {
                "name": "PHQ-9",
                "questions": [
                    {"name": "q1", "label": "Mood", "options": [{"value": "0", "label": "Good"}]}
                ]
            }
        },
        "q1": "0",
    })

    mock_cond_qs = MagicMock()
    mock_cond_qs.extra.return_value.prefetch_related.return_value = []

    with (
        patch("visit_summaries.helpers.note_queries.get_commands_for_note", return_value=[q_cmd]),
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockCond.objects.filter.return_value = mock_cond_qs
        context = build_note_context_for_llm(note)

    assert "PHQ-9" in context
    assert "Good" in context


def test_build_note_context_condition_fallback():
    """Cover the condition fallback when no diagnoses found in commands."""
    note = MagicMock()
    note.datetime_of_service = "2025-06-01T09:00:00"
    note.patient = MagicMock()
    note.dbid = "note-123"

    coding = MagicMock()
    coding.code = "I10"
    coding.display = "Essential hypertension"

    cond = MagicMock()
    cond.codings.first.return_value = coding

    mock_cond_qs = MagicMock()
    mock_cond_qs.extra.return_value.prefetch_related.return_value = [cond]

    with (
        patch("visit_summaries.helpers.note_queries.get_commands_for_note", return_value=[]),
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockCond.objects.filter.return_value = mock_cond_qs
        context = build_note_context_for_llm(note)

    assert "I10" in context
    assert "Essential hypertension" in context


# ---------------------------------------------------------------------------
# has_interim_activity
# ---------------------------------------------------------------------------

def test_has_interim_activity_lab_exists():
    """Short circuits on first match (labs)."""
    with (
        patch("visit_summaries.helpers.note_queries.LabReport") as MockLR,
    ):
        MockLR.objects.filter.return_value.exists.return_value = True
        result = has_interim_activity("p1", "2025-01-01", "2025-01-15")
    assert result is True


def test_has_interim_activity_medication_start():
    """Finds new medication start."""
    with (
        patch("visit_summaries.helpers.note_queries.LabReport") as MockLR,
        patch("visit_summaries.helpers.note_queries.Medication") as MockMed,
    ):
        MockLR.objects.filter.return_value.exists.return_value = False
        MockMed.objects.filter.return_value.exists.side_effect = [True]
        result = has_interim_activity("p1", "2025-01-01", "2025-01-15")
    assert result is True


def test_has_interim_activity_medication_stop():
    """Finds stopped medication."""
    with (
        patch("visit_summaries.helpers.note_queries.LabReport") as MockLR,
        patch("visit_summaries.helpers.note_queries.Medication") as MockMed,
    ):
        MockLR.objects.filter.return_value.exists.return_value = False
        MockMed.objects.filter.return_value.exists.side_effect = [False, True]
        result = has_interim_activity("p1", "2025-01-01", "2025-01-15")
    assert result is True


def test_has_interim_activity_condition():
    """Finds new condition."""
    with (
        patch("visit_summaries.helpers.note_queries.LabReport") as MockLR,
        patch("visit_summaries.helpers.note_queries.Medication") as MockMed,
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockLR.objects.filter.return_value.exists.return_value = False
        MockMed.objects.filter.return_value.exists.return_value = False
        MockCond.objects.filter.return_value.extra.return_value.exists.return_value = True
        result = has_interim_activity("p1", "2025-01-01", "2025-01-15")
    assert result is True


def test_has_interim_activity_task():
    """Finds completed task."""
    with (
        patch("visit_summaries.helpers.note_queries.LabReport") as MockLR,
        patch("visit_summaries.helpers.note_queries.Medication") as MockMed,
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
        patch("visit_summaries.helpers.note_queries.Task") as MockTask,
    ):
        MockLR.objects.filter.return_value.exists.return_value = False
        MockMed.objects.filter.return_value.exists.return_value = False
        MockCond.objects.filter.return_value.extra.return_value.exists.return_value = False
        MockTask.objects.filter.return_value.exists.return_value = True
        result = has_interim_activity("p1", "2025-01-01", "2025-01-15")
    assert result is True


def test_has_interim_activity_appointment():
    """Finds appointment."""
    with (
        patch("visit_summaries.helpers.note_queries.LabReport") as MockLR,
        patch("visit_summaries.helpers.note_queries.Medication") as MockMed,
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
        patch("visit_summaries.helpers.note_queries.Task") as MockTask,
        patch("visit_summaries.helpers.note_queries.Appointment") as MockAppt,
    ):
        MockLR.objects.filter.return_value.exists.return_value = False
        MockMed.objects.filter.return_value.exists.return_value = False
        MockCond.objects.filter.return_value.extra.return_value.exists.return_value = False
        MockTask.objects.filter.return_value.exists.return_value = False
        MockAppt.objects.filter.return_value.exists.return_value = True
        result = has_interim_activity("p1", "2025-01-01", "2025-01-15")
    assert result is True


def test_has_interim_activity_none():
    """Returns False when no activity in any category."""
    with (
        patch("visit_summaries.helpers.note_queries.LabReport") as MockLR,
        patch("visit_summaries.helpers.note_queries.Medication") as MockMed,
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
        patch("visit_summaries.helpers.note_queries.Task") as MockTask,
        patch("visit_summaries.helpers.note_queries.Appointment") as MockAppt,
    ):
        MockLR.objects.filter.return_value.exists.return_value = False
        MockMed.objects.filter.return_value.exists.return_value = False
        MockCond.objects.filter.return_value.extra.return_value.exists.return_value = False
        MockTask.objects.filter.return_value.exists.return_value = False
        MockAppt.objects.filter.return_value.exists.return_value = False
        result = has_interim_activity("p1", "2025-01-01", "2025-01-15")
    assert result is False


# ---------------------------------------------------------------------------
# format_service_date (timezone safety)
# ---------------------------------------------------------------------------

def test_format_service_date_none():
    assert format_service_date(None) == ""


def test_format_service_date_naive_utc_shifts_to_eastern():
    """A naive datetime near midnight UTC should shift to the previous day in US Eastern."""
    result = format_service_date("2026-03-24T03:00:00")
    assert "March 23, 2026" in result


def test_format_service_date_aware_preserves_tz():
    """A timezone-aware datetime should format in its own timezone."""
    import arrow as _arrow
    dt = _arrow.get("2026-03-24T10:00:00-04:00")
    result = format_service_date(dt)
    assert "March 24, 2026" in result


def test_format_service_date_custom_format():
    result = format_service_date("2025-06-15T12:00:00-04:00", "MMM D, YYYY")
    assert result == "Jun 15, 2025"


# ---------------------------------------------------------------------------
# extract_vitals_from_commands (height and BP fallback field names)
# ---------------------------------------------------------------------------

def test_extract_vitals_height():
    commands = [_make_cmd("vitals", {"height": 68})]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["height"] == "68"


def test_extract_vitals_height_inches_variant():
    commands = [_make_cmd("vitals", {"height_inches": 65})]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["height"] == "65"


def test_extract_vitals_bp_systole_diastole_fields():
    """Cover the blood_pressure_systole/diastole field names (Canvas default)."""
    commands = [_make_cmd("vitals", {"blood_pressure_systole": 130, "blood_pressure_diastole": 85})]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["systolic"] == "130"
    assert vitals["diastolic"] == "85"


def test_extract_vitals_bp_short_field_names():
    """Cover the fallback field names systolic/diastolic."""
    commands = [_make_cmd("vitals", {"systolic": 120, "diastolic": 80})]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["systolic"] == "120"
    assert vitals["diastolic"] == "80"


def test_extract_vitals_bp_long_names_take_priority():
    """blood_pressure_systole should be preferred over systolic."""
    commands = [_make_cmd("vitals", {
        "blood_pressure_systole": 140,
        "systolic": 999,
        "blood_pressure_diastole": 90,
        "diastolic": 999,
    })]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["systolic"] == "140"
    assert vitals["diastolic"] == "90"


def test_extract_vitals_height_absent():
    commands = [_make_cmd("vitals", {"heart_rate": 70})]
    vitals = extract_vitals_from_commands(commands)
    assert vitals["height"] is None


# ---------------------------------------------------------------------------
# extract_chief_complaint (HPI fallback)
# ---------------------------------------------------------------------------

def test_extract_chief_complaint_hpi_fallback():
    """When no RFV exists, HPI narrative should be used as chief complaint."""
    commands = [
        _make_cmd("vitals", {}),
        _make_cmd("hpi", {"narrative": "Patient presents with persistent cough for 3 days"}),
    ]
    result = extract_chief_complaint(commands)
    assert "persistent cough" in result


def test_extract_chief_complaint_rfv_takes_priority_over_hpi():
    """RFV should be preferred even when HPI is also present."""
    commands = [
        _make_cmd("reason_for_visit", {"comment": "Cough"}),
        _make_cmd("hpi", {"narrative": "Long HPI narrative about the cough"}),
    ]
    result = extract_chief_complaint(commands)
    assert result == "Cough"


def test_extract_chief_complaint_history_of_present_illness_variant():
    commands = [_make_cmd("history_of_present_illness", {"comment": "Chest pain"})]
    result = extract_chief_complaint(commands)
    assert result == "Chest pain"


def test_extract_chief_complaint_no_rfv_no_hpi():
    commands = [_make_cmd("vitals", {}), _make_cmd("assess", {})]
    result = extract_chief_complaint(commands)
    assert result == ""


# ---------------------------------------------------------------------------
# extract_assess_plan_from_commands (instruct and follow_up)
# ---------------------------------------------------------------------------

def test_extract_plan_instruct_command():
    commands = [_make_cmd("instruct", {"narrative": "Take medication with food"})]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert "Take medication with food" in plan_items[0]["text"]


def test_extract_plan_follow_up_command():
    commands = [_make_cmd("follow_up", {"comment": "Return in 2 weeks for BP check"})]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert "Return in 2 weeks" in plan_items[0]["text"]


def test_extract_instruct_unstructured_coding():
    """Instruct with UNSTRUCTURED system and display text."""
    commands = [_make_cmd("instruct", {
        "coding": {"code": "", "system": "UNSTRUCTURED", "display": "Apply ice 20min every 2 hours"},
    })]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert "Apply ice" in plan_items[0]["text"]


def test_extract_plan_mixed_plan_instruct_follow_up():
    commands = [
        _make_cmd("plan", {"narrative": "Continue current regimen"}),
        _make_cmd("instruct", {"narrative": "Elevate leg when resting"}),
        _make_cmd("follow_up", {"comment": "Follow up in 4 weeks"}),
    ]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 3


def test_extract_plan_followUp_camelcase():
    """Cover the camelCase followUp schema_key used by Canvas."""
    commands = [_make_cmd("followUp", {
        "note_type": {"text": "Office visit", "value": "1"},
        "requested_date": {"date": "2026-04-21", "input": "4 weeks"},
        "reason_for_visit": "",
    })]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert "4 weeks" in plan_items[0]["text"]
    assert "Office visit" in plan_items[0]["text"]


def test_extract_instruct_snomed_coding():
    """Instruct with SNOMED coding and a comment."""
    commands = [_make_cmd("instruct", {
        "coding": {"code": "304549008", "system": "http://snomed.info/sct", "display": "Apply ice for 20 minutes every 2 hours."},
        "comment": "As needed for swelling",
    })]
    _, plan_items = extract_assess_plan_from_commands(commands)
    assert len(plan_items) == 1
    assert "Apply ice" in plan_items[0]["text"]


# ---------------------------------------------------------------------------
# extract_medications_from_commands (prescribe_medication variant)
# ---------------------------------------------------------------------------

def test_extract_medications_with_all_fields():
    """Full prescribe command with all Canvas fields populated."""
    commands = [
        _make_cmd("prescribe", {
            "prescribe": {"text": "Metformin 500mg Tablet", "value": "99999", "extra": {"coding": []}},
            "sig": "BID with meals",
            "quantity_to_dispense": "60",
            "days_supply": 30,
            "refills": 3,
        })
    ]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert meds[0]["name"] == "Metformin 500mg Tablet"
    assert meds[0]["sig"] == "BID with meals"
    assert meds[0]["dose"] == "60"


def test_extract_medications_medication_statement():
    """Canvas medicationStatement uses data['medication']['text']."""
    commands = [
        _make_cmd("medicationStatement", {
            "medication": {
                "text": "Dulera 100 mcg-5 mcg/actuation HFA aerosol inhaler",
                "value": 1,
                "extra": {"coding": [{"code": "561632", "system": "http://www.fdbhealth.com/", "display": "Dulera 100 mcg-5 mcg/actuation HFA aerosol inhaler"}]},
            },
            "sig": "",
        })
    ]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert "Dulera" in meds[0]["name"]


# ---------------------------------------------------------------------------
# build_note_context_for_llm (height in output, instruct/follow_up in output)
# ---------------------------------------------------------------------------

def test_build_note_context_includes_height():
    note = MagicMock()
    note.datetime_of_service = "2025-01-15T10:00:00-05:00"

    commands = [_make_cmd("vitals", {"height": 70, "weight_lbs": 180})]

    mock_cond_qs = MagicMock()
    mock_cond_qs.extra.return_value.prefetch_related.return_value = []

    with (
        patch("visit_summaries.helpers.note_queries.get_commands_for_note", return_value=commands),
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockCond.objects.filter.return_value = mock_cond_qs
        context = build_note_context_for_llm(note)

    assert "Height: 70 in" in context
    assert "Weight: 180 lbs" in context


def test_build_note_context_includes_instruct_and_follow_up():
    note = MagicMock()
    note.datetime_of_service = "2025-06-01T09:00:00-04:00"

    commands = [
        _make_cmd("plan", {"narrative": "Continue meds"}),
        _make_cmd("instruct", {"narrative": "Rest for 48 hours"}),
        _make_cmd("follow_up", {"comment": "Return in 1 week"}),
    ]

    mock_cond_qs = MagicMock()
    mock_cond_qs.extra.return_value.prefetch_related.return_value = []

    with (
        patch("visit_summaries.helpers.note_queries.get_commands_for_note", return_value=commands),
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockCond.objects.filter.return_value = mock_cond_qs
        context = build_note_context_for_llm(note)

    assert "Continue meds" in context
    assert "Rest for 48 hours" in context
    assert "Return in 1 week" in context


def test_build_note_context_hpi_as_chief_complaint():
    note = MagicMock()
    note.datetime_of_service = "2025-06-01T09:00:00-04:00"

    commands = [_make_cmd("hpi", {"narrative": "Knee pain after running"})]

    mock_cond_qs = MagicMock()
    mock_cond_qs.extra.return_value.prefetch_related.return_value = []

    with (
        patch("visit_summaries.helpers.note_queries.get_commands_for_note", return_value=commands),
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockCond.objects.filter.return_value = mock_cond_qs
        context = build_note_context_for_llm(note)

    assert "Chief Complaint: Knee pain after running" in context


# ---------------------------------------------------------------------------
# extract_orders_from_commands
# ---------------------------------------------------------------------------

def test_extract_orders_referral():
    commands = [_make_cmd("refer", {
        "refer_to": {"text": "Dr. Smith, Cardiology", "value": "123"},
        "priority": "urgent",
        "notes_to_specialist": "Evaluate chest pain",
    })]
    orders = extract_orders_from_commands(commands)
    assert len(orders) == 1
    assert orders[0]["type"] == "Referral"
    assert "Cardiology" in orders[0]["description"]
    assert orders[0]["priority"] == "urgent"
    assert "chest pain" in orders[0]["notes"]


def test_extract_orders_lab_order():
    commands = [_make_cmd("labOrder", {
        "tests": [
            {"text": "CBC", "value": "1"},
            {"text": "BMP", "value": "2"},
        ],
        "comment": "Fasting preferred",
        "fasting_status": True,
    })]
    orders = extract_orders_from_commands(commands)
    assert len(orders) == 1
    assert orders[0]["type"] == "Lab order"
    assert "CBC" in orders[0]["description"]
    assert "BMP" in orders[0]["description"]
    assert "fasting required" in orders[0]["description"]


def test_extract_orders_imaging_order():
    commands = [_make_cmd("imagingOrder", {
        "image": {"text": "X-ray chest PA and lateral", "value": "71046"},
        "priority": "routine",
        "additional_details": "Rule out pneumonia",
    })]
    orders = extract_orders_from_commands(commands)
    assert len(orders) == 1
    assert orders[0]["type"] == "Imaging order"
    assert "X-ray" in orders[0]["description"]
    assert "pneumonia" in orders[0]["notes"]


def test_extract_orders_empty():
    orders = extract_orders_from_commands([])
    assert orders == []


def test_extract_orders_mixed():
    commands = [
        _make_cmd("refer", {"refer_to": {"text": "ENT specialist", "value": "1"}}),
        _make_cmd("labOrder", {"tests": [{"text": "TSH", "value": "3"}]}),
        _make_cmd("imagingOrder", {"image": {"text": "MRI brain", "value": "70553"}}),
    ]
    orders = extract_orders_from_commands(commands)
    assert len(orders) == 3
    assert orders[0]["type"] == "Referral"
    assert orders[1]["type"] == "Lab order"
    assert orders[2]["type"] == "Imaging order"


# ---------------------------------------------------------------------------
# extract_allergies_from_commands
# ---------------------------------------------------------------------------

def test_extract_allergies():
    commands = [_make_cmd("allergy", {
        "allergy": {"text": "Penicillin", "value": "123", "extra": {"category": "drug"}},
        "severity": "severe",
        "narrative": "Anaphylaxis reported",
    })]
    allergies = extract_allergies_from_commands(commands)
    assert len(allergies) == 1
    assert allergies[0]["name"] == "Penicillin"
    assert allergies[0]["severity"] == "severe"
    assert "Anaphylaxis" in allergies[0]["narrative"]


def test_extract_allergies_whitespace_skipped():
    commands = [_make_cmd("allergy", {"allergy": {"text": "  ", "value": ""}})]
    allergies = extract_allergies_from_commands(commands)
    assert allergies == []


def test_extract_allergies_empty():
    allergies = extract_allergies_from_commands([])
    assert allergies == []


# ---------------------------------------------------------------------------
# extract_immunizations_from_commands
# ---------------------------------------------------------------------------

def test_extract_immunizations_immunize():
    commands = [_make_cmd("immunize", {
        "coding": {"text": "Influenza vaccine", "value": "88", "extra": {"coding": []}},
        "consent_given": True,
    })]
    immunizations = extract_immunizations_from_commands(commands)
    assert len(immunizations) == 1
    assert immunizations[0]["name"] == "Influenza vaccine"


def test_extract_immunizations_statement():
    commands = [_make_cmd("immunizationStatement", {
        "statement": {"text": "COVID-19 mRNA vaccine", "value": "213"},
        "date": {"input": "Jan 2026", "date": "2026-01-15"},
        "comments": "Booster dose",
    })]
    immunizations = extract_immunizations_from_commands(commands)
    assert len(immunizations) == 1
    assert "COVID-19" in immunizations[0]["name"]
    assert immunizations[0]["date"] == "Jan 2026"


def test_extract_immunizations_empty():
    immunizations = extract_immunizations_from_commands([])
    assert immunizations == []


# ---------------------------------------------------------------------------
# extract_medications_from_commands (stopMedication and refill)
# ---------------------------------------------------------------------------

def test_extract_medications_stop():
    commands = [_make_cmd("stopMedication", {
        "medication": {"text": "Lisinopril 10mg Tablet", "value": 1},
        "rationale": "Patient reported cough",
    })]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert "Lisinopril" in meds[0]["name"]
    assert meds[0]["status"] == "stopped"


def test_extract_medications_refill():
    commands = [_make_cmd("refill", {
        "prescribe": {"text": "Metformin 500mg Tablet", "value": "99999"},
        "sig": "BID with meals",
        "quantity_to_dispense": "60",
    })]
    meds = extract_medications_from_commands(commands)
    assert len(meds) == 1
    assert "Metformin" in meds[0]["name"]
    assert meds[0]["status"] == "refill"
    assert meds[0]["sig"] == "BID with meals"


# ---------------------------------------------------------------------------
# extract_assess_plan_from_commands (updateDiagnosis and resolveCondition)
# ---------------------------------------------------------------------------

def test_extract_assess_update_diagnosis():
    commands = [_make_cmd("updateDiagnosis", {
        "new_condition": {
            "text": "Type 2 diabetes mellitus",
            "value": "E11.9",
            "extra": {"coding": [{"code": "E11.9", "system": "ICD-10", "display": "Type 2 diabetes mellitus"}]},
        },
        "condition": {"text": "Prediabetes", "value": "R73.03"},
    })]
    diagnoses, _ = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert "Type 2 diabetes" in diagnoses[0]["display"]
    assert diagnoses[0]["tag"] == "updated"
    assert diagnoses[0]["code"] == "E11.9"


def test_extract_assess_update_diagnosis_condition_fallback():
    """Falls back to condition when new_condition is absent."""
    commands = [_make_cmd("updateDiagnosis", {
        "condition": {"text": "Hypertension", "value": "I10"},
        "narrative": "Reclassified",
    })]
    diagnoses, _ = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert "Hypertension" in diagnoses[0]["display"]


def test_extract_assess_resolve_condition():
    commands = [_make_cmd("resolveCondition", {
        "condition": {"text": "Acute bronchitis", "value": 5},
        "rationale": "Symptoms resolved",
    })]
    diagnoses, _ = extract_assess_plan_from_commands(commands)
    assert len(diagnoses) == 1
    assert "Acute bronchitis" in diagnoses[0]["display"]
    assert diagnoses[0]["tag"] == "resolved"


# ---------------------------------------------------------------------------
# build_note_context_for_llm (orders, allergies, immunizations)
# ---------------------------------------------------------------------------

def test_build_note_context_with_orders_allergies_immunizations():
    note = MagicMock()
    note.datetime_of_service = "2025-06-01T09:00:00-04:00"

    commands = [
        _make_cmd("refer", {"refer_to": {"text": "Cardiology", "value": "1"}}),
        _make_cmd("labOrder", {"tests": [{"text": "Lipid panel", "value": "2"}]}),
        _make_cmd("allergy", {"allergy": {"text": "Sulfa drugs", "value": "3"}, "severity": "moderate"}),
        _make_cmd("immunize", {"coding": {"text": "Flu shot", "value": "4"}}),
    ]

    mock_cond_qs = MagicMock()
    mock_cond_qs.extra.return_value.prefetch_related.return_value = []

    with (
        patch("visit_summaries.helpers.note_queries.get_commands_for_note", return_value=commands),
        patch("visit_summaries.helpers.note_queries.Condition") as MockCond,
    ):
        MockCond.objects.filter.return_value = mock_cond_qs
        context = build_note_context_for_llm(note)

    assert "Referral: Cardiology" in context
    assert "Lab order: Lipid panel" in context
    assert "Sulfa drugs (moderate)" in context
    assert "Flu shot" in context
