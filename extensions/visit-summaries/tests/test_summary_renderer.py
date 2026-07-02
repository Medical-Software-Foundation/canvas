"""Tests for summary_renderer covering uncovered branches."""
import pytest

from visit_summaries.helpers.summary_renderer import (
    _render_list,
    render_avs,
    render_previous_visit,
    render_since_last_visit,
)


class TestRenderAvs:
    """Tests for render_avs edit mode markup."""

    def _base_call(self, **overrides):
        defaults = dict(
            llm_data={
                "discussion": "We talked about your health.",
                "medications": ["Take as directed"],
                "next_steps": [
                    {"text": "Follow up in 2 weeks", "schema_key": "followUp"},
                ],
                "warning_signs": ["Chest pain", "Difficulty breathing"],
            },
            patient_info={
                "first_name": "Jane",
                "last_name": "Doe",
                "visit_date": "April 7",
                "provider_name": "Dr. Smith",
            },
            medications=[
                {"name": "Aspirin", "dose": "81mg", "sig": "daily", "schema_key": "prescribe"},
            ],
            plan_items=[
                {"text": "Follow up in 2 weeks", "schema_key": "followUp"},
            ],
        )
        defaults.update(overrides)
        return render_avs(**defaults)

    # Section structure

    def test_all_sections_have_data_section_attribute(self):
        html = self._base_call()
        for name in ["greeting", "discussion", "medications", "next-steps", "when-to-seek-care", "questions"]:
            assert f'data-section="{name}"' in html

    def test_all_sections_have_avs_removable_class(self):
        html = self._base_call()
        assert html.count("avs-removable") == 6

    def test_all_sections_have_section_remove_button(self):
        html = self._base_call()
        assert html.count("section-remove") == 6

    def test_all_sections_have_avs_section_header(self):
        html = self._base_call()
        assert html.count("avs-section-header") == 6

    # Medication items

    def test_medication_with_schema_key_has_cmd_badge(self):
        html = self._base_call()
        assert "cmd-badge" in html
        assert "avs-provenance" in html

    def test_medication_without_schema_key_has_item_remove(self):
        meds = [{"name": "Vitamin D", "dose": "1000IU", "sig": "daily", "schema_key": ""}]
        html = self._base_call(medications=meds, llm_data={"medications": ["Take daily"]})
        med_section = html.split('data-section="medications"')[1].split('data-section="')[0]
        assert "item-remove" in med_section
        assert "cmd-badge" not in med_section

    # Next steps items

    def test_next_step_with_schema_key_has_cmd_badge(self):
        html = self._base_call()
        steps_section = html.split('data-section="next-steps"')[1].split('data-section="')[0]
        assert "cmd-badge" in steps_section

    def test_next_step_without_schema_key_has_item_remove(self):
        html = self._base_call(
            llm_data={"next_steps": [{"text": "Rest well", "schema_key": ""}]},
            plan_items=[{"text": "Rest well", "schema_key": ""}],
        )
        steps_section = html.split('data-section="next-steps"')[1].split('data-section="')[0]
        assert "item-remove" in steps_section
        assert "cmd-badge" not in steps_section

    # Warning signs

    def test_warning_signs_have_item_remove(self):
        html = self._base_call()
        warn_section = html.split('data-section="when-to-seek-care"')[1].split('data-section="')[0]
        assert warn_section.count("item-remove") == 2
        assert warn_section.count("avs-item-text") == 2

    def test_default_warning_has_item_remove(self):
        html = self._base_call(llm_data={})
        warn_section = html.split('data-section="when-to-seek-care"')[1].split('data-section="')[0]
        assert "item-remove" in warn_section
        assert "avs-item-text" in warn_section

    # Content

    def test_greeting_contains_patient_name(self):
        html = self._base_call()
        assert "Jane" in html

    def test_discussion_section_renders_llm_text(self):
        html = self._base_call()
        assert "We talked about your health." in html

    def test_empty_medications_shows_no_changes(self):
        html = self._base_call(medications=[], llm_data={})
        assert "No changes to your medications" in html

    def test_empty_plan_shows_default_message(self):
        html = self._base_call(plan_items=[], llm_data={})
        assert "Continue with your regular care routine" in html


class TestRenderList:
    """Tests for _render_list helper."""

    def test_removable_true_has_item_remove(self):
        html = _render_list(["Item one", "Item two"], removable=True)
        assert html.count("item-remove") == 2
        assert html.count("avs-item-text") == 2

    def test_removable_false_has_no_item_remove(self):
        html = _render_list(["Item one"])
        assert "item-remove" not in html

    def test_empty_list_shows_message(self):
        html = _render_list([], empty_msg="Nothing here")
        assert "Nothing here" in html
        assert "no-data" in html


