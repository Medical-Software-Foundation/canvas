"""Turns a submitted programme questionnaire into a task on the prescribing provider."""

from __future__ import annotations

import uuid

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Interview, InterviewQuestionResponse

from medication_followup_protocol.models import (
    EnrolledStep,
    EnrollmentStatus,
    StepKind,
    StepStatus,
)


def answers_of(interview: Interview) -> str:
    """The answers a patient gave, as the prescriber reads them on the task."""
    responses = (
        InterviewQuestionResponse.objects.filter(interview=interview)
        .select_related("question")
        .order_by("dbid")
    )
    lines = []
    for response in responses:
        question = response.question.name if response.question else ""
        given = response.response_option_value or response.comment or ""
        lines.append(f"{question}\n{given}")
    return "\n\n".join(lines)


class InterviewRouter(BaseHandler):
    """On a submitted programme questionnaire, raise the task carrying the answers."""

    RESPONDS_TO = EventType.Name(EventType.INTERVIEW_CREATED)

    def compute(self) -> list[Effect]:
        """Match the interview to a live step and raise the task on the prescriber."""
        interview = Interview.objects.filter(id=self.event.target.id).first()
        if interview is None:
            return []

        questionnaire_ids = {str(q.id) for q in interview.questionnaires.all()}
        if not questionnaire_ids:
            return []

        step = (
            EnrolledStep.objects.filter(
                kind=StepKind.QUESTIONNAIRE,
                status=StepStatus.FIRED,
                interview_id__isnull=True,
                enrollment__status=EnrollmentStatus.ACTIVE,
                enrollment__patient__dbid=interview.patient_id,
                program_step__questionnaire_id__in=questionnaire_ids,
            )
            .select_related("enrollment", "program_step")
            .first()
        )
        if step is None:
            return []

        step.interview_id = str(interview.id)
        step.save()

        enrollment = step.enrollment
        task_id = str(uuid.uuid4())
        # The task effect carries a title and no body, so the answers become a comment on
        # the task rather than being lost. The prescriber reads them without opening
        # anything else, which is the whole point of the questionnaire route.
        return [
            AddTask(
                id=task_id,
                title=f"Tolerability check in, {enrollment.medication_label}",
                patient_id=enrollment.patient.id,
                assignee_id=enrollment.prescriber_staff.id,
            ).apply(),
            AddTaskComment(task_id=task_id, body=answers_of(interview)).apply(),
        ]
