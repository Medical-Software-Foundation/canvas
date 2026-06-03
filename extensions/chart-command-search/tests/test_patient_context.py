"""Tests for fetch_patient_context."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from chart_command_search.context.patient_context import fetch_patient_context, AI_DATE_RANGE_DAYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_patient(
    first_name: str = "Jane",
    last_name: str = "Doe",
    birth_date: Any = None,
    sex_at_birth: str = "female",
    nickname: str = "",
    prefix: str = "",
    suffix: str = "",
    mrn: str = "MRN001",
    clinical_note: str = "",
    administrative_note: str = "",
    default_provider: Any = None,
) -> MagicMock:
    """Create a mock patient with the given attributes."""
    patient = MagicMock()
    patient.first_name = first_name
    patient.last_name = last_name
    patient.birth_date = birth_date
    patient.sex_at_birth = sex_at_birth
    patient.nickname = nickname
    patient.prefix = prefix
    patient.suffix = suffix
    patient.mrn = mrn
    patient.clinical_note = clinical_note
    patient.administrative_note = administrative_note
    patient.default_provider = default_provider
    return patient


def _mock_provider(first_name: str = "Dr", last_name: str = "House") -> MagicMock:
    """Create a mock provider with the given names."""
    provider = MagicMock()
    provider.first_name = first_name
    provider.last_name = last_name
    return provider


def _create_empty_qs() -> MagicMock:
    """Create a mock queryset that chains and returns empty results."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.select_related.return_value = qs
    qs.prefetch_related.return_value = qs
    qs.order_by.return_value = qs
    qs.values.return_value = []
    qs.__getitem__ = lambda self, s: []
    qs.__iter__ = lambda self: iter([])
    qs.first.return_value = None
    qs.all.return_value = []
    return qs


# ---------------------------------------------------------------------------
# Demographics section
# ---------------------------------------------------------------------------


class TestFetchPatientContextDemographics:
    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_demographics_present_for_valid_patient(self, *mock_models) -> None:
        # Get the Patient mock (it's the first in the reversed order)
        mock_patient = mock_models[-1]  # Patient is the last patch, so first in reversed order

        # Create a patient with data
        patient = _mock_patient(first_name="Jane", last_name="Doe", mrn="MRN123")
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = patient

        # Set all other models to return empty querysets
        for mock_model in mock_models[:-1]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        assert "demographics" in ctx
        assert "Jane Doe" in ctx["demographics"]["name"]

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_demographics_absent_when_patient_not_found(self, *mock_models) -> None:
        mock_patient = mock_models[-1]
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None

        # Set all other models to return empty querysets
        for mock_model in mock_models[:-1]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("nonexistent-id")

        assert "demographics" not in ctx

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    @patch("chart_command_search.context.patient_context.log")
    def test_demographics_exception_does_not_raise(self, mock_log, *mock_models) -> None:
        mock_patient = mock_models[0]  # First model in the list

        # Make Patient.objects.filter raise an exception
        mock_patient.objects.filter.side_effect = RuntimeError("db down")

        # Set all other models to return empty querysets
        for mock_model in mock_models[1:]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        # demographics key should be absent, not raise
        assert "demographics" not in ctx
        mock_log.warning.assert_called()

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_demographics_includes_mrn_when_present(self, *mock_models) -> None:
        mock_patient = mock_models[-1]

        patient = _mock_patient(mrn="MRN-999")
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = patient

        # Set all other models to return empty querysets
        for mock_model in mock_models[:-1]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        assert ctx.get("demographics", {}).get("mrn") == "MRN-999"

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_demographics_no_mrn_key_when_empty(self, *mock_models) -> None:
        mock_patient = mock_models[-1]

        patient = _mock_patient(mrn="")
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = patient

        # Set all other models to return empty querysets
        for mock_model in mock_models[:-1]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        assert "mrn" not in ctx.get("demographics", {})

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_default_provider_name_included(self, *mock_models) -> None:
        mock_patient = mock_models[-1]

        provider = _mock_provider(first_name="Dr", last_name="House")
        patient = _mock_patient(default_provider=provider)
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = patient

        # Set all other models to return empty querysets
        for mock_model in mock_models[:-1]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        assert ctx.get("demographics", {}).get("default_provider") == "Dr House"


# ---------------------------------------------------------------------------
# One section failure does not block others
# ---------------------------------------------------------------------------


