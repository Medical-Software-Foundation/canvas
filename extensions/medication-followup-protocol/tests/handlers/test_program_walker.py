"""The daily walk. Eight criteria and eight scenarios ride on this handler."""

import datetime
import json

import pytest
from canvas_sdk.test_utils.factories import NoteTypeFactory, TeamFactory
from canvas_sdk.v1.data import Appointment

from medication_followup_protocol.handlers.program_walker import ProgramWalker
from medication_followup_protocol.models import (
    EnrollmentStatus,
    StepKind,
    StepStatus,
)
from medication_followup_protocol.services.conditions import RECHECK_NOT_BOOKED
from tests.conftest import make_event

WALK_DAY = datetime.date(2026, 8, 15)


def walk(on: datetime.date = WALK_DAY):
    """Run the daily walk as though the scheduler fired it on this date."""
    event = make_event("CRON", target=f"{on.isoformat()}T00:10:00+00:00")
    return ProgramWalker(event).compute()


def payload(effect):
    """The data an effect carries."""
    return json.loads(effect.payload)["data"]


def kind_of(effect) -> str:
    """The name of an effect's type. The wire form is a protobuf enum, so an integer."""
    from canvas_generated.messages.effects_pb2 import EffectType

    return EffectType.Name(effect.type)


def test_message_step_due_today_sends_to_the_patient(enrolment, add_step, patient, staff):
    """Covers scenario: AC6, a message step due today sends to the patient. Covers criterion: AC6."""
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="How are you getting on?")

    effects = walk()

    assert len(effects) == 1
    sent = payload(effects[0])
    assert sent["sender_id"] == staff.id
    assert sent["recipient_id"] == patient.id
    assert sent["content"] == "How are you getting on?"
    step.refresh_from_db()
    assert step.status == StepStatus.FIRED
    assert step.fired_at is not None


def test_a_fired_message_uses_the_classs_named_sender_when_active(
    enrolment, add_step, medication_class
):
    """Covers criterion: AC6.

    The class names who its messages come from, and that name is read live rather than a
    name copied onto the enrolment at the start, so a step sends under the class's own
    sender when one is named and still active.
    """
    from canvas_sdk.test_utils.factories import StaffFactory

    sender = StaffFactory(active=True)
    medication_class.sender_staff_id = str(sender.id)
    medication_class.save()
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="How are you getting on?")

    effects = walk()

    assert payload(effects[0])["sender_id"] == sender.id
    step.refresh_from_db()
    assert step.sent_as_staff_id == sender.id


def test_a_fired_message_falls_back_to_the_prescriber_when_the_class_names_no_sender(
    enrolment, add_step, staff
):
    """Covers criterion: AC6."""
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="How are you getting on?")

    effects = walk()

    assert payload(effects[0])["sender_id"] == staff.id
    step.refresh_from_db()
    assert step.sent_as_staff_id == staff.id


def test_a_fired_message_falls_back_to_the_prescriber_when_the_classs_sender_has_left(
    enrolment, add_step, medication_class, staff
):
    """Covers criterion: AC6.

    A programme going silent is worse than a message carrying a name nobody answers to,
    so a class sender who is no longer active falls back to the enrolment's prescriber
    rather than the step failing.
    """
    from canvas_sdk.test_utils.factories import StaffFactory

    departed = StaffFactory(active=False)
    medication_class.sender_staff_id = str(departed.id)
    medication_class.save()
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="How are you getting on?")

    effects = walk()

    assert payload(effects[0])["sender_id"] == staff.id
    step.refresh_from_db()
    assert step.sent_as_staff_id == staff.id


def test_a_fired_questionnaire_records_who_it_was_sent_as(enrolment, add_step, staff):
    """Covers criterion: AC11."""
    step = add_step(
        kind=StepKind.QUESTIONNAIRE, due_date=WALK_DAY, questionnaire_id="questionnaire-1"
    )

    walk()

    step.refresh_from_db()
    assert step.sent_as_staff_id == staff.id


