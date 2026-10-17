"""What a submitted questionnaire puts in front of the prescriber."""

import json

from canvas_sdk.v1.data import (
    Interview,
    InterviewQuestionResponse,
    Questionnaire,
)
from canvas_sdk.v1.data.questionnaire import Question

from medication_followup_protocol.handlers.interview_router import InterviewRouter
from medication_followup_protocol.models import StepKind, StepStatus
from tests.conftest import make, make_event


def kind_of(effect) -> str:
    """The name of an effect's type."""
    from canvas_generated.messages.effects_pb2 import EffectType

    return EffectType.Name(effect.type)


def payload(effect):
    """The data an effect carries."""
    return json.loads(effect.payload)["data"]


def submitted(patient, questionnaire, answers):
    """An interview for this patient, carrying the answers they gave."""
    interview = make(Interview, patient=patient, progress_status="F")
    interview.questionnaires.add(questionnaire)
    for content, given in answers:
        question = make(Question, questionnaire=questionnaire, name=content)
        make(
            InterviewQuestionResponse,
            interview=interview,
            questionnaire=questionnaire,
            question=question,
            response_option_value=given,
        )
    return interview


def route(interview):
    """Drive the router over a created interview."""
    event = make_event("INTERVIEW_CREATED", target=str(interview.id))
    return InterviewRouter(event).compute()


def test_a_submitted_questionnaire_raises_a_task_on_the_prescriber(
    enrolment, add_step, patient, staff
):
    """Covers scenario: AC12, a submitted questionnaire raises a task on the prescriber. Covers criterion: AC12."""
    questionnaire = make(Questionnaire, name="Tolerability check in")
    step = add_step(kind=StepKind.QUESTIONNAIRE, questionnaire_id=str(questionnaire.id))
    step.status = StepStatus.FIRED
    step.save()

    interview = submitted(
        patient,
        questionnaire,
        [("How often have you felt sick?", "Most days"), ("Still taking it?", "Yes")],
    )

    effects = route(interview)

    tasks = [e for e in effects if kind_of(e) == "CREATE_TASK"]
    comments = [e for e in effects if kind_of(e) == "CREATE_TASK_COMMENT"]
    assert len(tasks) == 1
    assert payload(tasks[0])["assignee"]["id"] == staff.id
    assert payload(tasks[0])["patient"]["id"] == patient.id

    body = payload(comments[0])["body"]
    assert "How often have you felt sick?" in body
    assert "Most days" in body
    assert "Yes" in body

    step.refresh_from_db()
    assert step.interview_id == str(interview.id)


def test_a_questionnaire_no_step_is_waiting_for_raises_nothing(enrolment, patient):
    """Covers criterion: AC12."""
    questionnaire = make(Questionnaire, name="Something else entirely")
    interview = submitted(patient, questionnaire, [("Anything", "Nothing")])

    assert route(interview) == []
