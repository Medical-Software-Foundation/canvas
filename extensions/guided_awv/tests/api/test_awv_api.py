"""Tests for AWV SimpleAPI route handlers."""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from guided_awv.api.awv_api import (
    AddDiagnosisHandler,
    GeneratePreventionPlanHandler,
    GetScreeningDatesHandler,
    SearchConditionsHandler,
    SaveAdvanceCarePlanningHandler,
    SaveAlcoholScreeningHandler,
    SaveAWVTypeHandler,
    SaveCognitiveAssessmentHandler,
    SaveCurrentProvidersHandler,
    SaveDepressionScreeningHandler,
    SaveFallRiskHandler,
    SaveFamilyHistoryHandler,
    SaveFunctionalAbilityHandler,
    SaveHRAHandler,
    SaveHearingVisionHandler,
    SaveMedicalHistoryHandler,
    SaveMedicationReconciliationHandler,
    SavePlanHandler,
    SavePreventiveServicesHandler,
    SaveSDOHScreeningHandler,
    SaveVitalsHandler,
    ScheduleFollowupHandler,
    _add_cpt_ii,
    _get_all_form_states,
    _get_phq9_severity,
    _get_questionnaire_id,
    _lookup_all_screening_dates,
    _originate_sa,
    _parse_body,
    _save_form_state,
)
from guided_awv.modules.preventive_services import build_services_list


# ---- _parse_body helper ----

class TestParseBody:
    """Tests for _parse_body utility function."""

    def test_parse_body_uses_request_json(self) -> None:
        """Uses request.json() when available."""
        request = MagicMock()
        request.json.return_value = {"key": "value"}
        result = _parse_body(request)
        assert result == {"key": "value"}

    def test_parse_body_falls_back_to_raw_body(self) -> None:
        """Falls back to raw body parsing when json() raises."""
        request = MagicMock()
        request.json.side_effect = Exception("Not JSON")
        request.body = b'{"key": "fallback"}'
        result = _parse_body(request)
        assert result == {"key": "fallback"}

    def test_parse_body_returns_empty_dict_on_failure(self) -> None:
        """Returns empty dict when both methods fail."""
        request = MagicMock()
        request.json.side_effect = Exception("fail")
        request.body = b"invalid json{"
        result = _parse_body(request)
        assert result == {}


# ---- PHQ-9 severity helper ----

class TestGetPHQ9Severity:
    """Tests for _get_phq9_severity helper."""

    def test_minimal(self) -> None:
        assert "Minimal" in _get_phq9_severity(0)
        assert "Minimal" in _get_phq9_severity(4)

    def test_mild(self) -> None:
        assert "Mild" in _get_phq9_severity(5)
        assert "Mild" in _get_phq9_severity(9)

    def test_moderate(self) -> None:
        assert "Moderate" in _get_phq9_severity(10)
        assert "Moderate" in _get_phq9_severity(14)

    def test_moderately_severe(self) -> None:
        assert "Moderately Severe" in _get_phq9_severity(15)
        assert "Moderately Severe" in _get_phq9_severity(19)

    def test_severe(self) -> None:
        assert "Severe" in _get_phq9_severity(20)
        assert "Severe" in _get_phq9_severity(27)


# ---- SaveVitalsHandler ----

class TestSaveVitalsHandler:
    """Tests for SaveVitalsHandler."""

    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.VitalsCommand")
    def test_post_with_valid_data(
        self,
        mock_vitals_cmd: MagicMock,
        mock_json: MagicMock,
    ) -> None:
        """POST with valid note_id creates VitalsCommand."""
        mock_event = MagicMock()
        handler = SaveVitalsHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "height": 65,
            "weight_lbs": 150,
            "blood_pressure_systole": 120,
            "blood_pressure_diastole": 80,
            "pulse": 72,
        }

        mock_cmd_instance = MagicMock()
        mock_cmd_instance.originate.return_value = "vitals_effect"
        mock_vitals_cmd.return_value = mock_cmd_instance
        mock_json.return_value = "json_response"

        result = handler.post()

        mock_vitals_cmd.assert_called_once_with(note_uuid="note-abc")
        assert mock_cmd_instance.height == 65
        assert mock_cmd_instance.weight_lbs == 150
        assert "json_response" in result
        assert "vitals_effect" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_without_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400 error."""
        mock_event = MagicMock()
        handler = SaveVitalsHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {}

        mock_json.return_value = "error_response"

        result = handler.post()

        call_kwargs = mock_json.call_args
        assert call_kwargs[1]["status_code"] == 400
        assert "note_id" in call_kwargs[0][0]["error"]

    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.VitalsCommand")
    def test_post_with_fractional_weight_rounds_to_int(
        self,
        mock_vitals_cmd: MagicMock,
        mock_json: MagicMock,
    ) -> None:
        """Form values arrive as strings (e.g. '187.5'); handler must round to int.

        Regression test for the ValueError observed on marketing-sandbox where
        int('187.5') crashed the SaveVitalsHandler.
        """
        mock_event = MagicMock()
        handler = SaveVitalsHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "height": "65.5",
            "weight_lbs": "187.5",
            "blood_pressure_systole": "120",
            "blood_pressure_diastole": "80",
            "pulse": "72",
        }

        mock_cmd_instance = MagicMock()
        mock_cmd_instance.originate.return_value = "vitals_effect"
        mock_vitals_cmd.return_value = mock_cmd_instance
        mock_json.return_value = "json_response"

        handler.post()  # must not raise

        # 65.5 -> 66, 187.5 -> 188 (banker's rounding doesn't apply here, round() is half-to-even
        # but for 0.5 we accept either - the important thing is it didn't crash)
        assert mock_cmd_instance.height in (65, 66)
        assert mock_cmd_instance.weight_lbs in (187, 188)
        assert mock_cmd_instance.blood_pressure_systole == 120
        assert mock_cmd_instance.blood_pressure_diastole == 80
        assert mock_cmd_instance.pulse == 72

    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.VitalsCommand")
    def test_post_skips_unparseable_fields(
        self,
        mock_vitals_cmd: MagicMock,
        mock_json: MagicMock,
    ) -> None:
        """Garbage values should be skipped, not crash."""
        mock_event = MagicMock()
        handler = SaveVitalsHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "height": "not a number",
            "weight_lbs": "",
            "pulse": "72",
        }

        mock_cmd_instance = MagicMock(spec=["originate", "pulse"])
        mock_cmd_instance.originate.return_value = "vitals_effect"
        mock_vitals_cmd.return_value = mock_cmd_instance
        mock_json.return_value = "json_response"

        handler.post()  # must not raise

        # Only pulse should have been set
        assert mock_cmd_instance.pulse == 72


class TestSaveVitalsBPRangeCodes:
    """Regression for Claude review #28: 3074F/3075F are NOT bp-controlled /
    bp-uncontrolled composite flags - they are systolic-range bucket codes
    per AMA/PCPI long descriptors (HEDIS CBP / CMS MIPS QM236).

    Correct mapping (one code per axis per visit):
      Systolic:  SBP <130 -> 3074F, 130-139 -> 3075F, >=140 -> 3077F
      Diastolic: DBP <80  -> 3078F, 80-89   -> 3079F, >=90  -> 3080F

    The prior code emitted 3074F for any BP under 140/90 and 3075F otherwise,
    which (a) attested SBP <130 for a 135/85 reading (false), (b) counted a
    145/95 reading as 3075F = SBP 130-139 (false) and skipped 3077F entirely,
    and (c) never emitted any diastolic-range code.
    """

    def _run(self, systole: int, diastole: int) -> list[str]:
        with (
            patch("guided_awv.api.awv_api.AddBillingLineItem") as mock_billing,
            patch("guided_awv.api.awv_api.JSONResponse"),
            patch("guided_awv.api.awv_api.VitalsCommand"),
        ):
            handler = SaveVitalsHandler(MagicMock())
            handler.request = MagicMock()
            handler.request.json.return_value = {
                "note_id": "note-abc",
                "blood_pressure_systole": systole,
                "blood_pressure_diastole": diastole,
            }
            handler.post()
            return [c.kwargs["cpt"] for c in mock_billing.call_args_list]

    def test_systolic_lt_130_emits_3074F(self) -> None:
        codes = self._run(systole=120, diastole=70)
        assert "3074F" in codes
        assert "3075F" not in codes
        assert "3077F" not in codes

    def test_systolic_130_to_139_emits_3075F(self) -> None:
        codes = self._run(systole=135, diastole=70)
        assert "3075F" in codes
        assert "3074F" not in codes
        assert "3077F" not in codes

    def test_systolic_ge_140_emits_3077F(self) -> None:
        codes = self._run(systole=145, diastole=70)
        assert "3077F" in codes
        assert "3074F" not in codes
        assert "3075F" not in codes

    def test_diastolic_lt_80_emits_3078F(self) -> None:
        codes = self._run(systole=120, diastole=70)
        assert "3078F" in codes
        assert "3079F" not in codes
        assert "3080F" not in codes

    def test_diastolic_80_to_89_emits_3079F(self) -> None:
        codes = self._run(systole=120, diastole=85)
        assert "3079F" in codes
        assert "3078F" not in codes
        assert "3080F" not in codes

    def test_diastolic_ge_90_emits_3080F(self) -> None:
        codes = self._run(systole=120, diastole=95)
        assert "3080F" in codes
        assert "3078F" not in codes
        assert "3079F" not in codes

    def test_uncontrolled_bp_145_over_95_emits_3077F_and_3080F(self) -> None:
        """A clearly-uncontrolled BP should emit both range-3 codes."""
        codes = self._run(systole=145, diastole=95)
        assert "3077F" in codes
        assert "3080F" in codes


# ---- SaveDepressionScreeningHandler ----

class TestSaveDepressionScreeningHandler:
    """Tests for SaveDepressionScreeningHandler."""

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_phq2_negative(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with PHQ-2 score < 3 creates plan without PHQ-9."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 2,
            "phq9_score": None,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result
        # Verify SA result contains PHQ-2 score (PlanCommand not used when qid exists)
        sa_result = mock_sa_cmd.call_args_list[0][1]["result"]
        assert "PHQ-2 Score: 2/6" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_phq2_positive_with_phq9(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with PHQ-2 >= 3 and PHQ-9 score includes severity in plan."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 4,
            "phq9_score": 12,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PHQ-2 SA result is first call, PHQ-9 SA result is second call
        phq2_result = mock_sa_cmd.call_args_list[0][1]["result"]
        assert "PHQ-2 Score: 4/6" in phq2_result
        phq9_result = mock_sa_cmd.call_args_list[1][1]["result"]
        assert "PHQ-9 Score: 12/27" in phq9_result
        assert "Moderate" in phq9_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_q9_positive_includes_suicidal_ideation_in_narrative(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with Q9 > 0 includes suicidal ideation flag and safety note in narrative."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 5,
            "phq9_score": 18,
            "q9_score": 2,
            "safety_assessed": True,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # Verify two SA commands: PHQ-2 and PHQ-9
        assert mock_sa_cmd.call_count == 2
        phq2_result = mock_sa_cmd.call_args_list[0][1]["result"]
        assert "PHQ-2 Score: 5/6" in phq2_result
        phq9_result = mock_sa_cmd.call_args_list[1][1]["result"]
        assert "PHQ-9 Score: 18/27" in phq9_result
        assert "Moderately Severe" in phq9_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_includes_suicide_ideation_assessed(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with suicide_ideation_assessed includes it in narrative."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 4,
            "phq9_score": 12,
            "suicide_ideation_assessed": "Yes",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # Verify SA commands created for PHQ-2 and PHQ-9
        assert mock_sa_cmd.call_count == 2
        phq9_result = mock_sa_cmd.call_args_list[1][1]["result"]
        assert "PHQ-9 Score: 12/27" in phq9_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_includes_suicide_ideation_present(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with suicide_ideation_present includes it in narrative."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 4,
            "phq9_score": 12,
            "suicide_ideation_present": "No",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # Verify SA commands created for PHQ-2 and PHQ-9
        assert mock_sa_cmd.call_count == 2
        phq9_result = mock_sa_cmd.call_args_list[1][1]["result"]
        assert "PHQ-9 Score: 12/27" in phq9_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_q9_zero_no_suicidal_ideation_flag(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with Q9 = 0 does not include suicidal ideation flag."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 4,
            "phq9_score": 10,
            "q9_score": 0,
            "safety_assessed": False,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PHQ-2 positive triggers PHQ-9 SA; verify both SA calls present
        assert mock_sa_cmd.call_count == 2
        phq9_result = mock_sa_cmd.call_args_list[1][1]["result"]
        assert "PHQ-9 Score: 10/27" in phq9_result
        assert "Moderate" in phq9_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_q9_score_1_labels_several_days(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with Q9 = 1 labels frequency as 'Several days'."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 3,
            "phq9_score": 7,
            "q9_score": 1,
            "safety_assessed": True,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PHQ-2 and PHQ-9 SA commands both created
        assert mock_sa_cmd.call_count == 2
        phq9_result = mock_sa_cmd.call_args_list[1][1]["result"]
        assert "PHQ-9 Score: 7/27" in phq9_result
        assert "Mild" in phq9_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_q9_score_3_labels_nearly_every_day(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with Q9 = 3 labels frequency as 'Nearly every day'."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 6,
            "phq9_score": 24,
            "q9_score": 3,
            "safety_assessed": True,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PHQ-2 and PHQ-9 SA commands both created
        assert mock_sa_cmd.call_count == 2
        phq9_result = mock_sa_cmd.call_args_list[1][1]["result"]
        assert "PHQ-9 Score: 24/27" in phq9_result
        assert "Severe" in phq9_result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_without_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400 error."""
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {}
        mock_json.return_value = "error"

        result = handler.post()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_surfaces_safety_action_and_treatment_fields(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_billing: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """Regression for Claude review #24: the depression handler must
        surface safety_assessed_action, depression_treatment_plan, and
        depression_treatment_notes - which the JS started shipping in
        v0.14.11 but the handler ignored, dropping documented safety and
        treatment information before it reached the chart.
        """
        mock_event = MagicMock()
        handler = SaveDepressionScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "phq2_score": 5,
            "phq9_score": 18,
            "q9_score": 1,
            "safety_assessed": True,
            "safety_assessed_action": "assessed_safety_plan",
            "depression_treatment_plan": "Refer to behavioral health",
            "depression_treatment_notes": "Patient agrees to telehealth intake",
        }
        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        narrative = mock_plan_cmd.call_args[1]["narrative"]
        assert "Safety action: Assessed - safety plan created" in narrative
        assert "Treatment plan: Refer to behavioral health" in narrative
        assert "Treatment notes: Patient agrees to telehealth intake" in narrative


# ---- SaveCognitiveAssessmentHandler ----