class TestRenderPreviousVisit:
    """Tests for render_previous_visit edge cases."""

    def _base_call(self, **overrides):
        defaults = dict(
            llm_data={},
            chief_complaint="Headache",
            diagnoses=[],
            medications=[],
            plan_items=[],
            vitals={},
        )
        defaults.update(overrides)
        return render_previous_visit(**defaults)

    def test_empty_diagnoses_shows_none_documented(self):
        html = self._base_call(diagnoses=[])
        assert "None documented" in html
        assert "no-data" in html

    def test_diagnoses_with_code_and_llm_detail(self):
        diagnoses = [{"code": "J06.9", "display": "Acute URI"}]
        llm_data = {"diagnoses": ["Upper respiratory infection, mild"]}
        html = self._base_call(diagnoses=diagnoses, llm_data=llm_data)
        assert "J06.9" in html
        assert "Acute URI" in html
        assert "Upper respiratory infection, mild" in html

    def test_diagnoses_without_code(self):
        diagnoses = [{"display": "Headache"}]
        html = self._base_call(diagnoses=diagnoses)
        assert "Headache" in html
        assert "<strong>" not in html.split("Headache")[0].split("<li>")[-1]

    def test_diagnoses_without_llm_detail(self):
        diagnoses = [{"code": "R51", "display": "Headache"}]
        html = self._base_call(diagnoses=diagnoses, llm_data={"diagnoses": []})
        assert "R51" in html
        assert "Headache" in html

    def test_medications_with_data(self):
        meds = [{"name": "Amoxicillin", "dose": "500mg", "sig": "Take twice daily"}]
        html = self._base_call(medications=meds)
        assert "Amoxicillin 500mg" in html
        assert "Take twice daily" in html

    def test_medications_without_sig(self):
        meds = [{"name": "Ibuprofen", "dose": "200mg"}]
        html = self._base_call(medications=meds)
        assert "Ibuprofen 200mg" in html

    def test_medications_empty_shows_none(self):
        html = self._base_call(medications=[])
        assert "None documented" in html

    def test_vitals_individual_rows(self):
        vitals = {"heart_rate": "72", "weight": "180", "height": "70"}
        html = self._base_call(vitals=vitals)
        assert "HR" in html
        assert "72 bpm" in html
        assert "Weight" in html
        assert "180 lbs" in html
        assert "Height" in html
        assert "70 in" in html

    def test_vitals_bp_rendering(self):
        vitals = {"systolic": "120", "diastolic": "80"}
        html = self._base_call(vitals=vitals)
        assert "BP" in html
        assert "120/80 mmHg" in html

    def test_vitals_bp_missing_diastolic(self):
        vitals = {"systolic": "120"}
        html = self._base_call(vitals=vitals)
        assert "120/?" in html

    def test_vitals_empty(self):
        html = self._base_call(vitals={})
        assert "No vitals documented" in html


class TestRenderSinceLastVisit:
    """Tests for render_since_last_visit edge cases."""

    def _base_call(self, **overrides):
        defaults = dict(
            llm_data={},
            lab_reports=[],
            medication_changes={"new": [], "stopped": []},
            condition_changes={"new": [], "resolved": []},
            completed_tasks=[],
            other_encounters=[],
        )
        defaults.update(overrides)
        return render_since_last_visit(**defaults)

    def test_medication_changes_new_and_stopped(self):
        changes = {"new": ["Metformin 500mg"], "stopped": ["Glipizide 5mg"]}
        html = self._base_call(medication_changes=changes)
        assert "NEW:" in html
        assert "Metformin 500mg" in html
        assert "STOPPED:" in html
        assert "Glipizide 5mg" in html

    def test_medication_changes_only_new(self):
        changes = {"new": ["Lisinopril 10mg"], "stopped": []}
        html = self._base_call(medication_changes=changes)
        assert "NEW:" in html
        assert "Lisinopril 10mg" in html
        assert "STOPPED:" not in html

    def test_medication_changes_empty(self):
        html = self._base_call()
        assert "No medication changes" in html

    def test_condition_changes_new_and_resolved(self):
        changes = {"new": ["Type 2 Diabetes"], "resolved": ["Acute bronchitis"]}
        html = self._base_call(condition_changes=changes)
        assert "NEW:" in html
        assert "Type 2 Diabetes" in html
        assert "RESOLVED:" in html
        assert "Acute bronchitis" in html

    def test_condition_changes_only_resolved(self):
        changes = {"new": [], "resolved": ["Acute sinusitis"]}
        html = self._base_call(condition_changes=changes)
        assert "RESOLVED:" in html
        assert "Acute sinusitis" in html
        assert "NEW:" not in html

    def test_condition_changes_empty(self):
        html = self._base_call()
        assert "None." in html

    def test_lab_reports_with_flag_and_ref(self):
        labs = [{"name": "Glucose", "value": "250", "units": "mg/dL", "reference_range": "70-100", "flag": "H"}]
        html = self._base_call(lab_reports=labs)
        assert "Glucose" in html
        assert "250" in html
        assert "ref: 70-100" in html
        assert "[H]" in html

    def test_lab_reports_with_interpretation(self):
        labs = [{"name": "A1c", "value": "7.2", "units": "%"}]
        llm_data = {"lab_interpretation": "A1c trending up from last visit."}
        html = self._base_call(lab_reports=labs, llm_data=llm_data)
        assert "A1c trending up" in html
        assert "banner-warning" in html
