"""Builders for the patient records the eCQM protocols read, for database-backed tests.

An identical copy lives in each eCQM plugin's tests, alongside ``ecqm_common``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import arrow
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType
from canvas_sdk.test_utils.factories import (
    CanvasUserFactory,
    ImagingReportCodingFactory,
    ImagingReportFactory,
    LabReportFactory,
    LabValueCodingFactory,
    LabValueFactory,
    MedicationFactory,
    NoteFactory,
    PatientFactory,
    ProcedureCodingFactory,
    ProcedureFactory,
    ReferralReportCodingFactory,
    ReferralReportFactory,
)
from canvas_sdk.v1.data.billing import BillingLineItem
from canvas_sdk.v1.data.condition import Condition, ConditionCoding
from canvas_sdk.v1.data.instruction import Instruction, InstructionCoding
from canvas_sdk.v1.data.medication import MedicationCoding
from canvas_sdk.v1.data.observation import Observation, ObservationCoding, ObservationValueCoding
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.questionnaire import (
    Interview,
    InterviewQuestionnaireMap,
    InterviewQuestionResponse,
    Question,
    Questionnaire,
    ResponseOption,
    ResponseOptionSet,
)

LOINC = "http://loinc.org"
SNOMEDCT = "http://snomed.info/sct"
CPT = "http://www.ama-assn.org/go/cpt"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICD10 = "ICD-10"

NOW = arrow.get("2027-06-15T12:00:00+00:00")


def at(value: str) -> datetime:
    """An aware datetime for an ISO date such as ``2027-03-01``."""
    return arrow.get(value).datetime


def patient(birth_date: str = "1970-01-01", sex_at_birth: str = "F") -> Patient:
    """A patient with the given birth date and sex at birth."""
    return PatientFactory.create(birth_date=date.fromisoformat(birth_date), sex_at_birth=sex_at_birth)


# Canvas stores an unresolved condition or an ongoing medication with a NULL end date, but
# the SDK test schema declares those columns NOT NULL, so open records here end far in the future.
OPEN = "9999-12-31"


def condition(
    who: Patient,
    system: str,
    code: str,
    onset: str = "2020-01-01",
    resolved: str = OPEN,
    surgical: bool = False,
) -> Condition:
    """A committed condition with one coding."""
    row = Condition.objects.create(
        patient=who,
        deleted=False,
        committer=CanvasUserFactory.create(),
        onset_date=date.fromisoformat(onset),
        resolution_date=date.fromisoformat(resolved),
        clinical_status="active" if resolved == OPEN else "resolved",
        notes="",
        surgical=surgical,
    )
    ConditionCoding.objects.create(condition=row, system=system, code=code, display=code)
    return row


def visit(who: Patient, code: str, when: str, note: Any = None) -> BillingLineItem:
    """A billing line item for ``code`` on a note dated ``when`` (or on ``note``)."""
    note = note or NoteFactory.create(patient=who, datetime_of_service=at(when))
    return BillingLineItem.objects.create(
        note=note,
        patient=who,
        cpt=code,
        charge=0,
        description=code,
        units=1,
        command_type="",
        command_id=1,
        status="active",
    )


def lab(who: Patient, system: str, code: str, value: str, when: str) -> None:
    """A lab result: a report dated ``when`` with one coded value."""
    report = LabReportFactory.create(patient=who, original_date=at(when), junked=False)
    result = LabValueFactory.create(report=report, value=value)
    LabValueCodingFactory.create(value=result, system=system, code=code)


def observation(who: Patient, code: str, result: str, when: str) -> None:
    """A committed observation coded ``code`` (LOINC) with value coding ``result``."""
    row = Observation.objects.create(
        patient=who,
        committer=CanvasUserFactory.create(),
        category="",
        units="",
        value="",
        note_id=0,
        name=code,
        effective_datetime=at(when),
    )
    ObservationCoding.objects.create(observation=row, system=LOINC, code=code, display=code)
    ObservationValueCoding.objects.create(observation=row, system=SNOMEDCT, code=result, display=result)


def questionnaire_answer(
    who: Patient,
    questionnaire_code: str,
    question_code: str,
    response_code: str,
    when: str,
) -> None:
    """A committed interview of a LOINC-coded questionnaire answering one coded question."""
    option_set = ResponseOptionSet.objects.create(
        status="AC", name="", code_system="", code="", type="SING", use_in_shx=False
    )
    option = ResponseOption.objects.create(
        status="AC",
        name=response_code,
        code=response_code,
        code_description="",
        value=response_code,
        response_option_set=option_set,
        ordering=0,
    )
    question = Question.objects.create(
        status="AC",
        name=question_code,
        response_option_set=option_set,
        acknowledge_only=False,
        show_prologue=False,
        code_system=LOINC,
        code=question_code,
    )
    questionnaire = Questionnaire.objects.create(
        status="AC",
        name=questionnaire_code,
        expected_completion_time=0,
        can_originate_in_charting=True,
        use_case_in_charting="QUES",
        scoring_function_name="",
        scoring_code_system="",
        scoring_code="",
        code_system=LOINC,
        code=questionnaire_code,
        search_tags="",
        use_in_shx=False,
        carry_forward="",
    )
    interview = Interview.objects.create(
        patient=who,
        deleted=False,
        committer=CanvasUserFactory.create(),
        status="AC",
        name=questionnaire_code,
        language_id=1,
        use_case_in_charting="QUES",
        note_id=1,
        appointment_id=1,
        progress_status="F",
    )
    Interview.objects.filter(pk=interview.pk).update(created=at(when))
    InterviewQuestionnaireMap.objects.create(status="AC", interview=interview, questionnaire=questionnaire)
    InterviewQuestionResponse.objects.create(
        status="AC",
        interview=interview,
        questionnaire=questionnaire,
        question=question,
        response_option=option,
        response_option_value=response_code,
        questionnaire_state="",
        interview_state="",
        comment="",
    )


def medication(who: Patient, code: str, start: str, end: str = OPEN) -> None:
    """A committed medication (RxNorm ``code``) active from ``start`` to ``end``."""
    row = MedicationFactory.create(patient=who, start_date=at(start), end_date=at(end))
    MedicationCoding.objects.create(medication=row, system=RXNORM, code=code, display=code)


def instruction(who: Patient, system: str, code: str, when: str) -> None:
    """A committed instruction with one coding on a note dated ``when``."""
    note = NoteFactory.create(patient=who, datetime_of_service=at(when))
    row = Instruction.objects.create(
        patient=who, note=note, committer=CanvasUserFactory.create(), narrative=""
    )
    InstructionCoding.objects.create(instruction=row, system=system, code=code, display=code)


def procedure(who: Patient, system: str, code: str, when: str) -> None:
    """A committed procedure with one coding on a note dated ``when``."""
    note = NoteFactory.create(patient=who, datetime_of_service=at(when))
    row = ProcedureFactory.create(patient=who, note=note, committer=CanvasUserFactory.create())
    ProcedureCodingFactory.create(procedure=row, system=system, code=code)


def referral_report(who: Patient, system: str, code: str, when: str) -> None:
    """A referral report dated ``when`` with one coding."""
    report = ReferralReportFactory.create(patient=who, original_date=date.fromisoformat(when), junked=False)
    ReferralReportCodingFactory.create(report=report, system=system, code=code)


def imaging_report(who: Patient, system: str, code: str, when: str) -> None:
    """An imaging report dated ``when`` with one coding."""
    report = ImagingReportFactory.create(patient=who, original_date=date.fromisoformat(when), junked=False)
    ImagingReportCodingFactory.create(report=report, system=system, code=code)


def build(protocol_class: type, who: Patient, now: arrow.Arrow = NOW) -> Any:
    """A protocol for a patient-updated event on ``who``, evaluated at ``now``."""
    request = EventRequest(
        type=EventType.PATIENT_UPDATED, target=str(who.id), context=json.dumps({})
    )
    protocol = protocol_class(event=Event(request))
    protocol.now = now
    return protocol


def card(effects: list[Any]) -> dict[str, Any]:
    """The protocol card payload of a single ADD_OR_UPDATE_PROTOCOL_CARD effect."""
    assert len(effects) == 1
    return json.loads(effects[0].payload)["data"]