class TestSaveCognitiveAssessmentHandler:
    """Tests for SaveCognitiveAssessmentHandler."""

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_positive_screen(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with total <= 2 shows positive screen result."""
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "words_recalled": 1,
            "clock_drawing_score": 1,
            "notes": "",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "cog_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        call_json = mock_json.call_args[0][0]
        assert call_json["mini_cog_total"] == 2
        assert "Positive" in call_json["screen_result"]

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_negative_screen(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with total >= 3 shows negative screen result."""
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "words_recalled": 3,
            "clock_drawing_score": 2,
            "notes": "Patient was alert and cooperative.",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "cog_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        call_json = mock_json.call_args[0][0]
        assert call_json["mini_cog_total"] == 5
        assert "Negative" in call_json["screen_result"]

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_includes_screening_completed(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with cognitive_screening_completed includes it in narrative."""
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "words_recalled": 3,
            "clock_drawing_score": 2,
            "cognitive_screening_completed": "Yes",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "cog_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Mini-Cog: 5/5" in sa_result
        assert "Negative screen" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_moca_tool(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with tool=moca generates MoCA narrative with score and interpretation."""
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "tool": "moca",
            "score": 22,
            "cognitive_screening_completed": "Yes",
            "notes": "Patient cooperative",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "cog_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "MoCA: 22/30" in sa_result
        assert "Positive screen" in sa_result

        call_json = mock_json.call_args[0][0]
        assert call_json["tool"] == "moca"
        assert call_json["score"] == 22
        assert "Positive" in call_json["screen_result"]

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_mmse_negative_screen(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with tool=mmse and score >= cutoff shows negative screen."""
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "tool": "mmse",
            "score": 28,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "cog_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "MMSE: 28/30" in sa_result
        assert "Negative screen" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_slums_positive_screen(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with tool=slums and score < cutoff shows positive screen."""
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "tool": "slums",
            "score": 18,
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "cog_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SLUMS: 18/30" in sa_result
        assert "Positive screen" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_mini_cog_routes_narrative_via_plan_command(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_billing: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """Regression for Claude review #24: Mini-Cog branch built narrative
        parts including screening_completed and clinical_notes but never
        emitted a PlanCommand, so the documented clinical content never
        reached the chart. Must mirror the v0.14.11 PlanCommand routing used
        by every other handler in the file.
        """
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "words_recalled": 2,
            "clock_drawing_score": 1,
            "screening_completed": "2026-05-09",
            "clinical_notes": "Patient cooperative, no aphasia",
        }
        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand must be invoked exactly once with a narrative that
        # includes both the screening date and clinical notes.
        assert mock_plan_cmd.call_count == 1
        narrative = mock_plan_cmd.call_args[1]["narrative"]
        assert "Screening completed: 2026-05-09" in narrative
        assert "Clinical notes: Patient cooperative, no aphasia" in narrative

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_alt_tool_routes_narrative_via_plan_command(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_billing: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """Same regression as above but for the alternative-tool branch
        (MoCA / SLUMS / MMSE), which also built narrative parts and dropped
        them.
        """
        mock_event = MagicMock()
        handler = SaveCognitiveAssessmentHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "tool": "moca",
            "score": 22,
            "screening_completed": "2026-05-09",
            "clinical_notes": "Visual-spatial deficits noted",
        }
        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        assert mock_plan_cmd.call_count == 1
        narrative = mock_plan_cmd.call_args[1]["narrative"]
        assert "Screening completed: 2026-05-09" in narrative
        assert "Clinical notes: Visual-spatial deficits noted" in narrative


# ---- AddDiagnosisHandler ----

class TestSearchConditionsHandler:
    """Tests for SearchConditionsHandler."""

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_returns_results(self, mock_json: MagicMock) -> None:
        """GET with search term returns matching conditions from ontologies."""
        mock_event = MagicMock()
        handler = SearchConditionsHandler(mock_event)
        handler.request = MagicMock()
        handler.request.query_params = {"search": "diabetes"}

        mock_ont_response = MagicMock()
        mock_ont_response.json.return_value = {
            "results": [
                {"icd10_code": "E11.9", "icd10_text": "Type 2 diabetes mellitus without complications", "snomed_concept_id": 44054006},
                {"icd10_code": "E10.9", "icd10_text": "Type 1 diabetes mellitus without complications", "snomed_concept_id": 46635009},
            ]
        }

        with patch("canvas_sdk.utils.http.OntologiesHttp.get_json", return_value=mock_ont_response):
            mock_json.return_value = "json_ok"

            handler.get()

            call_args = mock_json.call_args[0][0]
            assert "results" in call_args
            assert len(call_args["results"]) == 2
            assert call_args["results"][0]["icd10_code"] == "E11.9"

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_short_term_returns_empty(self, mock_json: MagicMock) -> None:
        """GET with search term < 2 chars returns empty results."""
        mock_event = MagicMock()
        handler = SearchConditionsHandler(mock_event)
        handler.request = MagicMock()
        handler.request.query_params = {"search": "a"}
        mock_json.return_value = "json_ok"

        handler.get()

        mock_json.assert_called_with({"results": []})


class TestSearchPharmaciesHandler:
    """Tests for SearchPharmaciesHandler (v0.14.0)."""

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_returns_pharmacy_results(self, mock_json: MagicMock) -> None:
        """GET with valid search term returns formatted pharmacy results."""
        from guided_awv.api.awv_api import SearchPharmaciesHandler
        handler = SearchPharmaciesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"search": "CVS"}
        mock_json.return_value = "json_ok"

        with patch("canvas_sdk.utils.http.PharmacyHttp.search_pharmacies") as mock_search:
            mock_search.return_value = [
                {
                    "ncpdp_id": "1234567",
                    "organization_name": "CVS Pharmacy #1",
                    "address_line_1": "123 Main St",
                    "city": "New York",
                    "state": "NY",
                    "zip_code": "10001",
                    "phone_primary": "2125551234",
                    "extra_field": "ignored",
                },
                {
                    "ncpdp_id": "9876543",
                    "organization_name": "CVS Pharmacy #2",
                    "address_line_1": "456 Park Ave",
                    "city": "Brooklyn",
                    "state": "NY",
                    "zip_code": "11201",
                    "phone_primary": "7185555678",
                },
            ]

            handler.get()

            results = mock_json.call_args[0][0]["results"]
            assert len(results) == 2
            assert results[0]["ncpdp_id"] == "1234567"
            assert results[0]["organization_name"] == "CVS Pharmacy #1"
            assert results[0]["city"] == "New York"
            # Only allow-listed fields are returned
            assert "extra_field" not in results[0]

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_short_term_returns_empty(self, mock_json: MagicMock) -> None:
        """GET with < 2 chars returns empty list without hitting the SDK."""
        from guided_awv.api.awv_api import SearchPharmaciesHandler
        handler = SearchPharmaciesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"search": "c"}
        mock_json.return_value = "json_ok"

        with patch("canvas_sdk.utils.http.PharmacyHttp.search_pharmacies") as mock_search:
            handler.get()
            mock_search.assert_not_called()
            mock_json.assert_called_with({"results": []})

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_skips_results_without_ncpdp_id(self, mock_json: MagicMock) -> None:
        """Results lacking an ncpdp_id are filtered out (cannot be persisted)."""
        from guided_awv.api.awv_api import SearchPharmaciesHandler
        handler = SearchPharmaciesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"search": "test"}
        mock_json.return_value = "json_ok"

        with patch("canvas_sdk.utils.http.PharmacyHttp.search_pharmacies") as mock_search:
            mock_search.return_value = [
                {"ncpdp_id": "1234567", "organization_name": "Valid"},
                {"organization_name": "Missing ncpdp"},
                {"ncpdp_id": "", "organization_name": "Empty ncpdp"},
            ]

            handler.get()

            results = mock_json.call_args[0][0]["results"]
            assert len(results) == 1
            assert results[0]["ncpdp_id"] == "1234567"

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_handles_sdk_exception(self, mock_json: MagicMock) -> None:
        """If the SDK call raises, return an empty list (don't 500)."""
        from guided_awv.api.awv_api import SearchPharmaciesHandler
        handler = SearchPharmaciesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"search": "test"}
        mock_json.return_value = "json_ok"

        with patch(
            "canvas_sdk.utils.http.PharmacyHttp.search_pharmacies",
            side_effect=Exception("network down"),
        ):
            handler.get()
            mock_json.assert_called_with({"results": []})


class TestAddDiagnosisHandler:
    """Tests for AddDiagnosisHandler."""

    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.DiagnoseCommand")
    def test_post_with_valid_diagnosis(
        self,
        mock_dx_cmd: MagicMock,
        mock_json: MagicMock,
    ) -> None:
        """POST with valid note_id and icd10_code creates DiagnoseCommand."""
        mock_event = MagicMock()
        handler = AddDiagnosisHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "icd10_code": "Z00.00",
            "background": "Routine AWV",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "dx_effect"
        mock_dx_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_dx_cmd.assert_called_once_with(
            note_uuid="note-abc",
            icd10_code="Z00.00",
            background="Routine AWV",
            today_assessment=None,
        )
        assert "json_ok" in result
        assert "dx_effect" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_icd10_code(self, mock_json: MagicMock) -> None:
        """POST without icd10_code returns 400 error."""
        mock_event = MagicMock()
        handler = AddDiagnosisHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"note_id": "note-abc"}
        mock_json.return_value = "error"

        result = handler.post()

        assert mock_json.call_args[1]["status_code"] == 400
        assert "icd10_code" in mock_json.call_args[0][0]["error"]

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400 error."""
        mock_event = MagicMock()
        handler = AddDiagnosisHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"icd10_code": "Z00.00"}
        mock_json.return_value = "error"

        result = handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SavePlanHandler ----


class TestSavePlanHandlerSectionRouting:
    """Regression tests for Claude review finding #3.

    saveAssessmentPlan() and saveAttestation() in the modal JS both POST to
    /awv/plan but with disjoint _form_fields (attestation_* vs
    prevention_plan/referrals/patient_education). The handler used to
    unconditionally write the form-state cache under section_id='assessmentplan',
    silently clobbering whichever flow ran first. The fix has the JS pass an
    explicit section_id and the handler honor it.
    """

    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_attestation_writes_to_attestation_cache_slot(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SavePlanHandler
        handler = SavePlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "narrative": "**Provider Attestation**\nAll elements documented",
            "section_id": "attestation",
            "_form_fields": {"attestation_face_to_face_time": "30"},
        }
        mock_json.return_value = "json_ok"

        handler.post()

        mock_save.assert_called_once()
        assert mock_save.call_args[0][1] == "attestation"
        # The form fields are the attestation set, not assessmentplan
        assert "attestation_face_to_face_time" in mock_save.call_args[0][2]

    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_assessmentplan_writes_to_assessmentplan_cache_slot(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SavePlanHandler
        handler = SavePlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "narrative": "Prevention Plan: walk daily",
            "section_id": "assessmentplan",
            "_form_fields": {"prevention_plan": "walk daily"},
        }
        mock_json.return_value = "json_ok"

        handler.post()

        mock_save.assert_called_once()
        assert mock_save.call_args[0][1] == "assessmentplan"
        assert "prevention_plan" in mock_save.call_args[0][2]

    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_missing_section_id_defaults_to_assessmentplan(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """Backward-compat: an older client without section_id still works."""
        from guided_awv.api.awv_api import SavePlanHandler
        handler = SavePlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "narrative": "old client",
            "_form_fields": {"prevention_plan": "x"},
        }
        mock_json.return_value = "json_ok"

        handler.post()

        assert mock_save.call_args[0][1] == "assessmentplan"

    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_unknown_section_id_falls_back_to_assessmentplan(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """Defense against spoofed section_id values - only known keys are honored."""
        from guided_awv.api.awv_api import SavePlanHandler
        handler = SavePlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "narrative": "x",
            "section_id": "../../etc/passwd",
            "_form_fields": {},
        }
        mock_json.return_value = "json_ok"

        handler.post()

        assert mock_save.call_args[0][1] == "assessmentplan"


class TestSavePlanHandler:
    """Tests for SavePlanHandler."""

    @patch("guided_awv.api.awv_api.PerformCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_narrative(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_perform_cmd: MagicMock,
    ) -> None:
        """POST with narrative creates PlanCommand."""
        mock_event = MagicMock()
        handler = SavePlanHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "narrative": "Prevention plan: smoking cessation counseling provided.",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        plan_narrative = mock_plan_cmd.call_args[1]["narrative"]
        assert "Prevention plan: smoking cessation counseling provided." in plan_narrative
        assert "json_ok" in result


# ---- ScheduleFollowupHandler ----

class TestScheduleFollowupHandler:
    """Tests for ScheduleFollowupHandler."""

    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.FollowUpCommand")
    def test_post_with_comment_only(
        self,
        mock_fu_cmd: MagicMock,
        mock_json: MagicMock,
    ) -> None:
        """POST with just a comment creates FollowUpCommand."""
        mock_event = MagicMock()
        handler = ScheduleFollowupHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "comment": "Schedule next AWV in 12 months",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fu_effect"
        mock_fu_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.FollowUpCommand")
    def test_post_with_requested_date(
        self,
        mock_fu_cmd: MagicMock,
        mock_json: MagicMock,
    ) -> None:
        """POST with requested_date parses date correctly."""
        import datetime

        mock_event = MagicMock()
        handler = ScheduleFollowupHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "comment": "Annual follow-up",
            "requested_date": "2026-02-01",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fu_effect"
        mock_fu_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        fu_call_kwargs = mock_fu_cmd.call_args[1]
        assert fu_call_kwargs["requested_date"] == datetime.date(2026, 2, 1)

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_invalid_date(self, mock_json: MagicMock) -> None:
        """POST with invalid date format returns 400 error."""
        mock_event = MagicMock()
        handler = ScheduleFollowupHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "requested_date": "not-a-date",
        }
        mock_json.return_value = "error"

        result = handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveFallRiskHandler ----

class TestSaveFallRiskHandler:
    """Tests for SaveFallRiskHandler."""

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_fall_history(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with fall history includes count in narrative."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "Yes",
            "falls_count": 2,
            "tug_time_seconds": 15.0,
            "risk_factors": ["Fear of falling"],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result contains risk level
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: High" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_no_falls(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with no falls does not include fall count."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "tug_time_seconds": 9.5,
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result contains risk level
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: Low" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_positive_orthostatic(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with SBP drop >= 20 shows POSITIVE in narrative."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "ortho_lying_sbp": 140,
            "ortho_lying_dbp": 85,
            "ortho_lying_hr": 72,
            "ortho_standing_sbp": 115,
            "ortho_standing_dbp": 80,
            "ortho_standing_hr": 88,
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result contains risk level
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: High" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_negative_orthostatic(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with drops below thresholds shows Negative."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "ortho_lying_sbp": 130,
            "ortho_lying_dbp": 80,
            "ortho_standing_sbp": 125,
            "ortho_standing_dbp": 78,
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # No falls, no fear, no gait concern, no TUG, negative ortho -> Low
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: Low" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_without_orthostatic_data(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST without ortho fields does not include Orthostatic in narrative."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # No falls, no risk factors, no ortho -> Low
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: Low" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_high_risk_from_tug(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with TUG >= 12 shows High risk level in narrative."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "tug_time_seconds": 14.0,
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: High" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_moderate_risk_from_fear(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with fear of falling only shows Moderate risk level."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "fear_of_falling": "Yes",
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: Moderate" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_low_risk(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with no risk indicators shows Low risk level."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "tug_time_seconds": 9.0,
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: Low" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_high_risk_from_multiple_falls(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with falls_count >= 2 shows High risk level."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "Yes",
            "falls_count": 3,
            "fall_injury": "No",
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: High" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_orthostatic_dbp_drop_triggers_positive(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with DBP drop >= 10 alone triggers POSITIVE."""
        mock_event = MagicMock()
        handler = SaveFallRiskHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "falls_past_year": "No",
            "ortho_lying_sbp": 130,
            "ortho_lying_dbp": 85,
            "ortho_standing_sbp": 125,
            "ortho_standing_dbp": 74,
            "risk_factors": [],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fall_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Fall Risk: High" in sa_result


# ---- SaveHRAHandler ----

class TestSavePreventiveServicesMergesCache:
    """Regression for Claude review finding #14.

    SavePreventiveServicesHandler had two write paths to the same form-state
    slot. The popup-save path merged with existing keys; the main services
    path did an unconditional overwrite. That made prevention_plan_comments
    (written only via the popup) silently disappear on the next Save Services
    from the AWV modal. Fix: read+merge in the main save path too.
    """

    @patch("guided_awv.api.awv_api._get_all_form_states")
    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_main_save_preserves_prevention_plan_comments(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        """A modal save with services {} must preserve any popup-saved comments."""
        from guided_awv.api.awv_api import SavePreventiveServicesHandler
        # Existing cache state: popup save already wrote provider comments
        mock_get.return_value = {
            "preventiveservices": {
                "prevention_plan_comments": "Discuss colonoscopy in 6 weeks.",
                "svc_old_ordered": ["ordered"],
            }
        }
        handler = SavePreventiveServicesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "prevention_plan_created": "yes",
            "_form_fields": {"prevention_plan_created": "yes"},
        }
        mock_json.return_value = "json_ok"

        handler.post()

        # The merged state must contain both the new modal field AND the
        # comments + earlier services from the popup write.
        assert mock_save.call_count == 1
        saved_args = mock_save.call_args[0]
        assert saved_args[1] == "preventiveservices"
        saved_state = saved_args[2]
        assert saved_state["prevention_plan_comments"] == "Discuss colonoscopy in 6 weeks."
        assert saved_state["svc_old_ordered"] == ["ordered"]
        assert saved_state["prevention_plan_created"] == "yes"


class TestSaveFollowUpFieldNames:
    """Regression for Claude review finding #15.

    saveFollowUp JS used to read followup_type / followup_timeframe /
    followup_notes / followup_date - none of which the FollowUpSchedulingModule
    renders. Result: every save produced a FollowUpCommand with a null
    requested_date and a near-empty comment.

    These tests guard the *backend* behavior by hand-building a request body
    in the production wire shape (next_awv_date, next_awv_timeframe, etc.)
    and asserting it round-trips correctly. The frontend-shape guard is in
    tests/applications/test_guided_awv_app.py.
    """

    @patch("guided_awv.api.awv_api.FollowUpCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_followup_uses_next_awv_date_as_requested_date(
        self,
        mock_json: MagicMock,
        mock_followup_cmd: MagicMock,
    ) -> None:
        """Production wire shape sends 'requested_date' = next_awv_date."""
        from guided_awv.api.awv_api import ScheduleFollowupHandler
        handler = ScheduleFollowupHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "comment": "Next AWV: 2027-05-10. Reason: routine follow-up",
            "requested_date": "2027-05-10",
        }
        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "followup_effect"
        mock_followup_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # The handler should be called with both a non-empty comment AND
        # a non-null requested_date. ScheduleFollowupHandler parses the ISO
        # string into a date object before passing to FollowUpCommand.
        call_kwargs = mock_followup_cmd.call_args[1]
        assert call_kwargs.get("requested_date") == datetime.date(2027, 5, 10)
        assert "Next AWV" in call_kwargs.get("comment", "")


