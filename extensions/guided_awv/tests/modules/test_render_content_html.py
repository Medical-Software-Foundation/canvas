"""Tests for render_content_html() across all AWV modules."""

import datetime
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from guided_awv.modules.base import AWVType, BaseModule
from guided_awv.modules.hra import HRAModule
from guided_awv.modules.medical_history import MedicalHistoryModule
from guided_awv.modules.family_history import FamilyHistoryModule
from guided_awv.modules.current_providers import CurrentProvidersModule
from guided_awv.modules.vitals import VitalsModule
from guided_awv.modules.hearing_vision import HearingVisionModule
from guided_awv.modules.depression_screening import DepressionScreeningModule
from guided_awv.modules.alcohol_screening import AlcoholScreeningModule
from guided_awv.modules.cognitive_assessment import CognitiveAssessmentModule
from guided_awv.modules.fall_risk import FallRiskModule
from guided_awv.modules.functional_ability import FunctionalAbilityModule
from guided_awv.modules.advance_care_planning import AdvanceCarePlanningModule
from guided_awv.modules.preventive_services import PreventiveServicesModule
from guided_awv.modules.assessment_plan import AssessmentPlanModule
from guided_awv.modules.followup_scheduling import FollowUpSchedulingModule
from guided_awv.modules.medication_reconciliation import MedicationReconciliationModule
from guided_awv.modules.sdoh_screening import SDOHScreeningModule


# ---------------------------------------------------------------------------
# BaseModule helpers
# ---------------------------------------------------------------------------


class _Concrete(BaseModule):
    ORDER = 99
    TITLE = "Test"
    AWV_TYPES = AWVType.BOTH

    def get_context(self) -> dict[str, object]:
        return {}


class TestBaseModuleHelpers:
    """Tests for BaseModule HTML helper methods."""

    def _mod(self) -> _Concrete:
        return _Concrete("n", "p", AWVType.INITIAL)

    def test_text_input(self) -> None:
        html = self._mod()._text_input("fname", "First Name", placeholder="Enter name", value="Jane")
        assert 'name="fname"' in html
        assert 'value="Jane"' in html
        assert 'placeholder="Enter name"' in html
        assert 'class="awv-input"' in html

    def test_number_input_basic(self) -> None:
        html = self._mod()._number_input("age", "Age")
        assert 'type="number"' in html
        assert 'name="age"' in html

    def test_number_input_attrs(self) -> None:
        html = self._mod()._number_input("bp", "BP", min_val="0", max_val="300", step="1", readonly=True)
        assert 'min="0"' in html
        assert 'max="300"' in html
        assert 'step="1"' in html
        assert "readonly" in html

    def test_textarea(self) -> None:
        html = self._mod()._textarea("notes", "Notes", placeholder="Type here", rows=5)
        assert 'name="notes"' in html
        assert 'rows="5"' in html
        assert 'placeholder="Type here"' in html

    def test_radio_group_string_options(self) -> None:
        html = self._mod()._radio_group("color", "Pick color", ["Red", "Blue"])
        assert 'name="color"' in html
        assert 'value="Red"' in html
        assert 'value="Blue"' in html
        assert 'type="radio"' in html

    def test_radio_group_dict_options(self) -> None:
        html = self._mod()._radio_group("q", "Question", [{"value": "0", "label": "Never"}])
        assert 'value="0"' in html
        assert "Never" in html

    def test_select(self) -> None:
        html = self._mod()._select("size", "Size", [{"value": "S", "label": "Small"}, "Large"])
        assert '-- Select --' in html
        assert 'value="S"' in html
        assert "Small" in html
        assert 'value="Large"' in html

    def test_checkbox_group(self) -> None:
        html = self._mod()._checkbox_group("items", "Pick items", ["A", "B"])
        assert 'type="checkbox"' in html
        assert 'value="A"' in html
        assert 'value="B"' in html

    def test_info_row(self) -> None:
        html = self._mod()._info_row("Weight", "150 lbs")
        assert "Weight" in html
        assert "150 lbs" in html
        assert "awv-info-row" in html

    def test_subtitle(self) -> None:
        html = self._mod()._subtitle("Section Title")
        assert "<h3" in html
        assert "Section Title" in html

    def test_alert(self) -> None:
        html = self._mod()._alert("Warning!", "warning")
        assert "awv-alert--warning" in html
        assert "Warning!" in html

    def test_divider(self) -> None:
        assert "awv-divider" in self._mod()._divider()

    def test_save_button(self) -> None:
        html = self._mod()._save_button("saveThing", "Save Thing")
        assert 'onclick="saveThing()"' in html
        assert "Save Thing" in html
        assert 'id="_concrete-save-btn"' in html  # _Concrete -> "_concrete"
        assert 'id="_concrete-status"' in html

    def test_default_render_content_html(self) -> None:
        """Default implementation returns a placeholder message."""
        html = self._mod().render_content_html()
        assert "No content template defined" in html


