from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from chart_command_search.context.patient_context import fetch_patient_context


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


PATIENT_ID = "patient-abc-123"


class TestDemographics:
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_patient_found_with_provider(self, mock_patient_cls: MagicMock) -> None:
        provider = _mock_obj(first_name="Jane", last_name="Smith")
        patient = _mock_obj(
            first_name="John",
            last_name="Doe",
            birth_date=date(1980, 1, 15),
            sex_at_birth="male",
            nickname=None,
            prefix=None,
            suffix=None,
            clinical_note=None,
            administrative_note=None,
            mrn="MRN001",
            default_provider=provider,
        )
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = patient

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["demographics"]["name"] == "John Doe"
        assert ctx["demographics"]["dob"] == "1980-01-15"
        assert ctx["demographics"]["sex"] == "male"
        assert ctx["demographics"]["mrn"] == "MRN001"
        assert ctx["demographics"]["default_provider"] == "Jane Smith"

    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_patient_not_found(self, mock_patient_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None

        ctx = fetch_patient_context(PATIENT_ID)

        assert "demographics" not in ctx

    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_demographics_exception_handled(self, mock_patient_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context(PATIENT_ID)

        assert "demographics" not in ctx

    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_patient_optional_fields_included(self, mock_patient_cls: MagicMock) -> None:
        patient = _mock_obj(
            first_name="Anna",
            last_name="Lee",
            birth_date=None,
            sex_at_birth="",
            nickname="Annie",
            prefix="Dr.",
            suffix="Jr.",
            clinical_note="note text",
            administrative_note="admin text",
            mrn=None,
            default_provider=None,
        )
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = patient

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["demographics"]["nickname"] == "Annie"
        assert ctx["demographics"]["prefix"] == "Dr."
        assert ctx["demographics"]["suffix"] == "Jr."
        assert ctx["demographics"]["clinical_note"] == "note text"
        assert ctx["demographics"]["admin_note"] == "admin text"


class TestContacts:
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_contacts_with_results(self, mock_patient_cls: MagicMock, mock_contact_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = [
            {"system": "phone", "value": "555-1234", "use": "home"},
        ]

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["contacts"] == [{"system": "phone", "value": "555-1234", "use": "home"}]

    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_contacts_empty_values_filtered(self, mock_patient_cls: MagicMock, mock_contact_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = [
            {"system": "phone", "value": "", "use": None},
        ]

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["contacts"] == [{"system": "phone"}]

    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_contacts_exception_handled(self, mock_patient_cls: MagicMock, mock_contact_cls: MagicMock) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context(PATIENT_ID)

        assert "contacts" not in ctx


class TestAddresses:
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_addresses_with_results(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = [
            {"line1": "123 Main St", "line2": "", "city": "Springfield", "state_code": "IL", "postal_code": "62701", "use": "home"},
        ]

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["addresses"][0]["line1"] == "123 Main St"
        assert ctx["addresses"][0]["city"] == "Springfield"
        assert "line2" not in ctx["addresses"][0]

    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_addresses_exception_handled(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context(PATIENT_ID)

        assert "addresses" not in ctx


class TestConditions:
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_conditions_with_codings(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
        mock_condition_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []

        coding = _mock_obj(display="Hypertension", code="I10")
        condition = _mock_obj(clinical_status="active", onset_date=date(2020, 5, 1))
        condition.codings.all.return_value = [coding]

        mock_condition_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [condition]

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["conditions"][0]["name"] == "Hypertension"
        assert ctx["conditions"][0]["code"] == "I10"
        assert ctx["conditions"][0]["status"] == "active"
        assert ctx["conditions"][0]["onset"] == "2020-05-01"

    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_conditions_exception_handled(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
        mock_condition_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_condition_cls.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context(PATIENT_ID)

        assert "conditions" not in ctx


class TestAllergies:
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_allergies_with_codings_and_severity(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
        mock_condition_cls: MagicMock,
        mock_allergy_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_condition_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []

        coding = _mock_obj(display="Penicillin")
        allergy = _mock_obj(severity="severe", narrative="Causes rash and hives")
        allergy.codings.all.return_value = [coding]

        mock_allergy_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [allergy]

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["allergies"][0]["name"] == "Penicillin"
        assert ctx["allergies"][0]["severity"] == "severe"
        assert "rash" in ctx["allergies"][0]["narrative"]

    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_allergies_exception_handled(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
        mock_condition_cls: MagicMock,
        mock_allergy_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_condition_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
        mock_allergy_cls.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context(PATIENT_ID)

        assert "allergies" not in ctx


class TestMedications:
    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_medications_with_codings_and_dates(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
        mock_condition_cls: MagicMock,
        mock_allergy_cls: MagicMock,
        mock_med_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_condition_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
        mock_allergy_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []

        coding = _mock_obj(display="Metformin 500mg")
        med = _mock_obj(clinical_quantity_description="1 tablet", start_date=date(2021, 3, 10))
        med.codings.all.return_value = [coding]

        mock_med_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [med]

        ctx = fetch_patient_context(PATIENT_ID)

        assert ctx["medications"][0]["name"] == "Metformin 500mg"
        assert ctx["medications"][0]["quantity"] == "1 tablet"
        assert ctx["medications"][0]["start"] == "2021-03-10"

    @patch("canvas_sdk.v1.data.medication.Medication")
    @patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance")
    @patch("canvas_sdk.v1.data.condition.Condition")
    @patch("canvas_sdk.v1.data.patient.PatientAddress")
    @patch("canvas_sdk.v1.data.patient.PatientContactPoint")
    @patch("canvas_sdk.v1.data.patient.Patient")
    def test_medications_exception_handled(
        self,
        mock_patient_cls: MagicMock,
        mock_contact_cls: MagicMock,
        mock_addr_cls: MagicMock,
        mock_condition_cls: MagicMock,
        mock_allergy_cls: MagicMock,
        mock_med_cls: MagicMock,
    ) -> None:
        mock_patient_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_contact_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_addr_cls.objects.filter.return_value.values.return_value.__getitem__.return_value = []
        mock_condition_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
        mock_allergy_cls.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
        mock_med_cls.objects.filter.side_effect = RuntimeError("db error")

        ctx = fetch_patient_context(PATIENT_ID)

        assert "medications" not in ctx


def _patch_prior_sections() -> list[Any]:
    return [
        patch("canvas_sdk.v1.data.patient.Patient"),
        patch("canvas_sdk.v1.data.patient.PatientContactPoint"),
        patch("canvas_sdk.v1.data.patient.PatientAddress"),
        patch("canvas_sdk.v1.data.condition.Condition"),
        patch("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance"),
        patch("canvas_sdk.v1.data.medication.Medication"),
    ]


def _silence_prior_sections(*mocks: MagicMock) -> None:
    patient_mock, contact_mock, addr_mock, cond_mock, allergy_mock, med_mock = mocks
    patient_mock.objects.filter.return_value.select_related.return_value.first.return_value = None
    contact_mock.objects.filter.return_value.values.return_value.__getitem__.return_value = []
    addr_mock.objects.filter.return_value.values.return_value.__getitem__.return_value = []
    cond_mock.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    allergy_mock.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    med_mock.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []


class TestLabResults:
    def test_lab_results_with_values_and_report_dates(self) -> None:
        patches = _patch_prior_sections()
        with (
            patches[0] as p0,
            patches[1] as p1,
            patches[2] as p2,
            patches[3] as p3,
            patches[4] as p4,
            patches[5] as p5,
            patch("canvas_sdk.v1.data.lab.LabValue") as mock_labvalue,
            patch("canvas_sdk.v1.data.lab.LabReport") as mock_labreport,
            patch("canvas_sdk.v1.data.lab.LabOrder"),
        ):
            _silence_prior_sections(p0, p1, p2, p3, p4, p5)

            coding = _mock_obj(name="Glucose", code="2345-7")
            report = _mock_obj(original_date=date(2024, 6, 1))
            lv = _mock_obj(
                value="95",
                units="mg/dL",
                reference_range="70-100",
                abnormal_flag=None,
                comment=None,
                observation_status="final",
                low_threshold=None,
                high_threshold=None,
                report=report,
            )
            lv.codings.all.return_value = [coding]

            (
                mock_labvalue.objects
                .filter.return_value
                .select_related.return_value
                .prefetch_related.return_value
                .order_by.return_value
                .__getitem__.return_value
            ) = [lv]

            val_coding = _mock_obj(name="Glucose")
            val = _mock_obj(value="95", units="mg/dL")
            val.codings.all.return_value = [val_coding]
            rpt = _mock_obj(custom_document_name="BMP Panel", original_date=date(2024, 6, 1), requisition_number="REQ001")
            rpt.values.all.return_value = [val]

            (
                mock_labreport.objects
                .filter.return_value
                .prefetch_related.return_value
                .order_by.return_value
                .__getitem__.return_value
            ) = [rpt]

            ctx = fetch_patient_context(PATIENT_ID)

            assert ctx["lab_results"][0]["test"] == "Glucose"
            assert ctx["lab_results"][0]["value"] == "95"
            assert ctx["lab_results"][0]["units"] == "mg/dL"
            assert ctx["lab_results"][0]["date"] == "2024-06-01"

    def test_lab_reports_with_values_and_codings(self) -> None:
        patches = _patch_prior_sections()
        with (
            patches[0] as p0,
            patches[1] as p1,
            patches[2] as p2,
            patches[3] as p3,
            patches[4] as p4,
            patches[5] as p5,
            patch("canvas_sdk.v1.data.lab.LabValue") as mock_labvalue,
            patch("canvas_sdk.v1.data.lab.LabReport") as mock_labreport,
            patch("canvas_sdk.v1.data.lab.LabOrder"),
        ):
            _silence_prior_sections(p0, p1, p2, p3, p4, p5)

            (
                mock_labvalue.objects
                .filter.return_value
                .select_related.return_value
                .prefetch_related.return_value
                .order_by.return_value
                .__getitem__.return_value
            ) = []

            val_coding = _mock_obj(name="HbA1c")
            val = _mock_obj(value="6.5", units="%")
            val.codings.all.return_value = [val_coding]
            rpt = _mock_obj(custom_document_name="Diabetes Panel", original_date=date(2024, 7, 15), requisition_number=None)
            rpt.values.all.return_value = [val]

            (
                mock_labreport.objects
                .filter.return_value
                .prefetch_related.return_value
                .order_by.return_value
                .__getitem__.return_value
            ) = [rpt]

            ctx = fetch_patient_context(PATIENT_ID)

            assert ctx["lab_reports"][0]["name"] == "Diabetes Panel"
            assert ctx["lab_reports"][0]["date"] == "2024-07-15"
            assert "HbA1c: 6.5 %" in ctx["lab_reports"][0]["values"]

    def test_lab_exception_handled(self) -> None:
        patches = _patch_prior_sections()
        with (
            patches[0] as p0,
            patches[1] as p1,
            patches[2] as p2,
            patches[3] as p3,
            patches[4] as p4,
            patches[5] as p5,
            patch("canvas_sdk.v1.data.lab.LabValue") as mock_labvalue,
        ):
            _silence_prior_sections(p0, p1, p2, p3, p4, p5)
            mock_labvalue.objects.filter.side_effect = RuntimeError("db error")

            ctx = fetch_patient_context(PATIENT_ID)

            assert "lab_results" not in ctx
            assert "lab_reports" not in ctx


class TestVitalsAndObservations:
    def test_observations_with_components(self) -> None:
        patches = _patch_prior_sections()
        with (
            patches[0] as p0,
            patches[1] as p1,
            patches[2] as p2,
            patches[3] as p3,
            patches[4] as p4,
            patches[5] as p5,
            patch("canvas_sdk.v1.data.lab.LabValue") as mock_labvalue,
            patch("canvas_sdk.v1.data.lab.LabReport") as mock_labreport,
            patch("canvas_sdk.v1.data.lab.LabOrder"),
            patch("canvas_sdk.v1.data.observation.Observation") as mock_obs,
        ):
            _silence_prior_sections(p0, p1, p2, p3, p4, p5)
            mock_labvalue.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_labreport.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []

            component = _mock_obj(name="Systolic", value_quantity=120, value_quantity_unit="mmHg")
            obs_dt = MagicMock()
            obs_dt.date.return_value = date(2024, 8, 1)
            observation = _mock_obj(name="Blood Pressure", value=None, units=None, effective_datetime=obs_dt)
            observation.components.all.return_value = [component]

            mock_obs.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [observation]

            ctx = fetch_patient_context(PATIENT_ID)

            assert ctx["vitals_and_observations"][0]["name"] == "Blood Pressure"
            assert ctx["vitals_and_observations"][0]["components"][0]["name"] == "Systolic"
            assert ctx["vitals_and_observations"][0]["components"][0]["value"] == "120"

    def test_observations_exception_handled(self) -> None:
        patches = _patch_prior_sections()
        with (
            patches[0] as p0,
            patches[1] as p1,
            patches[2] as p2,
            patches[3] as p3,
            patches[4] as p4,
            patches[5] as p5,
            patch("canvas_sdk.v1.data.lab.LabValue") as mock_labvalue,
            patch("canvas_sdk.v1.data.lab.LabReport") as mock_labreport,
            patch("canvas_sdk.v1.data.lab.LabOrder"),
            patch("canvas_sdk.v1.data.observation.Observation") as mock_obs,
        ):
            _silence_prior_sections(p0, p1, p2, p3, p4, p5)
            mock_labvalue.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_labreport.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_obs.objects.filter.side_effect = RuntimeError("db error")

            ctx = fetch_patient_context(PATIENT_ID)

            assert "vitals_and_observations" not in ctx


class TestImmunizations:
    def test_immunizations_with_codings(self) -> None:
        patches = _patch_prior_sections()
        with (
            patches[0] as p0,
            patches[1] as p1,
            patches[2] as p2,
            patches[3] as p3,
            patches[4] as p4,
            patches[5] as p5,
            patch("canvas_sdk.v1.data.lab.LabValue") as mock_labvalue,
            patch("canvas_sdk.v1.data.lab.LabReport") as mock_labreport,
            patch("canvas_sdk.v1.data.lab.LabOrder"),
            patch("canvas_sdk.v1.data.observation.Observation") as mock_obs,
            patch("canvas_sdk.v1.data.immunization.Immunization") as mock_immz,
        ):
            _silence_prior_sections(p0, p1, p2, p3, p4, p5)
            mock_labvalue.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_labreport.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_obs.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []

            coding = _mock_obj(display="Influenza vaccine")
            immz = _mock_obj(status="completed", date_ordered=date(2023, 10, 5))
            immz.codings.all.return_value = [coding]

            mock_immz.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [immz]

            ctx = fetch_patient_context(PATIENT_ID)

            assert ctx["immunizations"][0]["vaccine"] == "Influenza vaccine"
            assert ctx["immunizations"][0]["status"] == "completed"
            assert ctx["immunizations"][0]["date"] == "2023-10-05"

    def test_immunizations_exception_handled(self) -> None:
        patches = _patch_prior_sections()
        with (
            patches[0] as p0,
            patches[1] as p1,
            patches[2] as p2,
            patches[3] as p3,
            patches[4] as p4,
            patches[5] as p5,
            patch("canvas_sdk.v1.data.lab.LabValue") as mock_labvalue,
            patch("canvas_sdk.v1.data.lab.LabReport") as mock_labreport,
            patch("canvas_sdk.v1.data.lab.LabOrder"),
            patch("canvas_sdk.v1.data.observation.Observation") as mock_obs,
            patch("canvas_sdk.v1.data.immunization.Immunization") as mock_immz,
        ):
            _silence_prior_sections(p0, p1, p2, p3, p4, p5)
            mock_labvalue.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_labreport.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_obs.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
            mock_immz.objects.filter.side_effect = RuntimeError("db error")

            ctx = fetch_patient_context(PATIENT_ID)

            assert "immunizations" not in ctx


def _build_full_pre_prescription_patches() -> list[Any]:
    return _patch_prior_sections() + [
        patch("canvas_sdk.v1.data.lab.LabValue"),
        patch("canvas_sdk.v1.data.lab.LabReport"),
        patch("canvas_sdk.v1.data.lab.LabOrder"),
        patch("canvas_sdk.v1.data.observation.Observation"),
        patch("canvas_sdk.v1.data.immunization.Immunization"),
    ]


def _silence_all_pre_prescription(mocks: list[MagicMock]) -> None:
    patient_m, contact_m, addr_m, cond_m, allergy_m, med_m, lv_m, lr_m, lo_m, obs_m, immz_m = mocks
    patient_m.objects.filter.return_value.select_related.return_value.first.return_value = None
    contact_m.objects.filter.return_value.values.return_value.__getitem__.return_value = []
    addr_m.objects.filter.return_value.values.return_value.__getitem__.return_value = []
    cond_m.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    allergy_m.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    med_m.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    lv_m.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    lr_m.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    obs_m.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    immz_m.objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []


class TestPrescriptions:
    def test_prescriptions_with_medication_codings_and_prescriber(self) -> None:
        pre_patches = _build_full_pre_prescription_patches()
        with (
            pre_patches[0] as p0,
            pre_patches[1] as p1,
            pre_patches[2] as p2,
            pre_patches[3] as p3,
            pre_patches[4] as p4,
            pre_patches[5] as p5,
            pre_patches[6] as p6,
            pre_patches[7] as p7,
            pre_patches[8] as p8,
            pre_patches[9] as p9,
            pre_patches[10] as p10,
            patch("canvas_sdk.v1.data.prescription.Prescription") as mock_rx,
        ):
            _silence_all_pre_prescription([p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10])

            coding = _mock_obj(display="Lisinopril 10mg")
            med = MagicMock()
            med.codings.all.return_value = [coding]
            prescriber = _mock_obj(first_name="Dr.", last_name="House")
            rx = _mock_obj(
                medication=med,
                sig_original_input="Take 1 tablet daily",
                dispense_quantity=30,
                count_of_refills_allowed=3,
                pharmacy_name="CVS",
                written_date=date(2024, 9, 1),
                prescriber=prescriber,
            )

            mock_rx.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [rx]

            ctx = fetch_patient_context(PATIENT_ID)

            assert ctx["prescriptions"][0]["medication"] == "Lisinopril 10mg"
            assert ctx["prescriptions"][0]["sig"] == "Take 1 tablet daily"
            assert ctx["prescriptions"][0]["quantity"] == "30"
            assert ctx["prescriptions"][0]["refills"] == "3"
            assert ctx["prescriptions"][0]["pharmacy"] == "CVS"
            assert ctx["prescriptions"][0]["prescriber"] == "Dr. House"

    def test_prescriptions_exception_handled(self) -> None:
        pre_patches = _build_full_pre_prescription_patches()
        with (
            pre_patches[0] as p0,
            pre_patches[1] as p1,
            pre_patches[2] as p2,
            pre_patches[3] as p3,
            pre_patches[4] as p4,
            pre_patches[5] as p5,
            pre_patches[6] as p6,
            pre_patches[7] as p7,
            pre_patches[8] as p8,
            pre_patches[9] as p9,
            pre_patches[10] as p10,
            patch("canvas_sdk.v1.data.prescription.Prescription") as mock_rx,
        ):
            _silence_all_pre_prescription([p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10])
            mock_rx.objects.filter.side_effect = RuntimeError("db error")

            ctx = fetch_patient_context(PATIENT_ID)

            assert "prescriptions" not in ctx


class TestGoals:
    def test_goals_with_various_fields(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            goal = _mock_obj(
                goal_statement="Reduce HbA1c below 7%",
                achievement_status="in-progress",
                priority="high",
                due_date=date(2025, 1, 1),
                progress="Patient exercising 3x/week",
            )
            mocks["Goal"].objects.filter.return_value.order_by.return_value.__getitem__.return_value = [goal]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["goals"][0]["goal"] == "Reduce HbA1c below 7%"
        assert ctx["goals"][0]["achievement"] == "in-progress"
        assert ctx["goals"][0]["priority"] == "high"
        assert ctx["goals"][0]["due"] == "2025-01-01"

    def test_goals_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["Goal"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "goals" not in ctx


def _run_with_all_silenced_up_to(
    extra_patches: dict[str, Any],
    callback: Any,
) -> Any:
    all_patches = [
        ("canvas_sdk.v1.data.patient.Patient", None),
        ("canvas_sdk.v1.data.patient.PatientContactPoint", None),
        ("canvas_sdk.v1.data.patient.PatientAddress", None),
        ("canvas_sdk.v1.data.condition.Condition", None),
        ("canvas_sdk.v1.data.allergy_intolerance.AllergyIntolerance", None),
        ("canvas_sdk.v1.data.medication.Medication", None),
        ("canvas_sdk.v1.data.lab.LabValue", None),
        ("canvas_sdk.v1.data.lab.LabReport", None),
        ("canvas_sdk.v1.data.lab.LabOrder", None),
        ("canvas_sdk.v1.data.observation.Observation", None),
        ("canvas_sdk.v1.data.immunization.Immunization", None),
        ("canvas_sdk.v1.data.prescription.Prescription", None),
        ("canvas_sdk.v1.data.goal.Goal", None),
        ("canvas_sdk.v1.data.referral.Referral", None),
        ("canvas_sdk.v1.data.imaging.ImagingOrder", None),
        ("canvas_sdk.v1.data.assessment.Assessment", None),
        ("canvas_sdk.v1.data.patient_consent.PatientConsentCoding", None),
        ("canvas_sdk.v1.data.patient_consent.PatientConsent", None),
        ("canvas_sdk.v1.data.care_team.CareTeamMembership", None),
        ("canvas_sdk.v1.data.patient.PatientSetting", None),
        ("canvas_sdk.v1.data.coverage.Coverage", None),
        ("canvas_sdk.v1.data.claim.Claim", None),
    ]

    active = []
    mocks: dict[str, MagicMock] = {}
    for target, _ in all_patches:
        p = patch(target)
        m = p.start()
        active.append(p)
        short_key = target.split(".")[-1]
        mocks[short_key] = m

    for k, v in extra_patches.items():
        if k in mocks:
            mocks[k] = v

    mocks["Patient"].objects.filter.return_value.select_related.return_value.first.return_value = None
    mocks["PatientContactPoint"].objects.filter.return_value.values.return_value.__getitem__.return_value = []
    mocks["PatientAddress"].objects.filter.return_value.values.return_value.__getitem__.return_value = []
    mocks["Condition"].objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["AllergyIntolerance"].objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Medication"].objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["LabValue"].objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["LabReport"].objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Observation"].objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Immunization"].objects.filter.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Prescription"].objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Goal"].objects.filter.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Referral"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["ImagingOrder"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["LabOrder"].objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Assessment"].objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["PatientConsentCoding"].objects.filter.return_value.__iter__ = MagicMock(return_value=iter([]))
    mocks["PatientConsent"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["CareTeamMembership"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["PatientSetting"].objects.filter.return_value.__iter__ = MagicMock(return_value=iter([]))
    mocks["Coverage"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []
    mocks["Claim"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []

    try:
        result = callback(mocks)
    finally:
        for p in reversed(active):
            p.stop()
    return result


class TestReferrals:
    def test_referrals_with_service_provider(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            sp = _mock_obj(name="Springfield Orthopedics")
            ref = _mock_obj(
                clinical_question="Knee pain evaluation",
                priority="routine",
                date_referred=date(2024, 5, 20),
                notes=None,
            )
            ref.service_provider = sp
            mocks["Referral"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [ref]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["referrals"][0]["referred_to"] == "Springfield Orthopedics"
        assert ctx["referrals"][0]["question"] == "Knee pain evaluation"

    def test_referrals_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["Referral"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "referrals" not in ctx


class TestImagingOrders:
    def test_imaging_orders_with_imaging_center(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            center = _mock_obj(name="City Radiology")
            ordered_dt = MagicMock()
            ordered_dt.date.return_value = date(2024, 4, 10)
            img = _mock_obj(
                imaging="MRI Brain without contrast",
                status="ordered",
                priority="urgent",
                date_time_ordered=ordered_dt,
            )
            img.imaging_center = center
            mocks["ImagingOrder"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [img]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["imaging_orders"][0]["imaging"] == "MRI Brain without contrast"
        assert ctx["imaging_orders"][0]["center"] == "City Radiology"
        assert ctx["imaging_orders"][0]["status"] == "ordered"

    def test_imaging_orders_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["ImagingOrder"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "imaging_orders" not in ctx


class TestLabOrders:
    def test_lab_orders_with_tests(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            test1 = _mock_obj(ontology_test_name="CBC", ontology_test_code=None)
            test2 = _mock_obj(ontology_test_name=None, ontology_test_code="85025")
            provider = _mock_obj(first_name="Alice", last_name="Green")
            lo = _mock_obj(
                comment="Fasting required",
                date_ordered=date(2024, 3, 5),
                fasting_status="fasting",
            )
            lo.tests.all.return_value = [test1, test2]
            lo.ordering_provider = provider
            mocks["LabOrder"].objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [lo]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["lab_orders"][0]["tests"] == ["CBC", "85025"]
        assert ctx["lab_orders"][0]["fasting"] == "fasting"
        assert ctx["lab_orders"][0]["provider"] == "Alice Green"

    def test_lab_orders_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["LabOrder"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "lab_orders" not in ctx


class TestAssessments:
    def test_assessments_with_condition_codings(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            coding = _mock_obj(display="Type 2 diabetes mellitus")
            cond = MagicMock()
            cond.codings.all.return_value = [coding]
            assessment = _mock_obj(status="active", narrative="Well controlled", background="Diagnosed 2015")
            assessment.condition = cond
            mocks["Assessment"].objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = [assessment]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["assessments"][0]["condition"] == "Type 2 diabetes mellitus"
        assert ctx["assessments"][0]["status"] == "active"
        assert ctx["assessments"][0]["narrative"] == "Well controlled"

    def test_assessments_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["Assessment"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "assessments" not in ctx


class TestConsents:
    def test_mandatory_consent_not_signed_appears_as_not_provided(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mandatory_ct = _mock_obj(dbid=99, display="HIPAA Notice", is_mandatory=True)
            mocks["PatientConsentCoding"].objects.filter.return_value.__getitem__ = lambda self, s: [mandatory_ct]
            mocks["PatientConsent"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert any(
            c["type"] == "HIPAA Notice" and "Not provided" in c["status"]
            for c in ctx["consents"]
        )

    def test_signed_consent_appears_with_status(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            category = _mock_obj(display="Financial Policy", dbid=10, is_mandatory=False)
            consent = _mock_obj(state="accepted", effective_date=date(2023, 1, 1), expired_date=None)
            consent.category = category
            consent.rejection_reason = None
            mocks["PatientConsentCoding"].objects.filter.return_value.__getitem__ = lambda self, s: []
            mocks["PatientConsent"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [consent]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["consents"][0]["type"] == "Financial Policy"
        assert ctx["consents"][0]["status"] == "Accepted"

    def test_consents_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["PatientConsentCoding"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "consents" not in ctx


class TestCareTeam:
    def test_care_team_with_staff_and_role(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            staff = _mock_obj(first_name="Bob", last_name="Nurse")
            role = _mock_obj(display="Primary Care Physician")
            member = _mock_obj(status="active", lead=True, role_display=None)
            member.staff = staff
            member.role = role
            mocks["CareTeamMembership"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [member]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["care_team"][0]["member"] == "Bob Nurse"
        assert ctx["care_team"][0]["role"] == "Primary Care Physician"
        assert ctx["care_team"][0]["status"] == "active"
        assert ctx["care_team"][0]["lead"] == "Yes"

    def test_care_team_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["CareTeamMembership"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "care_team" not in ctx


class TestPatientSettings:
    def test_preferences_populated(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            s1 = _mock_obj(name="language", value="en")
            s2 = _mock_obj(name="contact_preference", value="email")
            mocks["PatientSetting"].objects.filter.return_value.__getitem__ = lambda self, s: [s1, s2]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["preferences"]["language"] == "en"
        assert ctx["preferences"]["contact_preference"] == "email"

    def test_preferences_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["PatientSetting"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "preferences" not in ctx


class TestCoverages:
    def test_coverages_with_issuer(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            issuer = _mock_obj(name="BlueCross BlueShield")
            cov = _mock_obj(
                plan="PPO Gold",
                plan_type="PPO",
                coverage_rank=1,
                coverage_start_date=date(2023, 1, 1),
                coverage_end_date=None,
                comments=None,
            )
            cov.issuer = issuer
            mocks["Coverage"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [cov]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["coverages"][0]["payer"] == "BlueCross BlueShield"
        assert ctx["coverages"][0]["plan"] == "PPO Gold"
        assert ctx["coverages"][0]["rank"] == "Primary"
        assert ctx["coverages"][0]["start"] == "2023-01-01"

    def test_coverages_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["Coverage"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "coverages" not in ctx


class TestClaims:
    def test_claims_with_queue_and_note(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            dos_dt = MagicMock()
            dos_dt.date.return_value = date(2024, 2, 14)
            note = _mock_obj(datetime_of_service=dos_dt)
            queue = _mock_obj(display_name="Billing Queue", name="billing_queue")
            claim = _mock_obj(narrative="Follow-up visit")
            claim.note = note
            claim.current_queue = queue
            mocks["Claim"].objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [claim]
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)

        assert ctx["claims"][0]["dos"] == "2024-02-14"
        assert ctx["claims"][0]["queue"] == "Billing Queue"
        assert ctx["claims"][0]["narrative"] == "Follow-up visit"

    def test_claims_exception_handled(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            mocks["Claim"].objects.filter.side_effect = RuntimeError("db error")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert "claims" not in ctx

    def test_returns_empty_dict_when_all_sections_fail(self) -> None:
        def run(mocks: dict[str, MagicMock]) -> dict[str, Any]:
            for mock in mocks.values():
                mock.objects.filter.side_effect = RuntimeError("all broken")
            return fetch_patient_context(PATIENT_ID)

        ctx = _run_with_all_silenced_up_to({}, run)
        assert isinstance(ctx, dict)