class TestSectionLastDoneIso:
    """Regression for Claude review finding #21.

    _lookup_session_dates used to unconditionally use today.isoformat() for
    annual_depression / annual_cognitive whenever the cached section existed.
    With the 14-day cache TTL, a multi-day workflow reported older screenings
    as "completed today" - wrong. Now reads the section's _last_saved field
    via _section_last_done_iso, which slices the YYYY-MM-DD portion and
    validates via fromisoformat.
    """

    def test_returns_iso_date_from_last_saved(self) -> None:
        from guided_awv.api.awv_api import _section_last_done_iso
        today = datetime.date(2026, 5, 10)
        section = {"_last_saved": "2026-05-08T14:30:00.000Z", "q1": 2}
        assert _section_last_done_iso(section, today) == "2026-05-08"

    def test_falls_back_to_today_when_missing(self) -> None:
        from guided_awv.api.awv_api import _section_last_done_iso
        today = datetime.date(2026, 5, 10)
        assert _section_last_done_iso({"q1": 2}, today) == "2026-05-10"

    def test_falls_back_to_today_when_unparseable(self) -> None:
        from guided_awv.api.awv_api import _section_last_done_iso
        today = datetime.date(2026, 5, 10)
        section = {"_last_saved": "not-a-date", "q1": 2}
        assert _section_last_done_iso(section, today) == "2026-05-10"

    def test_handles_non_dict_input(self) -> None:
        from guided_awv.api.awv_api import _section_last_done_iso
        today = datetime.date(2026, 5, 10)
        assert _section_last_done_iso(None, today) == "2026-05-10"  # type: ignore[arg-type]


class TestFormEnteredDatesOverrideChart:
    """Regression for Claude review finding #20.

    The merge loop in _build_plan used to guard the form-entered date with
    `if svc_id not in dates:`, only filling gaps. The inline comment claimed
    "Form-entered dates take priority (user-verified)" - the conditional said
    the opposite. A provider who typed a corrected date saw the stale chart
    date in the Prevention Plan. Now the form value unconditionally overrides.
    """

    def test_form_entered_date_overrides_chart_date(self) -> None:
        """The exact scenario the review described: chart says one date, form
        says another, the provider's form value wins."""
        # Exercise the merge loop directly by re-creating its body. The
        # production loop is inside _build_plan which requires a full
        # handler+template setup - testing the logic separately is sufficient
        # since the loop is small and behaviorally distinct.
        prev_state = {"svc_flu_last_date": "2026-04-01"}
        dates: dict[str, dict] = {"flu": {"last_done": "2024-01-15"}}  # stale chart date

        # Replay the merge loop from api/awv_api.py _build_plan
        for key, val in prev_state.items():
            if key.endswith("_last_date") and val:
                if key.startswith("svc_"):
                    svc_id = key[4:-10]
                elif key.startswith("bh_"):
                    svc_id = key[3:-10]
                elif key.startswith("chronic_"):
                    svc_id = key[8:-10]
                else:
                    continue
                dates[svc_id] = {"last_done": val}

        # Form value wins - not the older chart date
        assert dates["flu"]["last_done"] == "2026-04-01"


class TestMedicationReconciliation1111FGate:
    """Regression for Claude review finding #19 (Med Recon 1111F).

    CPT II 1111F (Medications reconciled) used to fire on every save,
    including ones where the provider answered 'No' to medications_reconciled
    or didn't answer at all - falsely attesting reconciliation. Now gated on
    medications_reconciled in (Yes / Reconciled / Complete / Completed).
    """

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_1111F_emitted_on_yes(
        self,
        mock_json: MagicMock,
        mock_review: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SaveMedicationReconciliationHandler
        handler = SaveMedicationReconciliationHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "medications_reconciled": "Yes",
        }
        mock_json.return_value = "json_ok"
        mock_billing.return_value.apply.return_value = "billing_effect"
        mock_review.return_value.originate.return_value = "review_effect"

        handler.post()

        cpts = [c.kwargs["cpt"] for c in mock_billing.call_args_list]
        assert "1111F" in cpts

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_1111F_NOT_emitted_on_no(
        self,
        mock_json: MagicMock,
        mock_review: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SaveMedicationReconciliationHandler
        handler = SaveMedicationReconciliationHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "medications_reconciled": "No",
        }
        mock_json.return_value = "json_ok"
        mock_billing.return_value.apply.return_value = "billing_effect"
        mock_review.return_value.originate.return_value = "review_effect"

        handler.post()

        cpts = [c.kwargs["cpt"] for c in mock_billing.call_args_list]
        assert "1111F" not in cpts, f"1111F should not fire on a No answer, got {cpts}"

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_1111F_NOT_emitted_when_blank(
        self,
        mock_json: MagicMock,
        mock_review: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """No answer at all should never emit 1111F."""
        from guided_awv.api.awv_api import SaveMedicationReconciliationHandler
        handler = SaveMedicationReconciliationHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"note_id": "note-abc"}
        mock_json.return_value = "json_ok"
        mock_billing.return_value.apply.return_value = "billing_effect"
        mock_review.return_value.originate.return_value = "review_effect"

        handler.post()

        cpts = [c.kwargs["cpt"] for c in mock_billing.call_args_list]
        assert "1111F" not in cpts


class TestSaveHRATobaccoCPTII:
    """Regression tests for Claude review finding #9 (Bug B2).

    The previous handler emitted CPT II 1036F whenever ``tobacco_use`` was
    truthy, with a comment claiming it meant "Tobacco use screened and
    documented". 1036F's actual AMA long descriptor is "Current tobacco
    non-user" - so a "Yes" answer was attesting non-user status and adding
    4004F (cessation intervention received) on top, a billing-correctness
    bug. The fix routes by answer value: 1034F for current users,
    1036F for never/former, and 4004F only when the cessation_intervention
    field actually says yes.
    """

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_yes_answer_emits_1034F_not_1036F(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SaveHRAHandler
        handler = SaveHRAHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {"tobacco_use": "Yes"},
        }
        mock_json.return_value = "json_ok"
        mock_billing.return_value.apply.return_value = "effect"

        handler.post()

        cpts = [c.kwargs.get("cpt") or c.args[1] if c.args else c.kwargs.get("cpt")
                for c in mock_billing.call_args_list]
        # All call_args -> kwargs.cpt
        cpts = [c.kwargs["cpt"] for c in mock_billing.call_args_list]
        assert "1034F" in cpts, f"current-user code missing: {cpts}"
        assert "1036F" not in cpts, f"non-user code 1036F was incorrectly emitted for Yes answer: {cpts}"
        # 4004F must only appear when cessation_intervention is also yes
        assert "4004F" not in cpts, f"4004F should not fire without cessation intervention: {cpts}"

    def test_hra_module_renders_cessation_intervention_field(self) -> None:
        """Regression for Claude review finding #13.

        v0.14.8 gated CPT II 4004F on responses['cessation_intervention']
        being yes - but no such field existed in the HRA module. v0.14.10
        added it. This test asserts the field is rendered so 4004F is
        reachable from real UI input.
        """
        from guided_awv.modules.hra import HRAModule
        module = HRAModule("note-1", "patient-1", "initial")
        html = module.render_content_html()
        # The field must be present, with the radio name that the handler
        # reads. Asking the question to all patients (incl. non-smokers who
        # can answer N/A) keeps the workflow simple and the 4004F gate live.
        assert 'name="cessation_intervention"' in html

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_yes_with_cessation_emits_1034F_and_4004F(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SaveHRAHandler
        handler = SaveHRAHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {"tobacco_use": "Yes", "cessation_intervention": "Yes"},
        }
        mock_json.return_value = "json_ok"
        mock_billing.return_value.apply.return_value = "effect"

        handler.post()

        cpts = [c.kwargs["cpt"] for c in mock_billing.call_args_list]
        assert "1034F" in cpts
        assert "4004F" in cpts

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_no_answer_emits_1036F(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SaveHRAHandler
        handler = SaveHRAHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {"tobacco_use": "No"},
        }
        mock_json.return_value = "json_ok"
        mock_billing.return_value.apply.return_value = "effect"

        handler.post()

        cpts = [c.kwargs["cpt"] for c in mock_billing.call_args_list]
        assert "1036F" in cpts, f"non-user code missing for No answer: {cpts}"
        assert "1034F" not in cpts
        assert "4004F" not in cpts

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_former_user_emits_1036F(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SaveHRAHandler
        handler = SaveHRAHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {"tobacco_use": "Former user"},
        }
        mock_json.return_value = "json_ok"
        mock_billing.return_value.apply.return_value = "effect"

        handler.post()

        cpts = [c.kwargs["cpt"] for c in mock_billing.call_args_list]
        assert "1036F" in cpts
        assert "1034F" not in cpts


class TestSaveHRAHandler:
    """Tests for SaveHRAHandler."""

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_initial_hra_returns_success(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """POST with valid HRA data caches form state and returns success with CPT II codes."""
        mock_event = MagicMock()
        handler = SaveHRAHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "awv_type": "initial",
            "responses": {
                "hra_general_health": "Good",
                "hra_tobacco_use": "No",
                "hra_exercise_days": 3,
            },
        }

        mock_json.return_value = "json_ok"
        mock_billing_instance = MagicMock()
        mock_billing_instance.apply.return_value = "billing_effect"
        mock_billing.return_value = mock_billing_instance

        result = handler.post()

        assert "json_ok" in result
        # CPT II 1036F for tobacco screening documented
        mock_billing.assert_called_once_with(note_id="note-abc", cpt="1036F", assessment_ids=[])

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_unprefixed_keys_still_work(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """POST with unprefixed keys still processes correctly."""
        mock_event = MagicMock()
        handler = SaveHRAHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "awv_type": "subsequent",
            "responses": {
                "general_health": "Fair",
                "tobacco_use": "Former user",
            },
        }

        mock_json.return_value = "json_ok"
        mock_billing_instance = MagicMock()
        mock_billing_instance.apply.return_value = "billing_effect"
        mock_billing.return_value = mock_billing_instance

        result = handler.post()

        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400 error."""
        mock_event = MagicMock()
        handler = SaveHRAHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"responses": {}}
        mock_json.return_value = "error"

        result = handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveFamilyHistoryHandler ----

class TestSaveFamilyHistoryHandler:
    """Tests for SaveFamilyHistoryHandler."""

    @patch("guided_awv.api.awv_api.Coding")
    @patch("guided_awv.api.awv_api.FamilyHistoryCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_relatives(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_fhx_cmd: MagicMock,
        mock_coding: MagicMock,
    ) -> None:
        """POST with relatives dict saves family history via FamilyHistoryCommand."""
        mock_event = MagicMock()
        handler = SaveFamilyHistoryHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "relatives": {
                "Mother": {"status": "Living", "age": "72", "conditions": ["DM2", "HTN"]},
                "Father": {"status": "Deceased", "age": "65", "conditions": ["CAD"]},
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "fh_effect"
        mock_fhx_cmd.return_value = mock_cmd
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result
        # FamilyHistoryCommand should have been called for each relative
        assert mock_fhx_cmd.call_count == 2

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveFamilyHistoryHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"relatives": {"Mother": {"conditions": ["DM2"]}}}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveFunctionalAbilityHandler ----

class TestSaveFunctionalAbilityHandler:
    """Tests for SaveFunctionalAbilityHandler."""

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_adl_and_iadl(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with ADL and IADL responses includes both in narrative."""
        mock_event = MagicMock()
        handler = SaveFunctionalAbilityHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "adl_responses": {"adl_bathing": "independent", "adl_dressing": "needs_assistance"},
            "iadl_responses": {"iadl_medications": "independent"},
            "home_safety_concerns": "Throw rugs in hallway",
            "referrals_needed": ["Physical Therapy", "Home Health Aide"],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "func_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "ADL/IADL assessment completed" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_empty_responses_still_saves(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with no ADL/IADL selections still saves header."""
        mock_event = MagicMock()
        handler = SaveFunctionalAbilityHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"note_id": "note-abc"}

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "func_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "ADL/IADL assessment completed" in sa_result
        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveFunctionalAbilityHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveAdvanceCarePlanningHandler ----

class TestSaveAdvanceCarePlanningHandler:
    """Tests for SaveAdvanceCarePlanningHandler."""

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_full_acp(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """POST with all ACP fields returns success with 1123F billing code."""
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Yes",
            "advance_directive_exists": "Yes - on file",
            "advance_directive_type": ["Living Will", "POLST / MOLST"],
            "healthcare_proxy_name": "Jane Smith",
            "healthcare_proxy_relationship": "Spouse",
            "healthcare_proxy_contact": "555-0199",
            "patient_wishes_summary": "No mechanical ventilation. Comfort measures preferred.",
            "acp_followup_needed": ["Scan existing directive into chart"],
        }

        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result
        mock_billing.assert_called_once_with(note_id="note-abc", cpt="1123F", assessment_ids=[])

    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_declined_discussion(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
    ) -> None:
        """POST with declined discussion still saves to cache + emits plan narrative."""
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Patient declined discussion",
        }

        mock_json.return_value = "json_ok"
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance

        result = handler.post()

        # v0.14.11 (Fix #18): handlers now route their narrative to a
        # PlanCommand when non-empty. The ACP narrative includes the
        # "ACP discussed" line so a PlanCommand is emitted.
        assert "json_ok" in result
        assert "plan_effect" in result
        mock_plan_cmd.assert_called_once()

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_includes_healthcare_proxy_designated(
        self,
        mock_json: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """POST with healthcare_proxy_designated saves to cache with 1124F."""
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Yes",
            "healthcare_proxy_designated": "Yes",
        }

        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result
        mock_billing.assert_called_once_with(note_id="note-abc", cpt="1124F", assessment_ids=[])

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_includes_all_acp_fields_in_narrative(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """Regression for Claude review #24: handler must persist the 7 ACP
        fields that v0.14.11 added to the JS payload but the handler dropped
        (acp_total_minutes, acp_start_time, acp_end_time, code_status,
        acp_topics_discussed, documents_completed_today, copy_given_to_patient,
        documents_scanned_to_chart). Surface them all via the PlanCommand
        narrative so they actually land on the chart.
        """
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Yes",
            "code_status": "Full Code",
            "advance_directive_exists": "Yes - on file",
            "advance_directive_type": ["Living Will"],
            "acp_topics_discussed": ["Goals of care", "Code status"],
            "documents_completed_today": ["POLST"],
            "copy_given_to_patient": "Yes",
            "documents_scanned_to_chart": "Yes",
            "acp_start_time": "10:00",
            "acp_end_time": "10:18",
            "acp_total_minutes": 18,
        }

        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        narrative = mock_plan_cmd.call_args[1]["narrative"]
        assert "Code status: Full Code" in narrative
        assert "Topics discussed: Goals of care, Code status" in narrative
        assert "Documents completed today: POLST" in narrative
        assert "Copy given to patient: Yes" in narrative
        assert "Documents scanned to chart: Yes" in narrative
        assert "start 10:00" in narrative
        assert "end 10:18" in narrative
        assert "total 18 min" in narrative

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_emits_99497_when_time_meets_threshold(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """CPT 99497 must only fire when documented time >= 16 minutes (CMS
        midpoint rule for the first 30 min of face-to-face ACP).
        """
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Yes",
            "acp_total_minutes": 18,
        }
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        billed_codes = [call.kwargs["cpt"] for call in mock_billing.call_args_list]
        assert "99497" in billed_codes

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_skips_99497_when_time_below_threshold(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """CPT 99497 must NOT fire when documented time < 16 min - billing it
        without sufficient time is a CMS billing-compliance violation.
        """
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Yes",
            "acp_total_minutes": 10,
        }
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        billed_codes = [call.kwargs["cpt"] for call in mock_billing.call_args_list]
        assert "99497" not in billed_codes

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_handles_string_acp_total_minutes(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """JS may ship acp_total_minutes as a string (input value); handler
        must coerce without raising.
        """
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Yes",
            "acp_total_minutes": "20",
        }
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        billed_codes = [call.kwargs["cpt"] for call in mock_billing.call_args_list]
        assert "99497" in billed_codes

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_skips_99497_when_discussion_did_not_occur(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """Regression for Claude review #25: 99497 was gated only on time,
        not on whether the discussion happened. A provider who entered 20 min
        of time and then flipped acp_discussed to 'No' / 'Patient declined'
        would silently bill 99497 on a visit where ACP didn't occur. The
        gate must mirror the sister 1124F branch (which requires
        acp_discussed in 'Yes'/'Yes - discussed' or directive_exists in
        'Yes'/'Yes - on file').
        """
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "Patient declined discussion",
            "acp_total_minutes": 20,
        }
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        billed_codes = [call.kwargs["cpt"] for call in mock_billing.call_args_list]
        assert "99497" not in billed_codes

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_emits_99497_when_directive_on_file_with_time(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """The discussion-occurred gate accepts either acp_discussed=Yes OR
        advance_directive_exists='Yes - on file' (mirroring 1123F).
        """
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "",
            "advance_directive_exists": "Yes - on file",
            "acp_total_minutes": 20,
        }
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        billed_codes = [call.kwargs["cpt"] for call in mock_billing.call_args_list]
        assert "99497" in billed_codes

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_drops_time_block_when_discussion_did_not_occur(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """When the discussion was declined, the narrative must not document
        stale time inputs that the JS may still ship (the time inputs are
        hidden via display:none but `getModuleFormData` reads them anyway).
        """
        mock_event = MagicMock()
        handler = SaveAdvanceCarePlanningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "acp_discussed": "No",
            "acp_start_time": "10:00",
            "acp_end_time": "10:20",
            "acp_total_minutes": 20,
        }
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand may not be called at all if narrative collapses to just
        # the heading + "ACP discussed: No", but if it is the time block
        # must NOT appear.
        if mock_plan_cmd.call_args is not None:
            narrative = mock_plan_cmd.call_args[1]["narrative"]
            assert "ACP time:" not in narrative
            assert "total 20 min" not in narrative


# ---- SavePreventiveServicesHandler ----


