from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from chart_command_search.context.patient_context import fetch_patient_context


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _coding(display: str = "Test", code: str = "T01") -> MagicMock:
    return _mock_obj(display=display, code=code)


def _lab_coding(name: str = "Test", code: str = "T01") -> MagicMock:
    return _mock_obj(name=name, code=code)


@patch("canvas_sdk.v1.data.patient.Patient")
class TestDemographics:
    def test_with_patient(self, mock_patient: Any) -> None:
        patient = _mock_obj(
            first_name="John", last_name="Doe", birth_date=date(1990, 1, 1),
            sex_at_birth="male", nickname="Johnny", prefix="Mr", suffix="Jr",
            clinical_note="Some clinical note", administrative_note="Admin note",
            mrn="MRN-001", default_provider=_mock_obj(first_name="Dr", last_name="Smith"),
        )
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = patient

        ctx = fetch_patient_context("patient-1")
        assert "demographics" in ctx
        assert ctx["demographics"]["name"] == "John Doe"
        assert ctx["demographics"]["dob"] == "1990-01-01"
        assert ctx["demographics"]["sex"] == "male"
        assert ctx["demographics"]["nickname"] == "Johnny"
        assert ctx["demographics"]["prefix"] == "Mr"
        assert ctx["demographics"]["suffix"] == "Jr"
        assert ctx["demographics"]["mrn"] == "MRN-001"
        assert ctx["demographics"]["default_provider"] == "Dr Smith"

    def test_patient_not_found(self, mock_patient: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        ctx = fetch_patient_context("patient-1")
        assert "demographics" not in ctx

    def test_exception_handled(self, mock_patient: Any) -> None:
        mock_patient.objects.filter.side_effect = RuntimeError("db down")
        ctx = fetch_patient_context("patient-1")
        assert "demographics" not in ctx


@patch("canvas_sdk.v1.data.patient.PatientContactPoint")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestContacts:
    def test_with_contacts(self, mock_patient: Any, mock_contact: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        contacts = [{"system": "phone", "value": "555-1234", "use": "home"}]
        qs = mock_contact.objects.filter.return_value
        qs.values.return_value.__getitem__ = lambda self, s: contacts

        ctx = fetch_patient_context("patient-1")
        assert "contacts" in ctx
        assert ctx["contacts"][0]["value"] == "555-1234"


@patch("canvas_sdk.v1.data.patient.PatientAddress")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestAddresses:
    def test_with_addresses(self, mock_patient: Any, mock_addr: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        addrs = [{"line1": "123 Main St", "city": "Springfield", "state_code": "IL", "postal_code": "62701", "use": "home", "line2": ""}]
        qs = mock_addr.objects.filter.return_value
        qs.values.return_value.__getitem__ = lambda self, s: addrs

        ctx = fetch_patient_context("patient-1")
        assert "addresses" in ctx
        assert ctx["addresses"][0]["city"] == "Springfield"


@patch("canvas_sdk.v1.data.condition.Condition")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestConditions:
    def test_with_conditions(self, mock_patient: Any, mock_cond: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        coding = _coding("Hypertension", "I10")
        cond = _mock_obj(clinical_status="active", onset_date=date(2023, 1, 1))
        cond.codings.all.return_value = [coding]
        qs = mock_cond.objects.filter.return_value
        qs.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [cond]

        ctx = fetch_patient_context("patient-1")
        assert "conditions" in ctx
        assert ctx["conditions"][0]["name"] == "Hypertension"
        assert ctx["conditions"][0]["code"] == "I10"

    def test_exception_handled(self, mock_patient: Any, mock_cond: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_cond.objects.filter.side_effect = RuntimeError("db error")
        ctx = fetch_patient_context("patient-1")
        assert "conditions" not in ctx


@patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestAllergies:
    def test_with_allergies(self, mock_patient: Any, mock_allergy: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        coding = _coding("Penicillin", "P01")
        allergy = _mock_obj(severity="severe", narrative="Rash and hives")
        allergy.codings.all.return_value = [coding]
        qs = mock_allergy.objects.filter.return_value
        qs.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [allergy]

        ctx = fetch_patient_context("patient-1")
        assert "allergies" in ctx
        assert ctx["allergies"][0]["name"] == "Penicillin"
        assert ctx["allergies"][0]["severity"] == "severe"


@patch("canvas_sdk.v1.data.medication.Medication")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestMedications:
    def test_with_medications(self, mock_patient: Any, mock_med: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        coding = _coding("Lisinopril 10mg", "L01")
        med = _mock_obj(clinical_quantity_description="10mg daily", start_date=date(2024, 1, 1))
        med.codings.all.return_value = [coding]
        qs = mock_med.objects.filter.return_value
        qs.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [med]

        ctx = fetch_patient_context("patient-1")
        assert "medications" in ctx
        assert ctx["medications"][0]["name"] == "Lisinopril 10mg"


@patch("canvas_sdk.v1.data.lab.LabValue")
@patch("canvas_sdk.v1.data.lab.LabReport")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestLabResults:
    def test_with_lab_values(self, mock_patient: Any, mock_report: Any, mock_lv: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        coding = _lab_coding("Glucose", "GLU")
        report = _mock_obj(original_date=date(2024, 3, 1))
        lv = _mock_obj(
            value="95", units="mg/dL", reference_range="70-100", abnormal_flag="",
            comment="", observation_status="final", low_threshold="70", high_threshold="100",
            report=report,
        )
        lv.codings.all.return_value = [coding]
        qs = mock_lv.objects.filter.return_value
        qs.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [lv]
        mock_report.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: []

        ctx = fetch_patient_context("patient-1")
        assert "lab_results" in ctx
        assert ctx["lab_results"][0]["test"] == "Glucose"
        assert ctx["lab_results"][0]["value"] == "95"

    def test_with_lab_reports(self, mock_patient: Any, mock_report: Any, mock_lv: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        val_coding = _lab_coding("Hemoglobin", "HGB")
        val = _mock_obj(value="14.5", units="g/dL")
        val.codings.all.return_value = [val_coding]
        report = _mock_obj(custom_document_name="CBC Panel", original_date=date(2024, 3, 1), requisition_number="REQ-001")
        report.values.all.return_value = [val]

        mock_lv.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: []
        mock_report.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [report]

        ctx = fetch_patient_context("patient-1")
        assert "lab_reports" in ctx
        assert ctx["lab_reports"][0]["name"] == "CBC Panel"
        assert "Hemoglobin" in ctx["lab_reports"][0]["values"]


@patch("canvas_sdk.v1.data.observation.Observation")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestObservations:
    def test_with_vitals(self, mock_patient: Any, mock_obs: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        component = _mock_obj(name="Systolic", value_quantity="120", value_quantity_unit="mmHg")
        obs = _mock_obj(
            name="Blood Pressure", value="120/80", units="mmHg",
            effective_datetime=datetime(2024, 3, 1, 10, 0),
        )
        obs.components.all.return_value = [component]
        obs.codings = MagicMock()
        qs = mock_obs.objects.filter.return_value
        qs.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [obs]

        ctx = fetch_patient_context("patient-1")
        assert "vitals_and_observations" in ctx
        assert ctx["vitals_and_observations"][0]["name"] == "Blood Pressure"


@patch("canvas_sdk.v1.data.immunization.Immunization")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestImmunizations:
    def test_with_immunizations(self, mock_patient: Any, mock_imm: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        coding = _coding("Flu Vaccine", "FLU")
        imm = _mock_obj(status="completed", date_ordered=date(2024, 1, 15))
        imm.codings.all.return_value = [coding]
        qs = mock_imm.objects.filter.return_value
        qs.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [imm]

        ctx = fetch_patient_context("patient-1")
        assert "immunizations" in ctx
        assert ctx["immunizations"][0]["vaccine"] == "Flu Vaccine"


@patch("canvas_sdk.v1.data.prescription.Prescription")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestPrescriptions:
    def test_with_prescriptions(self, mock_patient: Any, mock_rx: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        coding = _coding("Metformin 500mg", "MET")
        med = _mock_obj()
        med.codings.all.return_value = [coding]
        rx = _mock_obj(
            medication=med,
            sig_original_input="Take twice daily",
            dispense_quantity=60,
            count_of_refills_allowed=3,
            pharmacy_name="CVS",
            written_date=date(2024, 2, 1),
            prescriber=_mock_obj(first_name="Dr", last_name="Smith"),
        )
        qs = mock_rx.objects.filter.return_value
        qs.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [rx]

        ctx = fetch_patient_context("patient-1")
        assert "prescriptions" in ctx
        assert ctx["prescriptions"][0]["medication"] == "Metformin 500mg"
        assert ctx["prescriptions"][0]["prescriber"] == "Dr Smith"


@patch("canvas_sdk.v1.data.goal.Goal")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestGoals:
    def test_with_goals(self, mock_patient: Any, mock_goal: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        goal = _mock_obj(
            goal_statement="Lose 10 lbs", achievement_status="in-progress",
            priority="high", due_date=date(2024, 6, 1), progress="Down 3 lbs so far",
        )
        qs = mock_goal.objects.filter.return_value
        qs.order_by.return_value.__getitem__ = lambda self, s: [goal]

        ctx = fetch_patient_context("patient-1")
        assert "goals" in ctx
        assert ctx["goals"][0]["goal"] == "Lose 10 lbs"


@patch("canvas_sdk.v1.data.referral.Referral")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestReferrals:
    def test_with_referrals(self, mock_patient: Any, mock_ref: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        ref = _mock_obj(
            service_provider=_mock_obj(name="Springfield Cardiology"),
            clinical_question="Evaluate chest pain",
            priority="urgent", date_referred=date(2024, 3, 1),
            notes="Refer for stress test",
        )
        qs = mock_ref.objects.filter.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [ref]

        ctx = fetch_patient_context("patient-1")
        assert "referrals" in ctx
        assert ctx["referrals"][0]["referred_to"] == "Springfield Cardiology"


@patch("canvas_sdk.v1.data.imaging.ImagingOrder")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestImagingOrders:
    def test_with_imaging(self, mock_patient: Any, mock_img: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        img = _mock_obj(
            imaging="Chest X-Ray", status="ordered", priority="stat",
            date_time_ordered=datetime(2024, 3, 1, 10, 0),
            imaging_center=_mock_obj(name="Springfield Imaging"),
        )
        qs = mock_img.objects.filter.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [img]

        ctx = fetch_patient_context("patient-1")
        assert "imaging_orders" in ctx
        assert ctx["imaging_orders"][0]["imaging"] == "Chest X-Ray"


@patch("canvas_sdk.v1.data.lab.LabOrder")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestLabOrders:
    def test_with_lab_orders(self, mock_patient: Any, mock_lo: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        test = _mock_obj(ontology_test_name="CBC", ontology_test_code="CBC01")
        lo = _mock_obj(
            comment="Fasting required", date_ordered=date(2024, 3, 1),
            fasting_status="fasting",
            ordering_provider=_mock_obj(first_name="Dr", last_name="Smith"),
        )
        lo.tests.all.return_value = [test]
        qs = mock_lo.objects.filter.return_value
        qs.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [lo]

        ctx = fetch_patient_context("patient-1")
        assert "lab_orders" in ctx
        assert ctx["lab_orders"][0]["tests"] == ["CBC"]


@patch("canvas_sdk.v1.data.assessment.Assessment")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestAssessments:
    def test_with_assessments(self, mock_patient: Any, mock_assess: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        coding = _coding("Diabetes", "E11")
        condition = _mock_obj()
        condition.codings.all.return_value = [coding]
        assess = _mock_obj(
            condition=condition, status="active",
            narrative="Well controlled", background="Type 2 diabetes diagnosed 2020",
        )
        qs = mock_assess.objects.filter.return_value
        qs.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [assess]

        ctx = fetch_patient_context("patient-1")
        assert "assessments" in ctx
        assert ctx["assessments"][0]["condition"] == "Diabetes"


@patch("canvas_sdk.v1.data.patient_consent.PatientConsent")
@patch("canvas_sdk.v1.data.patient_consent.PatientConsentCoding")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestConsents:
    def test_with_signed_consent(self, mock_patient: Any, mock_coding: Any, mock_consent: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        ct = _mock_obj(dbid=1, display="HIPAA", is_mandatory=True)
        mock_coding.objects.filter.return_value = [ct]
        consent = _mock_obj(
            state="accepted", effective_date=date(2024, 1, 1), expired_date=None,
            category=ct, rejection_reason=None,
        )
        qs = mock_consent.objects.filter.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [consent]

        ctx = fetch_patient_context("patient-1")
        assert "consents" in ctx
        assert ctx["consents"][0]["type"] == "HIPAA"
        assert ctx["consents"][0]["status"] == "Accepted"

    def test_missing_mandatory_consent(self, mock_patient: Any, mock_coding: Any, mock_consent: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        ct = _mock_obj(dbid=1, display="HIPAA", is_mandatory=True)
        mock_coding.objects.filter.return_value = [ct]
        qs = mock_consent.objects.filter.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = lambda self, s: []

        ctx = fetch_patient_context("patient-1")
        assert "consents" in ctx
        missing = [c for c in ctx["consents"] if "Not provided" in c.get("status", "")]
        assert len(missing) == 1


@patch("canvas_sdk.v1.data.care_team.CareTeamMembership")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestCareTeam:
    def test_with_members(self, mock_patient: Any, mock_ctm: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        member = _mock_obj(
            staff=_mock_obj(first_name="Jane", last_name="Nurse"),
            role=_mock_obj(display="Primary Nurse"),
            role_display="Primary Nurse",
            status="active", lead=True,
        )
        qs = mock_ctm.objects.filter.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [member]

        ctx = fetch_patient_context("patient-1")
        assert "care_team" in ctx
        assert ctx["care_team"][0]["member"] == "Jane Nurse"
        assert ctx["care_team"][0]["lead"] == "Yes"


@patch("canvas_sdk.v1.data.patient.PatientSetting")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestPreferences:
    def test_with_settings(self, mock_patient: Any, mock_setting: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        setting = _mock_obj(name="language", value="en")
        mock_setting.objects.filter.return_value = [setting]

        ctx = fetch_patient_context("patient-1")
        assert "preferences" in ctx
        assert ctx["preferences"]["language"] == "en"


@patch("canvas_sdk.v1.data.coverage.Coverage")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestCoverages:
    def test_with_coverage(self, mock_patient: Any, mock_cov: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        cov = _mock_obj(
            issuer=_mock_obj(name="Blue Cross"),
            plan="Gold Plan", plan_type="HMO",
            coverage_rank=1, coverage_start_date=date(2024, 1, 1),
            coverage_end_date=None, comments="",
        )
        qs = mock_cov.objects.filter.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [cov]

        ctx = fetch_patient_context("patient-1")
        assert "coverages" in ctx
        assert ctx["coverages"][0]["payer"] == "Blue Cross"
        assert ctx["coverages"][0]["rank"] == "Primary"


@patch("canvas_sdk.v1.data.claim.Claim")
@patch("canvas_sdk.v1.data.patient.Patient")
class TestClaims:
    def test_with_claims(self, mock_patient: Any, mock_claim: Any) -> None:
        mock_patient.objects.filter.return_value.select_related.return_value.first.return_value = None
        claim = _mock_obj(
            note=_mock_obj(datetime_of_service=datetime(2024, 3, 1, 10, 0)),
            current_queue=_mock_obj(display_name="Billing Queue", name="billing"),
            narrative="Office visit claim",
        )
        qs = mock_claim.objects.filter.return_value
        qs.select_related.return_value.order_by.return_value.__getitem__ = lambda self, s: [claim]

        ctx = fetch_patient_context("patient-1")
        assert "claims" in ctx
        assert ctx["claims"][0]["queue"] == "Billing Queue"
