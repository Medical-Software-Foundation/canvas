"""Tests for individual AWV workflow modules."""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from guided_awv.modules.base import AWVType
from guided_awv.modules.hra import HRAModule
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
from guided_awv.modules.followup_scheduling import FollowUpSchedulingModule
from guided_awv.modules.preventive_services import PreventiveServicesModule
from guided_awv.modules.assessment_plan import AssessmentPlanModule
from guided_awv.modules import ALL_MODULES


class TestHRAModule:
    """Tests for HRAModule."""

    def test_initial_title(self) -> None:
        """Initial AWV shows 'Initial' in title."""
        module = HRAModule("note-1", "patient-1", AWVType.INITIAL)
        assert "Initial" in module.TITLE

    def test_subsequent_title(self) -> None:
        """Subsequent AWV shows 'Update' in title."""
        module = HRAModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert "Update" in module.TITLE

    def test_initial_context_has_adl_section(self) -> None:
        """Initial AWV includes ADL/IADL section in questionnaire."""
        module = HRAModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        section_ids = [s["id"] for s in context["questionnaire_sections"]]
        assert "adl_iadl" in section_ids

    def test_subsequent_context_no_adl_section(self) -> None:
        """Subsequent AWV does not include full ADL section."""
        module = HRAModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        context = module.get_context()
        section_ids = [s["id"] for s in context["questionnaire_sections"]]
        assert "adl_iadl" not in section_ids

    def test_context_has_required_sections(self) -> None:
        """Context includes health_status and behavioral_risks sections."""
        module = HRAModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        section_ids = [s["id"] for s in context["questionnaire_sections"]]
        assert "health_status" in section_ids
        assert "behavioral_risks" in section_ids
        assert "psychosocial_risks" in section_ids

    def test_is_initial_flag_in_context(self) -> None:
        """Context includes is_initial flag."""
        initial_module = HRAModule("note-1", "patient-1", AWVType.INITIAL)
        subseq_module = HRAModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert initial_module.get_context()["is_initial"] is True
        assert subseq_module.get_context()["is_initial"] is False


class TestFamilyHistoryModule:
    """Tests for FamilyHistoryModule."""

    def test_get_context_has_required_keys(self) -> None:
        """get_context includes conditions, family_members, and instructions."""
        module = FamilyHistoryModule("note-1", "patient-1", AWVType.BOTH)
        context = module.get_context()
        assert "common_conditions" in context
        assert "family_members" in context
        assert "instructions" in context

    def test_common_conditions_are_strings(self) -> None:
        """Common conditions list contains strings."""
        module = FamilyHistoryModule("note-1", "patient-1", AWVType.INITIAL)
        conditions = module.get_context()["common_conditions"]
        assert all(isinstance(c, str) for c in conditions)


class TestVitalsModule:
    """Tests for VitalsModule."""

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_get_context_has_vitals_fields(self, mock_obs: MagicMock) -> None:
        """get_context returns vitals_fields list."""
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        module = VitalsModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "vitals_fields" in context
        assert len(context["vitals_fields"]) > 0

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_bmi_field_is_readonly(self, mock_obs: MagicMock) -> None:
        """BMI field is marked as readonly."""
        mock_obs.filter.return_value.order_by.return_value.values.return_value = []
        module = VitalsModule("note-1", "patient-1", AWVType.INITIAL)
        fields = module.get_context()["vitals_fields"]
        bmi_field = next((f for f in fields if f["id"] == "bmi"), None)
        assert bmi_field is not None
        assert bmi_field["readonly"] is True

    @patch("guided_awv.modules.vitals.Observation.objects")
    def test_recent_vitals_populated_when_available(self, mock_obs: MagicMock) -> None:
        """Recent vital value is populated from ORM when available."""
        mock_obs.filter.return_value.order_by.return_value.values.return_value = [
            {"codings__code": "8480-6", "value": "120"},
        ]

        module = VitalsModule("note-1", "patient-1", AWVType.INITIAL)
        fields = module.get_context()["vitals_fields"]
        # At least one field should have a recent_value populated
        recent_values = [f["recent_value"] for f in fields if f.get("recent_value")]
        assert len(recent_values) > 0