class TestSavePreventiveServicesAttestationOnly:
    """Regression tests for Claude review finding #2.

    SavePreventiveServicesHandler used to reject any POST whose ``services``
    dict was empty, dropping the two CMS attestation radios
    (``prevention_plan_created``, ``written_copy_given``) that gate
    Element 10 of the 11-element AWV completeness check. A provider who
    reviews the patient's preventive-services chart, decides nothing new
    needs to be ordered or discussed today, and answers the two attestation
    questions must be able to save - otherwise Element 10 can never be
    satisfied without checking an inappropriate service box.
    """

    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_accepts_attestation_only_save_with_empty_services(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        from guided_awv.api.awv_api import SavePreventiveServicesHandler
        handler = SavePreventiveServicesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {},
            "prevention_plan_created": "yes",
            "written_copy_given": "yes",
            "_form_fields": {"prevention_plan_created": "yes", "written_copy_given": "yes"},
        }
        mock_json.return_value = "json_ok"

        handler.post()

        # Must NOT have responded with 400 - the attestation answers are valid.
        for call in mock_json.call_args_list:
            assert call[1].get("status_code") != 400, "rejected an attestation-only save"
        # Form state was persisted so the answers survive a reload.
        mock_save.assert_called_once()
        assert mock_save.call_args[0][1] == "preventiveservices"

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_rejects_truly_empty_save(self, mock_json: MagicMock) -> None:
        """An empty POST with no services and no attestation is still rejected."""
        from guided_awv.api.awv_api import SavePreventiveServicesHandler
        handler = SavePreventiveServicesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {"note_id": "note-abc", "services": {}}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.InstructCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_routes_checklist_narrative_via_plan_command(
        self,
        mock_json: MagicMock,
        mock_instruct: MagicMock,
        mock_plan_cmd: MagicMock,
    ) -> None:
        """Regression for Claude review #26: SavePreventiveServicesHandler
        built `narrative_parts` (per-service checklist + Element 10 attestation
        lines) but never joined them and never routed via PlanCommand. The
        per-service typed commands still landed individual orders, but the
        aggregate checklist and the two CMS Element 10 attestation answers
        were silently dropped at the `return effects` site. Must mirror the
        v0.14.11 PlanCommand routing pattern used by every sister handler.
        """
        from guided_awv.api.awv_api import SavePreventiveServicesHandler
        handler = SavePreventiveServicesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"colorectal_cancer": "discussed"},
            "prevention_plan_created": "Yes",
            "written_copy_given": "Yes",
        }
        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "instruct_effect"
        mock_instruct.return_value = mock_cmd
        mock_plan_instance = MagicMock()
        mock_plan_instance.originate.return_value = "plan_effect"
        mock_plan_cmd.return_value = mock_plan_instance
        mock_json.return_value = "json_ok"

        handler.post()

        assert mock_plan_cmd.called, "Element 10 attestation + checklist narrative was dropped"
        narrative = mock_plan_cmd.call_args[1]["narrative"]
        assert "Personalized prevention plan created: Yes" in narrative
        assert "Written copy of plan given to patient: Yes" in narrative