def test_a_task_step_with_no_assignee_falls_back_to_the_classs_owner_team(
    enrolment, add_step, medication_class
):
    """Covers criterion: AC7.

    A task step naming neither a team nor a person still has to reach somebody, so it
    falls back to the team the class itself names as owning the programme.
    """
    team = TeamFactory(name="Nursing")
    medication_class.owner_team_id = str(team.id)
    medication_class.save()
    add_step(kind=StepKind.TASK, due_date=WALK_DAY, task_title="Check in")

    effects = walk()

    task = payload(effects[0])
    assert task["team"]["id"] == str(team.id)
    assert task["assignee"]["id"] is None


def test_a_task_step_naming_an_assignee_ignores_the_classs_owner_team(
    enrolment, add_step, medication_class, patient
):
    """Covers criterion: AC7.

    The owner team is a fallback for a step that names nobody, never a second choice
    layered on top of one the step already names.
    """
    from canvas_sdk.test_utils.factories import StaffFactory

    owner_team = TeamFactory(name="Nursing")
    medication_class.owner_team_id = str(owner_team.id)
    medication_class.save()
    nurse = StaffFactory(active=True)
    add_step(kind=StepKind.TASK, due_date=WALK_DAY, task_title="Check in",
             assignee_staff_id=str(nurse.id))

    effects = walk()

    task = payload(effects[0])
    assert task["assignee"]["id"] == str(nurse.id)
    assert task["team"]["id"] is None


def test_the_completion_task_goes_to_the_classs_owner_team_when_one_is_named(
    enrolment, add_step, medication_class
):
    """Covers criterion: AC14.

    The completion task no longer names the sender. It goes to the class's owner team
    first, and only falls back to the enrolment's prescriber when the class names none.
    """
    team = TeamFactory(name="Nursing")
    medication_class.owner_team_id = str(team.id)
    medication_class.save()
    failed = add_step(kind=StepKind.MESSAGE, day_offset=0, due_date=WALK_DAY, message_body="Day zero")
    failed.status = StepStatus.FAILED
    failed.failure_reason = "No portal account."
    failed.save()

    effects = walk()

    tasks = [e for e in effects if kind_of(e) == "CREATE_TASK"]
    assert len(tasks) == 1
    assert payload(tasks[0])["team"]["id"] == str(team.id)
    assert payload(tasks[0])["assignee"]["id"] is None


def test_task_step_due_today_raises_a_task_for_the_team(enrolment, add_step, patient):
    """Covers scenario: AC7, a task step due today raises a task for the named team. Covers criterion: AC7."""
    team = TeamFactory(name="Scheduling")
    add_step(
        kind=StepKind.TASK,
        due_date=WALK_DAY,
        task_title="Phone the patient to book",
        assignee_team_id=str(team.id),
    )

    effects = walk()

    task = payload(effects[0])
    assert task["title"] == "Phone the patient to book"
    assert task["team"]["id"] == str(team.id)
    assert task["assignee"]["id"] is None
    assert task["patient"]["id"] == patient.id


def test_conditional_step_is_skipped_once_a_recheck_is_booked(enrolment, add_step, patient):
    """Covers scenario: AC8, a step conditional on the recheck is skipped once one is booked. Covers criterion: AC8."""
    note_type = NoteTypeFactory(id=enrolment.recheck_note_type_id)
    Appointment.objects.create(
        patient=patient,
        note_type=note_type,
        start_time=datetime.datetime(2026, 8, 20, 9, 0, tzinfo=datetime.timezone.utc),
        status="confirmed",
        duration_minutes=20,
        telehealth_instructions_sent=False,
        meeting_link="",
    )
    step = add_step(
        kind=StepKind.MESSAGE,
        due_date=WALK_DAY,
        condition=RECHECK_NOT_BOOKED,
        message_body="Time to book your recheck",
    )

    effects = walk()

    assert effects == []
    step.refresh_from_db()
    assert step.status == StepStatus.SKIPPED
    assert step.failure_reason