class TestDepressionScreeningModule:
    """Tests for DepressionScreeningModule."""

    def test_context_has_phq2_and_phq9(self) -> None:
        """Context includes both PHQ-2 and PHQ-9 questions."""
        module = DepressionScreeningModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "phq2_questions" in context
        assert "phq9_additional_questions" in context
        assert len(context["phq2_questions"]) == 2
        assert len(context["phq9_additional_questions"]) == 7

    def test_response_options_have_four_items(self) -> None:
        """Response options include all four PHQ frequency options."""
        module = DepressionScreeningModule("note-1", "patient-1", AWVType.INITIAL)
        options = module.get_context()["response_options"]
        assert len(options) == 4
        assert options[0]["value"] == "0"
        assert options[3]["value"] == "3"

    def test_phq2_positive_threshold(self) -> None:
        """PHQ-2 positive threshold is 3."""
        module = DepressionScreeningModule("note-1", "patient-1", AWVType.INITIAL)
        assert module.get_context()["phq2_positive_threshold"] == 3


class TestCognitiveAssessmentModule:
    """Tests for CognitiveAssessmentModule."""

    def test_context_has_mini_cog_steps(self) -> None:
        """Context includes 3 Mini-Cog assessment steps."""
        module = CognitiveAssessmentModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert len(context["instructions"]) == 3

    def test_context_has_recall_words(self) -> None:
        """Context includes 3 recall words for Mini-Cog."""
        module = CognitiveAssessmentModule("note-1", "patient-1", AWVType.INITIAL)
        assert len(module.get_context()["recall_words"]) == 3

    def test_context_has_scoring_guide(self) -> None:
        """Context includes scoring guide."""
        module = CognitiveAssessmentModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "scoring" in context
        assert "0-2" in context["scoring"]


class TestFallRiskModule:
    """Tests for FallRiskModule."""

    def test_context_has_screening_questions(self) -> None:
        """Context includes fall risk screening questions."""
        module = FallRiskModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "screening_questions" in context
        assert len(context["screening_questions"]) > 0

    def test_context_has_tug_test(self) -> None:
        """Context includes TUG test instructions."""
        module = FallRiskModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "tug_test" in context
        assert "instructions" in context["tug_test"]


class TestFunctionalAbilityModule:
    """Tests for FunctionalAbilityModule."""

    def test_context_has_adl_and_iadl(self) -> None:
        """Context includes both ADL and IADL items."""
        module = FunctionalAbilityModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "adl_items" in context
        assert "iadl_items" in context
        assert len(context["adl_items"]) > 0
        assert len(context["iadl_items"]) > 0

    def test_function_options_include_independent(self) -> None:
        """Function options include Independent as a choice."""
        module = FunctionalAbilityModule("note-1", "patient-1", AWVType.INITIAL)
        option_values = [o["value"] for o in module.get_context()["function_options"]]
        assert "independent" in option_values


class TestAdvanceCarePlanningModule:
    """Tests for AdvanceCarePlanningModule."""

    def test_context_has_discussion_fields(self) -> None:
        """Context includes discussion fields."""
        module = AdvanceCarePlanningModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "discussion_fields" in context
        assert len(context["discussion_fields"]) > 0

    def test_context_has_billing_note(self) -> None:
        """Context includes billing note."""
        module = AdvanceCarePlanningModule("note-1", "patient-1", AWVType.INITIAL)
        assert "billing_note" in module.get_context()