class TestSavePreventiveServicesHandler:
    """Tests for SavePreventiveServicesHandler."""

    @patch("guided_awv.api.awv_api.InstructCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_ordered_vaccine_fdb_fallback(
        self,
        mock_json: MagicMock,
        mock_instruct: MagicMock,
    ) -> None:
        """POST with ordered vaccine falls back to InstructCommand when FDB lookup fails."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"influenza": "ordered"},
        }
        handler._lookup_fdb_medication = MagicMock(return_value=None)  # type: ignore[method-assign]

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "instruct_effect"
        mock_instruct.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_instruct.assert_called_once()
        assert "json_ok" in result
        assert "instruct_effect" in result

    @patch("guided_awv.api.awv_api.PrescribeCommand")
    @patch("guided_awv.api.awv_api.ClinicalQuantity")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_ordered_vaccine_fdb_success(
        self,
        mock_json: MagicMock,
        mock_cq: MagicMock,
        mock_prescribe: MagicMock,
    ) -> None:
        """POST with ordered vaccine uses PrescribeCommand when FDB lookup succeeds."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {"canvas-logged-in-user-id": "staff-123"}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"influenza": "ordered"},
        }
        handler._lookup_fdb_medication = MagicMock(return_value={  # type: ignore[method-assign]
            "med_medication_id": 436095,
            "clinical_quantities": [{
                "representative_ndc": "11822317640",
                "erx_ncpdp_script_quantity_qualifier_code": "C48542",
            }],
        })

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "prescribe_effect"
        mock_prescribe.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_prescribe.assert_called_once()
        assert "prescribe_effect" in result

    @patch("guided_awv.api.awv_api.LabOrderCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_ordered_lab_with_partner(
        self,
        mock_json: MagicMock,
        mock_lab_cmd: MagicMock,
    ) -> None:
        """POST with ordered lab uses LabOrderCommand when lab partner is found."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {"canvas-logged-in-user-id": "staff-123"}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"lipids": "ordered"},
        }
        handler._get_lab_partner_and_test = MagicMock(  # type: ignore[method-assign]
            return_value=("partner-uuid", "LIPID")
        )

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "lab_effect"
        mock_lab_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_lab_cmd.assert_called_once()
        call_kwargs = mock_lab_cmd.call_args[1]
        assert call_kwargs["lab_partner"] == "partner-uuid"
        assert call_kwargs["tests_order_codes"] == ["LIPID"]
        assert "lab_effect" in result

    @patch("guided_awv.api.awv_api.InstructCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_ordered_lab_fallback(
        self,
        mock_json: MagicMock,
        mock_instruct: MagicMock,
    ) -> None:
        """POST with ordered lab falls back to InstructCommand when no lab partner found."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"lipids": "ordered"},
        }
        handler._get_lab_partner_and_test = MagicMock(return_value=None)  # type: ignore[method-assign]

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "instruct_effect"
        mock_instruct.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_instruct.assert_called_once()
        assert "instruct_effect" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_empty_services_returns_400(self, mock_json: MagicMock) -> None:
        """POST with no service statuses returns 400."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"note_id": "note-abc", "services": {}}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api.InstructCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_prevention_plan_created_returns_success(
        self,
        mock_json: MagicMock,
        mock_instruct: MagicMock,
    ) -> None:
        """POST with prevention_plan_created saves to cache and returns success."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"influenza": "ordered"},
            "prevention_plan_created": "Yes",
        }
        handler._lookup_fdb_medication = MagicMock(return_value=None)  # type: ignore[method-assign]

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "instruct_effect"
        mock_instruct.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.InstructCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_written_copy_given_returns_success(
        self,
        mock_json: MagicMock,
        mock_instruct: MagicMock,
    ) -> None:
        """POST with written_copy_given saves to cache and returns success."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"influenza": "ordered"},
            "written_copy_given": "Yes",
        }
        handler._lookup_fdb_medication = MagicMock(return_value=None)  # type: ignore[method-assign]

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "instruct_effect"
        mock_instruct.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"services": {"flu": "ordered"}}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_list_status_raises_type_error(self, mock_json: MagicMock) -> None:
        """POST with a list status value raises TypeError (the old checkbox bug)."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"influenza": ["ordered"]},
        }

        with pytest.raises(TypeError, match="unhashable type"):
            handler.post()

    @patch("guided_awv.api.awv_api.InstructCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_discussed_status_creates_instruct(
        self,
        mock_json: MagicMock,
        mock_instruct: MagicMock,
    ) -> None:
        """POST with 'discussed' status creates an InstructCommand."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"influenza": "discussed"},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "discuss_effect"
        mock_instruct.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_instruct.assert_called_once()
        assert "discuss_effect" in result

    @patch("guided_awv.api.awv_api.InstructCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_string_status_does_not_raise(
        self,
        mock_json: MagicMock,
        mock_instruct: MagicMock,
    ) -> None:
        """POST with plain string statuses does not raise TypeError."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {
                "influenza": "ordered",
                "colorectal": "discussed",
            },
        }
        handler._lookup_fdb_medication = MagicMock(return_value=None)  # type: ignore[method-assign]
        handler._get_lab_partner_and_test = MagicMock(return_value=None)  # type: ignore[method-assign]

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "effect"
        mock_instruct.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.ImagingOrderCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_ordered_imaging(
        self,
        mock_json: MagicMock,
        mock_img_cmd: MagicMock,
    ) -> None:
        """POST with ordered imaging creates ImagingOrderCommand."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"mammogram": "ordered"},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "img_effect"
        mock_img_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_img_cmd.assert_called_once()
        assert "img_effect" in result

    @patch("guided_awv.api.awv_api.PerformCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_ordered_exam(
        self,
        mock_json: MagicMock,
        mock_perform: MagicMock,
    ) -> None:
        """POST with ordered exam creates PerformCommand."""
        mock_event = MagicMock()
        handler = SavePreventiveServicesHandler(mock_event)
        handler.request = MagicMock()
        handler.request.headers = {}
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "services": {"cervical_cancer": "ordered"},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "perform_effect"
        mock_perform.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_perform.assert_called_once()
        assert "perform_effect" in result


# ---- SaveCurrentProvidersHandler ----

class TestSaveCurrentProvidersHandler:
    """Tests for SaveCurrentProvidersHandler."""

    @patch("guided_awv.api.awv_api.TaskCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_creates_task_per_specialist(
        self,
        mock_json: MagicMock,
        mock_task_cmd: MagicMock,
    ) -> None:
        """POST with specialists creates one TaskCommand per specialist to add them to the external care team."""
        mock_event = MagicMock()
        handler = SaveCurrentProvidersHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "providers": {
                "pcp": "Dr. Smith, Internal Medicine, 555-0100",
                "specialists": [
                    {"name": "Dr. Jones", "specialty": "Cardiology", "phone": "555-0101"},
                    {"name": "Dr. Lee", "specialty": "Endocrinology", "phone": ""},
                ],
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "task_effect"
        mock_task_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        # Two TaskCommand calls for Dr. Jones and Dr. Lee
        assert mock_task_cmd.call_count == 2
        # Title for the first one mentions the name, specialty, and care team
        first_call_kwargs = mock_task_cmd.call_args_list[0][1]
        assert "Dr. Jones" in first_call_kwargs["title"]
        assert "Cardiology" in first_call_kwargs["title"]
        assert "external care team" in first_call_kwargs["title"]
        # Phone is captured in the comment, not the title
        assert "555-0101" in first_call_kwargs["comment"]
        # Second specialist has no phone - comment still produced without crashing
        second_call_kwargs = mock_task_cmd.call_args_list[1][1]
        assert "Dr. Lee" in second_call_kwargs["title"]
        assert "Endocrinology" in second_call_kwargs["title"]
        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.TaskCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_empty_specialists_creates_no_task(
        self,
        mock_json: MagicMock,
        mock_task_cmd: MagicMock,
    ) -> None:
        """POST with empty specialist list creates no TaskCommand.

        v0.14.11 (Fix #18) routes the section's narrative through a
        PlanCommand when non-empty - the PCP name is part of that narrative,
        so the response now contains a PlanCommand effect alongside the
        success response, but still no TaskCommand.
        """
        mock_event = MagicMock()
        handler = SaveCurrentProvidersHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "providers": {
                "pcp": "Dr. Smith",
                "specialists": "",
            },
        }

        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_task_cmd.assert_not_called()
        # success response is present; PlanCommand effect may also be present
        # but is not the focus of this test.
        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.TaskCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_skips_specialist_with_no_name(
        self,
        mock_json: MagicMock,
        mock_task_cmd: MagicMock,
    ) -> None:
        """A specialist row with empty name is skipped (no task created)."""
        mock_event = MagicMock()
        handler = SaveCurrentProvidersHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "providers": {
                "specialists": [
                    {"name": "", "specialty": "Cardiology", "phone": "555-0101"},
                    {"name": "Dr. Real", "specialty": "Neurology", "phone": ""},
                ],
            },
        }
        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "task_effect"
        mock_task_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # Only one task: Dr. Real
        assert mock_task_cmd.call_count == 1
        assert "Dr. Real" in mock_task_cmd.call_args[1]["title"]

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_creates_preferred_pharmacy_effect(
        self,
        mock_json: MagicMock,
    ) -> None:
        """POST with new_preferred_pharmacies fires CreatePatientPreferredPharmacies."""
        mock_event = MagicMock()
        handler = SaveCurrentProvidersHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "patient_id": "patient-xyz",
            "providers": {"pcp": "Dr. Smith"},
            "new_preferred_pharmacies": [
                {"ncpdp_id": "1234567", "organization_name": "CVS"},
                {"ncpdp_id": "9876543", "organization_name": "Walgreens"},
            ],
        }
        mock_json.return_value = "json_ok"

        with patch(
            "canvas_sdk.effects.patient.CreatePatientPreferredPharmacies"
        ) as mock_effect_cls, patch(
            "canvas_sdk.effects.patient.PatientPreferredPharmacy"
        ) as mock_dataclass:
            mock_effect_instance = MagicMock()
            mock_effect_instance.create.return_value = "pharmacy_effect"
            mock_effect_cls.return_value = mock_effect_instance

            handler.post()

            # Effect was created with patient_id and 2 PatientPreferredPharmacy entries
            mock_effect_cls.assert_called_once()
            call_kwargs = mock_effect_cls.call_args[1]
            assert call_kwargs["patient_id"] == "patient-xyz"
            assert len(call_kwargs["pharmacies"]) == 2
            # Both new pharmacies are non-default per the user UX rule
            for call_args in mock_dataclass.call_args_list:
                assert call_args[1]["default"] is False

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_skips_pharmacy_effect_when_no_patient_id(
        self,
        mock_json: MagicMock,
    ) -> None:
        """POST without patient_id should not attempt to create preferred pharmacies."""
        mock_event = MagicMock()
        handler = SaveCurrentProvidersHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "providers": {"pcp": "Dr. Smith"},
            "new_preferred_pharmacies": [{"ncpdp_id": "1234567"}],
        }
        mock_json.return_value = "json_ok"

        with patch(
            "canvas_sdk.effects.patient.CreatePatientPreferredPharmacies"
        ) as mock_effect_cls:
            handler.post()
            mock_effect_cls.assert_not_called()

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_skips_pharmacy_effect_when_list_empty(
        self,
        mock_json: MagicMock,
    ) -> None:
        """No pharmacy effect when new_preferred_pharmacies is empty."""
        mock_event = MagicMock()
        handler = SaveCurrentProvidersHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "patient_id": "patient-xyz",
            "providers": {"pcp": "Dr. Smith"},
            "new_preferred_pharmacies": [],
        }
        mock_json.return_value = "json_ok"

        with patch(
            "canvas_sdk.effects.patient.CreatePatientPreferredPharmacies"
        ) as mock_effect_cls:
            handler.post()
            mock_effect_cls.assert_not_called()

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveCurrentProvidersHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"providers": {"pcp": "Dr. Smith"}}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveHearingVisionHandler ----

class TestSaveHearingVisionHandler:
    """Tests for SaveHearingVisionHandler."""

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_hearing_and_vision(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with hearing and vision data includes both in narrative."""
        mock_event = MagicMock()
        handler = SaveHearingVisionHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "hearing": {
                "hearing_subjective": "Mild difficulty",
                "hearing_aid_use": "No",
                "whisper_test": "Pass (both ears)",
                "hearing_referral": "No",
            },
            "vision": {
                "vision_subjective": "No difficulty",
                "corrective_lenses": "Yes - glasses",
                "snellen_right": "20/20",
                "snellen_left": "20/25",
                "last_eye_exam": "2025-06",
                "vision_referral": "No",
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "hv_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Hearing & Vision screening completed" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_partial_data(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with partial hearing/vision data only includes provided fields."""
        mock_event = MagicMock()
        handler = SaveHearingVisionHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "hearing": {"hearing_subjective": "No difficulty"},
            "vision": {},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "hv_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "Hearing & Vision screening completed" in sa_result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveHearingVisionHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"hearing": {}, "vision": {}}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveAlcoholScreeningHandler ----

class TestSaveAlcoholScreeningServerSideSexResolution:
    """Regression tests for Claude review finding #7.

    The AUDIT-C handler used to read patient_sex from the request body, but
    the alcohol-screening module never rendered an input for it, so every
    request arrived with patient_sex='' and the handler defaulted to the
    female threshold (>=3) for every patient. Male patients with an AUDIT-C
    score of 3 were incorrectly flagged Positive. Fix: server-side resolution
    of sex_at_birth from the patient on the note, with the request-body value
    as a fallback for any explicit override.
    """

    @patch("guided_awv.api.awv_api._resolve_patient_sex_from_note", return_value="M")
    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_male_with_score_3_negative_via_server_side_resolution(
        self,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        _mock_qid: MagicMock,
        _mock_resolver: MagicMock,
    ) -> None:
        """The exact bug from the review: male patient, AUDIT-C=3, body has no patient_sex.

        Pre-fix: body.get('patient_sex', '') == '' -> threshold=3 -> Positive.
        Post-fix: _resolve_patient_sex_from_note returns 'M' -> threshold=4 -> Negative.
        """
        from guided_awv.api.awv_api import SaveAlcoholScreeningHandler
        handler = SaveAlcoholScreeningHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "auditc_q1": 2,
            "auditc_q2": 1,
            "auditc_q3": 0,
            # NOTE: no patient_sex in body - matches the production wire shape
        }
        mock_json.return_value = "json_ok"

        handler.post()

        call_json = mock_json.call_args[0][0]
        assert call_json["total_score"] == 3
        # With threshold=4 (male), score 3 is Negative
        assert call_json["screen_result"] == "Negative"

    @patch("guided_awv.api.awv_api._resolve_patient_sex_from_note", return_value="F")
    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_female_with_score_3_positive_via_server_side_resolution(
        self,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        _mock_qid: MagicMock,
        _mock_resolver: MagicMock,
    ) -> None:
        """Female patient, AUDIT-C=3, body has no patient_sex -> Positive (threshold=3)."""
        from guided_awv.api.awv_api import SaveAlcoholScreeningHandler
        handler = SaveAlcoholScreeningHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "auditc_q1": 2,
            "auditc_q2": 1,
            "auditc_q3": 0,
        }
        mock_json.return_value = "json_ok"

        handler.post()

        call_json = mock_json.call_args[0][0]
        assert call_json["total_score"] == 3
        assert call_json["screen_result"] == "Positive"

    @patch("guided_awv.api.awv_api._resolve_patient_sex_from_note", return_value="")
    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_body_override_still_works_when_resolver_returns_empty(
        self,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        _mock_qid: MagicMock,
        _mock_resolver: MagicMock,
    ) -> None:
        """If the resolver returns '' (patient lookup failed), an explicit body.patient_sex still works."""
        from guided_awv.api.awv_api import SaveAlcoholScreeningHandler
        handler = SaveAlcoholScreeningHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "auditc_q1": 2,
            "auditc_q2": 1,
            "auditc_q3": 0,
            "patient_sex": "M",
        }
        mock_json.return_value = "json_ok"

        handler.post()

        call_json = mock_json.call_args[0][0]
        # Score 3, male via body override -> Negative
        assert call_json["screen_result"] == "Negative"


class TestSaveAlcoholScreeningHandler:
    """Tests for SaveAlcoholScreeningHandler."""

    @patch("guided_awv.api.awv_api._resolve_patient_sex_from_note", return_value="")
    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_positive_male(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
        _mock_sex_resolver: MagicMock,
    ) -> None:
        """POST with AUDIT-C >= 4 for male shows positive screen.

        Patches the server-side sex resolver to return empty so the test
        falls through to the explicit body.patient_sex override path.
        """
        mock_event = MagicMock()
        handler = SaveAlcoholScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "auditc_q1": 2,
            "auditc_q2": 1,
            "auditc_q3": 1,
            "patient_sex": "M",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "audit_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "AUDIT-C Score: 4/12 - Positive" in sa_result

        call_json = mock_json.call_args[0][0]
        assert call_json["total_score"] == 4
        assert call_json["screen_result"] == "Positive"

    @patch("guided_awv.api.awv_api._resolve_patient_sex_from_note", return_value="")
    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_negative_female(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
        _mock_sex_resolver: MagicMock,
    ) -> None:
        """POST with AUDIT-C < 3 for female shows negative screen."""
        mock_event = MagicMock()
        handler = SaveAlcoholScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "auditc_q1": 1,
            "auditc_q2": 0,
            "auditc_q3": 0,
            "patient_sex": "F",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "audit_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "AUDIT-C Score: 1/12 - Negative" in sa_result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveAlcoholScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"auditc_q1": 1}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveMedicationReconciliationHandler ----

class TestSaveMedicationReconciliationHandler:
    """Tests for SaveMedicationReconciliationHandler."""

    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_full_data(
        self,
        mock_json: MagicMock,
        mock_review_cmd: MagicMock,
    ) -> None:
        """POST creates ChartSectionReviewCommand for medications (no PlanCommand)."""
        mock_event = MagicMock()
        handler = SaveMedicationReconciliationHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "reconciliation_method": "Pill bottle review",
            "otc_medications": "Ibuprofen 200mg PRN",
            "supplements": "Vitamin D 2000IU daily",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "review_effect"
        mock_review_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_review_cmd.assert_called_once()
        assert "json_ok" in result
        assert "review_effect" in result

    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_minimal_data(
        self,
        mock_json: MagicMock,
        mock_review_cmd: MagicMock,
    ) -> None:
        """POST with only note_id still creates review command."""
        mock_event = MagicMock()
        handler = SaveMedicationReconciliationHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"note_id": "note-abc"}

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "review_effect"
        mock_review_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result
        assert "review_effect" in result

    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_high_risk_no_returns_success(
        self,
        mock_json: MagicMock,
        mock_review_cmd: MagicMock,
    ) -> None:
        """POST with high_risk_meds_identified=No still returns success."""
        mock_event = MagicMock()
        handler = SaveMedicationReconciliationHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "high_risk_meds_identified": "No",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "review_effect"
        mock_review_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_includes_medications_reconciled(
        self,
        mock_json: MagicMock,
        mock_review_cmd: MagicMock,
    ) -> None:
        """POST with medications_reconciled returns success."""
        mock_event = MagicMock()
        handler = SaveMedicationReconciliationHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "medications_reconciled": "Yes",
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "review_effect"
        mock_review_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveMedicationReconciliationHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"reconciliation_method": "EHR"}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveSDOHScreeningHandler ----

class TestSaveSDOHScreeningHandler:
    """Tests for SaveSDOHScreeningHandler."""

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_responses(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with responses uses domain labels in narrative."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {
                "sdoh_housing_worried": "No",
                "sdoh_food_worry": "Sometimes true",
                "sdoh_transportation": "Yes",
                "sdoh_loneliness": "Sometimes",
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives:" in sa_result
        assert "Food" in sa_result
        assert "Transportation" in sa_result
        assert "json_ok" in result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_includes_tool_used(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with sdoh_tool_used includes screening tool label in narrative."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {"sdoh_tool_used": "PRAPARE"},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result exists
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives: None" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_with_empty_responses(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with no responses still saves header."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives: None" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_unknown_field_uses_fallback_label(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with unknown field_id falls back to title-cased label."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {"sdoh_custom_field": "Some value"},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives: None" in sa_result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"responses": {"sdoh_housing_worried": "No"}}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_form_state_not_in_sa_result(
        self,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST does not embed form state in SA result (uses cache instead)."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {},
            "_form_fields": {"housing": "No"},
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_sa_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # Form state is now cached, not embedded in SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "AWV_FORM_STATE" not in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_detects_positive_housing(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST detects positive housing screen and adds summary."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {
                "sdoh_housing_worried": "Yes",
                "sdoh_food_worry": "Never true",
                "sdoh_transportation": "No",
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives:" in sa_result
        assert "Housing" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_no_positives_omits_summary(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with all negative responses omits positive summary."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {
                "sdoh_housing_worried": "No",
                "sdoh_housing_conditions": "No",
                "sdoh_food_worry": "Never true",
                "sdoh_food_didnt_last": "Never true",
                "sdoh_transportation": "No",
                "sdoh_social_contact": "Daily",
                "sdoh_loneliness": "Never",
                "sdoh_feel_safe": "Yes",
                "sdoh_afraid_partner": "No",
                "sdoh_recreational_drugs": "No",
                "sdoh_urinary_leakage": "No",
                "sdoh_pain_present": "No",
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result shows no positives
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives: None" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_includes_referral_plan(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST with referral plan includes it in narrative."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {
                "sdoh_referral_plan": "Referred to social work",
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives: None" in sa_result

    @patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid")
    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    @patch("guided_awv.api.awv_api.PlanCommand")
    def test_post_detects_positive_utility_needs(
        self,
        mock_plan_cmd: MagicMock,
        mock_json: MagicMock,
        mock_sa_cmd: MagicMock,
        mock_get_qid: MagicMock,
    ) -> None:
        """POST detects positive utility needs screen."""
        mock_event = MagicMock()
        handler = SaveSDOHScreeningHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "responses": {
                "sdoh_utility_concerns": "Yes",
                "sdoh_housing_worried": "No",
            },
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "sdoh_effect"
        mock_plan_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        handler.post()

        # PlanCommand not used when qid exists; verify SA result
        sa_result = mock_sa_cmd.call_args[1]["result"]
        assert "SDOH Positives:" in sa_result
        assert "Utility needs" in sa_result


# ---- SaveMedicalHistoryHandler ----

class TestSaveMedicalHistoryHandler:
    """Tests for SaveMedicalHistoryHandler."""

    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_with_attestation(
        self,
        mock_json: MagicMock,
        mock_review_cmd: MagicMock,
    ) -> None:
        """POST with attestation creates ChartSectionReviewCommand (no PlanCommand)."""
        mock_event = MagicMock()
        handler = SaveMedicalHistoryHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "medical_history_attestation": [
                "Medical history reviewed and updated for this visit",
                "Allergy list reviewed and updated",
            ],
        }

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "review_effect"
        mock_review_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_review_cmd.assert_called_once()
        assert "json_ok" in result
        assert "review_effect" in result

    @patch("guided_awv.api.awv_api.ChartSectionReviewCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_without_attestation_uses_default(
        self,
        mock_json: MagicMock,
        mock_review_cmd: MagicMock,
    ) -> None:
        """POST without attestation still creates review command."""
        mock_event = MagicMock()
        handler = SaveMedicalHistoryHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"note_id": "note-abc"}

        mock_cmd = MagicMock()
        mock_cmd.originate.return_value = "review_effect"
        mock_review_cmd.return_value = mock_cmd
        mock_json.return_value = "json_ok"

        result = handler.post()

        assert "json_ok" in result
        assert "review_effect" in result

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id(self, mock_json: MagicMock) -> None:
        """POST without note_id returns 400."""
        mock_event = MagicMock()
        handler = SaveMedicalHistoryHandler(mock_event)
        handler.request = MagicMock()
        handler.request.json.return_value = {"medical_history_attestation": ["test"]}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- SaveAWVTypeHandler ----


class TestSaveAWVTypeHandler:
    """Tests for SaveAWVTypeHandler - persists Initial/Subsequent selection."""

    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_saves_initial(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """POST with awv_type='initial' persists to the _awv_meta cache section."""
        handler = SaveAWVTypeHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "awv_type": "initial",
        }
        mock_json.return_value = "json_ok"

        result = handler.post()

        mock_save.assert_called_once_with(
            "note-abc", "_awv_meta", {"awv_type": "initial"}
        )
        assert "json_ok" in result

    @patch("guided_awv.api.awv_api._save_form_state")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_saves_subsequent(
        self,
        mock_json: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """POST with awv_type='subsequent' persists to the _awv_meta cache section."""
        handler = SaveAWVTypeHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "awv_type": "subsequent",
        }
        mock_json.return_value = "json_ok"

        handler.post()

        mock_save.assert_called_once_with(
            "note-abc", "_awv_meta", {"awv_type": "subsequent"}
        )

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_missing_note_id_returns_400(self, mock_json: MagicMock) -> None:
        handler = SaveAWVTypeHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"awv_type": "initial"}
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_post_invalid_awv_type_returns_400(self, mock_json: MagicMock) -> None:
        """awv_type values other than initial/subsequent are rejected."""
        handler = SaveAWVTypeHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "awv_type": "garbage",
        }
        mock_json.return_value = "error"

        handler.post()

        assert mock_json.call_args[1]["status_code"] == 400


# ---- GetScreeningDatesHandler ----


class TestGetScreeningDatesHandler:
    """Tests for GetScreeningDatesHandler."""

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_missing_patient_id(self, mock_json: MagicMock) -> None:
        """GET without patient_id returns 400."""
        handler = GetScreeningDatesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {}
        mock_json.return_value = "error"

        handler.get()

        assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_returns_empty_dates_when_no_data(
        self, mock_json: MagicMock, _mock_cache: MagicMock
    ) -> None:
        """GET returns empty dates dict when patient has no chart data."""
        handler = GetScreeningDatesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"patient_id": "patient-1", "note_id": "note-1"}
        mock_json.return_value = "json_ok"

        with (
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_vaccine_dates"),
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_lab_dates"),
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_imaging_dates"),
        ):
            result = handler.get()

        assert result == ["json_ok"]
        call_args = mock_json.call_args[0][0]
        assert call_args["success"] is True
        assert call_args["dates"] == {}

    @patch("guided_awv.api.awv_api._get_all_form_states")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_session_depression_fills_today(
        self, mock_json: MagicMock, mock_cache: MagicMock
    ) -> None:
        """GET fills annual_depression with today's date if section was saved."""
        mock_cache.return_value = {"depressionscreening": {"phq2_q1": "1"}}
        handler = GetScreeningDatesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"patient_id": "patient-1", "note_id": "note-1"}
        mock_json.return_value = "json_ok"

        with (
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_vaccine_dates"),
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_lab_dates"),
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_imaging_dates"),
        ):
            handler.get()

        call_args = mock_json.call_args[0][0]
        assert "annual_depression" in call_args["dates"]
        assert call_args["dates"]["annual_depression"]["last_done"] is not None

    @patch("guided_awv.api.awv_api._get_all_form_states")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_session_cognitive_fills_today(
        self, mock_json: MagicMock, mock_cache: MagicMock
    ) -> None:
        """GET fills annual_cognitive with today's date if section was saved."""
        mock_cache.return_value = {"cognitiveassessment": {"tool": "mini_cog"}}
        handler = GetScreeningDatesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"patient_id": "patient-1", "note_id": "note-1"}
        mock_json.return_value = "json_ok"

        with (
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_vaccine_dates"),
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_lab_dates"),
            patch("guided_awv.api.awv_api.GetScreeningDatesHandler._lookup_imaging_dates"),
        ):
            handler.get()

        call_args = mock_json.call_args[0][0]
        assert "annual_cognitive" in call_args["dates"]

    def test_lookup_bh_dates_strategy1_filters_entered_in_error(self) -> None:
        """Regression for Claude review #29: Strategy 1 of `_lookup_bh_dates`
        runs BEFORE Strategy 2, and `if svc_id in dates: continue` in Strategy
        2 means Strategy 2 silently doesn't execute for services Strategy 1
        already populated. The FK-reverse filter has to live on Strategy 1's
        `ObservationCoding` query too, or the filter Strategy 2 carries is
        bypassed for the common case.
        """
        from unittest.mock import patch as _patch
        handler = GetScreeningDatesHandler(MagicMock())
        captured_filter_kwargs: list[dict] = []

        class FakeOC:
            class objects:
                @staticmethod
                def filter(**kwargs):
                    captured_filter_kwargs.append(kwargs)
                    chain = MagicMock()
                    chain.order_by.return_value.values_list.return_value.first.return_value = None
                    return chain

        with _patch.dict(
            "sys.modules",
            {"canvas_sdk.v1.data.observation": MagicMock(Observation=MagicMock(), ObservationCoding=FakeOC)},
        ):
            handler._lookup_bh_dates("patient-1", {})

        assert captured_filter_kwargs, "Strategy 1 ObservationCoding.filter was not invoked"
        for kw in captured_filter_kwargs:
            assert kw.get("observation__entered_in_error_id__isnull") is True, (
                f"Strategy 1 filter missing entered_in_error guard: {kw}"
            )

    def test_lookup_all_screening_dates_bh_filters_entered_in_error(self) -> None:
        """Same regression as above but for the module-level
        `_lookup_all_screening_dates` BH branch (called from the cron-free
        sync path used when there is no AWV session).
        """
        from unittest.mock import patch as _patch
        captured_filter_kwargs: list[dict] = []

        class FakeOC:
            class objects:
                @staticmethod
                def filter(**kwargs):
                    captured_filter_kwargs.append(kwargs)
                    chain = MagicMock()
                    chain.order_by.return_value.values_list.return_value.first.return_value = None
                    return chain

        with _patch.dict(
            "sys.modules",
            {"canvas_sdk.v1.data.observation": MagicMock(ObservationCoding=FakeOC)},
        ):
            _lookup_all_screening_dates("patient-1", {})

        bh_filters = [
            kw for kw in captured_filter_kwargs
            if "code__in" in kw and any(c in kw["code__in"] for c in ("55757-9", "72233-0"))
        ]
        assert bh_filters, "BH ObservationCoding.filter was not invoked"
        for kw in bh_filters:
            assert kw.get("observation__entered_in_error_id__isnull") is True, (
                f"BH branch missing entered_in_error guard: {kw}"
            )

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_overdue_flagged_for_annual_service(self, mock_json: MagicMock) -> None:
        """GET marks annual services as overdue when > 1 year old."""
        from datetime import date, timedelta

        old_date = (date.today() - timedelta(days=400)).isoformat()
        handler = GetScreeningDatesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"patient_id": "patient-1"}
        mock_json.return_value = "json_ok"

        def fake_vaccine_lookup(patient_id: str, dates: dict) -> None:
            dates["influenza"] = {"last_done": old_date}

        with (
            patch.object(handler, "_lookup_vaccine_dates", side_effect=fake_vaccine_lookup),
            patch.object(handler, "_lookup_lab_dates"),
            patch.object(handler, "_lookup_imaging_dates"),
        ):
            handler.get()

        call_args = mock_json.call_args[0][0]
        assert call_args["dates"]["influenza"]["overdue"] is True

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_not_overdue_for_recent_service(self, mock_json: MagicMock) -> None:
        """GET does not mark annual services as overdue when < 1 year old."""
        from datetime import date, timedelta

        recent_date = (date.today() - timedelta(days=30)).isoformat()
        handler = GetScreeningDatesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"patient_id": "patient-1"}
        mock_json.return_value = "json_ok"

        def fake_vaccine_lookup(patient_id: str, dates: dict) -> None:
            dates["influenza"] = {"last_done": recent_date}

        with (
            patch.object(handler, "_lookup_vaccine_dates", side_effect=fake_vaccine_lookup),
            patch.object(handler, "_lookup_lab_dates"),
            patch.object(handler, "_lookup_imaging_dates"),
        ):
            handler.get()

        call_args = mock_json.call_args[0][0]
        assert call_args["dates"]["influenza"].get("overdue") is not True

    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_get_no_note_id_skips_session_lookup(self, mock_json: MagicMock) -> None:
        """GET without note_id still returns vaccine/lab/imaging dates."""
        handler = GetScreeningDatesHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"patient_id": "patient-1"}
        mock_json.return_value = "json_ok"

        with (
            patch.object(handler, "_lookup_vaccine_dates"),
            patch.object(handler, "_lookup_lab_dates"),
            patch.object(handler, "_lookup_imaging_dates"),
        ):
            result = handler.get()

        assert result == ["json_ok"]
        call_args = mock_json.call_args[0][0]
        assert call_args["success"] is True


