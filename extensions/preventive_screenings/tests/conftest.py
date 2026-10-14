"""Shared fixtures for building patients and chart records in the test database.

Each test runs inside a transaction that is rolled back at the end.
See https://docs.canvasmedical.com/sdk/testing-utils/

The query paths are tested against this database rather than against mocks, on
purpose: a mocked queryset never resolves a field name and cannot count queries,
so it would not catch a typo'd lookup or a query budget regression. Request
handling and failure branches are mocked instead - see the plugin's CLAUDE.md.
"""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from canvas_sdk.test_utils.factories import (
    CanvasUserFactory,
    ImagingReportCodingFactory,
    ImagingReportFactory,
    LabReportFactory,
    LabValueCodingFactory,
    LabValueFactory,
    NoteFactory,
    PatientFactory,
    ProcedureCodingFactory,
    ProcedureFactory,
    ProtocolOverrideFactory,
    ReferralReportCodingFactory,
    ReferralReportFactory,
)
from canvas_sdk.v1.data import Condition, Patient
from canvas_sdk.v1.data.condition import ConditionCoding
from canvas_sdk.v1.data.questionnaire import Interview, Questionnaire

import preventive_screenings
from preventive_screenings.models import ScreeningAttestation

LOINC = "http://loinc.org"
CPT = "http://www.ama-assn.org/go/cpt"
SNOMED = "http://snomed.info/sct"


@pytest.fixture
def manifest() -> dict[str, Any]:
    """The plugin's CANVAS_MANIFEST.json, to check the code against what Canvas is told."""
    path = Path(preventive_screenings.__file__).parent / "CANVAS_MANIFEST.json"
    manifest: dict[str, Any] = json.loads(path.read_text())
    return manifest


@pytest.fixture
def attestation_table() -> Iterator[None]:
    """Create the attestation CustomModel's table for the duration of a test.

    The pytest fixtures do not create custom-data tables. Mocking the model
    instead is what let an N+1 hide in the sweep's write path for two days, so
    anything that reads or writes attestations is tested against a real table.

    `schema_editor` cannot run inside the test's atomic block - SQLite refuses
    to disable foreign-key checks mid-transaction - so every test asking for
    this needs `django_db(transaction=True)`.
    """
    with connection.schema_editor() as editor:
        editor.create_model(ScreeningAttestation)
    yield
    with connection.schema_editor() as editor:
        editor.delete_model(ScreeningAttestation)


@pytest.fixture
def patient() -> Patient:
    """A 50-year-old female patient, old enough for most shipped screenings."""
    return PatientFactory.create(
        birth_date=date(1976, 6, 15), sex_at_birth="F", deceased=False
    )


@pytest.fixture
def make_imaging() -> Callable[..., Any]:
    """Build an imaging report for a patient, coded and dated."""

    def _make(patient: Patient, code: str, when: date, system: str = LOINC) -> Any:
        report = ImagingReportFactory.create(patient=patient, result_date=when)
        ImagingReportCodingFactory.create(report=report, code=code, system=system)
        return report

    return _make


@pytest.fixture
def make_procedure() -> Callable[..., Any]:
    """Build a committed procedure, dated by its note's date of service."""

    def _make(patient: Patient, code: str, when: date, system: str = CPT) -> Any:
        note = NoteFactory.create(
            patient=patient,
            datetime_of_service=datetime(when.year, when.month, when.day, tzinfo=UTC),
        )
        procedure = ProcedureFactory.create(
            patient=patient, note=note, committer=CanvasUserFactory.create(), deleted=False
        )
        ProcedureCodingFactory.create(procedure=procedure, code=code, system=system)
        return procedure

    return _make