def test_the_same_step_fires_while_no_recheck_is_booked(enrolment, add_step):
    """Covers scenario: AC9, the same step fires while no recheck is booked. Covers criterion: AC9."""
    step = add_step(
        kind=StepKind.MESSAGE,
        due_date=WALK_DAY,
        condition=RECHECK_NOT_BOOKED,
        message_body="Time to book your recheck",
    )

    effects = walk()

    assert len(effects) == 1
    step.refresh_from_db()
    assert step.status == StepStatus.FIRED


def test_a_program_stops_rather_than_messaging_a_deceased_patient(enrolment, add_step, patient):
    """Covers scenario: AC10, a program stops rather than messaging a deceased patient. Covers criterion: AC10."""
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="How are you getting on?")
    patient.deceased = True
    patient.save()

    effects = walk()

    assert effects == []
    enrolment.refresh_from_db()
    step.refresh_from_db()
    assert enrolment.status == EnrollmentStatus.STOPPED
    assert "deceased" in enrolment.stopped_reason.lower()
    assert step.status == StepStatus.PENDING


def test_an_inactive_patient_stops_the_program_too(enrolment, add_step, patient):
    """Covers criterion: AC10."""
    add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="How are you getting on?")
    patient.active = False
    patient.save()

    assert walk() == []
    enrolment.refresh_from_db()
    assert enrolment.status == EnrollmentStatus.STOPPED


def test_a_finished_program_with_an_undelivered_step_raises_one_task(enrolment, add_step, staff):
    """Covers scenario: AC14, a finished program with an undelivered step raises one task. Covers criterion: AC14."""
    failed = add_step(kind=StepKind.MESSAGE, day_offset=0, due_date=WALK_DAY, message_body="Day zero")
    failed.status = StepStatus.FAILED
    failed.failure_reason = "No portal account."
    failed.save()
    settled = add_step(kind=StepKind.MESSAGE, day_offset=3, due_date=WALK_DAY, message_body="Day three")
    settled.status = StepStatus.SKIPPED
    settled.save()

    effects = walk()

    enrolment.refresh_from_db()
    assert enrolment.status == EnrollmentStatus.COMPLETED
    tasks = [e for e in effects if kind_of(e) == "CREATE_TASK"]
    comments = [e for e in effects if kind_of(e) == "CREATE_TASK_COMMENT"]
    assert len(tasks) == 1
    assert payload(tasks[0])["assignee"]["id"] == staff.id
    assert "Day 0" in payload(comments[0])["body"]
    assert "No portal account." in payload(comments[0])["body"]


def test_an_edit_to_the_wording_reaches_a_running_enrolment(enrolment, add_step):
    """Covers scenario: AC18, an edit to a step's wording reaches an enrolment already running. Covers criterion: AC18."""
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="The old wording")

    # The practice rewrites the step on the class after the patient was enrolled.
    program_step = step.program_step
    program_step.message_body = "The corrected wording"
    program_step.save()

    effects = walk()

    assert payload(effects[0])["content"] == "The corrected wording"


def test_an_edit_to_the_day_offset_does_not_move_a_running_enrolment(enrolment, add_step):
    """Covers scenario: AC19, an edit to a step's day offset does not move an enrolment already running. Covers criterion: AC19."""
    computed = enrolment.start_date + datetime.timedelta(days=28)
    step = add_step(kind=StepKind.MESSAGE, day_offset=28, message_body="Book your recheck")
    assert step.due_date == computed

    # The practice moves the step from day 28 to day 21 on the class.
    program_step = step.program_step
    program_step.day_offset = 21
    program_step.save()

    # Nothing fires on the date the edited offset would give.
    edited = enrolment.start_date + datetime.timedelta(days=21)
    assert walk(on=edited) == []
    step.refresh_from_db()
    assert step.status == StepStatus.PENDING

    # It fires on the date computed at enrolment.
    assert len(walk(on=computed)) == 1
    step.refresh_from_db()
    assert step.status == StepStatus.FIRED
    assert step.due_date == computed


