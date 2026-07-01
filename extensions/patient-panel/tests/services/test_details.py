"""Tests for patient_panel.services.details.

clean_task_title is pure; the fetchers use real ORM records via factories.
Date-formatting fetchers receive a simple UTC formatter (the production
formatter is the API's tz-bound _format_local).
"""

__is_plugin__ = True

from typing import Any

import arrow
import pytest

from canvas_sdk.test_utils.factories import (
    PatientFactory,
    ProtocolCurrentFactory,
    ReferralFactory,
    ServiceProviderFactory,
    TaskCommentFactory,
    TaskFactory,
)
from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.medication import Medication

from patient_panel.services.details import (
    clean_task_title,
    get_allergies_details,
    get_conditions_details,
    get_gaps_details,
    get_medications_details,
    get_open_tasks,
    get_referrals_details,
    get_task_comments,
)


def _fmt(dt: Any, fmt: str) -> str:
    return arrow.get(dt).to("UTC").format(fmt)


# ── clean_task_title (pure) ───────────────────────────────────────────────

class TestCleanTaskTitle:
    def test_removes_patient_markup(self) -> None:
        title = "Review phone call on 9/25/2025 with <patient:2:abc|Joseph Daniel Adams>"
        assert clean_task_title(title) == "Review phone call on 9/25/2025 with Joseph Daniel Adams"

    def test_removes_multiple_references(self) -> None:
        title = "Call <patient:1:abc|John Doe> and <staff:2:def|Jane Smith>"
        assert clean_task_title(title) == "Call John Doe and Jane Smith"

    def test_no_markup_unchanged(self) -> None:
        assert clean_task_title("Regular task title") == "Regular task title"

    def test_empty_string(self) -> None:
        assert clean_task_title("") == ""

    def test_none(self) -> None:
        assert clean_task_title(None) is None


# ── ORM fetchers ──────────────────────────────────────────────────────────

pytestmark = pytest.mark.django_db


def _make_condition(patient: object, **overrides: object) -> Condition:
    from canvas_sdk.test_utils.factories import CanvasUserFactory
    user = CanvasUserFactory.create()
    defaults = dict(
        patient=patient,
        clinical_status="active",
        deleted=False,
        onset_date=arrow.utcnow().date(),
        resolution_date=arrow.utcnow().date(),
        notes="",
        surgical=False,
        committer=user,
    )
    defaults.update(overrides)
    return Condition.objects.create(**defaults)


def _make_medication(patient: object, **overrides: object) -> Medication:
    defaults = dict(
        patient=patient,
        deleted=False,
        status="active",
        start_date=arrow.utcnow().datetime,
        end_date=arrow.utcnow().shift(days=30).datetime,
        quantity_qualifier_description="",
        clinical_quantity_description="",
        potency_unit_code="",
        national_drug_code="",
        erx_quantity=0.0,
    )
    defaults.update(overrides)
    return Medication.objects.create(**defaults)


def _make_medication_committed(patient: object, **overrides: object) -> Medication:
    from canvas_sdk.test_utils.factories import CanvasUserFactory
    user = CanvasUserFactory.create()
    return _make_medication(patient, committer=user, **overrides)


def _make_allergy(patient: object, **overrides: object) -> AllergyIntolerance:
    defaults = dict(
        patient=patient,
        deleted=False,
        note_id=0,
        allergy_intolerance_type="allergy",
        category=1,
        status="active",
        severity="moderate",
        onset_date=arrow.utcnow().date(),
        onset_date_original_input="",
        last_occurrence=arrow.utcnow().date(),
        last_occurrence_original_input="",
        recorded_date=arrow.utcnow().datetime,
        narrative="",
    )
    defaults.update(overrides)
    return AllergyIntolerance.objects.create(**defaults)


class TestGetOpenTasks:
    def test_returns_empty_when_no_tasks(self) -> None:
        patient = PatientFactory.create()
        assert get_open_tasks(str(patient.id)) == []


class TestGetTaskComments:
    def test_returns_ordered_comments(self) -> None:
        patient = PatientFactory.create()
        task = TaskFactory.create(patient=patient)
        TaskCommentFactory.create(task=task, body="first")
        TaskCommentFactory.create(task=task, body="second")
        result = get_task_comments(str(task.id), format_local=_fmt)
        assert len(result) == 2