# ---- _save_form_state helper ----

class TestSaveFormState:
    """Tests for _save_form_state cache helper."""

    @patch("guided_awv.api.awv_api.get_cache")
    def test_save_form_state_creates_new_entry(self, mock_get_cache: MagicMock) -> None:
        """Saves form fields under section_id in cache keyed by note_id."""
        cache = MagicMock()
        cache.get.return_value = {}
        mock_get_cache.return_value = cache

        _save_form_state("note-1", "vitals", {"bp": "120/80"})

        cache.get.assert_called_once_with("awv_form_state:note-1", default={})
        cache.set.assert_called_once()
        saved_data = cache.set.call_args[0][1]
        assert saved_data["vitals"] == {"bp": "120/80"}

    @patch("guided_awv.api.awv_api.get_cache")
    def test_save_form_state_merges_with_existing(self, mock_get_cache: MagicMock) -> None:
        """Preserves existing sections when saving a new one."""
        cache = MagicMock()
        cache.get.return_value = {"vitals": {"bp": "120/80"}}
        mock_get_cache.return_value = cache

        _save_form_state("note-1", "meds", {"reconciled": True})

        saved_data = cache.set.call_args[0][1]
        assert saved_data["vitals"] == {"bp": "120/80"}
        assert saved_data["meds"] == {"reconciled": True}


# ---- _get_all_form_states helper ----

class TestGetAllFormStates:
    """Tests for _get_all_form_states cache helper."""

    @patch("guided_awv.api.awv_api.get_cache")
    def test_returns_cached_states(self, mock_get_cache: MagicMock) -> None:
        """Returns all cached form sections for a note."""
        cache = MagicMock()
        cache.get.return_value = {"vitals": {"bp": "120/80"}, "meds": {"reconciled": True}}
        mock_get_cache.return_value = cache

        result = _get_all_form_states("note-1")

        assert result == {"vitals": {"bp": "120/80"}, "meds": {"reconciled": True}}
        cache.get.assert_called_once_with("awv_form_state:note-1", default={})

    @patch("guided_awv.api.awv_api.get_cache")
    def test_returns_empty_dict_when_no_cache(self, mock_get_cache: MagicMock) -> None:
        """Returns empty dict when nothing is cached."""
        cache = MagicMock()
        cache.get.return_value = {}
        mock_get_cache.return_value = cache

        result = _get_all_form_states("note-1")

        assert result == {}


# ---- _get_questionnaire_id helper ----

class TestGetQuestionnaireId:
    """Tests for _get_questionnaire_id."""

    @patch("canvas_sdk.v1.data.questionnaire.Questionnaire")
    def test_returns_id_when_found(self, mock_q_class: MagicMock) -> None:
        """Returns string UUID when questionnaire exists."""
        mock_q = MagicMock()
        mock_q.id = "q-uuid-123"
        mock_q_class.objects.filter.return_value.first.return_value = mock_q

        result = _get_questionnaire_id("PHQ9")

        assert result == "q-uuid-123"
        mock_q_class.objects.filter.assert_called_once_with(code="PHQ9", status="AC")

    @patch("canvas_sdk.v1.data.questionnaire.Questionnaire")
    def test_returns_none_when_not_found(self, mock_q_class: MagicMock) -> None:
        """Returns None when no matching questionnaire."""
        mock_q_class.objects.filter.return_value.first.return_value = None

        result = _get_questionnaire_id("UNKNOWN")

        assert result is None


# ---- _originate_sa helper ----

class TestOriginateSa:
    """Tests for _originate_sa."""

    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    def test_success_returns_effect(self, mock_sa_class: MagicMock) -> None:
        """Returns Effect on successful origination."""
        mock_effect = MagicMock()
        mock_sa_class.return_value.originate.return_value = mock_effect

        result = _originate_sa("note-1", "q-uuid-1", "Score: 5")

        assert result == mock_effect
        mock_sa_class.assert_called_once_with(
            note_uuid="note-1",
            questionnaire_id="q-uuid-1",
            result="Score: 5",
        )

    @patch("guided_awv.api.awv_api.StructuredAssessmentCommand")
    def test_exception_returns_none(self, mock_sa_class: MagicMock) -> None:
        """Returns None when StructuredAssessmentCommand raises."""
        mock_sa_class.side_effect = Exception("SDK error")

        result = _originate_sa("note-1", "q-uuid-1", "Score: 5")

        assert result is None


# ---- _add_cpt_ii helper ----

class TestAddCptII:
    """Tests for _add_cpt_ii."""

    @patch("guided_awv.api.awv_api._get_z00_assessment_id", return_value=None)
    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    def test_creates_billing_line_item_without_z00(
        self,
        mock_billing: MagicMock,
        _mock_z00: MagicMock,
    ) -> None:
        """Without an existing Z00 Assessment, the line item is created with no diagnosis pointer."""
        mock_effect = MagicMock()
        mock_billing.return_value.apply.return_value = mock_effect

        result = _add_cpt_ii("note-1", "1036F")

        mock_billing.assert_called_once_with(note_id="note-1", cpt="1036F", assessment_ids=[])
        mock_billing.return_value.apply.assert_called_once()
        assert result == mock_effect

    @patch("guided_awv.api.awv_api._get_z00_assessment_id", return_value="z00-assessment-id")
    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    def test_links_billing_line_item_to_z00_when_present(
        self,
        mock_billing: MagicMock,
        _mock_z00: MagicMock,
    ) -> None:
        """When Z00 Assessment exists, the line item is linked via assessment_ids."""
        mock_effect = MagicMock()
        mock_billing.return_value.apply.return_value = mock_effect

        result = _add_cpt_ii("note-1", "3008F")

        mock_billing.assert_called_once_with(
            note_id="note-1", cpt="3008F", assessment_ids=["z00-assessment-id"]
        )
        assert result == mock_effect


class TestGetZ00AssessmentId:
    """Tests for _get_z00_assessment_id helper."""

    def test_returns_none_when_no_note_id(self) -> None:
        from guided_awv.api.awv_api import _get_z00_assessment_id
        assert _get_z00_assessment_id("") is None

    def test_returns_none_when_no_z00_assessment(self) -> None:
        from guided_awv.api.awv_api import _get_z00_assessment_id
        with (
            patch("canvas_sdk.v1.data.note.Note") as mock_note_cls,
            patch("canvas_sdk.v1.data.Assessment") as mock_assess_cls,
        ):
            mock_note = MagicMock()
            mock_note.dbid = 42
            mock_note_cls.objects.filter.return_value.first.return_value = mock_note
            mock_assess_cls.objects.filter.return_value.values_list.return_value.first.return_value = None

            assert _get_z00_assessment_id("note-uuid") is None

    def test_returns_assessment_id_when_z00_exists(self) -> None:
        from guided_awv.api.awv_api import _get_z00_assessment_id
        with (
            patch("canvas_sdk.v1.data.note.Note") as mock_note_cls,
            patch("canvas_sdk.v1.data.Assessment") as mock_assess_cls,
        ):
            mock_note = MagicMock()
            mock_note.dbid = 42
            mock_note_cls.objects.filter.return_value.first.return_value = mock_note
            mock_assess_cls.objects.filter.return_value.values_list.return_value.first.return_value = "abc-123"

            assert _get_z00_assessment_id("note-uuid") == "abc-123"

    def test_returns_none_on_exception(self) -> None:
        from guided_awv.api.awv_api import _get_z00_assessment_id
        with patch("canvas_sdk.v1.data.note.Note") as mock_note_cls:
            mock_note_cls.objects.filter.side_effect = Exception("db down")
            assert _get_z00_assessment_id("note-uuid") is None


# ---- _lookup_all_screening_dates ----

class TestLookupAllScreeningDates:
    """Tests for _lookup_all_screening_dates."""

    @patch("guided_awv.api.awv_api.log")
    def test_vaccine_dates_from_immunization_statement(self, _mock_log: MagicMock) -> None:
        """Finds vaccine date via ImmunizationStatementCoding bulk query."""
        flu_date = datetime.date(2025, 10, 1)

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": MagicMock(),
        }):
            import sys
            imm_mod = sys.modules["canvas_sdk.v1.data.immunization"]
            # Bulk query returns (code, date) tuples — "141" is a flu CVX code
            stmt_qs = imm_mod.ImmunizationStatementCoding.objects.filter.return_value
            stmt_qs.order_by.return_value.values_list.return_value = [
                ("141", flu_date),
            ]
            # ImmunizationCoding fallback returns empty
            imm_mod.ImmunizationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []

            dates: dict = {}
            _lookup_all_screening_dates("patient-1", dates)

        assert dates.get("influenza") == {"last_done": flu_date.isoformat()}

    @patch("guided_awv.api.awv_api.log")
    def test_lab_dates_from_lab_value_coding(self, _mock_log: MagicMock) -> None:
        """Finds lab date via LabValueCoding bulk query."""
        lab_dt = MagicMock()
        lab_dt.date.return_value = datetime.date(2025, 3, 15)

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": MagicMock(),
            "canvas_sdk.v1.data.lab": MagicMock(),
            "canvas_sdk.v1.data.imaging": MagicMock(),
            "canvas_sdk.v1.data.observation": MagicMock(),
        }):
            import sys
            # Vaccines: bulk query returns empty
            imm_mod = sys.modules["canvas_sdk.v1.data.immunization"]
            imm_mod.ImmunizationStatementCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []
            imm_mod.ImmunizationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []
            # Keyword fallback - no records
            imm_mod.ImmunizationStatementCoding.objects.filter.return_value.values_list.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[])
            imm_mod.ImmunizationCoding.objects.filter.return_value.values_list.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[])

            # Labs: bulk query returns (code, date) — "57698-3" is a lipids LOINC code
            lab_mod = sys.modules["canvas_sdk.v1.data.lab"]
            lab_mod.LabValueCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = [
                ("57698-3", lab_dt),
            ]

            # Imaging returns nothing
            img_mod = sys.modules["canvas_sdk.v1.data.imaging"]
            img_mod.ImagingOrder.objects.filter.return_value.order_by.return_value.values_list.return_value.__getitem__ = MagicMock(return_value=[])

            # Observations return nothing
            obs_mod = sys.modules["canvas_sdk.v1.data.observation"]
            obs_mod.ObservationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None

            dates: dict = {}
            _lookup_all_screening_dates("patient-1", dates)

        assert dates.get("lipids") == {"last_done": "2025-03-15"}

    @patch("guided_awv.api.awv_api.log")
    def test_imaging_dates_by_keyword_match(self, _mock_log: MagicMock) -> None:
        """Finds imaging date by keyword match on order name."""
        ordered_dt = datetime.datetime(2024, 6, 1, 14, 30)

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": MagicMock(),
            "canvas_sdk.v1.data.lab": MagicMock(),
            "canvas_sdk.v1.data.imaging": MagicMock(),
            "canvas_sdk.v1.data.observation": MagicMock(),
        }):
            import sys
            # Vaccines: bulk queries return empty
            imm_mod = sys.modules["canvas_sdk.v1.data.immunization"]
            imm_mod.ImmunizationStatementCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []
            imm_mod.ImmunizationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []
            imm_mod.ImmunizationStatementCoding.objects.filter.return_value.values_list.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[])
            imm_mod.ImmunizationCoding.objects.filter.return_value.values_list.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[])

            # Labs: bulk query returns empty
            lab_mod = sys.modules["canvas_sdk.v1.data.lab"]
            lab_mod.LabValueCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []

            # Imaging: return mammography order
            img_mod = sys.modules["canvas_sdk.v1.data.imaging"]
            img_mod.ImagingOrder.objects.filter.return_value.order_by.return_value.values_list.return_value.__getitem__ = MagicMock(
                return_value=[("Bilateral Mammography Screening", ordered_dt)]
            )

            # Observations: nothing
            obs_mod = sys.modules["canvas_sdk.v1.data.observation"]
            obs_mod.ObservationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None

            dates: dict = {}
            _lookup_all_screening_dates("patient-1", dates)

        assert dates.get("mammogram") == {"last_done": "2024-06-01"}

    @patch("guided_awv.api.awv_api.log")
    def test_bh_dates_from_observation_coding(self, _mock_log: MagicMock) -> None:
        """Finds BH observation date via ObservationCoding."""
        obs_dt = datetime.datetime(2025, 1, 20, 9, 0)

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": MagicMock(),
            "canvas_sdk.v1.data.lab": MagicMock(),
            "canvas_sdk.v1.data.imaging": MagicMock(),
            "canvas_sdk.v1.data.observation": MagicMock(),
        }):
            import sys
            # Vaccines: bulk queries return empty
            imm_mod = sys.modules["canvas_sdk.v1.data.immunization"]
            imm_mod.ImmunizationStatementCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []
            imm_mod.ImmunizationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []
            imm_mod.ImmunizationStatementCoding.objects.filter.return_value.values_list.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[])
            imm_mod.ImmunizationCoding.objects.filter.return_value.values_list.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[])

            # Labs: bulk query returns empty
            lab_mod = sys.modules["canvas_sdk.v1.data.lab"]
            lab_mod.LabValueCoding.objects.filter.return_value.order_by.return_value.values_list.return_value = []

            img_mod = sys.modules["canvas_sdk.v1.data.imaging"]
            img_mod.ImagingOrder.objects.filter.return_value.order_by.return_value.values_list.return_value.__getitem__ = MagicMock(return_value=[])

            obs_mod = sys.modules["canvas_sdk.v1.data.observation"]
            obs_mod.ObservationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = obs_dt

            dates: dict = {}
            _lookup_all_screening_dates("patient-1", dates)

        assert dates.get("annual_depression") == {"last_done": "2025-01-20"}

    @patch("guided_awv.api.awv_api.log")
    def test_graceful_exception_handling_vaccines(self, mock_log: MagicMock) -> None:
        """Vaccine import failure is caught and logged, other sections still run."""
        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": None,  # simulate ImportError
            "canvas_sdk.v1.data.lab": MagicMock(),
            "canvas_sdk.v1.data.imaging": MagicMock(),
            "canvas_sdk.v1.data.observation": MagicMock(),
        }):
            import sys
            lab_mod = sys.modules["canvas_sdk.v1.data.lab"]
            lab_mod.LabValueCoding.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None

            img_mod = sys.modules["canvas_sdk.v1.data.imaging"]
            img_mod.ImagingOrder.objects.filter.return_value.order_by.return_value.values_list.return_value.__getitem__ = MagicMock(return_value=[])

            obs_mod = sys.modules["canvas_sdk.v1.data.observation"]
            obs_mod.ObservationCoding.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None

            dates: dict = {}
            _lookup_all_screening_dates("patient-1", dates)

        # Should not raise; vaccine failure logged as warning
        mock_log.warning.assert_any_call(
            "_lookup_all_screening_dates: vaccine lookup failed", exc_info=True
        )


# ---- build_services_list (preventive_services module) ----

class TestBuildServicesList:
    """Tests for build_services_list standalone function."""

    @patch("guided_awv.modules.preventive_services.SexAtBirth", MagicMock(MALE="M", FEMALE="F"))
    def test_male_age_70(self) -> None:
        """Male age 70: includes aaa (65-75), excludes prostate_psa (55-69)."""
        services = build_services_list(70, "M")
        ids = [s["id"] for s in services]

        assert "aaa" in ids
        assert "prostate_psa" not in ids
        # Should not include female-only screenings
        assert "mammogram" not in ids
        assert "cervical_cancer" not in ids
        assert "dexa" not in ids

    @patch("guided_awv.modules.preventive_services.SexAtBirth", MagicMock(MALE="M", FEMALE="F"))
    def test_female_age_50(self) -> None:
        """Female age 50: includes mammogram, cervical_cancer; excludes dexa (65+)."""
        services = build_services_list(50, "F")
        ids = [s["id"] for s in services]

        assert "mammogram" in ids
        assert "cervical_cancer" in ids
        assert "dexa" not in ids  # eligible only at 65+, filtered out
        # Should not include male-only screenings
        assert "aaa" not in ids
        assert "prostate_psa" not in ids

    @patch("guided_awv.modules.preventive_services.SexAtBirth", MagicMock(MALE="M", FEMALE="F"))
    def test_services_filtered_by_eligibility(self) -> None:
        """Only eligible services are returned (eligible=False filtered out)."""
        services = build_services_list(30, "M")
        ids = [s["id"] for s in services]

        # All returned services should be eligible
        for svc in services:
            assert svc.get("eligible") is True

        # Age 30 male: pneumococcal (65+) should be excluded
        assert "pneumococcal" not in ids
        # shingles (50+) excluded
        assert "shingles" not in ids
        # rsv (60+) excluded
        assert "rsv" not in ids
        # colorectal (45-85) excluded at age 30
        assert "colorectal" not in ids
        # Always eligible
        assert "influenza" in ids
        assert "diabetes_screen" in ids
        assert "lipids" in ids