def test_a_step_more_than_a_week_overdue_is_skipped_rather_than_fired_late(enrolment, add_step):
    """Covers criterion: AC6."""
    step = add_step(
        kind=StepKind.MESSAGE,
        due_date=WALK_DAY - datetime.timedelta(days=8),
        message_body="Long overdue",
    )

    assert walk() == []
    step.refresh_from_db()
    assert step.status == StepStatus.SKIPPED


def test_a_stopped_enrolment_is_ignored_by_the_walk(enrolment, add_step):
    """Covers scenario: AC17, stopping a program from the patient scoped pane halts every remaining step. Covers criterion: AC17."""
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="Should never send")
    enrolment.status = EnrollmentStatus.STOPPED
    enrolment.save()

    assert walk() == []
    step.refresh_from_db()
    assert step.status == StepStatus.PENDING


def test_a_questionnaire_step_goes_live_and_tells_the_patient(enrolment, add_step, patient):
    """Covers criterion: AC11."""
    step = add_step(
        kind=StepKind.QUESTIONNAIRE,
        due_date=WALK_DAY,
        questionnaire_id="questionnaire-1",
        message_body="A short form is waiting in your portal.",
    )

    effects = walk()

    # A message, and no FormResult, because that effect only answers the portal asking.
    assert [kind_of(e) for e in effects] == ["CREATE_AND_SEND_MESSAGE"]
    assert payload(effects[0])["recipient_id"] == patient.id
    step.refresh_from_db()
    assert step.status == StepStatus.FIRED


def test_a_message_step_can_carry_the_booking_address(enrolment, add_step):
    """Covers criterion: AC6."""
    from canvas_sdk.test_utils.factories import OrganizationFactory
    from canvas_sdk.v1.data import BusinessLine

    BusinessLine.objects.create(
        name="Main",
        subdomain="examplepractice",
        active=True,
        organization=OrganizationFactory(),
    )
    add_step(
        kind=StepKind.MESSAGE,
        due_date=WALK_DAY,
        message_body="Time to book your recheck",
        attach_booking_link=True,
    )

    content = payload(walk()[0])["content"]

    assert "Time to book your recheck" in content
    assert "examplepractice" in content


def test_a_message_step_with_no_wording_fails_rather_than_sending_nothing(enrolment, add_step):
    """Covers criterion: AC6."""
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="   ")

    effects = walk()

    # Nothing is sent. The enrolment then finishes, so the failure task is raised, which
    # is the same one step 25 raises for any step that never landed.
    assert not [e for e in effects if kind_of(e) == "CREATE_AND_SEND_MESSAGE"]
    step.refresh_from_db()
    assert step.status == StepStatus.FAILED
    assert step.failure_reason


def test_a_step_carrying_an_unknown_condition_fails_rather_than_guessing(enrolment, add_step):
    """Covers criterion: AC8."""
    step = add_step(
        kind=StepKind.MESSAGE, due_date=WALK_DAY, condition="whatever", message_body="Hello"
    )

    effects = walk()

    assert not [e for e in effects if kind_of(e) == "CREATE_AND_SEND_MESSAGE"]
    step.refresh_from_db()
    assert step.status == StepStatus.FAILED


def test_a_task_step_carrying_wording_comments_it_onto_the_task(enrolment, add_step, patient):
    """Covers scenario: AC7, a task step due today raises a task for the named team. Covers criterion: AC7.

    The task effect carries a title and no body, so wording the practice wrote for the step
    becomes a comment against the same task, minted in one batch of effects.
    """
    team = TeamFactory(name="Scheduling")
    add_step(kind=StepKind.TASK, due_date=WALK_DAY, task_title="Phone the patient",
             task_body="Ask how they are tolerating the dose.",
             assignee_team_id=str(team.id))

    effects = walk()

    tasks = [e for e in effects if kind_of(e) == "CREATE_TASK"]
    comments = [e for e in effects if kind_of(e) == "CREATE_TASK_COMMENT"]
    assert len(tasks) == 1 and len(comments) == 1
    assert payload(comments[0])["task"]["id"] == payload(tasks[0])["id"]
    assert payload(comments[0])["body"] == "Ask how they are tolerating the dose."