class TestGetGapsDetails:
    def test_returns_due_only(self) -> None:
        from canvas_sdk.v1.data.protocol_result import ProtocolResultStatus

        patient = PatientFactory.create()
        ProtocolCurrentFactory.create(patient=patient, status=ProtocolResultStatus.STATUS_DUE)
        rows = list(get_gaps_details(str(patient.id)))
        assert all(r["status"] == ProtocolResultStatus.STATUS_DUE for r in rows)


class TestGetConditionsDetails:
    def test_picks_icd_code_when_present(self) -> None:
        patient = PatientFactory.create()
        condition = _make_condition(patient)
        condition.codings.create(code="I10", display="", system="http://hl7.org/fhir/sid/icd-10")
        condition.codings.create(code="38341003", display="Hypertension", system="http://snomed.info/sct")
        result = get_conditions_details(str(patient.id), format_local=_fmt)
        assert any(r["code"] == "I10" and r["display"] == "Hypertension" for r in result)

    def test_falls_back_to_display_coding_code(self) -> None:
        patient = PatientFactory.create()
        condition = _make_condition(patient)
        condition.codings.create(code="44054006", display="Diabetes", system="http://snomed.info/sct")
        result = get_conditions_details(str(patient.id), format_local=_fmt)
        row = next(r for r in result if r["display"] == "Diabetes")
        assert row["code"] == "44054006"

    def test_empty_for_patient_without_conditions(self) -> None:
        patient = PatientFactory.create()
        assert get_conditions_details(str(patient.id), format_local=_fmt) == []

    def test_onset_date_formatted_via_tz_callback(self) -> None:
        patient = PatientFactory.create()
        condition = _make_condition(patient)
        condition.codings.create(code="44054006", display="Diabetes", system="http://snomed.info/sct")
        captured: list[Any] = []

        def _capturing_fmt(dt: Any, fmt: str) -> str:
            captured.append((dt, fmt))
            return "TZ-FORMATTED"

        result = get_conditions_details(str(patient.id), format_local=_capturing_fmt)
        row = next(r for r in result if r["display"] == "Diabetes")
        assert row["onset_date"] == "TZ-FORMATTED"
        assert captured and captured[0][1] == "MM.DD.YYYY"


class TestGetMedicationsDetails:
    def test_picks_display_from_coding(self) -> None:
        patient = PatientFactory.create()
        med = _make_medication_committed(patient)
        med.codings.create(
            code="abc",
            display="Lisinopril 10 mg tablet",
            system="http://www.nlm.nih.gov/research/umls/rxnorm",
        )
        result = get_medications_details(str(patient.id), format_local=_fmt)
        assert any(r["display"] == "Lisinopril 10 mg tablet" for r in result)

    def test_empty_for_patient_without_meds(self) -> None:
        patient = PatientFactory.create()
        assert get_medications_details(str(patient.id), format_local=_fmt) == []


class TestGetAllergiesDetails:
    def test_picks_display_from_coding(self) -> None:
        patient = PatientFactory.create()
        allergy = _make_allergy(patient, severity="severe")
        allergy.codings.create(code="abc", display="Penicillin", system="http://snomed.info/sct")
        result = get_allergies_details(str(patient.id), format_local=_fmt)
        row = next(r for r in result if r["display"] == "Penicillin")
        assert row["severity"] == "severe"

    def test_empty_for_patient_without_allergies(self) -> None:
        patient = PatientFactory.create()
        assert get_allergies_details(str(patient.id), format_local=_fmt) == []


class TestGetReferralsDetails:
    def test_includes_provider_and_question(self) -> None:
        patient = PatientFactory.create()
        provider = ServiceProviderFactory.create(first_name="Jane", last_name="Smith")
        ReferralFactory.create(
            patient=patient,
            clinical_question="Cardiology consult",
            service_provider=provider,
        )
        result = get_referrals_details(str(patient.id), format_local=_fmt)
        row = next(iter(result), None)
        assert row is not None
        assert row["clinical_question"] == "Cardiology consult"
        assert "Jane Smith" in row["provider"]

    def test_default_question_when_empty(self) -> None:
        patient = PatientFactory.create()
        ReferralFactory.create(patient=patient, clinical_question="")
        result = get_referrals_details(str(patient.id), format_local=_fmt)
        row = next(iter(result), None)
        assert row is not None
        assert row["clinical_question"] == "(no clinical question)"