@pytest.fixture
def make_referral() -> Callable[..., Any]:
    """Build an inbound referral report for a patient, coded and dated.

    This is where the instance's own CMS130v6 looks for a colonoscopy, ahead of
    imaging and instead of the procedure table.
    """

    def _make(
        patient: Patient, code: str, when: date, system: str = LOINC, junked: bool = False
    ) -> Any:
        report = ReferralReportFactory.create(
            patient=patient, original_date=when, junked=junked
        )
        ReferralReportCodingFactory.create(report=report, code=code, system=system)
        return report

    return _make


@pytest.fixture
def make_lab() -> Callable[..., Any]:
    """Build a lab value on a report for a patient, coded and dated."""

    def _make(patient: Patient, code: str, when: date, system: str = LOINC) -> Any:
        report = LabReportFactory.create(
            patient=patient,
            date_performed=datetime(when.year, when.month, when.day, tzinfo=UTC),
        )
        value = LabValueFactory.create(report=report)
        LabValueCodingFactory.create(value=value, code=code, system=system)
        return value

    return _make


@pytest.fixture
def make_questionnaire() -> Callable[..., Questionnaire]:
    """Build an active questionnaire addressed by code."""

    def _make(code: str, name: str = "Screening", code_system: str = "LOINC") -> Questionnaire:
        return Questionnaire.objects.create(
            status="AC",
            name=name,
            code=code,
            code_system=code_system,
            expected_completion_time=1.0,
            can_originate_in_charting=True,
            use_case_in_charting="QUES",
            scoring_function_name="",
            scoring_code_system="",
            scoring_code="",
            search_tags="",
            use_in_shx=False,
            carry_forward="",
        )

    return _make


@pytest.fixture
def make_interview(make_questionnaire: Callable[..., Questionnaire]) -> Callable[..., Interview]:
    """Build a committed interview for a questionnaire, backdated by age_days."""

    def _make(patient: Patient, code: str, age_days: int = 0) -> Interview:
        questionnaire = make_questionnaire(code)
        interview = Interview.objects.create(
            deleted=False,
            committer=CanvasUserFactory.create(),
            status="AC",
            name=questionnaire.name,
            language_id=0,
            use_case_in_charting="QUES",
            patient=patient,
            note_id=0,
            appointment_id=0,
            progress_status="CO",
        )
        interview.questionnaires.add(questionnaire)
        if age_days:
            # `created` is auto_now_add, so it can only be backdated with update().
            Interview.objects.filter(pk=interview.pk).update(
                created=datetime.now(UTC) - timedelta(days=age_days)
            )
            interview.refresh_from_db()
        return interview

    return _make


@pytest.fixture
def make_snooze() -> Callable[..., Any]:
    """Snooze one of our cards for a patient, until a given date.

    `protocol_key` is our own card key - `preventive_screening:<screening id>` -
    because that is what Canvas records when a provider snoozes our card.
    """

    def _make(
        patient: Patient,
        protocol_key: str,
        until: date,
        *,
        status: str = "active",
        deleted: bool = False,
        is_snooze: bool = True,
        entered_in_error: bool = False,
    ) -> Any:
        return ProtocolOverrideFactory.create(
            patient=patient,
            protocol_key=protocol_key,
            is_snooze=is_snooze,
            snooze_date=until,
            status=status,
            deleted=deleted,
            entered_in_error=CanvasUserFactory.create() if entered_in_error else None,
        )

    return _make


@pytest.fixture
def make_condition() -> Callable[..., Condition]:
    """Build a committed condition on the patient's problem list."""

    def _make(patient: Patient, code: str, onset: date, system: str = SNOMED) -> Condition:
        condition = Condition.objects.create(
            deleted=False,
            committer=CanvasUserFactory.create(),
            patient=patient,
            onset_date=onset,
            # The SDK model declares resolution_date non-null, so the test
            # database requires a value. Nothing in this plugin reads it.
            resolution_date=onset,
            clinical_status="active",
            notes="",
            surgical=False,
        )
        ConditionCoding.objects.create(condition=condition, code=code, system=system, display="")
        return condition

    return _make