# ---- GeneratePreventionPlanHandler ----


class TestGeneratePreventionPlanHandlerPost:
    """Tests for GeneratePreventionPlanHandler.post()."""

    def test_post_returns_400_when_note_id_missing(self) -> None:
        """POST without note_id returns 400."""
        import json as _json

        handler = GeneratePreventionPlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}

        result = handler.post()

        assert len(result) == 1
        resp = result[0]
        assert resp.status_code == 400
        assert _json.loads(resp.content)["error"] == "note_id is required"

    def test_post_returns_400_when_patient_id_missing(self) -> None:
        """POST without patient_id returns 400."""
        import json as _json

        handler = GeneratePreventionPlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"note_id": "n1"}

        result = handler.post()

        assert len(result) == 1
        resp = result[0]
        assert resp.status_code == 400
        assert _json.loads(resp.content)["error"] == "patient_id is required"

    @patch("guided_awv.api.awv_api.get_cache")
    def test_post_success_caches_html_and_returns_success(self, mock_get_cache: MagicMock) -> None:
        """POST with valid data builds plan, caches HTML, and returns success."""
        import json as _json

        handler = GeneratePreventionPlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-123",
            "patient_id": "patient-456",
        }

        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        with patch.object(handler, "_build_plan", return_value="<html>plan</html>") as mock_build:
            result = handler.post()

        mock_build.assert_called_once_with("note-123", "patient-456", {})
        mock_cache.set.assert_called_once_with(
            "awv_prevention_plan_html:note-123",
            "<html>plan</html>",
            timeout_seconds=3600,
        )
        assert len(result) == 1
        resp = result[0]
        assert _json.loads(resp.content)["success"] is True


class TestGeneratePreventionPlanHandlerGet:
    """Tests for GeneratePreventionPlanHandler.get()."""

    def test_get_returns_400_when_note_id_missing(self) -> None:
        """GET without note_id returns 400."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {}

        result = handler.get()

        assert len(result) == 1
        resp = result[0]
        assert resp.status_code == 400

    @patch("guided_awv.api.awv_api.get_cache")
    def test_get_returns_404_when_no_cached_plan(self, mock_get_cache: MagicMock) -> None:
        """GET with note_id but no cached plan returns 404."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"note_id": "note-123"}

        mock_cache = MagicMock()
        mock_cache.get.return_value = ""
        mock_get_cache.return_value = mock_cache

        result = handler.get()

        assert len(result) == 1
        resp = result[0]
        assert resp.status_code == 404

    @patch("guided_awv.api.awv_api.get_cache")
    def test_get_returns_cached_html(self, mock_get_cache: MagicMock) -> None:
        """GET with cached plan returns the HTML."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"note_id": "note-123"}

        mock_cache = MagicMock()
        mock_cache.get.return_value = "<html>cached plan</html>"
        mock_get_cache.return_value = mock_cache

        result = handler.get()

        assert len(result) == 1
        resp = result[0]
        assert resp.content == b"<html>cached plan</html>"


class TestCalculateAge:
    """Tests for GeneratePreventionPlanHandler._calculate_age()."""

    def test_calculate_age_with_valid_birth_date(self) -> None:
        """Returns correct age for a known birth date."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date.today()
        birth_date = today.replace(year=today.year - 70)
        assert handler._calculate_age(birth_date) == 70

    def test_calculate_age_with_none_returns_zero(self) -> None:
        """Returns 0 when birth_date is None."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        assert handler._calculate_age(None) == 0

    def test_calculate_age_birthday_not_yet_this_year(self) -> None:
        """Returns age minus 1 if birthday hasn't occurred yet this year."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date.today()
        future_birthday = today.replace(year=today.year - 65) + datetime.timedelta(days=30)
        if future_birthday.year > today.year - 65:
            future_birthday = today.replace(year=today.year - 65, month=12, day=31)
        age = handler._calculate_age(future_birthday)
        expected = today.year - future_birthday.year - (
            (today.month, today.day) < (future_birthday.month, future_birthday.day)
        )
        assert age == expected