# ---------------------------------------------------------------------------
# Non-ORM modules (no mocking required)
# ---------------------------------------------------------------------------


class TestHRARender:
    def test_returns_html_string(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert isinstance(html, str)
        assert len(html) > 0

    def test_contains_section_subtitles(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "General Health Status" in html
        assert "Behavioral Risk Factors" in html
        assert "Psychosocial Risks" in html

    def test_initial_has_adl_section(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Activities of Daily Living" in html

    def test_subsequent_no_adl_section(self) -> None:
        html = HRAModule("n", "p", AWVType.SUBSEQUENT).render_content_html()
        assert "Activities of Daily Living" not in html

    def test_tobacco_alert_hidden(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="tobacco-alert"' in html
        assert 'style="display:none;"' in html

    def test_radio_groups_present(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="general_health"' in html
        assert 'name="tobacco_use"' in html

    def test_number_inputs_present(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="alcohol_use"' in html
        assert 'name="exercise_days"' in html

    def test_hra_completion_radio(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="hra_completed"' in html

    def test_hra_completion_method_conditional(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'data-conditional-on="hra_completed"' in html
        assert 'name="hra_completion_method"' in html

    def test_hra_health_concerns_textarea(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="hra_health_concerns"' in html


class TestDepressionScreeningRender:
    def test_phq2_questions(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="phq2_q1"' in html
        assert 'name="phq2_q2"' in html

    def test_phq9_questions(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        for i in range(3, 10):
            assert f'name="phq9_q{i}"' in html

    def test_phq2_score_element(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="phq2-score"' in html
        assert 'id="phq2-alert"' in html

    def test_phq9_score_and_severity(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="phq9-score"' in html
        assert 'id="phq9-severity"' in html

    def test_response_options(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Not at all" in html
        assert "Nearly every day" in html

    def test_scoring_reference(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Scoring Reference" in html
        assert "0-4" in html

    def test_suicide_ideation_assessed_radio(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="suicide_ideation_assessed"' in html
        assert "N/A - PHQ-2 negative" in html

    def test_suicide_ideation_present_radio(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="suicide_ideation_present"' in html

    def test_followup_section_hidden(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="depression-followup-section"' in html

    def test_safety_assessment_radio(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="safety_assessed"' in html
        assert "assessed_no_risk" in html

    def test_treatment_plan_select(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="depression_treatment_plan"' in html
        assert "Behavioral health referral" in html

    def test_treatment_notes_textarea(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="depression_treatment_notes"' in html


class TestCognitiveAssessmentRender:
    def test_mini_cog_fields(self) -> None:
        html = CognitiveAssessmentModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="words_recalled"' in html
        assert 'name="clock_drawing_score"' in html

    def test_tool_selector_radio(self) -> None:
        html = CognitiveAssessmentModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="cognitive_tool"' in html
        assert 'value="mini_cog"' in html
        assert 'value="moca"' in html
        assert 'value="slums"' in html
        assert 'value="mmse"' in html

    def test_alt_tool_section(self) -> None:
        html = CognitiveAssessmentModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="tool-alt"' in html
        assert 'name="alt_cog_score"' in html
        assert 'id="alt-cog-alert"' in html
        assert 'id="alt-cog-interpretation-value"' in html

    def test_mini_cog_wrapper_div(self) -> None:
        html = CognitiveAssessmentModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="tool-mini_cog"' in html

    def test_screening_completed_radio(self) -> None:
        html = CognitiveAssessmentModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="cognitive_screening_completed"' in html
        assert "No - patient refused" in html
        assert "No - deferred" in html

    def test_interpretation_display(self) -> None:
        html = CognitiveAssessmentModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="minicog-interpretation"' in html
        assert 'id="minicog-interpretation-value"' in html

    def test_followup_plan_section(self) -> None:
        html = CognitiveAssessmentModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="cognitive-followup-section"' in html
        assert 'name="cognitive_followup_plan"' in html


class TestFallRiskRender:
    def test_screening_questions(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="falls_past_year"' in html
        assert 'name="fear_of_falling"' in html

    def test_conditional_fields(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'data-conditional-on="falls_past_year"' in html
        assert 'data-conditional-value="Yes"' in html

    def test_steadi_result_display(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="steadi-result"' in html
        assert 'id="steadi-result-value"' in html
        assert "STEADI Screen Result" in html

    def test_tug_test(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="tug_time_seconds"' in html
        assert "Timed Up and Go" in html

    def test_orthostatic_section_present(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Orthostatic (Postural) Vital Signs" in html

    def test_orthostatic_lying_fields(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="ortho_lying_sbp"' in html
        assert 'name="ortho_lying_dbp"' in html
        assert 'name="ortho_lying_hr"' in html

    def test_orthostatic_standing_fields(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="ortho_standing_sbp"' in html
        assert 'name="ortho_standing_dbp"' in html
        assert 'name="ortho_standing_hr"' in html

    def test_orthostatic_result_fields_readonly(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        for field_name in ("ortho_sbp_drop", "ortho_dbp_drop"):
            idx = html.index(f'name="{field_name}"')
            tag_start = html.rfind("<input", 0, idx)
            tag_end = html.index(">", idx)
            tag = html[tag_start:tag_end + 1]
            assert "readonly" in tag

    def test_orthostatic_result_display(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="ortho-result"' in html
        assert 'id="ortho-alert"' in html

    def test_orthostatic_hypotension_in_risk_factors(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'value="Orthostatic hypotension"' in html

    def test_steadi_assessment_wrapper(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="steadi-assessment"' in html
        assert 'style="display:none;"' in html
        # TUG and Orthostatic sections are inside the wrapper
        wrapper_start = html.index('id="steadi-assessment"')
        wrapper_close = html.index('</div>', html.index('id="ortho-alert"'))
        tug_pos = html.index("Timed Up and Go")
        ortho_pos = html.index("Orthostatic (Postural)")
        assert wrapper_start < tug_pos < wrapper_close
        assert wrapper_start < ortho_pos < wrapper_close

    def test_section_ordering(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        tug_pos = html.index("Timed Up and Go")
        ortho_pos = html.index("Orthostatic (Postural)")
        risk_pos = html.index("Risk Factors to Assess")
        assert tug_pos < ortho_pos < risk_pos

    def test_fall_risk_level_display(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="fall-risk-level"' in html
        assert "Overall Fall Risk Level" in html

    def test_fall_risk_alert(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="fall-risk-alert"' in html
        assert 'style="display:none;"' in html

    def test_risk_factor_checkboxes(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="fall_risk_factors"' in html
        assert "Polypharmacy" in html

    def test_intervention_plan_section(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="fall-intervention-section"' in html
        assert 'name="fall_intervention_plan"' in html


class TestFunctionalAbilityRender:
    def test_adl_and_iadl_fields(self) -> None:
        html = FunctionalAbilityModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Basic Activities of Daily Living" in html
        assert "Instrumental ADLs (IADLs)" in html


class TestAdvanceCarePlanningRender:
    def test_billing_note(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "CPT 99497" in html

    def test_conditional_directive_type(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'data-conditional-on="advance_directive_exists"' in html
        assert 'data-conditional-value="Yes - on file"' in html

    def test_discussion_fields(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="acp_discussed"' in html
        assert 'name="healthcare_proxy_name"' in html
        assert 'name="patient_wishes_summary"' in html

    def test_field_types(self) -> None:
        """Renders radio, text, textarea, and checkbox field types."""
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'type="radio"' in html
        assert 'type="text"' in html
        assert "<textarea" in html
        assert 'type="checkbox"' in html

    def test_healthcare_proxy_designated_radio(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="healthcare_proxy_designated"' in html

    def test_time_documentation_fields(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="acp_start_time"' in html
        assert 'name="acp_end_time"' in html
        assert 'name="acp_total_minutes"' in html

    def test_code_status_radio(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="code_status"' in html
        assert "Full Code" in html
        assert "DNR/DNI" in html
        assert "Comfort Care Only" in html

    def test_topics_discussed_checkboxes(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="acp_topics_discussed"' in html
        assert "Values and goals explored" in html

    def test_documents_completed_checkboxes(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="documents_completed_today"' in html

    def test_copy_and_scan_radios(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="copy_given_to_patient"' in html
        assert 'name="documents_scanned_to_chart"' in html

    def test_proxy_contact_field(self) -> None:
        html = AdvanceCarePlanningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="healthcare_proxy_contact"' in html
        assert "Phone number" in html


class TestCurrentProvidersRender:
    def test_provider_categories(self) -> None:
        html = CurrentProvidersModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="pcp"' in html
        # v0.14.0: pharmacy is now a structured section with search + pending list,
        # not a free-text input
        assert 'id="pharmacy-search"' in html
        assert 'id="pharmacy-pending"' in html

    def test_structured_specialist_fields(self) -> None:
        html = CurrentProvidersModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="specialist_0_name"' in html
        assert 'name="specialist_0_specialty"' in html
        assert 'name="specialist_0_phone"' in html
        assert 'id="add-specialist-btn"' in html
        assert 'id="specialist-rows"' in html

    def test_specialty_is_dropdown(self) -> None:
        html = CurrentProvidersModule("n", "p", AWVType.INITIAL).render_content_html()
        assert '<select name="specialist_0_specialty"' in html
        assert "Cardiology" in html
        assert "-- Select specialty --" in html


class TestHearingVisionRender:
    def test_hearing_and_vision_sections(self) -> None:
        html = HearingVisionModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Hearing" in html
        assert "Vision" in html


class TestAlcoholScreeningRender:
    def test_auditc_questions(self) -> None:
        html = AlcoholScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="auditc_q1"' in html
        assert 'name="auditc_q2"' in html
        assert 'name="auditc_q3"' in html

    def test_score_element(self) -> None:
        html = AlcoholScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="auditc-score"' in html


# ---------------------------------------------------------------------------
# ORM-dependent modules (require mocking)
# ---------------------------------------------------------------------------


class TestVitalsRender:
    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_save_button(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'onclick="saveVitals()"' in html
        assert 'id="vitals-save-btn"' in html

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_vitals_input_fields(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="height"' in html
        assert 'name="weight"' in html
        assert 'name="bmi"' in html
        assert 'name="systolic_bp"' in html

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_bmi_readonly(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        # BMI input should be readonly — find its input tag
        bmi_idx = html.index('name="bmi"')
        # Look backwards for the nearest <input to find the full tag
        tag_start = html.rfind("<input", 0, bmi_idx)
        tag_end = html.index(">", bmi_idx)
        bmi_tag = html[tag_start:tag_end + 1]
        assert "readonly" in bmi_tag

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_bmi_alert_hidden_div(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="bmi-calc-alert"' in html

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_recent_vitals_section(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Recent Vitals (from Chart)" in html
        assert "Enter New Vitals" in html

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_high_bmi_alert_shown(self, mock_obs: MagicMock) -> None:
        """BMI >= 30 shows an inline warning alert."""
        mock_obs.filter.return_value.order_by.return_value.values.return_value = [
            {"codings__code": "39156-5", "value": "35.2"},
        ]
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "awv-alert--warning" in html
        assert "obesity counseling" in html

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_bp_arm_radio(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="bp_arm"' in html
        assert "Left" in html
        assert "Right" in html

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_bp_position_radio(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="bp_position"' in html
        assert "Seated" in html

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_bmi_category_display(self, mock_obs: MagicMock) -> None:
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        html = VitalsModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="bmi-category"' in html
        assert 'id="bmi-category-value"' in html


class TestMedicalHistoryRender:
    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_has_save_button(self, mock_cond: MagicMock, mock_med: MagicMock, mock_allergy: MagicMock) -> None:
        """MedicalHistory now has a save button for attestation."""
        _empty_qs: Callable[[], MagicMock] = lambda: MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []})
        mock_cond.filter.side_effect = [_empty_qs(), _empty_qs()]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []
        html = MedicalHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'onclick="saveMedicalHistory()"' in html
        assert 'id="medicalhistory-save-btn"' in html

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_empty_state_placeholders(self, mock_cond: MagicMock, mock_med: MagicMock, mock_allergy: MagicMock) -> None:
        """Shows placeholder text when no data exists."""
        _empty_qs: Callable[[], MagicMock] = lambda: MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []})
        mock_cond.filter.side_effect = [_empty_qs(), _empty_qs()]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []
        html = MedicalHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "No active conditions on record" in html
        assert "No surgical history on record" in html
        assert "No current medications on record" in html
        assert "No allergies on record" in html

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_with_data(self, mock_cond: MagicMock, mock_med: MagicMock, mock_allergy: MagicMock) -> None:
        """Renders conditions, medications, and allergies when present."""
        medical_qs = MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": [
            {"id": "c1", "codings__display": "Hypertension", "onset_date": "2020-01-01"},
        ]})
        surgical_qs = MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": [
            {"id": "c2", "codings__display": "Knee Replacement", "onset_date": "2019-06-15", "resolution_date": "2019-06-15", "clinical_status": "resolved"},
        ]})
        mock_cond.filter.side_effect = [medical_qs, surgical_qs]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = [
            {"id": "m1", "medication__codings__display": "Lisinopril 10mg", "sig_original_input": "1 daily"},
        ]
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = [
            {"id": "a1", "codings__display": "Penicillin", "narrative": "Rash"},
        ]
        html = MedicalHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Hypertension" in html
        assert "Knee Replacement" in html
        assert "Active Conditions (1)" in html
        assert "Surgical History (1)" in html
        assert "Lisinopril 10mg" in html
        assert "Penicillin" in html

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_section_subtitles(self, mock_cond: MagicMock, mock_med: MagicMock, mock_allergy: MagicMock) -> None:
        _empty_qs: Callable[[], MagicMock] = lambda: MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []})
        mock_cond.filter.side_effect = [_empty_qs(), _empty_qs()]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []
        html = MedicalHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Active Conditions" in html
        assert "Surgical History" in html
        assert "Current Medications" in html
        assert "Allergies" in html

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_new_diagnosis_search(self, mock_cond: MagicMock, mock_med: MagicMock, mock_allergy: MagicMock) -> None:
        _empty_qs: Callable[[], MagicMock] = lambda: MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []})
        mock_cond.filter.side_effect = [_empty_qs(), _empty_qs()]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []
        html = MedicalHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="new-dx-search"' in html
        assert 'id="new-dx-results"' in html
        assert 'id="added-diagnoses"' in html
        assert "Add New Diagnosis" in html

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_attestation_checkboxes(self, mock_cond: MagicMock, mock_med: MagicMock, mock_allergy: MagicMock) -> None:
        mock_cond.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []
        html = MedicalHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="medical_history_attestation"' in html
        assert "Medical history reviewed and updated for this visit" in html


class TestPreventiveServicesRender:
    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_save_button(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'onclick="savePreventiveServices()"' in html
        assert 'id="preventiveservices-save-btn"' in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_patient_not_found_error(self, mock_patient_objects: MagicMock) -> None:
        mock_patient_objects.filter.return_value.first.return_value = None
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "awv-alert--error" in html
        assert "Patient not found" in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_services_rendered(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Influenza Vaccine" in html
        assert "Mammography" in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_rsv_vaccine_shown_age_60_plus(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1960, 1, 1)
        mock_patient.sex_at_birth = "M"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "RSV Vaccine" in html
        assert 'name="svc_rsv_ordered"' in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_rsv_vaccine_hidden_under_60(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1980, 1, 1)
        mock_patient.sex_at_birth = "M"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "RSV Vaccine" not in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_service_checkboxes_and_date(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'type="date"' in html
        assert 'value="ordered"' in html
        assert 'value="discussed"' in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_prevention_plan_created_radio(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="prevention_plan_created"' in html
        assert "Documentation" in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_written_copy_given_radio(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="written_copy_given"' in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_next_due_date_inputs(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert '_next_date"' in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_chronic_disease_monitoring(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Chronic Disease Monitoring" in html
        assert 'name="chronic_hba1c' in html
        assert "Diabetic Eye Exam" in html

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_behavioral_health_monitoring(self, mock_patient_objects: MagicMock) -> None:
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient
        html = PreventiveServicesModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Behavioral Health Monitoring" in html
        assert "Annual Depression Screening" in html
        assert "Annual Cognitive Assessment" in html


class TestAssessmentPlanRender:
    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_save_button(self, mock_cond: MagicMock) -> None:
        mock_cond.filter.return_value.values.return_value.order_by.return_value = []
        html = AssessmentPlanModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'onclick="saveAssessmentPlan()"' in html
        assert 'id="assessmentplan-save-btn"' in html

    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_empty_conditions_placeholder(self, mock_cond: MagicMock) -> None:
        mock_cond.filter.return_value.values.return_value.order_by.return_value = []
        html = AssessmentPlanModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "No active conditions" in html

    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_with_conditions(self, mock_cond: MagicMock) -> None:
        mock_cond.filter.return_value.values.return_value.order_by.return_value = [
            {"id": "c1", "codings__display": "Diabetes", "codings__code": "E11"},
        ]
        html = AssessmentPlanModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Diabetes" in html

    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_plan_fields(self, mock_cond: MagicMock) -> None:
        mock_cond.filter.return_value.values.return_value.order_by.return_value = []
        html = AssessmentPlanModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="prevention_plan"' in html

    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_prevention_plan_textarea_is_required(self, mock_cond: MagicMock) -> None:
        """Regression for Claude review #27: the Personalized Prevention Plan
        textarea was declared with `required: True` in the field dict but the
        render loop never read `field.get('required')` and never passed it to
        `_textarea`. The rendered HTML therefore lacked the `data-required`
        attribute that `validateSection` (templates/guided_awv.html) checks,
        so the validator never blocked submission with an empty plan. Every
        other dict-driven module (hra, vitals, ACP, followup, cognitive,
        SDOH) reads required from the field dict - assessment_plan was the
        lone holdout.
        """
        mock_cond.filter.return_value.values.return_value.order_by.return_value = []
        html = AssessmentPlanModule("n", "p", AWVType.INITIAL).render_content_html()
        prevention_block = html[html.index('name="prevention_plan"'):]
        prevention_block = prevention_block[:prevention_block.index("</textarea>")]
        assert 'data-required="true"' in prevention_block

    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_optional_fields_have_no_required_attr(self, mock_cond: MagicMock) -> None:
        """Non-required plan fields (referrals, patient_education) must not
        carry data-required - else the validator blocks valid empty submissions.
        """
        mock_cond.filter.return_value.values.return_value.order_by.return_value = []
        html = AssessmentPlanModule("n", "p", AWVType.INITIAL).render_content_html()
        # referrals is an optional textarea
        referrals_block = html[html.index('name="referrals"'):]
        referrals_block = referrals_block[:referrals_block.index("</textarea>")]
        assert 'data-required="true"' not in referrals_block


# ---------------------------------------------------------------------------
# New modules: Medication Reconciliation + SDOH Screening
# ---------------------------------------------------------------------------


class TestMedicationReconciliationRender:
    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_save_button(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'onclick="saveMedicationReconciliation()"' in html
        assert 'id="medicationreconciliation-save-btn"' in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_reconciliation_method_select(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="reconciliation_method"' in html
        assert "Patient-reported" in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_otc_and_supplements_textareas(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="otc_medications"' in html
        assert 'name="supplements"' in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_adherence_assessment(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="adherence_assessment"' in html
        assert "Taking all medications as prescribed" in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_high_risk_meds_conditional(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="high_risk_meds_identified"' in html
        assert 'data-conditional-on="high_risk_meds_identified"' in html
        assert 'name="high_risk_meds_notes"' in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_attestation_checkboxes(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="reconciliation_attestation"' in html
        assert "All medications reviewed with patient" in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_displays_medications_from_orm(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = [
            {"id": "m1", "medication__codings__display": "Metformin 500mg", "sig_original_input": "1 daily"},
        ]
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Metformin 500mg" in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_empty_medications_placeholder(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "No current medications on record" in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_medications_reconciled_radio(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="medications_reconciled"' in html

    @patch("guided_awv.modules.medication_reconciliation.MedicationStatement.objects")
    def test_reconciliation_notes_textarea(self, mock_med: MagicMock) -> None:
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        html = MedicationReconciliationModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="reconciliation_notes"' in html

class TestSDOHScreeningRender:
    def test_sdoh_tool_used_select(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_tool_used"' in html
        assert "PRAPARE" in html
        assert "AHC-HRSN" in html

    def test_housing_fields(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_housing_worried"' in html
        assert 'name="sdoh_housing_conditions"' in html

    def test_food_security_fields(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_food_worry"' in html
        assert 'name="sdoh_food_didnt_last"' in html

    def test_transportation_field(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_transportation"' in html

    def test_social_support_fields(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_social_contact"' in html
        assert 'name="sdoh_loneliness"' in html

    def test_safety_fields(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_feel_safe"' in html
        assert 'name="sdoh_afraid_partner"' in html

    def test_utility_needs_fields(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_utility_concerns"' in html
        assert 'data-conditional-on="sdoh_utility_concerns"' in html
        assert 'name="sdoh_utility_details"' in html
        assert "Utility Needs" in html

    def test_substance_use_conditional(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_recreational_drugs"' in html
        assert 'data-conditional-on="sdoh_recreational_drugs"' in html
        assert 'name="sdoh_substance_details"' in html

    def test_incontinence_conditional(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_urinary_leakage"' in html
        assert 'data-conditional-on="sdoh_urinary_leakage"' in html

    def test_pain_assessment(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="sdoh_pain_present"' in html
        assert 'name="sdoh_pain_scale"' in html
        assert 'name="sdoh_pain_location"' in html

    def test_section_subtitles(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert "Housing Stability" in html
        assert "Food Security" in html
        assert "Transportation" in html
        assert "Safety" in html
        assert "Pain Assessment" in html

    def test_per_domain_alert_divs(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        alert_ids = [
            "sdoh-housing-alert",
            "sdoh-food-alert",
            "sdoh-transportation-alert",
            "sdoh-social-alert",
            "sdoh-utility-alert",
            "sdoh-safety-alert",
            "sdoh-substance-alert",
            "sdoh-incontinence-alert",
            "sdoh-pain-alert",
        ]
        for alert_id in alert_ids:
            assert f'id="{alert_id}"' in html
            # Each alert should be hidden by default
            idx = html.index(f'id="{alert_id}"')
            tag_start = html.rfind("<div", 0, idx)
            tag_end = html.index(">", idx)
            tag = html[tag_start:tag_end + 1]
            assert 'style="display:none;"' in tag
            assert "awv-alert--warning" in tag

    def test_referral_section(self) -> None:
        html = SDOHScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'id="sdoh-referral-section"' in html
        assert 'name="sdoh_referral_plan"' in html
        assert 'id="sdoh-positive-summary"' in html
        assert "Positive Screens &amp; Referral Plan" in html or "Positive Screens & Referral Plan" in html


class TestFamilyHistoryRender:
    def test_member_status_radios(self) -> None:
        html = FamilyHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="fhx_mother_status"' in html
        assert 'name="fhx_father_status"' in html
        assert "Living" in html
        assert "Deceased" in html

    def test_member_age_inputs(self) -> None:
        html = FamilyHistoryModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="fhx_mother_age"' in html
        assert 'name="fhx_father_age"' in html


class TestFollowUpRender:
    def test_next_awv_date_input(self) -> None:
        html = FollowUpSchedulingModule("n", "p", AWVType.INITIAL).render_content_html()
        assert 'name="next_awv_date"' in html
        assert 'type="date"' in html


# ---------------------------------------------------------------------------
# Required field validation: spot-check data-required attributes
# ---------------------------------------------------------------------------


class TestRequiredFieldsInModules:
    """Verify data-required attributes are present on CMS-required fields."""

    def test_hra_required_fields(self) -> None:
        html = HRAModule("n", "p", AWVType.INITIAL).render_content_html()
        # hra_completed radio group should have data-required
        assert 'data-required="true"' in html
        # general_health should also be required
        idx_general = html.find('name="general_health"')
        assert idx_general > 0
        # Find the enclosing radio group div
        group_start = html.rfind("awv-radio-group", 0, idx_general)
        assert 'data-required="true"' in html[group_start:idx_general]

    def test_vitals_required_fields(self) -> None:
        mod = VitalsModule.__new__(VitalsModule)
        mod.note_id = "n"
        mod.patient_id = "p"
        mod.awv_type = AWVType.INITIAL
        # Mock get_context to avoid ORM
        vitals_context = {
            "bmi_value": None,
            "vitals_fields": [
                {"id": "height", "label": "Height", "unit": "in", "step": "0.1", "required": True, "recent_value": None},
                {"id": "weight", "label": "Weight", "unit": "lbs", "step": "0.1", "required": True, "recent_value": None},
                {"id": "bmi", "label": "BMI", "unit": "kg/m²", "step": "0.1", "readonly": True, "recent_value": None},
                {"id": "systolic_bp", "label": "Systolic BP", "unit": "mmHg", "step": "1", "required": True, "recent_value": None},
                {"id": "diastolic_bp", "label": "Diastolic BP", "unit": "mmHg", "step": "1", "required": True, "recent_value": None},
                {"id": "heart_rate", "label": "Heart Rate", "unit": "bpm", "step": "1", "recent_value": None},
            ],
            "note_id": "n",
        }
        with patch.object(VitalsModule, "get_context", return_value=vitals_context):
            rendered = mod.render_content_html()
        for field_name in ("height", "weight", "systolic_bp", "diastolic_bp"):
            idx = rendered.find(f'name="{field_name}"')
            assert idx > 0, f"{field_name} not found"
            # data-required should be on the same input element
            snippet = rendered[max(0, idx - 120):idx + 80]
            assert 'data-required="true"' in snippet, f"{field_name} missing data-required"
        # bp_arm and bp_position should also be required
        assert rendered.count('data-required="true"') >= 6

    def test_depression_required_fields(self) -> None:
        html = DepressionScreeningModule("n", "p", AWVType.INITIAL).render_content_html()
        for q in ("phq2_q1", "phq2_q2"):
            idx = html.find(f'name="{q}"')
            assert idx > 0
            group_start = html.rfind("awv-radio-group", 0, idx)
            assert 'data-required="true"' in html[group_start:idx]

    def test_fall_risk_required_fields(self) -> None:
        html = FallRiskModule("n", "p", AWVType.INITIAL).render_content_html()
        for q in ("falls_past_year", "fear_of_falling", "gait_concern"):
            idx = html.find(f'name="{q}"')
            assert idx > 0
            group_start = html.rfind("awv-radio-group", 0, idx)
            assert 'data-required="true"' in html[group_start:idx], f"{q} missing required"

    def test_preventive_services_required_fields(self) -> None:
        # Uses ORM (Patient), so mock at module level
        mod = PreventiveServicesModule.__new__(PreventiveServicesModule)
        mod.note_id = "n"
        mod.patient_id = "p"
        mod.awv_type = AWVType.INITIAL
        preventive_context = {
            "patient_age": 70, "patient_sex": "M", "services": [],
            "is_subsequent": False, "note_id": "n",
        }
        with patch.object(PreventiveServicesModule, "get_context", return_value=preventive_context):
            html = mod.render_content_html()
        for field in ("prevention_plan_created", "written_copy_given"):
            idx = html.find(f'name="{field}"')
            assert idx > 0
            group_start = html.rfind("awv-radio-group", 0, idx)
            assert 'data-required="true"' in html[group_start:idx]

    def test_current_providers_pcp_required(self) -> None:
        html = CurrentProvidersModule("n", "p", AWVType.INITIAL).render_content_html()
        idx = html.find('name="pcp"')
        assert idx > 0
        snippet = html[max(0, idx - 120):idx + 120]
        assert 'data-required="true"' in snippet

    def test_followup_next_awv_date_required(self) -> None:
        html = FollowUpSchedulingModule("n", "p", AWVType.INITIAL).render_content_html()
        idx = html.find('name="next_awv_date"')
        assert idx > 0
        snippet = html[max(0, idx - 120):idx + 120]
        assert 'data-required="true"' in snippet


# ---------------------------------------------------------------------------
# Cross-cutting: all modules with save buttons
# ---------------------------------------------------------------------------


SAVE_BUTTON_MODULES = [
    (HRAModule, "hra", "saveHRA"),
    (DepressionScreeningModule, "depressionscreening", "saveDepressionScreening"),
    (CognitiveAssessmentModule, "cognitiveassessment", "saveCognitiveAssessment"),
    (FallRiskModule, "fallrisk", "saveFallRisk"),
    (FunctionalAbilityModule, "functionalability", "saveFunctionalAbility"),
    (AdvanceCarePlanningModule, "advancecareplanning", "saveAdvanceCarePlanning"),
    (FamilyHistoryModule, "familyhistory", "saveFamilyHistory"),
    (CurrentProvidersModule, "currentproviders", "saveCurrentProviders"),
    (HearingVisionModule, "hearingvision", "saveHearingVision"),
    (AlcoholScreeningModule, "alcoholscreening", "saveAlcoholScreening"),
    (FollowUpSchedulingModule, "followupscheduling", "saveFollowUp"),
    (SDOHScreeningModule, "sdohscreening", "saveSDOHScreening"),
]


@pytest.mark.parametrize("module_class,section_id,save_fn", SAVE_BUTTON_MODULES)
class TestSaveButtonConsistency:
    """Verify save button IDs and JS function names match for all non-ORM modules."""

    def test_button_id(self, module_class: type, section_id: str, save_fn: str) -> None:
        html = module_class("n", "p", AWVType.INITIAL).render_content_html()
        assert f'id="{section_id}-save-btn"' in html

    def test_status_id(self, module_class: type, section_id: str, save_fn: str) -> None:
        html = module_class("n", "p", AWVType.INITIAL).render_content_html()
        assert f'id="{section_id}-status"' in html

    def test_onclick(self, module_class: type, section_id: str, save_fn: str) -> None:
        html = module_class("n", "p", AWVType.INITIAL).render_content_html()
        assert f'onclick="{save_fn}()"' in html