class TestFollowUpSchedulingModule:
    """Tests for FollowUpSchedulingModule."""

    def test_context_has_followup_fields(self) -> None:
        """Context includes follow-up fields."""
        module = FollowUpSchedulingModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "followup_fields" in context

    def test_context_has_awv_type(self) -> None:
        """Context includes AWV type for conditional rendering."""
        module = FollowUpSchedulingModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert module.get_context()["awv_type"] == AWVType.SUBSEQUENT


class TestPreventiveServicesModule:
    """Tests for PreventiveServicesModule."""

    def test_subsequent_title(self) -> None:
        """Subsequent AWV shows Gap Analysis in title."""
        module = PreventiveServicesModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert "Gap Analysis" in module.TITLE

    def test_initial_title(self) -> None:
        """Initial AWV shows Checklist in title."""
        module = PreventiveServicesModule("note-1", "patient-1", AWVType.INITIAL)
        assert "Checklist" in module.TITLE

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_get_context_patient_not_found(self, mock_patient_objects: MagicMock) -> None:
        """Returns error context when patient not found."""
        mock_patient_objects.filter.return_value.first.return_value = None
        module = PreventiveServicesModule("note-1", "patient-999", AWVType.INITIAL)
        context = module.get_context()
        assert "error" in context

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_get_context_builds_services_list(self, mock_patient_objects: MagicMock) -> None:
        """Builds services list for a 70-year-old female patient."""
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient

        module = PreventiveServicesModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "services" in context
        assert len(context["services"]) > 0

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_mammogram_included_for_females(self, mock_patient_objects: MagicMock) -> None:
        """Mammography is included for eligible female patients."""
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1960, 1, 1)
        mock_patient.sex_at_birth = "F"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient

        module = PreventiveServicesModule("note-1", "patient-1", AWVType.INITIAL)
        services = module.get_context()["services"]
        service_ids = [s["id"] for s in services]
        assert "mammogram" in service_ids

    @patch("guided_awv.modules.preventive_services.Patient.objects")
    def test_aaa_included_for_males(self, mock_patient_objects: MagicMock) -> None:
        """AAA screening is included for eligible male patients."""
        mock_patient = MagicMock()
        mock_patient.birth_date = datetime.date(1955, 1, 1)
        mock_patient.sex_at_birth = "M"
        mock_patient_objects.filter.return_value.first.return_value = mock_patient

        module = PreventiveServicesModule("note-1", "patient-1", AWVType.INITIAL)
        services = module.get_context()["services"]
        service_ids = [s["id"] for s in services]
        assert "aaa" in service_ids

    def test_calculate_age(self) -> None:
        """Age calculation returns correct integer age."""
        module = PreventiveServicesModule("note-1", "patient-1", AWVType.INITIAL)
        dob = datetime.date.today().replace(year=datetime.date.today().year - 70)
        age = module._calculate_age(dob)
        assert age == 70

    def test_calculate_age_none(self) -> None:
        """Age calculation returns 0 for None birth date."""
        module = PreventiveServicesModule("note-1", "patient-1", AWVType.INITIAL)
        assert module._calculate_age(None) == 0


class TestAssessmentPlanModule:
    """Tests for AssessmentPlanModule."""

    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_get_context_has_plan_fields(self, mock_condition_objects: MagicMock) -> None:
        """Context includes plan_fields for narrative capture."""
        mock_condition_objects.filter.return_value.values.return_value.order_by.return_value = []
        module = AssessmentPlanModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "plan_fields" in context
        assert len(context["plan_fields"]) > 0

    @patch("guided_awv.modules.assessment_plan.Condition.objects")
    def test_get_context_includes_active_conditions(self, mock_condition_objects: MagicMock) -> None:
        """Context includes active conditions list."""
        mock_conditions = [
            {"id": "cond-1", "codings__display": "Hypertension", "codings__code": "I10"},
        ]
        mock_condition_objects.filter.return_value.values.return_value.order_by.return_value = mock_conditions

        module = AssessmentPlanModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert context["condition_count"] == 1
        assert context["active_conditions"][0]["codings__display"] == "Hypertension"