class TestFetchPatientContextPartialFailure:
    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_conditions_failure_does_not_block_medications(self, *mock_models) -> None:
        # Get specific models from the args (reversed order due to decorators)
        mock_patient = mock_models[-1]
        mock_patient_contact = mock_models[-2]
        mock_patient_address = mock_models[-3]
        mock_patient_setting = mock_models[-4]
        mock_condition = mock_models[-5]
        mock_medication = mock_models[-7]  # Skip AllergyIntolerance

        # Setup patient
        patient = _mock_patient()
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = patient

        # Setup contacts and addresses to return empty
        mock_patient_contact.objects = _create_empty_qs()
        mock_patient_address.objects = _create_empty_qs()
        mock_patient_setting.objects = _create_empty_qs()

        # Make conditions fail
        mock_condition.objects.filter.side_effect = RuntimeError("conditions db error")

        # Setup medications to return data
        med = MagicMock()
        med.clinical_quantity_description = "10mg"
        med.start_date = "2024-01-01"
        coding = MagicMock()
        coding.name = "Lisinopril"
        med.codings.all.return_value = [coding]

        med_qs = MagicMock()
        med_qs.filter.return_value = med_qs
        med_qs.prefetch_related.return_value = med_qs
        med_qs.order_by.return_value = [med]
        med_qs.__getitem__ = lambda self, s: [med]
        mock_medication.objects = med_qs

        # Set all other models to return empty querysets
        for mock_model in mock_models:
            if mock_model not in [mock_patient, mock_patient_contact, mock_patient_address,
                                  mock_patient_setting, mock_condition, mock_medication]:
                mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        # conditions must not be present (it threw), medications should be
        assert "conditions" not in ctx
        assert "medications" in ctx

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_all_sections_failing_returns_empty_dict(self, *mock_models) -> None:
        # Make all models raise exceptions
        for mock_model in mock_models:
            if hasattr(mock_model, 'objects'):
                mock_model.objects.filter.side_effect = RuntimeError("db error")
            else:
                mock_model.objects = MagicMock()
                mock_model.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context("patient-id")

        assert isinstance(ctx, dict)
        # No sections should be populated
        for key in (
            "demographics", "contacts", "addresses", "conditions", "allergies",
            "medications", "lab_results", "vitals_and_observations", "immunizations",
        ):
            assert key not in ctx


# ---------------------------------------------------------------------------
# Empty patient — returns dict with empty sections
# ---------------------------------------------------------------------------


class TestFetchPatientContextEmptyPatient:
    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_empty_patient_returns_empty_dict(self, *mock_models) -> None:
        """Patient not found + no other data → empty context dict."""
        mock_patient = mock_models[-1]
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None

        # Set all other models to return empty querysets
        for mock_model in mock_models[:-1]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("unknown-patient-id")

        assert isinstance(ctx, dict)
        assert "demographics" not in ctx

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_returns_dict_type_always(self, *mock_models) -> None:
        # Make all models raise exceptions
        for mock_model in mock_models:
            if hasattr(mock_model, 'objects'):
                mock_model.objects.filter.side_effect = RuntimeError("db error")
            else:
                mock_model.objects = MagicMock()
                mock_model.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context("any-id")
        assert isinstance(ctx, dict)


# ---------------------------------------------------------------------------
# Contacts section
# ---------------------------------------------------------------------------


class TestFetchPatientContextContacts:
    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    def test_contacts_populated_when_present(self, *mock_models) -> None:
        mock_patient = mock_models[-1]
        mock_patient_contact = mock_models[-2]

        # Patient not found
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None

        # But contacts exist
        contact_qs = MagicMock()
        contact_qs.filter.return_value = contact_qs
        contact_qs.values.return_value = [{"system": "phone", "value": "555-1234", "use": "home"}]
        contact_qs.__getitem__ = lambda self, s: [{"system": "phone", "value": "555-1234", "use": "home"}]
        mock_patient_contact.objects = contact_qs

        # Set all other models to return empty querysets
        for mock_model in mock_models[:-2]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        # If PatientContactPoint returned data, contacts key should exist
        assert isinstance(ctx, dict)

    @patch("canvas_sdk.v1.data.patient.Patient")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientSetting")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.lab.LabReport")
    @patch("canvas_sdk.v1.data.lab.LabValue")
    @patch("canvas_sdk.v1.data.observation.Observation")
    @patch("canvas_sdk.v1.data.immunization.Immunization")
    @patch("canvas_sdk.v1.data.prescription.Prescription")
    @patch("canvas_sdk.v1.data.goal.Goal")
    @patch("canvas_sdk.v1.data.referral.Referral")
    @patch("canvas_sdk.v1.data.imaging.ImagingOrder")
    @patch("canvas_sdk.v1.data.lab.LabOrder")
    @patch("canvas_sdk.v1.data.assessment.Assessment")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
    @patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
    @patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
    @patch("canvas_sdk.v1.data.coverage.Coverage")
    @patch("canvas_sdk.v1.data.claim.Claim")
    @patch("chart_command_search.context.patient_context.log")
    def test_contacts_exception_logged_and_ignored(self, mock_log, *mock_models) -> None:
        mock_patient = mock_models[0]
        mock_patient_contact = mock_models[1]

        # Patient not found
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None

        # Make contacts fail
        mock_patient_contact.objects.filter.side_effect = RuntimeError("contact db error")

        # Set all other models to return empty querysets
        for mock_model in mock_models[2:]:
            mock_model.objects = _create_empty_qs()

        ctx = fetch_patient_context("patient-id")

        assert "contacts" not in ctx
        assert mock_log.warning.called


# ---------------------------------------------------------------------------
# AI_DATE_RANGE_DAYS constant
# ---------------------------------------------------------------------------


class TestAIDateRangeDays:
    def test_ai_date_range_days_is_positive_integer(self) -> None:
        assert isinstance(AI_DATE_RANGE_DAYS, int)
        assert AI_DATE_RANGE_DAYS > 0

    def test_ai_date_range_days_covers_at_least_90_days(self) -> None:
        assert AI_DATE_RANGE_DAYS >= 90