"""The daily walk. Evaluates conditions and fires whatever is due.

The firing of a step is a strategy per kind rather than a chain of ifs. The walk itself
knows only the registry below and never names a kind, so a fourth kind of step is a new
function and one new row in FIRE_STEP.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Callable

import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.message import Message
from canvas_sdk.effects.task import AddTask, AddTaskComment
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data import BusinessLine, Patient, Staff
from logger import log

from medication_followup_protocol.models import (
    EnrolledStep,
    Enrollment,
    EnrollmentStatus,
    StepKind,
    StepStatus,
)
from medication_followup_protocol.services.banner import remove_banner
from medication_followup_protocol.services.conditions import UnknownCondition, holds
from medication_followup_protocol.services.practice_time import to_practice_date

#: A step still pending this many days after its due date is skipped rather than fired
#: late. A message about week two arriving in week five is worse than no message.
OVERDUE_DAYS = 7


class StepOutcome:
    """What firing one step produced. The status the step lands on and what to emit.

    A plain class rather than a dataclass, because the decorator reaches for dunder
    attributes the plugin sandbox does not allow and the handler fails to load.
    """

    def __init__(self, status: str, effects: list[Effect] | None = None, reason: str = "") -> None:
        self.status = status
        self.effects = effects or []
        self.reason = reason


def _booking_address() -> str:
    """The patient portal address, composed from the active business line subdomain.

    The path that lands a patient directly on the booking form is an open question in the
    specification, section 7 item 2, so the message carries the portal address and the
    wording tells the patient where to go. When that path is settled this is where it goes.
    """
    business_line = BusinessLine.objects.filter(active=True).first()
    if business_line is None or not business_line.subdomain:
        return ""
    return f"https://{business_line.subdomain}.canvasmedical.com/"


def _message_body(step: EnrolledStep) -> str:
    """The wording a message step sends, read live off the class rather than copied.

    Reading it here rather than at enrolment is what makes an edit to the wording reach a
    patient already running on the class.
    """
    body = step.program_step.message_body
    if step.program_step.attach_booking_link:
        address = _booking_address()
        if address:
            body = f"{body}\n\nYou can book your appointment in your patient portal, {address}"
    return body


def _resolve_sender(enrollment: Enrollment) -> str:
    """Which staff member a step fires as, decided fresh each time rather than copied.

    The class names who its messages come from, and that name is read live so an edit to
    it reaches every enrolment already running. The class's sender is used only while that
    Staff row is still active, because a message carrying the name of somebody who has left
    the practice is worse than one carrying the prescriber's name instead. A programme going
    silent is worse still, which is why this always resolves to somebody rather than failing.
    """
    class_sender_id = enrollment.medication_class.sender_staff_id
    if class_sender_id:
        sender = Staff.objects.filter(id=class_sender_id, active=True).first()
        if sender is not None:
            return sender.id
    return enrollment.prescriber_staff.id


def _fire_message(step: EnrolledStep, enrollment: Enrollment, patient: Patient) -> StepOutcome:
    """Send the patient the wording the practice wrote."""
    body = _message_body(step)
    if not body.strip():
        return StepOutcome(StepStatus.FAILED, reason="The step carries no wording to send.")

    sender_id = _resolve_sender(enrollment)
    step.sent_as_staff_id = sender_id
    effect = Message(
        content=body,
        sender_id=sender_id,
        recipient_id=patient.id,
    ).create_and_send()
    # The platform creates the message row when it applies this effect and hands back no
    # identifier, so nothing here can populate EnrolledStep.message_id. See the report,
    # this is where the specification's step 21 does not survive the SDK.
    return StepOutcome(StepStatus.FIRED, [effect])


def _fire_questionnaire(step: EnrolledStep, enrollment: Enrollment, patient: Patient) -> StepOutcome:
    """Go live in the portal and tell the patient a form is waiting.

    No FormResult is emitted here. That effect only means anything in answer to the portal
    asking which forms to show, which PortalForms handles.
    """
    if not step.program_step.questionnaire_id:
        return StepOutcome(StepStatus.FAILED, reason="The step names no questionnaire.")

    body = step.program_step.message_body or (
        "A short form is waiting for you in your patient portal."
    )
    sender_id = _resolve_sender(enrollment)
    step.sent_as_staff_id = sender_id
    effect = Message(
        content=body,
        sender_id=sender_id,
        recipient_id=patient.id,
    ).create_and_send()
    return StepOutcome(StepStatus.FIRED, [effect])


def _fire_task(step: EnrolledStep, enrollment: Enrollment, patient: Patient) -> StepOutcome:
    """Raise the task for the team or the person the practice named.

    The task effect carries a title and no body, so the wording the practice wrote for the
    step becomes a comment on the task. The identifier is minted here so the comment can
    name the task it belongs to in the same batch of effects. A step naming neither a team
    nor a person falls back to the class's own owner team, because a task raised to nobody
    is a task nobody ever sees.
    """
    program_step = step.program_step
    if not program_step.task_title:
        return StepOutcome(StepStatus.FAILED, reason="The step carries no task title.")

    team_id = program_step.assignee_team_id or None
    staff_id = program_step.assignee_staff_id or None
    if not team_id and not staff_id:
        team_id = enrollment.medication_class.owner_team_id or None

    task_id = str(uuid.uuid4())
    # Exactly one of the two, because a task assigned to both is a task nobody owns.
    effects = [
        AddTask(
            id=task_id,
            title=program_step.task_title,
            patient_id=patient.id,
            team_id=team_id,
            assignee_id=(None if team_id else staff_id),
        ).apply()
    ]
    if program_step.task_body:
        effects.append(AddTaskComment(task_id=task_id, body=program_step.task_body).apply())

    return StepOutcome(StepStatus.FIRED, effects)


#: The registry. One entry per kind of step. The walk below never names a kind.
FIRE_STEP: dict[str, Callable[[EnrolledStep, Enrollment, Patient], StepOutcome]] = {
    StepKind.MESSAGE: _fire_message,
    StepKind.QUESTIONNAIRE: _fire_questionnaire,
    StepKind.TASK: _fire_task,
}


class ProgramWalker(CronTask):
    """Once a day, walk every active enrolment and fire whatever is due."""

    #: Five fields, once a day, a little after midnight in the practice timezone.
    SCHEDULE = "10 0 * * *"

    def execute(self) -> list[Effect]:
        """Walk the active enrolments.

        This runs over every active enrolment in the practice, so the reads are batched
        rather than done per row. One query for the enrolments, one for their patients,
        and the prescriber and the class are joined in, because a walk that costs a
        handful of queries per enrolment works on a development instance and falls over
        on a real practice.
        """
        today = to_practice_date(arrow.get(self.event.target.id).datetime)
        effects: list[Effect] = []

        enrollments = list(
            Enrollment.objects.filter(status=EnrollmentStatus.ACTIVE).select_related(
                "prescriber_staff", "medication_class"
            )
        )
        patients = {
            patient.dbid: patient
            for patient in Patient.objects.filter(
                dbid__in={enrollment.patient_id for enrollment in enrollments}
            )
        }

        for enrollment in enrollments:
            effects.extend(
                self._walk_enrollment(enrollment, today, patients.get(enrollment.patient_id))
            )

        return effects

    def _walk_enrollment(
        self, enrollment: Enrollment, today: datetime.date, patient: Patient | None
    ) -> list[Effect]:
        """Fire what is due on one enrolment, guarding the patient first."""

        # The patient guard, before any step fires. The platform sends a message to a
        # patient who has died, because it checks only that the recipient exists, so this
        # check is the plugin's own and it is the reason nothing below runs without it.
        if patient is None or not patient.active or patient.deceased:
            enrollment.status = EnrollmentStatus.STOPPED
            enrollment.stopped_reason = (
                "The patient is deceased." if patient is not None and patient.deceased
                else "The patient is no longer active."
            )
            enrollment.save()
            log.info(
                f"medication follow up, stopped enrolment {enrollment.dbid}, "
                f"{enrollment.stopped_reason}"
            )
            # Behaviour step 49. Every route off active status removes the chart
            # banner, and this guard is one of them, so it takes the same
            # remove_banner call the staff initiated stop path already applies.
            # Skipped when the enrolment never carried a banner_key at all, the
            # same way an enrolment with no recorded start_note_dbid renders its
            # note name with no link rather than one to nothing, since there is
            # nothing on the chart for an empty key to remove.
            return [remove_banner(enrollment)] if enrollment.banner_key else []

        effects: list[Effect] = []
        # The content of every due step is read live off the class, so join it rather
        # than fetching one row per step. Queried against EnrolledStep directly, because
        # the sandbox does not hand back Django reverse related managers.
        due = (
            EnrolledStep.objects.filter(
                enrollment__dbid=enrollment.dbid,
                status=StepStatus.PENDING,
                due_date__lte=today,
            )
            .select_related("program_step")
            .order_by("day_offset", "sequence")
        )

        for step in due:
            effects.extend(self._fire(step, enrollment, patient, today))

        effects.extend(self._settle(enrollment, patient))
        return effects

    def _fire(
        self,
        step: EnrolledStep,
        enrollment: Enrollment,
        patient: Patient,
        today: datetime.date,
    ) -> list[Effect]:
        """Decide whether one due step fires, and fire it."""
        try:
            should_fire = holds(step.condition, enrollment)
        except UnknownCondition:
            step.status = StepStatus.FAILED
            step.failure_reason = f"The step carries an unknown condition, {step.condition}."
            step.save()
            return []

        if not should_fire:
            step.status = StepStatus.SKIPPED
            step.failure_reason = "The recheck is already booked."
            step.save()
            return []

        if (today - step.due_date).days > OVERDUE_DAYS:
            step.status = StepStatus.SKIPPED
            step.failure_reason = (
                f"It was due on {step.due_date} and more than {OVERDUE_DAYS} days have passed."
            )
            step.save()
            return []

        outcome = FIRE_STEP[step.kind](step, enrollment, patient)
        step.status = outcome.status
        step.failure_reason = outcome.reason
        if outcome.status == StepStatus.FIRED:
            step.fired_at = datetime.datetime.now(datetime.timezone.utc)
        step.save()
        return outcome.effects

    def _settle(self, enrollment: Enrollment, patient: Patient | None) -> list[Effect]:
        """Complete an enrolment whose steps have all left pending.

        One task per finished enrolment naming every step that never landed, rather than
        one on the day of each failure, so a person hears about it once with the whole
        picture while there is still time to act.
        """
        steps = list(EnrolledStep.objects.filter(enrollment__dbid=enrollment.dbid))
        if not steps or any(step.status == StepStatus.PENDING for step in steps):
            return []

        enrollment.status = EnrollmentStatus.COMPLETED
        enrollment.save()
        # Behaviour step 49. Completing is one of the routes off active status, so the
        # banner comes down here too, whether or not a failure task follows below.
        # Skipped when the enrolment never carried a banner_key, the same guard the
        # deceased and inactive path above applies, since there is nothing on the
        # chart for an empty key to remove.
        effects: list[Effect] = [remove_banner(enrollment)] if enrollment.banner_key else []

        failed = [step for step in steps if step.status == StepStatus.FAILED]
        if not failed:
            return effects

        patient = Patient.objects.filter(dbid=enrollment.patient_id).first()
        task_id = str(uuid.uuid4())
        lines = "\n".join(
            f"Day {step.day_offset}, {step.kind}, {step.failure_reason}" for step in failed
        )
        # The class's owner team first, and only when it names none does this fall back
        # to the enrolment's prescriber. Exactly one of the two, the same rule a task step
        # follows, because a task assigned to both is a task nobody owns.
        owner_team_id = enrollment.medication_class.owner_team_id or None
        effects.extend(
            [
                AddTask(
                    id=task_id,
                    title=(
                        "Follow up programme finished with steps that never delivered, "
                        f"{enrollment.medication_label}"
                    ),
                    patient_id=patient.id if patient else None,
                    team_id=owner_team_id,
                    assignee_id=(None if owner_team_id else enrollment.prescriber_staff.id),
                ).apply(),
                AddTaskComment(
                    task_id=task_id,
                    body=f"These steps never reached the patient.\n{lines}",
                ).apply(),
            ]
        )
        return effects