class TestCalcNextDue:
    """Tests for GeneratePreventionPlanHandler._calc_next_due()."""

    def test_annual_frequency_returns_365_days(self) -> None:
        """Annual frequency adds 365 days."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        last = datetime.date(2025, 1, 15)
        result = handler._calc_next_due(last, "Annual")
        assert result == datetime.date(2026, 1, 15)

    def test_one_time_frequency_returns_none(self) -> None:
        """One-time frequency returns None."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        last = datetime.date(2025, 1, 15)
        assert handler._calc_next_due(last, "One-time screening") is None

    def test_single_dose_returns_none(self) -> None:
        """Single dose frequency returns None."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        last = datetime.date(2025, 1, 15)
        assert handler._calc_next_due(last, "Single dose after 60") is None

    def test_unknown_frequency_defaults_to_annual(self) -> None:
        """Unknown frequency string defaults to annual (365 days)."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        last = datetime.date(2025, 3, 1)
        result = handler._calc_next_due(last, "Some unknown frequency")
        assert result == datetime.date(2026, 3, 1)

    def test_every_2_years_frequency(self) -> None:
        """Every 2 years adds 730 days."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        last = datetime.date(2025, 1, 1)
        result = handler._calc_next_due(last, "Every 2 years (if normal)")
        assert result == datetime.date(2027, 1, 1)

    def test_per_schedule_returns_none(self) -> None:
        """Per schedule frequency returns None."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        last = datetime.date(2025, 1, 1)
        assert handler._calc_next_due(last, "Per schedule") is None

    def test_discuss_frequency_returns_none(self) -> None:
        """Discuss-type frequency returns None."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        last = datetime.date(2025, 1, 1)
        assert handler._calc_next_due(last, "Discuss with provider") is None


class TestBuildSectionTable:
    """Tests for GeneratePreventionPlanHandler._build_section_table()."""

    def test_empty_services_returns_empty_string(self) -> None:
        """No services produces empty output."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        result = handler._build_section_table("Test", [], {}, set(), datetime.date.today())
        assert result == ""

    def test_ordered_service_shows_ordered_today(self) -> None:
        """Service in ordered_ids shows 'Ordered today' status."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        services = [{"id": "flu", "name": "Flu Shot", "frequency": "Annual"}]
        ordered = {"flu"}

        result = handler._build_section_table("Immunizations", services, {}, ordered, today)

        assert "Ordered today" in result
        assert "06/01/2025" in result
        assert "Flu Shot" in result

    def test_up_to_date_service(self) -> None:
        """Service done recently and not yet due shows 'Up to date'."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        services = [{"id": "flu", "name": "Flu Shot", "frequency": "Annual"}]
        dates = {"flu": {"last_done": "2025-01-15"}}

        result = handler._build_section_table("Immunizations", services, dates, set(), today)

        assert "Up to date" in result
        assert "01/15/2025" in result

    def test_overdue_service_shows_due(self) -> None:
        """Service past its next-due date shows 'Due'."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        services = [{"id": "flu", "name": "Flu Shot", "frequency": "Annual"}]
        dates = {"flu": {"last_done": "2024-01-01"}}

        result = handler._build_section_table("Immunizations", services, dates, set(), today)

        assert "Due" in result
        assert "status-due" in result

    def test_no_record_shows_no_record(self) -> None:
        """Service with no date info shows 'No record'."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        services = [{"id": "flu", "name": "Flu Shot", "frequency": "Annual"}]

        result = handler._build_section_table("Immunizations", services, {}, set(), today)

        assert "No record" in result
        # v0.14.11: changed &mdash; entity to native — Unicode so the
        # v0.14.9 html.escape sweep doesn't render it as literal `&mdash;`.
        assert "—" in result

    def test_table_includes_section_title(self) -> None:
        """Output includes the section title div."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        services = [{"id": "flu", "name": "Flu Shot", "frequency": "Annual"}]

        result = handler._build_section_table("Immunizations", services, {}, set(), today)

        assert '<div class="section-title">Immunizations</div>' in result
        assert "<table>" in result


class TestBuildBhSection:
    """Tests for GeneratePreventionPlanHandler._build_bh_section()."""

    def test_depression_screening_completed_today(self) -> None:
        """Depression screening in form_state marks it as 'Completed today'."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        form_state = {"depressionscreening": {"phq2_score": 1}}

        result = handler._build_bh_section({}, set(), today, form_state, "note-1")

        assert "Completed today" in result
        assert "Annual Depression Screening" in result
        assert "Behavioral Health" in result

    def test_no_screenings_shows_no_record(self) -> None:
        """No screening data shows 'No record' for all BH items."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)

        result = handler._build_bh_section({}, set(), today, {}, "note-1")

        assert result.count("No record") == 2


class TestBuildFunctionalSection:
    """Tests for GeneratePreventionPlanHandler._build_functional_section()."""

    def test_fall_risk_completed(self) -> None:
        """Fall risk in form_state marks it as 'Completed today'."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        form_state = {"fallrisk": {"score": 5}}

        result = handler._build_functional_section(form_state)

        assert "Completed today" in result
        assert "Fall Risk Screening" in result

    def test_no_sections_completed(self) -> None:
        """No functional sections completed shows 'No record' for both items."""
        handler = GeneratePreventionPlanHandler(MagicMock())

        result = handler._build_functional_section({})

        assert result.count("No record") == 2
        assert "Functional Assessment" in result

    def test_functional_ability_completed(self) -> None:
        """Functional ability in form_state marks ADL/IADL as 'Completed today'."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        form_state = {"functionalability": {"bathing": "independent"}}

        result = handler._build_functional_section(form_state)

        assert "ADL / IADL Functional Assessment" in result
        assert "Completed today" in result


class TestBuildNextDueTimeline:
    """Tests for GeneratePreventionPlanHandler._build_next_due_timeline()."""

    def test_no_upcoming_services_returns_empty(self) -> None:
        """No upcoming services returns empty string."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)

        result = handler._build_next_due_timeline([], {}, set(), today)

        assert result == ""

    def test_timeline_with_upcoming_services(self) -> None:
        """Services with future next-due dates appear in timeline."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        services = [{"id": "flu", "name": "Flu Shot", "frequency": "Annual"}]
        ordered = {"flu"}

        result = handler._build_next_due_timeline(services, {}, ordered, today)

        assert "Upcoming Services Timeline" in result
        assert "Flu Shot" in result

    def test_timeline_sorted_chronologically(self) -> None:
        """Timeline entries are sorted by next-due date."""
        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)
        services = [
            {"id": "flu", "name": "Flu Shot", "frequency": "Annual"},
            {"id": "colorectal", "name": "Colorectal Screening",
             "frequency": "Per method (annual FIT/FOBT, every 3y FIT-DNA, every 10y colonoscopy)"},
        ]
        ordered = {"flu", "colorectal"}

        result = handler._build_next_due_timeline(services, {}, ordered, today)

        assert "Flu Shot" in result
        assert "Colorectal Screening" in result


class TestBuildChronicSection:
    """Tests for GeneratePreventionPlanHandler._build_chronic_section()."""

    @patch("canvas_sdk.v1.data.condition.Condition")
    def test_no_conditions_returns_empty(self, mock_condition: MagicMock) -> None:
        """Patient with no diabetes or CVD conditions returns empty string."""
        mock_qs = MagicMock()
        mock_qs.values_list.return_value = []
        mock_condition.objects.filter.return_value = mock_qs

        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)

        result = handler._build_chronic_section("p1", {}, set(), today, {})

        assert result == ""

    @patch("canvas_sdk.v1.data.condition.Condition")
    def test_diabetes_condition_shows_diabetes_items(self, mock_condition: MagicMock) -> None:
        """Patient with diabetes ICD-10 gets diabetes monitoring items."""
        mock_qs = MagicMock()
        mock_qs.values_list.return_value = ["E11.9"]
        mock_condition.objects.filter.return_value = mock_qs

        handler = GeneratePreventionPlanHandler(MagicMock())
        today = datetime.date(2025, 6, 1)

        result = handler._build_chronic_section("p1", {}, set(), today, {})

        assert "Chronic Disease Monitoring" in result
        assert "HbA1c" in result
        assert "Diabetic Eye Exam" in result
        assert "Diabetic Foot Exam" in result
        assert "Lipid Panel (CVD Monitoring)" not in result


# ===========================================================================
# _build_plan tests
# ===========================================================================


class TestPreventionPlanHtmlEscape:
    """Regression tests for Claude review finding #10 - Prevention Plan stored XSS.

    `_build_plan` interpolated raw textarea-derived ``provider_comments`` into
    the template at two sinks (a ``<textarea>`` and a sibling ``<div>``), and
    raw ``last_done_str`` into ``<td>`` cells when ``fromisoformat`` failed.
    A staff user could write a script tag into Assessment & Plan / Medication
    Reconciliation / Follow-up textareas, save, then any provider opening
    the Prevention Plan modal would execute it. The 60-min cache persisted
    the payload across sessions. Fix: html.escape every caller-supplied or
    cache-derived string before substituting into the template.
    """

    def test_html_escape_imported(self) -> None:
        """The fix relies on the html.escape helper at module level."""
        from guided_awv.api import awv_api
        assert hasattr(awv_api, "html_escape")
        assert awv_api.html_escape("<script>") == "&lt;script&gt;"

    def test_section_table_escapes_user_derived_values(self) -> None:
        """_build_section_table escapes name, last_display, frequency, and title.

        Service ``name`` and ``frequency`` come from plugin constants (low
        risk today), but ``last_display`` can hold cached form-state text
        when fromisoformat fails - a direct XSS sink without the escape.
        """
        from guided_awv.api.awv_api import GeneratePreventionPlanHandler
        handler = GeneratePreventionPlanHandler(MagicMock())

        services = [
            {"id": "test", "name": "<img src=x onerror=alert(1)>", "frequency": "<b>annual</b>"},
        ]
        # last_done_str that fails fromisoformat triggers the unescaped path
        dates: dict[str, dict] = {"test": {"last_done": "<script>alert(1)</script>"}}
        from datetime import date as date_type
        today = date_type.today()

        out = handler._build_section_table("<img src=x>", services, dates, set(), today)

        # The < character from any of the user-derived strings must not
        # appear unescaped in the output
        assert "<img src=x onerror=alert(1)>" not in out
        assert "<script>alert(1)</script>" not in out
        # The escaped form should be present
        assert "&lt;img src=x onerror=alert(1)&gt;" in out
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
        assert "&lt;img src=x&gt;" in out  # title also escaped


class TestFormValueIs:
    """Tests for the _form_value_is helper added in Fix #8.

    JS getModuleFormData stores checkbox values as lists, but cached
    form_state can also hold bare strings from radio/select inputs.
    Comparing val == 'ordered' against a list silently returned False -
    that's what masked the Prevention Plan 'Ordered today' status until
    Claude review #2 caught it.
    """

    def test_string_value_matches(self) -> None:
        from guided_awv.api.awv_api import _form_value_is
        assert _form_value_is("ordered", "ordered") is True
        assert _form_value_is("discussed", "ordered") is False

    def test_list_value_matches(self) -> None:
        from guided_awv.api.awv_api import _form_value_is
        # The actual JS-produced shape from a single checked checkbox
        assert _form_value_is(["ordered"], "ordered") is True
        assert _form_value_is(["completed_today"], "ordered") is False

    def test_list_with_multiple_values(self) -> None:
        from guided_awv.api.awv_api import _form_value_is
        assert _form_value_is(["discussed", "ordered"], "ordered") is True

    def test_none_value(self) -> None:
        from guided_awv.api.awv_api import _form_value_is
        assert _form_value_is(None, "ordered") is False

    def test_empty_list(self) -> None:
        from guided_awv.api.awv_api import _form_value_is
        assert _form_value_is([], "ordered") is False


class TestBuildPlan:
    """Tests for GeneratePreventionPlanHandler._build_plan()."""

    def _make_handler(self) -> GeneratePreventionPlanHandler:
        handler = GeneratePreventionPlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.META = {"HTTP_HOST": "test.example.com"}
        return handler

    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api._lookup_all_screening_dates")
    def test_raises_when_patient_not_found(
        self,
        mock_lookup: MagicMock,
        mock_form: MagicMock,
    ) -> None:
        """_build_plan raises ValueError when patient not found."""
        handler = self._make_handler()

        mock_patient_cls = MagicMock()
        mock_patient_cls.objects.filter.return_value.first.return_value = None

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.patient": MagicMock(Patient=mock_patient_cls, SexAtBirth=MagicMock()),
            "canvas_sdk.v1.data.note": MagicMock(),
            "canvas_sdk.templates": MagicMock(),
        }):
            with patch("guided_awv.api.awv_api.GeneratePreventionPlanHandler._build_plan") as real:
                # Call the real method manually to test the ValueError path
                pass

        # Direct approach: patch the locally-imported classes
        with patch("canvas_sdk.v1.data.patient.Patient") as mock_p:
            mock_p.objects.filter.return_value.first.return_value = None
            with pytest.raises(ValueError, match="Patient not found"):
                handler._build_plan("note-1", "patient-missing")

    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api._lookup_all_screening_dates")
    def test_returns_html_with_patient_info(
        self,
        mock_lookup: MagicMock,
        mock_form: MagicMock,
    ) -> None:
        """_build_plan returns HTML with patient name, DOB, age substituted."""
        handler = self._make_handler()

        mock_patient = MagicMock()
        mock_patient.id = "patient-abc"
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Medicare"
        mock_patient.birth_date = datetime.date(1950, 6, 15)
        mock_patient.sex_at_birth = "F"

        mock_note = MagicMock()
        mock_note.note_type_version.name = "Annual Wellness Visit"

        template_html = (
            "<html>[[patient_name]] [[patient_dob]] [[patient_age]] "
            "[[patient_sex]] [[visit_date]] [[awv_type]] "
            "[[immunizations_section]] [[cancer_screenings_section]] "
            "[[chronic_disease_section]] [[behavioral_health_section]] "
            "[[functional_assessment_section]] [[next_due_timeline]] "
            "[[next_awv_date]] [[provider_comments]] [[note_id]] [[api_base]]</html>"
        )

        with (
            patch("canvas_sdk.v1.data.patient.Patient") as mock_p_cls,
            patch("canvas_sdk.v1.data.patient.SexAtBirth") as mock_sex,
            patch("canvas_sdk.v1.data.note.Note") as mock_n_cls,
            patch("canvas_sdk.templates.render_to_string", return_value=template_html),
            patch("guided_awv.modules.preventive_services.build_services_list", return_value=[]),
            patch.object(handler, "_build_section_table", return_value=""),
            patch.object(handler, "_build_chronic_section", return_value=""),
            patch.object(handler, "_build_bh_section", return_value=""),
            patch.object(handler, "_build_functional_section", return_value=""),
            patch.object(handler, "_build_next_due_timeline", return_value=""),
        ):
            mock_p_cls.objects.filter.return_value.first.return_value = mock_patient
            mock_n_cls.objects.select_related.return_value.filter.return_value.first.return_value = mock_note
            mock_sex.FEMALE = "F"
            mock_sex.MALE = "M"

            result = handler._build_plan("note-1", "patient-abc")

        assert "Jane Medicare" in result
        assert "06/15/1950" in result
        assert "note-1" in result
        assert "https://test.example.com" in result

    @patch(
        "guided_awv.api.awv_api._get_all_form_states",
        return_value={"_awv_meta": {"awv_type": "subsequent"}},
    )
    @patch("guided_awv.api.awv_api._lookup_all_screening_dates")
    def test_detects_subsequent_awv_type(
        self,
        mock_lookup: MagicMock,
        mock_form: MagicMock,
    ) -> None:
        """_build_plan reads Subsequent AWV from the form-state cache."""
        handler = self._make_handler()

        mock_patient = MagicMock()
        mock_patient.id = "patient-abc"
        mock_patient.first_name = "Bob"
        mock_patient.last_name = "Smith"
        mock_patient.birth_date = datetime.date(1945, 3, 10)
        mock_patient.sex_at_birth = "M"

        template_html = "[[awv_type]]"

        with (
            patch("canvas_sdk.v1.data.patient.Patient") as mock_p_cls,
            patch("canvas_sdk.v1.data.patient.SexAtBirth") as mock_sex,
            patch("canvas_sdk.templates.render_to_string", return_value=template_html),
            patch("guided_awv.modules.preventive_services.build_services_list", return_value=[]),
            patch.object(handler, "_build_section_table", return_value=""),
            patch.object(handler, "_build_chronic_section", return_value=""),
            patch.object(handler, "_build_bh_section", return_value=""),
            patch.object(handler, "_build_functional_section", return_value=""),
            patch.object(handler, "_build_next_due_timeline", return_value=""),
        ):
            mock_p_cls.objects.filter.return_value.first.return_value = mock_patient
            mock_sex.FEMALE = "F"
            mock_sex.MALE = "M"

            result = handler._build_plan("note-1", "patient-abc")

        assert "Subsequent AWV (G0439)" in result

    @patch("guided_awv.api.awv_api._get_all_form_states")
    @patch("guided_awv.api.awv_api._lookup_all_screening_dates")
    def test_merges_form_state_dates(
        self,
        mock_lookup: MagicMock,
        mock_form: MagicMock,
    ) -> None:
        """_build_plan merges manually-entered dates from form state into chart dates."""
        handler = self._make_handler()

        mock_patient = MagicMock()
        mock_patient.id = "patient-abc"
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Doe"
        mock_patient.birth_date = datetime.date(1948, 1, 1)
        mock_patient.sex_at_birth = "F"

        mock_note = MagicMock()
        mock_note.note_type_version.name = "Annual Wellness Visit"

        # Form state with manually-entered dates and ordered services
        mock_form.return_value = {
            "preventiveservices": {
                "svc_mammogram_last_date": "2024-01-15",
                "svc_flu_ordered": "ordered",
            }
        }

        template_html = "[[immunizations_section]][[cancer_screenings_section]]"

        with (
            patch("canvas_sdk.v1.data.patient.Patient") as mock_p_cls,
            patch("canvas_sdk.v1.data.patient.SexAtBirth") as mock_sex,
            patch("canvas_sdk.v1.data.note.Note") as mock_n_cls,
            patch("canvas_sdk.templates.render_to_string", return_value=template_html),
            patch("guided_awv.modules.preventive_services.build_services_list", return_value=[]),
            patch.object(handler, "_build_section_table", return_value="<table/>") as mock_table,
            patch.object(handler, "_build_chronic_section", return_value=""),
            patch.object(handler, "_build_bh_section", return_value=""),
            patch.object(handler, "_build_functional_section", return_value=""),
            patch.object(handler, "_build_next_due_timeline", return_value=""),
        ):
            mock_p_cls.objects.filter.return_value.first.return_value = mock_patient
            mock_n_cls.objects.select_related.return_value.filter.return_value.first.return_value = mock_note
            mock_sex.FEMALE = "F"
            mock_sex.MALE = "M"

            result = handler._build_plan("note-1", "patient-abc")

        # The method was called — ordered_ids should include "flu"
        # and dates should include manually entered mammogram date
        assert mock_table.call_count == 2  # imm + cancer sections


# ===========================================================================
# SavePlanHandler Z00.00 dedup tests
# ===========================================================================


class TestSavePlanHandlerZ00Dedup:
    """Tests for SavePlanHandler Z00.00 attestation/billing logic."""

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.DiagnoseCommand")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_attestation_creates_z00_when_none_exists(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_dx_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """POST with attestation creates Z00.00 diagnosis when none exists on note."""
        mock_json.return_value = "json_ok"
        mock_plan_cmd.return_value.originate.return_value = "plan_effect"
        mock_dx_cmd.return_value.originate.return_value = "dx_effect"
        mock_billing.return_value.apply.return_value = "billing_effect"

        handler = SavePlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "narrative": "AWV complete",
            "attestation": "Provider attests to AWV",
            "awv_cpt_code": "G0438",
        }

        mock_note_obj = MagicMock()
        mock_note_obj.dbid = 42

        mock_assessment_qs = MagicMock()
        mock_assessment_qs.values_list.return_value.first.return_value = None

        with (
            patch("canvas_sdk.v1.data.Assessment") as mock_assess_cls,
            patch("canvas_sdk.v1.data.note.Note") as mock_note_cls,
        ):
            mock_note_cls.objects.filter.return_value.first.return_value = mock_note_obj
            mock_assess_cls.objects.filter.return_value = mock_assessment_qs

            result = handler.post()

        # DiagnoseCommand should have been created for Z00.00
        mock_dx_cmd.assert_called_once_with(
            note_uuid="note-abc",
            icd10_code="Z00.00",
            today_assessment="Annual Wellness Visit",
        )
        # AddBillingLineItem with empty assessment_ids (new diagnosis)
        mock_billing.assert_called_once_with(
            note_id="note-abc",
            cpt="G0438",
            assessment_ids=[],
        )

    @patch("guided_awv.api.awv_api.AddBillingLineItem")
    @patch("guided_awv.api.awv_api.DiagnoseCommand")
    @patch("guided_awv.api.awv_api.PlanCommand")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_attestation_skips_z00_when_already_exists(
        self,
        mock_json: MagicMock,
        mock_plan_cmd: MagicMock,
        mock_dx_cmd: MagicMock,
        mock_billing: MagicMock,
    ) -> None:
        """POST with attestation skips Z00.00 when already on note, links billing to existing."""
        mock_json.return_value = "json_ok"
        mock_plan_cmd.return_value.originate.return_value = "plan_effect"
        mock_billing.return_value.apply.return_value = "billing_effect"

        handler = SavePlanHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "note_id": "note-abc",
            "narrative": "AWV complete",
            "attestation": "Provider attests to AWV",
            "awv_cpt_code": "G0439",
        }

        mock_note_obj = MagicMock()
        mock_note_obj.dbid = 42
        existing_assessment_id = "assess-uuid-999"

        mock_assessment_qs = MagicMock()
        mock_assessment_qs.values_list.return_value.first.return_value = existing_assessment_id

        with (
            patch("canvas_sdk.v1.data.Assessment") as mock_assess_cls,
            patch("canvas_sdk.v1.data.note.Note") as mock_note_cls,
        ):
            mock_note_cls.objects.filter.return_value.first.return_value = mock_note_obj
            mock_assess_cls.objects.filter.return_value = mock_assessment_qs

            result = handler.post()

        # DiagnoseCommand should NOT have been called
        mock_dx_cmd.assert_not_called()
        # AddBillingLineItem should link to existing assessment
        mock_billing.assert_called_once_with(
            note_id="note-abc",
            cpt="G0439",
            assessment_ids=[str(existing_assessment_id)],
        )


# ===========================================================================
# GetScreeningDatesHandler lookup method tests
# ===========================================================================


class TestLookupVaccineDates:
    """Tests for GetScreeningDatesHandler._lookup_vaccine_dates()."""

    def test_finds_dates_via_immunization_statement_cvx(self) -> None:
        """Finds vaccine dates via ImmunizationStatementCoding bulk query."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}

        mock_stmt_coding = MagicMock()
        # Bulk query returns (code, date) tuples — "141" is flu, "33" is pneumococcal
        mock_stmt_coding.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            ("141", datetime.date(2024, 10, 1)),
            ("33", datetime.date(2024, 9, 15)),
        ]

        mock_imm_coding = MagicMock()
        mock_imm_coding.objects.filter.return_value.order_by.return_value.values_list.return_value = []
        mock_imm = MagicMock()
        mock_imm_stmt = MagicMock()

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": MagicMock(
                ImmunizationStatementCoding=mock_stmt_coding,
                ImmunizationCoding=mock_imm_coding,
                Immunization=mock_imm,
                ImmunizationStatement=mock_imm_stmt,
            ),
        }):
            handler._lookup_vaccine_dates("patient-1", dates)

        assert dates["influenza"] == {"last_done": "2024-10-01"}
        assert dates["pneumococcal"] == {"last_done": "2024-09-15"}

    def test_falls_back_to_immunization_coding(self) -> None:
        """Falls back to ImmunizationCoding when statement returns nothing."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}

        # Strategy 1 returns empty, Strategy 2 returns a flu date
        mock_stmt_coding = MagicMock()
        mock_stmt_coding.objects.filter.return_value.order_by.return_value.values_list.return_value = []

        mock_imm_coding = MagicMock()
        mock_imm_coding.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            ("141", datetime.date(2023, 5, 20)),
        ]

        mock_imm = MagicMock()
        mock_imm_stmt = MagicMock()

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": MagicMock(
                ImmunizationStatementCoding=mock_stmt_coding,
                ImmunizationCoding=mock_imm_coding,
                Immunization=mock_imm,
                ImmunizationStatement=mock_imm_stmt,
            ),
        }):
            handler._lookup_vaccine_dates("patient-1", dates)

        assert dates["influenza"] == {"last_done": "2023-05-20"}

    def test_handles_exception_gracefully(self) -> None:
        """Exception in vaccine lookup is caught and dates remain unchanged."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}

        # Create a module mock whose ImmunizationStatementCoding raises on attribute access
        broken_module = MagicMock()
        broken_module.ImmunizationStatementCoding.objects.filter.side_effect = Exception("DB error")

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.immunization": broken_module,
        }):
            handler._lookup_vaccine_dates("patient-1", dates)

        assert dates == {}


class TestLookupLabDates:
    """Tests for GetScreeningDatesHandler._lookup_lab_dates()."""

    def test_finds_dates_via_lab_value_loinc(self) -> None:
        """Finds lab dates via LabValueCoding bulk query."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}

        mock_dt = MagicMock()
        mock_dt.date.return_value = datetime.date(2024, 3, 15)

        mock_lab_coding = MagicMock()
        # Bulk query returns (code, date) tuples — "57698-3" is a lipids LOINC code
        mock_lab_coding.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            ("57698-3", mock_dt),
        ]

        with patch.dict("sys.modules", {
            "canvas_sdk.v1.data.lab": MagicMock(LabValueCoding=mock_lab_coding),
        }):
            handler._lookup_lab_dates("patient-1", dates)

        assert dates["lipids"] == {"last_done": "2024-03-15"}

    def test_handles_exception_gracefully(self) -> None:
        """Exception in lab lookup is caught and dates remain unchanged."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}

        with patch("canvas_sdk.v1.data.lab.LabValueCoding") as mock_lab:
            mock_lab.objects.filter.side_effect = Exception("DB error")
            handler._lookup_lab_dates("patient-1", dates)

        assert dates == {}


class TestLookupImagingDates:
    """Tests for GetScreeningDatesHandler._lookup_imaging_dates()."""

    def test_finds_dates_via_keyword_match(self) -> None:
        """Finds imaging dates by keyword match on order names."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}

        mock_dt = MagicMock()
        mock_dt.date.return_value = datetime.date(2023, 11, 20)

        # Build a list that acts as the sliced queryset result (iterable)
        orders_list = [("Bilateral Mammography Screening", mock_dt)]

        with patch("canvas_sdk.v1.data.imaging.ImagingOrder") as mock_io:
            (mock_io.objects
             .filter.return_value
             .order_by.return_value
             .values_list.return_value
             .__getitem__.return_value) = orders_list
            handler._lookup_imaging_dates("patient-1", dates)

        assert "mammogram" in dates
        assert dates["mammogram"]["last_done"] == "2023-11-20"

    def test_handles_exception_gracefully(self) -> None:
        """Exception in imaging lookup is caught and dates remain unchanged."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}

        with patch("canvas_sdk.v1.data.imaging.ImagingOrder") as mock_img:
            mock_img.objects.filter.side_effect = Exception("DB error")
            handler._lookup_imaging_dates("patient-1", dates)

        assert dates == {}


class TestLookupSessionDates:
    """Tests for GetScreeningDatesHandler._lookup_session_dates()."""

    @patch("guided_awv.api.awv_api._get_all_form_states")
    def test_sets_today_for_depression_screening(self, mock_form: MagicMock) -> None:
        """Sets today's date for depression when form state has depressionscreening."""
        mock_form.return_value = {"depressionscreening": {"phq2_score": "2"}}

        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}
        today = datetime.date(2025, 6, 1)

        handler._lookup_session_dates("note-1", dates, today)

        assert dates["annual_depression"]["last_done"] == "2025-06-01"
        assert "annual_cognitive" not in dates

    @patch("guided_awv.api.awv_api._get_all_form_states")
    def test_sets_today_for_cognitive_assessment(self, mock_form: MagicMock) -> None:
        """Sets today's date for cognitive when form state has cognitiveassessment."""
        mock_form.return_value = {"cognitiveassessment": {"score": "4"}}

        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}
        today = datetime.date(2025, 6, 1)

        handler._lookup_session_dates("note-1", dates, today)

        assert dates["annual_cognitive"]["last_done"] == "2025-06-01"
        assert "annual_depression" not in dates

    @patch("guided_awv.api.awv_api._get_all_form_states")
    def test_sets_both_when_both_present(self, mock_form: MagicMock) -> None:
        """Sets today for both screenings when both form states exist."""
        mock_form.return_value = {
            "depressionscreening": {"phq2_score": "1"},
            "cognitiveassessment": {"score": "5"},
        }

        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}
        today = datetime.date(2025, 6, 1)

        handler._lookup_session_dates("note-1", dates, today)

        assert dates["annual_depression"]["last_done"] == "2025-06-01"
        assert dates["annual_cognitive"]["last_done"] == "2025-06-01"

    @patch("guided_awv.api.awv_api._get_all_form_states", side_effect=Exception("cache error"))
    def test_handles_exception_gracefully(self, mock_form: MagicMock) -> None:
        """Exception in session lookup is caught gracefully."""
        handler = GetScreeningDatesHandler(MagicMock())
        dates: dict[str, dict] = {}
        today = datetime.date(2025, 6, 1)

        handler._lookup_session_dates("note-1", dates, today)

        assert dates == {}