def test_a_task_step_with_no_title_fails_rather_than_raising_a_nameless_task(enrolment, add_step):
    """Covers criterion: AC7.

    A task with no title is a row in somebody's queue saying nothing, so the step records the
    failure and the practice sees it on the panel instead.
    """
    step = add_step(kind=StepKind.TASK, due_date=WALK_DAY, task_title="")
    # A later step keeps the programme running, so the only effect a walk could produce here
    # is the one this test says must not exist.
    add_step(kind=StepKind.MESSAGE, day_offset=60, sequence=1, message_body="Later")

    assert walk() == []
    step.refresh_from_db()
    assert step.status == StepStatus.FAILED
    assert step.failure_reason == "The step carries no task title."


def test_a_questionnaire_step_naming_no_questionnaire_fails(enrolment, add_step):
    """Covers criterion: AC11.

    AC11 has the portal offering the questionnaire the step carries, so a step carrying none
    has nothing to offer and says so rather than going live over an empty form.
    """
    step = add_step(kind=StepKind.QUESTIONNAIRE, due_date=WALK_DAY, questionnaire_id="")
    add_step(kind=StepKind.MESSAGE, day_offset=60, sequence=1, message_body="Later")

    assert walk() == []
    step.refresh_from_db()
    assert step.status == StepStatus.FAILED
    assert step.failure_reason == "The step names no questionnaire."


def test_a_conditional_step_fires_when_the_class_names_no_recheck_type(enrolment, add_step):
    """Covers criterion: AC9.

    No recheck appointment type means no recheck can be booked, so a step conditional on one
    not being booked still has to fire. Reading it the other way would silently skip every
    step on a class the practice never gave a recheck type.
    """
    enrolment.recheck_note_type_id = ""
    enrolment.save()
    step = add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, condition=RECHECK_NOT_BOOKED,
                    message_body="Book your recheck")

    assert len(walk()) == 1
    step.refresh_from_db()
    assert step.status == StepStatus.FIRED


def test_two_overlapping_programs_both_send_their_day_zero_message(
    enrolment, add_step, patient, staff, medication_class
):
    """Covers scenario: AC35, overlapping programs both send their day zero message with nothing deduplicated. Covers criterion: AC35.

    Two separate Enrollment rows on the same patient and the same medication, one under
    medication_class through the shared fixture and one under a second class created
    here, each carrying its own day zero message step due today. The walk owns no
    notion of two enrolments overlapping on one medication, that decision belongs to
    the write this criterion's sibling, AC31, covers, so this only has to prove the
    walk fires both steps rather than treating the second as a duplicate of the first.
    """
    from medication_followup_protocol.models import (
        EnrolledStep,
        Enrollment,
        MedicationClass,
        ProgramStep,
    )

    add_step(kind=StepKind.MESSAGE, due_date=WALK_DAY, message_body="Welcome to the first program.")

    second_class = MedicationClass.objects.create(
        name="Second program", active=True,
        recheck_note_type_id=medication_class.recheck_note_type_id,
    )
    second_enrolment = Enrollment.objects.create(
        patient_id=patient.dbid, medication_class=second_class,
        medication_label=enrolment.medication_label, sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid, start_date=enrolment.start_date,
        recheck_note_type_id=second_class.recheck_note_type_id,
    )
    second_step = ProgramStep.objects.create(
        medication_class=second_class, sequence=0, day_offset=0, kind=StepKind.MESSAGE,
        message_body="Welcome to the second program.",
    )
    EnrolledStep.objects.create(
        enrollment=second_enrolment, program_step=second_step, sequence=0, day_offset=0,
        kind=StepKind.MESSAGE, due_date=WALK_DAY,
    )

    effects = walk()

    bodies = {payload(e)["content"] for e in effects}
    assert bodies == {"Welcome to the first program.", "Welcome to the second program."}