class TestCurrentProvidersModule:
    """Tests for CurrentProvidersModule."""

    def test_initial_title_complete_capture(self) -> None:
        """Initial AWV shows 'Complete Capture' in title."""
        module = CurrentProvidersModule("note-1", "patient-1", AWVType.INITIAL)
        assert "Complete Capture" in module.TITLE

    def test_subsequent_title_review_update(self) -> None:
        """Subsequent AWV shows 'Review & Update' in title."""
        module = CurrentProvidersModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert "Review & Update" in module.TITLE

    def test_context_has_provider_categories(self) -> None:
        """Context includes provider categories.

        v0.14.0: pharmacy moved out of free-text PROVIDER_CATEGORIES into a
        dedicated structured section, leaving 4 free-text categories
        (pcp, dme_suppliers, home_health, other_providers).
        """
        module = CurrentProvidersModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "provider_categories" in context
        assert len(context["provider_categories"]) == 4
        assert "existing_pharmacies" in context
        assert isinstance(context["existing_pharmacies"], list)

    def test_context_includes_pcp_category(self) -> None:
        """Provider categories include PCP."""
        module = CurrentProvidersModule("note-1", "patient-1", AWVType.INITIAL)
        categories = module.get_context()["provider_categories"]
        ids = [c["id"] for c in categories]
        assert "pcp" in ids

    # --- _read_existing_pharmacies (v0.14.0) ---

    def test_read_existing_pharmacies_returns_empty_when_no_patient(self) -> None:
        from unittest.mock import patch
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.first.return_value = None
            result = CurrentProvidersModule._read_existing_pharmacies("missing-id")
            assert result == []

    def test_read_existing_pharmacies_handles_single_dict(self) -> None:
        """Tolerate Canvas returning a single pharmacy dict (not a list)."""
        from unittest.mock import MagicMock, patch
        mock_patient_obj = MagicMock()
        # Explicitly disable the plural attribute so the parser falls back to
        # the singular field, matching the legacy shape this test exercises.
        mock_patient_obj.preferred_pharmacies = None
        mock_patient_obj.preferred_pharmacy = {
            "ncpdp_id": "1234567",
            "organization_name": "CVS",
            "address_line_1": "123 Main St",
            "city": "NYC",
            "state": "NY",
            "zip_code": "10001",
            "default": True,
        }
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.first.return_value = mock_patient_obj
            result = CurrentProvidersModule._read_existing_pharmacies("p-id")
            assert len(result) == 1
            assert result[0]["ncpdp_id"] == "1234567"
            assert result[0]["organization_name"] == "CVS"
            assert result[0]["default"] is True

    def test_read_existing_pharmacies_handles_list(self) -> None:
        """Tolerate Canvas returning a list of pharmacy dicts."""
        from unittest.mock import MagicMock, patch
        mock_patient_obj = MagicMock()
        mock_patient_obj.preferred_pharmacies = None
        mock_patient_obj.preferred_pharmacy = [
            {"ncpdp_id": "1", "organization_name": "Pharm A", "default": True},
            {"ncpdp_id": "2", "organization_name": "Pharm B", "default": False},
        ]
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.first.return_value = mock_patient_obj
            result = CurrentProvidersModule._read_existing_pharmacies("p-id")
            assert len(result) == 2
            assert result[0]["default"] is True
            assert result[1]["default"] is False

    def test_read_existing_pharmacies_returns_empty_for_none(self) -> None:
        """Patient with no preferred_pharmacy field returns empty list."""
        from unittest.mock import MagicMock, patch
        mock_patient_obj = MagicMock()
        mock_patient_obj.preferred_pharmacy = None
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.first.return_value = mock_patient_obj
            result = CurrentProvidersModule._read_existing_pharmacies("p-id")
            assert result == []

    def test_read_existing_pharmacies_prefers_plural_attribute(self) -> None:
        """When patient.preferred_pharmacies (plural) is populated, use it.

        Live UAT on 2026-05-10 against marketing-sandbox confirmed that the
        singular preferred_pharmacy field exposes only the default pharmacy,
        even when the patient has additional non-default preferred pharmacies
        in their chart (visible in the Profile UI). The plural attribute, when
        present, is the full list and must take precedence.
        """
        from unittest.mock import MagicMock, patch
        mock_patient_obj = MagicMock()
        # Plural attribute carries the full list (default + non-default)
        mock_patient_obj.preferred_pharmacies = [
            {"ncpdp_id": "1", "organization_name": "Mark Cuban Cost Plus", "default": True},
            {"ncpdp_id": "2", "organization_name": "Benevere (CVS Specialty)", "default": False},
        ]
        # Singular only shows the default - we must NOT fall back to it when the
        # plural is populated, otherwise we'd lose the non-default entry.
        mock_patient_obj.preferred_pharmacy = {
            "ncpdp_id": "1",
            "organization_name": "Mark Cuban Cost Plus",
            "default": True,
        }
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.first.return_value = mock_patient_obj
            result = CurrentProvidersModule._read_existing_pharmacies("p-id")
            assert len(result) == 2
            assert result[0]["organization_name"] == "Mark Cuban Cost Plus"
            assert result[0]["default"] is True
            assert result[1]["organization_name"] == "Benevere (CVS Specialty)"
            assert result[1]["default"] is False

    def test_read_existing_pharmacies_falls_back_to_singular_when_plural_empty(self) -> None:
        """If the plural attribute is an empty list, fall back to the singular field."""
        from unittest.mock import MagicMock, patch
        mock_patient_obj = MagicMock()
        mock_patient_obj.preferred_pharmacies = []  # plural exists but empty
        mock_patient_obj.preferred_pharmacy = {"ncpdp_id": "1", "organization_name": "Solo", "default": True}
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.first.return_value = mock_patient_obj
            result = CurrentProvidersModule._read_existing_pharmacies("p-id")
            assert len(result) == 1
            assert result[0]["organization_name"] == "Solo"

    def test_read_existing_pharmacies_handles_exception(self) -> None:
        """Any exception during ORM access yields an empty list, not a crash."""
        from unittest.mock import patch
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.side_effect = Exception("db down")
            result = CurrentProvidersModule._read_existing_pharmacies("p-id")
            assert result == []

    def test_read_existing_pharmacies_resolves_name_via_pharmacy_http(self) -> None:
        """If chart JSON has only an NCPDP id, fetch name/address from pharmacy_http.

        Real-world UAT showed the chart's preferred_pharmacy entries arriving
        without 'organization_name' under the keys we expected, producing
        '(unnamed pharmacy)' in the UI. This guards the fallback resolution.
        """
        from unittest.mock import MagicMock, patch
        mock_patient_obj = MagicMock()
        mock_patient_obj.preferred_pharmacies = None
        # Only ncpdp_id and default present - no name/address
        mock_patient_obj.preferred_pharmacy = {"ncpdp_id": "1234567", "default": True}

        with patch("canvas_sdk.v1.data.Patient") as mock_patient, patch(
            "canvas_sdk.utils.http.PharmacyHttp.get_pharmacy_by_ncpdp_id"
        ) as mock_get:
            mock_patient.objects.filter.return_value.first.return_value = mock_patient_obj
            mock_get.return_value = {
                "ncpdp_id": "1234567",
                "organization_name": "Walgreens",
                "address_line_1": "100 Market St",
                "city": "San Francisco",
                "state": "CA",
                "zip_code": "94103",
            }

            result = CurrentProvidersModule._read_existing_pharmacies("p-id")

            mock_get.assert_called_once_with("1234567")
            assert len(result) == 1
            assert result[0]["organization_name"] == "Walgreens"
            assert result[0]["city"] == "San Francisco"
            assert result[0]["default"] is True

    def test_read_existing_pharmacies_tries_alt_key_names(self) -> None:
        """Tolerate camelCase or alternative keys (organizationName, addressLine1, etc.)."""
        from unittest.mock import MagicMock, patch
        mock_patient_obj = MagicMock()
        mock_patient_obj.preferred_pharmacies = None
        mock_patient_obj.preferred_pharmacy = {
            "pharmacy_id": "1234567",  # alt for ncpdp_id
            "organizationName": "CVS",  # camelCase
            "addressLine1": "1 Main St",
            "is_default": True,
        }
        with patch("canvas_sdk.v1.data.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.first.return_value = mock_patient_obj
            result = CurrentProvidersModule._read_existing_pharmacies("p-id")
            assert len(result) == 1
            assert result[0]["ncpdp_id"] == "1234567"
            assert result[0]["organization_name"] == "CVS"
            assert result[0]["address_line_1"] == "1 Main St"
            assert result[0]["default"] is True


class TestHearingVisionModule:
    """Tests for HearingVisionModule."""

    def test_context_has_hearing_and_vision_fields(self) -> None:
        """Context includes both hearing and vision field sets."""
        module = HearingVisionModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "hearing_fields" in context
        assert "vision_fields" in context

    def test_hearing_fields_include_whisper_test(self) -> None:
        """Hearing fields include the whispered voice test."""
        module = HearingVisionModule("note-1", "patient-1", AWVType.INITIAL)
        hearing_ids = [f["id"] for f in module.get_context()["hearing_fields"]]
        assert "whisper_test" in hearing_ids

    def test_vision_fields_include_snellen(self) -> None:
        """Vision fields include Snellen acuity for both eyes."""
        module = HearingVisionModule("note-1", "patient-1", AWVType.INITIAL)
        vision_ids = [f["id"] for f in module.get_context()["vision_fields"]]
        assert "snellen_right" in vision_ids
        assert "snellen_left" in vision_ids


class TestAlcoholScreeningModule:
    """Tests for AlcoholScreeningModule."""

    def test_context_has_questions(self) -> None:
        """Context includes 3 AUDIT-C questions."""
        module = AlcoholScreeningModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "questions" in context
        assert len(context["questions"]) == 3

    def test_scoring_thresholds(self) -> None:
        """Scoring includes sex-specific thresholds."""
        module = AlcoholScreeningModule("note-1", "patient-1", AWVType.INITIAL)
        scoring = module.get_context()["scoring"]
        assert scoring["male_threshold"] == 4
        assert scoring["female_threshold"] == 3
        assert scoring["max_score"] == 12

    def test_context_has_billing_note(self) -> None:
        """Context includes Medicare billing information."""
        module = AlcoholScreeningModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()
        assert "billing_note" in context
        assert "G0442" in context["billing_note"]


class TestAllModules:
    """Tests that verify the complete module registry."""

    def test_all_modules_have_17_entries(self) -> None:
        """ALL_MODULES contains all 17 AWV section modules."""
        assert len(ALL_MODULES) == 17

    def test_all_modules_have_order(self) -> None:
        """All modules define ORDER >= 1."""
        for module_class in ALL_MODULES:
            assert module_class.ORDER >= 1, f"{module_class.__name__} must have ORDER >= 1"

    def test_all_modules_can_be_instantiated(self) -> None:
        """All modules can be instantiated without error."""
        for module_class in ALL_MODULES:
            module = module_class("note-1", "patient-1", AWVType.INITIAL)  # type: ignore[abstract]
            assert module is not None

    def test_orders_are_sequential(self) -> None:
        """Module orders form a proper sequence 1-17."""
        orders = sorted(m.ORDER for m in ALL_MODULES)
        assert orders == list(range(1, 18))
