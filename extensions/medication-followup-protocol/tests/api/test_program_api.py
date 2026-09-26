"""The read and write surface. Configuration, enrolment and the chart panel payload."""

import base64
import datetime
import json
from http import HTTPStatus

import pytest
from canvas_sdk.test_utils.factories import NoteTypeFactory, StaffFactory, TeamFactory
from canvas_sdk.v1.data import NoteType

from medication_followup_protocol.api.program_api import ProgramAPI
from medication_followup_protocol.models import (
    CoverageKind,
    EnrolledStep,
    Enrollment,
    EnrollmentStatus,
    MedicationClass,
    MedicationClassCoverage,
    ProgramDefaults,
    ProgramStep,
    StepKind,
    StepStatus,
)
from tests.conftest import make_event

PREFIX = "/programme"


def call(method: str, path: str, body: dict | None = None, caller=None):
    """Drive one request all the way through the API, as the platform would."""
    headers = {"Content-Type": "application/json"}
    if caller is not None:
        headers["canvas-logged-in-user-id"] = str(caller.id)
        headers["canvas-logged-in-user-type"] = "Staff"

    full_path, _, query_string = path.partition("?")
    event = make_event(
        "SIMPLE_API_REQUEST",
        context={
            "method": method,
            "path": f"{PREFIX}{full_path}",
            "query_string": query_string,
            "body": base64.b64encode(json.dumps(body or {}).encode()).decode(),
            "headers": headers,
        },
    )
    effects = ProgramAPI(event).compute()
    assert effects, f"{method} {path} produced no response"
    return json.loads(effects[0].payload)


def _effects(method: str, path: str, body: dict | None = None, caller=None) -> list:
    """Every effect one request produced, rather than only the response call() returns.

    call() reads the first item back as the response, which is all most of these tests
    need. The two below are about what rides along beside it, so they drive the same
    request and keep the whole list.
    """
    headers = {"Content-Type": "application/json"}
    if caller is not None:
        headers["canvas-logged-in-user-id"] = str(caller.id)
        headers["canvas-logged-in-user-type"] = "Staff"
    full_path, _, query_string = path.partition("?")
    event = make_event(
        "SIMPLE_API_REQUEST",
        context={
            "method": method,
            "path": f"{PREFIX}{full_path}",
            "query_string": query_string,
            "body": base64.b64encode(json.dumps(body or {}).encode()).decode(),
            "headers": headers,
        },
    )
    return ProgramAPI(event).compute()


def _reload_targets(effects) -> list[str]:
    """The patient each action button reload effect in this list was aimed at."""
    targets = []
    for effect in effects:
        payload = json.loads(effect.payload) if isinstance(effect.payload, str) else effect.payload
        # The reload effect carries its subject under data rather than at the top level,
        # which is how every effect in this list is shaped and not special to this one.
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and data.get("patient_id") and "note_id" in data:
            targets.append(data["patient_id"])
    return targets


def json_body(response) -> dict:
    """The JSON a response carries."""
    return json.loads(base64.b64decode(response["body"]))


def status_of(response) -> int:
    """The status code a response carries."""
    return response["status_code"]


def html_body(response) -> str:
    """The raw markup an HTMLResponse carries, for a page rather than a JSON body."""
    return base64.b64decode(response["body"]).decode()


@pytest.fixture
def lead():
    """A staff member allowed to build a programme."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    staff = StaffFactory(active=True)
    StaffRoleFactory(staff=staff, domain="CLI", domain_privilege_level=5)
    return staff


def test_a_staff_member_creates_a_medication_class(lead):
    """Covers scenario: AC1, a staff member creates a medication class. Covers criterion: AC1."""
    note_type = NoteTypeFactory(name="Follow up, 20 minutes", is_active=True,
                                is_scheduleable_via_patient_portal=True)

    response = call("POST", "/classes",
                    {"name": "GLP-1", "recheck_note_type_id": str(note_type.id)}, caller=lead)

    assert status_of(response) == HTTPStatus.CREATED
    row = MedicationClass.objects.get(name="GLP-1")
    assert row.recheck_note_type_id == str(note_type.id)


def test_a_staff_member_adds_a_step_to_a_class(lead, medication_class):
    """Covers scenario: AC2, a staff member adds a step to a class. Covers criterion: AC2."""
    wording = "Time to book your recheck"

    response = call("POST", f"/classes/{medication_class.dbid}/steps",
                    {"day_offset": 28, "kind": "message", "message_body": wording}, caller=lead)

    assert status_of(response) == HTTPStatus.CREATED
    step = ProgramStep.objects.get(medication_class=medication_class)
    assert step.day_offset == 28
    assert step.kind == StepKind.MESSAGE
    assert step.message_body == wording


def test_the_assignee_picker_offers_every_team_on_the_instance(lead):
    """Covers scenario: AC3, the assignee picker offers every team on the instance. Covers criterion: AC3."""
    for name in ("Nursing", "Scheduling", "Behavioural Health"):
        TeamFactory(name=name)

    offered = json_body(call("GET", "/assignees", caller=lead))

    assert {team["name"] for team in offered["teams"]} == {
        "Nursing", "Scheduling", "Behavioural Health"
    }


def test_the_recheck_picker_offers_only_types_a_patient_can_book(lead):
    """Covers criterion: AC1."""
    NoteTypeFactory(
        name="Bookable", is_active=True, is_scheduleable_via_patient_portal=True,
        online_duration=20,
    )
    NoteTypeFactory(name="Not bookable", is_active=True, is_scheduleable_via_patient_portal=False)
    # Flagged for the portal and left at zero minutes, which the portal itself refuses, so
    # offering it here would put a recheck on the page that no patient could ever book.
    NoteTypeFactory(
        name="No duration", is_active=True, is_scheduleable_via_patient_portal=True,
        online_duration=0,
    )

    offered = json_body(call("GET", "/note-types", caller=lead))

    assert [n["name"] for n in offered["note_types"]] == ["Bookable"]


# --- The practice defaults for a new class
#
# AC1's When is a staff member creating a class, and the create card now carries every choice
# a class holds rather than two of the four, so what that one action stores is part of that
# criterion. The practice default itself describes behaviour AC1 does not, which is recorded
# as a change request in 00-inputs rather than papered over here.


def test_creating_a_class_stores_its_sender_and_its_owning_team(lead):
    """Covers criterion: AC1."""
    sender = StaffFactory(active=True)
    team = TeamFactory(name="Nursing")

    response = call("POST", "/classes", {
        "name": "GLP-1",
        "sender_staff_id": str(sender.id),
        "owner_team_id": str(team.id),
    }, caller=lead)

    assert status_of(response) == HTTPStatus.CREATED
    row = MedicationClass.objects.get(name="GLP-1")
    assert row.sender_staff_id == str(sender.id)
    assert row.owner_team_id == str(team.id)


def test_the_practice_defaults_start_empty(lead):
    """Covers criterion: AC1."""
    stored = json_body(call("GET", "/defaults", caller=lead))

    assert stored == {"sender_staff_id": "", "owner_team_id": ""}


def test_the_practice_defaults_are_read_back_as_they_were_stored(lead):
    """Covers criterion: AC1."""
    sender = StaffFactory(active=True)
    team = TeamFactory(name="Nursing")

    call("PUT", "/defaults", {
        "sender_staff_id": str(sender.id),
        "owner_team_id": str(team.id),
    }, caller=lead)
    stored = json_body(call("GET", "/defaults", caller=lead))

    assert stored == {"sender_staff_id": str(sender.id), "owner_team_id": str(team.id)}


def test_writing_the_defaults_twice_updates_one_row_rather_than_adding_another(lead):
    """Covers criterion: AC1."""
    first = StaffFactory(active=True)
    second = StaffFactory(active=True)

    call("PUT", "/defaults", {"sender_staff_id": str(first.id)}, caller=lead)
    call("PUT", "/defaults", {"sender_staff_id": str(second.id)}, caller=lead)

    assert ProgramDefaults.objects.count() == 1
    stored = json_body(call("GET", "/defaults", caller=lead))
    assert stored["sender_staff_id"] == str(second.id)


def test_writing_one_default_leaves_the_other_alone(lead):
    """Covers criterion: AC1."""
    team = TeamFactory(name="Nursing")
    call("PUT", "/defaults", {"owner_team_id": str(team.id)}, caller=lead)

    # The sender key is absent rather than empty, which the write treats as no opinion. A
    # caller sending one field would otherwise wipe the other by omission.
    call("PUT", "/defaults", {}, caller=lead)

    stored = json_body(call("GET", "/defaults", caller=lead))
    assert stored["owner_team_id"] == str(team.id)


def test_a_caller_who_may_not_configure_cannot_write_the_defaults():
    """Covers criterion: AC1."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)

    response = call("PUT", "/defaults", {"sender_staff_id": "9"}, caller=administrator)

    assert status_of(response) == HTTPStatus.FORBIDDEN
    assert not ProgramDefaults.objects.exists()


def test_changing_a_class_recheck_type_stores_the_new_one(lead, medication_class):
    """Covers criterion: AC1."""
    replacement = NoteTypeFactory(
        name="Lab visit", is_active=True, is_scheduleable_via_patient_portal=True,
        online_duration=15,
    )

    response = call("PATCH", f"/classes/{medication_class.dbid}",
                    {"recheck_note_type_id": str(replacement.id)}, caller=lead)

    assert status_of(response) == HTTPStatus.OK
    medication_class.refresh_from_db()
    assert medication_class.recheck_note_type_id == str(replacement.id)


def test_enrolling_a_patient_schedules_every_step_of_the_class(medication_class, patient, staff):
    """Covers scenario: AC4, enrolling a patient schedules every step of the class. Covers criterion: AC4."""
    offsets = [0, 7, 14, 28, 42]
    for index, offset in enumerate(offsets):
        ProgramStep.objects.create(medication_class=medication_class, sequence=index,
                                   day_offset=offset, kind=StepKind.MESSAGE,
                                   message_body=f"Day {offset}")

    # Keys rather than database ids, because that is what the endpoints this write is fed
    # from actually hand out. The earlier version of this test passed dbid straight through,
    # which is why it passed while every enrolment made from the real form failed on the
    # server. A test that skips the seam between two endpoints cannot see a break in it.
    response = call("POST", "/enrollments", {
        "patient_id": patient.id,
        "medication_class_id": medication_class.dbid,
        "medication_label": "semaglutide",
        "sender_staff_id": staff.id,
        "prescriber_staff_id": staff.id,
    }, caller=staff)

    assert status_of(response) == HTTPStatus.CREATED
    enrolment = Enrollment.objects.get(medication_label="semaglutide")
    steps = list(enrolment.steps.all())
    assert len(steps) == len(offsets)
    for step in steps:
        assert step.due_date == enrolment.start_date + datetime.timedelta(days=step.day_offset)


def test_a_patient_is_not_enrolled_twice_on_the_same_medication(
    medication_class, patient, staff, enrolment
):
    """Covers scenario: AC5, enrolling twice under the same class is refused but a different class on the same medication succeeds. Covers criterion: AC5."""
    response = call("POST", "/enrollments", {
        "patient_id": patient.id,
        "medication_class_id": medication_class.dbid,
        "medication_label": enrolment.medication_label,
        "prescriber_staff_id": staff.id,
    }, caller=staff)

    assert status_of(response) == HTTPStatus.CONFLICT
    assert Enrollment.objects.filter(medication_label=enrolment.medication_label).count() == 1

    # The refusal names the programme already running, because the form offers to stop it and
    # an offer needs something to act on.
    assert json_body(response)["running_enrollment_id"] == enrolment.dbid


def test_the_chart_panel_shows_every_program_a_patient_is_on(
    medication_class, patient, staff, enrolment, add_step
):
    """Covers scenario: AC15, the Follow ups control opens the Ongoing tab showing every program a patient is on. Covers criterion: AC15."""
    add_step(kind=StepKind.MESSAGE, day_offset=0, message_body="Day zero")
    add_step(kind=StepKind.MESSAGE, day_offset=7, message_body="Day seven")
    second = Enrollment.objects.create(
        patient_id=patient.dbid, medication_class=medication_class,
        medication_label="apixaban", sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid, start_date=datetime.date(2026, 8, 5),
    )

    shown = json_body(call("GET", f"/enrollments?patient_id={patient.id}", caller=staff))

    labels = {e["medication_label"] for e in shown["enrollments"]}
    assert labels == {enrolment.medication_label, second.medication_label}
    first = [e for e in shown["enrollments"] if e["id"] == enrolment.dbid][0]
    assert len(first["steps"]) == 2
    for step in first["steps"]:
        assert step["due_date"] and step["status"] and step["summary"]


def test_the_chart_panel_offers_to_enrol_a_patient_who_has_no_program(patient, staff):
    """Covers scenario: AC16, a patient with no enrolment and no eligible prescription shows no banner and no Follow ups control. Covers criterion: AC16."""
    shown = json_body(call("GET", f"/enrollments?patient_id={patient.id}", caller=staff))

    # The empty state itself is drawn by the panel, and this is what tells it to draw one.
    assert shown["enrollments"] == []


def test_stopping_a_program_records_who_stopped_it_and_why(enrolment, add_step, staff):
    """Covers scenario: AC17, stopping a program from the patient scoped pane halts every remaining step. Covers criterion: AC17."""
    step = add_step(kind=StepKind.MESSAGE, day_offset=7, message_body="Still to come")

    call("POST", f"/enrollments/{enrolment.dbid}/stop",
         {"reason": "The patient asked us to stop."}, caller=staff)

    enrolment.refresh_from_db()
    step.refresh_from_db()
    assert enrolment.status == EnrollmentStatus.STOPPED
    assert enrolment.stopped_reason == "The patient asked us to stop."
    assert enrolment.stopped_by == str(staff.id)
    # Every pending step is left pending, the walk simply ignores a stopped enrolment.
    assert step.status == StepStatus.PENDING


def test_a_caller_below_the_role_floor_cannot_change_a_program(medication_class):
    """Covers criterion: AC1."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    # An administrative role is not a clinical one, so this caller has no top clinical
    # role and does not clear the floor. The staff factory grants a clinical role by
    # default, which is why the existing one is cleared first.
    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)

    response = call("POST", "/classes", {"name": "Should not be created"}, caller=administrator)

    assert status_of(response) == HTTPStatus.FORBIDDEN
    assert not MedicationClass.objects.filter(name="Should not be created").exists()


def test_an_unknown_kind_of_step_is_refused(lead, medication_class):
    """Covers criterion: AC2."""
    response = call("POST", f"/classes/{medication_class.dbid}/steps",
                    {"day_offset": 1, "kind": "carrier pigeon"}, caller=lead)

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    assert not ProgramStep.objects.exists()


def test_a_step_added_to_a_class_that_does_not_exist_is_refused(lead):
    """Covers criterion: AC2."""
    response = call("POST", "/classes/99999/steps",
                    {"day_offset": 1, "kind": "message"}, caller=lead)

    assert status_of(response) == HTTPStatus.NOT_FOUND


def test_a_class_with_no_name_is_refused(lead):
    """Covers criterion: AC1."""
    response = call("POST", "/classes", {"name": "  "}, caller=lead)

    assert status_of(response) == HTTPStatus.BAD_REQUEST


def test_enrolling_onto_a_class_that_is_not_active_is_refused(patient, staff, medication_class):
    """Covers criterion: AC4."""
    medication_class.active = False
    medication_class.save()

    response = call("POST", "/enrollments", {
        "patient_id": patient.dbid,
        "medication_class_id": medication_class.dbid,
        "medication_label": "semaglutide",
        "sender_staff_id": staff.dbid,
    }, caller=staff)

    assert status_of(response) == HTTPStatus.NOT_FOUND
    assert not Enrollment.objects.exists()


def test_stopping_a_program_that_does_not_exist_is_refused(staff):
    """Covers criterion: AC17."""
    response = call("POST", "/enrollments/99999/stop", {"reason": "none"}, caller=staff)

    assert status_of(response) == HTTPStatus.NOT_FOUND


# --- The listing the configuration page reads
#
# Both of these assert a name where the row stores an identifier. A practice cannot work out
# which appointment type counts as a recheck, or which team a task goes to, from a uuid.


def test_the_class_listing_names_the_recheck_appointment_type(lead):
    """Covers scenario: AC1, a staff member creates a medication class. Covers criterion: AC1."""
    note_type = NoteTypeFactory(name="Follow up, 20 minutes", is_active=True,
                                is_scheduleable_via_patient_portal=True)
    MedicationClass.objects.create(name="GLP-1", description="", active=True,
                                   recheck_note_type_id=str(note_type.id))

    listed = json_body(call("GET", "/classes", caller=lead))["classes"]

    assert [c["recheck_note_type_name"] for c in listed] == ["Follow up, 20 minutes"]


def test_the_class_listing_names_its_sender_and_its_owner_team(lead):
    """Covers criterion: AC1.

    The class names who its messages go out as and which team owns a task naming neither
    an assignee nor a team of its own, and the listing has to show a practice who those
    are rather than the identifiers alone.
    """
    sender = StaffFactory(active=True, first_name="Grace", last_name="Hopper")
    team = TeamFactory(name="Nursing")
    MedicationClass.objects.create(
        name="GLP-1", description="", active=True,
        sender_staff_id=str(sender.id), owner_team_id=str(team.id),
    )

    listed = json_body(call("GET", "/classes", caller=lead))["classes"]

    assert listed[0]["sender_staff_id"] == str(sender.id)
    assert listed[0]["sender_staff_name"] == "Grace Hopper"
    assert listed[0]["owner_team_id"] == str(team.id)
    assert listed[0]["owner_team_name"] == "Nursing"


def test_a_class_naming_no_sender_or_owner_team_reads_empty(lead, medication_class):
    """Covers criterion: AC1."""
    listed = json_body(call("GET", "/classes", caller=lead))["classes"]

    assert listed[0]["sender_staff_id"] == ""
    assert listed[0]["sender_staff_name"] == ""
    assert listed[0]["owner_team_id"] == ""
    assert listed[0]["owner_team_name"] == ""


def test_a_class_is_created_naming_its_sender_and_owner_team(lead):
    """Covers criterion: AC1."""
    sender = StaffFactory(active=True)
    team = TeamFactory(name="Nursing")

    response = call("POST", "/classes", {
        "name": "GLP-1",
        "sender_staff_id": str(sender.id),
        "owner_team_id": str(team.id),
    }, caller=lead)

    assert status_of(response) == HTTPStatus.CREATED
    row = MedicationClass.objects.get(name="GLP-1")
    assert row.sender_staff_id == str(sender.id)
    assert row.owner_team_id == str(team.id)


def test_a_classs_sender_and_owner_team_can_be_edited(lead, medication_class):
    """Covers criterion: AC1."""
    sender = StaffFactory(active=True)
    team = TeamFactory(name="Scheduling")

    call("PATCH", f"/classes/{medication_class.dbid}", {
        "sender_staff_id": str(sender.id),
        "owner_team_id": str(team.id),
    }, caller=lead)

    medication_class.refresh_from_db()
    assert medication_class.sender_staff_id == str(sender.id)
    assert medication_class.owner_team_id == str(team.id)


def test_the_class_listing_names_whoever_a_task_step_is_assigned_to(lead, medication_class):
    """Covers scenario: AC3, the assignee picker offers every team on the instance. Covers criterion: AC3.

    AC3's Given is a staff member editing a step of kind task, and this is the other half of
    that surface, the step drawn back with the assignee it already carries. Both kinds of
    assignee are asserted because the picker offers both.
    """
    team = TeamFactory(name="Scheduling")
    nurse = StaffFactory(active=True, first_name="Ada", last_name="Byron")
    ProgramStep.objects.create(medication_class=medication_class, sequence=0, day_offset=7,
                               kind=StepKind.TASK, task_title="Phone the patient",
                               assignee_team_id=str(team.id))
    ProgramStep.objects.create(medication_class=medication_class, sequence=1, day_offset=14,
                               kind=StepKind.TASK, task_title="Review tolerability",
                               assignee_staff_id=str(nurse.id))

    steps = json_body(call("GET", "/classes", caller=lead))["classes"][0]["steps"]

    assert [step["assignee_name"] for step in steps] == ["Scheduling", "Ada Byron"]


# --- Editing a step, which is the seam AC18 and AC19 presuppose
#
# The walker tests for both criteria rewrite the row directly, so neither of them crosses the
# endpoint a staff member actually uses. Every identifier defect this plugin had lived in
# exactly that seam, which is why these two exist rather than being taken as covered.


def test_a_staff_member_edits_the_wording_of_a_step(lead, add_step):
    """Covers scenario: AC18, an edit to a step's wording reaches an enrolment already running. Covers criterion: AC18."""
    scheduled = add_step(kind=StepKind.MESSAGE, day_offset=7, message_body="The old wording")

    response = call("PATCH", f"/steps/{scheduled.program_step.dbid}",
                    {"message_body": "The corrected wording"}, caller=lead)

    assert status_of(response) == HTTPStatus.OK
    scheduled.program_step.refresh_from_db()
    assert scheduled.program_step.message_body == "The corrected wording"


def test_editing_a_day_offset_does_not_move_a_step_already_scheduled(lead, add_step):
    """Covers scenario: AC19, an edit to a step's day offset does not move an enrolment already running. Covers criterion: AC19."""
    scheduled = add_step(kind=StepKind.MESSAGE, day_offset=28, message_body="Book your recheck")
    computed_at_enrolment = scheduled.due_date

    call("PATCH", f"/steps/{scheduled.program_step.dbid}", {"day_offset": 21}, caller=lead)

    scheduled.program_step.refresh_from_db()
    scheduled.refresh_from_db()
    assert scheduled.program_step.day_offset == 21
    # The due date was computed at enrolment and the edit does not reach back to it.
    assert scheduled.due_date == computed_at_enrolment


def test_a_task_step_is_retargeted_at_a_different_team(lead, medication_class):
    """Covers scenario: AC7, a task step due today raises a task for the named team. Covers criterion: AC7."""
    nursing = TeamFactory(name="Nursing")
    scheduling = TeamFactory(name="Scheduling")
    step = ProgramStep.objects.create(medication_class=medication_class, sequence=0, day_offset=7,
                                      kind=StepKind.TASK, task_title="Phone the patient",
                                      assignee_team_id=str(nursing.id))

    call("PATCH", f"/steps/{step.dbid}", {
        "kind": StepKind.TASK,
        "task_title": "Book the recheck",
        "task_body": "The patient is due a follow up.",
        "assignee_team_id": str(scheduling.id),
        "assignee_staff_id": "",
        "sequence": 1,
    }, caller=lead)

    step.refresh_from_db()
    assert step.assignee_team_id == str(scheduling.id)
    assert step.task_title == "Book the recheck"
    assert step.assignee_staff_id is None


def test_a_condition_is_put_on_a_step_that_had_none(lead, medication_class):
    """Covers scenario: AC8, a step conditional on the recheck is skipped once one is booked. Covers criterion: AC8."""
    step = ProgramStep.objects.create(medication_class=medication_class, sequence=0, day_offset=28,
                                      kind=StepKind.MESSAGE, message_body="Book your recheck",
                                      attach_booking_link=False)

    call("PATCH", f"/steps/{step.dbid}",
         {"condition": "recheck_not_booked", "attach_booking_link": True}, caller=lead)

    step.refresh_from_db()
    assert step.condition == "recheck_not_booked"
    assert step.attach_booking_link is True


def test_a_step_is_pointed_at_a_questionnaire(lead, medication_class):
    """Covers scenario: AC11, the portal offers the questionnaire of a live step. Covers criterion: AC11."""
    step = ProgramStep.objects.create(medication_class=medication_class, sequence=0, day_offset=14,
                                      kind=StepKind.MESSAGE, message_body="How are you finding it")

    call("PATCH", f"/steps/{step.dbid}", {
        "kind": StepKind.QUESTIONNAIRE,
        "questionnaire_id": "0d2f5c73-9b81-4a6e-8c14-5f7a2e9b3d68",
    }, caller=lead)

    step.refresh_from_db()
    assert step.kind == StepKind.QUESTIONNAIRE
    assert step.questionnaire_id == "0d2f5c73-9b81-4a6e-8c14-5f7a2e9b3d68"


def test_editing_a_step_to_an_unknown_kind_is_refused(lead, medication_class):
    """Covers criterion: AC2."""
    step = ProgramStep.objects.create(medication_class=medication_class, sequence=0, day_offset=0,
                                      kind=StepKind.MESSAGE, message_body="Unchanged")

    response = call("PATCH", f"/steps/{step.dbid}", {"kind": "carrier pigeon"}, caller=lead)

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    step.refresh_from_db()
    assert step.kind == StepKind.MESSAGE


def test_editing_a_step_to_an_unknown_condition_is_refused(lead, medication_class):
    """Covers criterion: AC8."""
    step = ProgramStep.objects.create(medication_class=medication_class, sequence=0, day_offset=0,
                                      kind=StepKind.MESSAGE, message_body="Unchanged")

    response = call("PATCH", f"/steps/{step.dbid}", {"condition": "the moon is full"}, caller=lead)

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    step.refresh_from_db()
    assert step.condition is None


def test_editing_a_step_that_does_not_exist_is_refused(lead):
    """Covers criterion: AC18."""
    response = call("PATCH", "/steps/99999", {"message_body": "Nowhere"}, caller=lead)

    assert status_of(response) == HTTPStatus.NOT_FOUND


def test_a_caller_below_the_role_floor_cannot_edit_a_step(medication_class):
    """Covers criterion: AC18."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)
    step = ProgramStep.objects.create(medication_class=medication_class, sequence=0, day_offset=0,
                                      kind=StepKind.MESSAGE, message_body="Unchanged")

    response = call("PATCH", f"/steps/{step.dbid}", {"message_body": "Changed"}, caller=administrator)

    assert status_of(response) == HTTPStatus.FORBIDDEN
    step.refresh_from_db()
    assert step.message_body == "Unchanged"


# --- The prescriptions the enrolment form offers
#
# AC4's Given is a note carrying a committed prescription and its When is a provider choosing
# that prescription, so what the form is handed to choose from is part of that criterion.


def test_the_enrolment_form_reads_the_prescriptions_committed_on_the_note(patient, staff):
    """Covers scenario: AC4, enrolling a patient schedules every step of the class. Covers criterion: AC4."""
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory
    from canvas_sdk.v1.data import MedicationCoding

    from tests.conftest import make

    medication = MedicationFactory(patient=patient)
    # A Medication carries no name of its own, the drug name lives on its codings. Without
    # this the form offered a prescriber the string "Medication object (17)".
    make(MedicationCoding, medication=medication, display="Semaglutide 0.25 MG/DOSE",
         system="http://www.nlm.nih.gov/research/umls/rxnorm", code="1991302")
    prescription = PrescriptionFactory(patient=patient, prescriber=staff, medication=medication)

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.id}", caller=staff)
    )["prescriptions"]

    assert len(offered) == 1
    assert offered[0]["label"] == "Semaglutide 0.25 MG/DOSE"
    # Keys rather than database ids, because the form hands these straight back to the write.
    assert offered[0]["patient_id"] == str(patient.id)
    assert offered[0]["prescriber_id"] == str(staff.id)
    assert offered[0]["prescriber_name"] == f"{staff.first_name} {staff.last_name}"


def test_the_prescription_listing_takes_the_integer_note_id_the_platform_hands_it(patient, staff):
    """Covers criterion: AC4.

    The note footer button reads note_id off the event context and the platform puts the
    integer primary key there, while the SDK's own Note.id is the public uuid. Filtering on
    one while being handed the other raised inside the field, which the browser saw as a 500
    with no body, so the form came up empty and said nothing about why.
    """
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory

    medication = MedicationFactory(patient=patient)
    prescription = PrescriptionFactory(patient=patient, prescriber=staff, medication=medication)

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.dbid}", caller=staff)
    )["prescriptions"]

    assert [p["id"] for p in offered] == [str(prescription.id)]
    # No coding was made for this medication, so the name falls back down the chain to the
    # sig, which is what a clinician can still read. The factory writes that sig.
    assert offered[0]["label"] == prescription.sig_original_input


def test_the_prescription_listing_is_empty_when_no_note_was_named(staff):
    """Covers criterion: AC4."""
    offered = json_body(call("GET", "/prescriptions", caller=staff))

    assert offered["prescriptions"] == []
    assert offered["note"] is None


def test_the_prescription_listing_carries_the_notes_own_identifying_line(patient, staff):
    """Covers criterion: AC4.

    The enrolment panel opens over one note and a provider must be able to tell which one
    without leaving the panel, so what that line is built from rides along with the
    prescriptions rather than needing a second request.

    The moment is asserted as an instant rather than as words. The panel has to read as the
    same sentence the home app draws at the top of that note, and the home app formats that
    time in the browser in whatever timezone the reader is sitting in. Formatting it here
    put the panel two hours off the note beside it on a machine in CEST.
    """
    import datetime as dt

    from canvas_sdk.test_utils.factories import (
        MedicationFactory,
        NoteFactory,
        NoteTypeFactory,
        PracticeLocationFactory,
        PrescriptionFactory,
    )

    note = NoteFactory(
        patient=patient,
        provider=staff,
        note_type_version=NoteTypeFactory(name="Office visit"),
        location=PracticeLocationFactory(full_name="Canvas Clinic San Francisco"),
        datetime_of_service=dt.datetime(2026, 7, 19, 17, 45, tzinfo=dt.timezone.utc),
    )
    medication = MedicationFactory(patient=patient)
    PrescriptionFactory(patient=patient, prescriber=staff, medication=medication, note=note)

    offered = json_body(call("GET", f"/prescriptions?note_id={note.id}", caller=staff))["note"]

    assert offered["note_type_name"] == "Office visit"
    # The instant, unformatted, so the browser can render it in the reader's own timezone.
    assert dt.datetime.fromisoformat(offered["at"]) == dt.datetime(
        2026, 7, 19, 17, 45, tzinfo=dt.timezone.utc
    )
    assert "day_of_week" not in offered and "time" not in offered
    assert offered["provider_name"] == f"{staff.first_name} {staff.last_name}"
    assert offered["location_name"] == "Canvas Clinic San Francisco"


def test_the_prescription_listing_names_the_program_already_running_on_a_medication(
    patient, staff, medication_class
):
    """Covers criterion: AC4.

    The medication dropdown must offer only prescriptions with no program running, so the
    listing has to carry the same running or not answer the write below refuses on.
    """
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory
    from canvas_sdk.v1.data import MedicationCoding

    from medication_followup_protocol.models import Enrollment
    from tests.conftest import make

    medication = MedicationFactory(patient=patient)
    make(MedicationCoding, medication=medication, display="Semaglutide 0.25 MG/DOSE",
         system="http://www.nlm.nih.gov/research/umls/rxnorm", code="1991302")
    prescription = PrescriptionFactory(patient=patient, prescriber=staff, medication=medication)
    enrollment = Enrollment.objects.create(
        patient_id=patient.dbid,
        medication_class=medication_class,
        medication_label="Semaglutide 0.25 MG/DOSE",
        sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid,
        start_date=datetime.date(2026, 7, 1),
    )

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.id}", caller=staff)
    )["prescriptions"]

    # A running enrolment is now the same section shape both panes render, rather than the
    # four field dict this endpoint used to compose for itself. A section names its class
    # rather than carrying its id, which is what lets one renderer serve both panes, so the
    # id assertion that stood here is gone rather than restored.
    running = offered[0]["running_enrollment"]
    assert len(offered) == 1
    assert running["id"] == enrollment.dbid
    assert running["medication_class"] == medication_class.name
    assert running["medication_label"] == "Semaglutide 0.25 MG/DOSE"
    assert running["start_date"] == "2026-07-01"
    assert "steps" in running


# --- The guards on the writes
#
# The three page routes have no test here and cannot have one. They render through
# render_to_string, which raises "Method that expected plugin context was called from outside
# a plugin" under pytest, because a template is resolved against the installed package rather
# than the checkout. Gate three loads all three pages in a browser, which is the stronger
# claim anyway, so do not try to unit test them again.


def test_a_caller_below_the_role_floor_cannot_add_a_step(medication_class):
    """Covers criterion: AC2."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)

    response = call("POST", f"/classes/{medication_class.dbid}/steps",
                    {"day_offset": 1, "kind": "message"}, caller=administrator)

    assert status_of(response) == HTTPStatus.FORBIDDEN
    assert not ProgramStep.objects.exists()


def test_a_step_added_with_an_unknown_condition_is_refused(lead, medication_class):
    """Covers criterion: AC8."""
    response = call("POST", f"/classes/{medication_class.dbid}/steps",
                    {"day_offset": 1, "kind": "message", "condition": "the moon is full"},
                    caller=lead)

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    assert not ProgramStep.objects.exists()


def test_the_panel_asks_for_nothing_when_no_patient_was_named(staff):
    """Covers criterion: AC15."""
    shown = json_body(call("GET", "/enrollments", caller=staff))

    assert shown["enrollments"] == []


def test_enrolling_a_patient_who_does_not_exist_is_refused(medication_class, staff):
    """Covers criterion: AC4."""
    response = call("POST", "/enrollments", {
        "patient_id": "5c9f1a2b3d4e5f60718293a4b5c6d7e8",
        "medication_class_id": medication_class.dbid,
        "medication_label": "semaglutide",
        "sender_staff_id": staff.id,
    }, caller=staff)

    assert status_of(response) == HTTPStatus.NOT_FOUND
    assert not Enrollment.objects.exists()


def test_enrolling_with_no_prescriber_resolvable_is_refused(medication_class, patient, staff):
    """Covers criterion: AC6.

    A message falls back to the enrolment's prescriber whenever the class names no sender
    of its own, and the questionnaire answers land on the prescriber outright, so a program
    that resolves no prescriber at all is refused here rather than discovered on the morning
    a step tries to fire under nobody's name.
    """
    response = call("POST", "/enrollments", {
        "patient_id": patient.id,
        "medication_class_id": medication_class.dbid,
        "medication_label": "semaglutide",
    }, caller=staff)

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    assert not Enrollment.objects.exists()


def test_creating_an_enrollment_writes_no_sender(medication_class, patient, staff):
    """Covers criterion: AC4.

    Who a step is sent as is resolved live off the medication class when it fires, not
    decided at enrolment any more, so the write stores none.
    """
    response = call("POST", "/enrollments", {
        "patient_id": patient.id,
        "medication_class_id": medication_class.dbid,
        "medication_label": "semaglutide",
        "prescriber_staff_id": staff.id,
    }, caller=staff)

    assert status_of(response) == HTTPStatus.CREATED
    row = Enrollment.objects.get(medication_label="semaglutide")
    assert row.sender_staff_id is None


def test_the_prescriber_falls_back_to_the_selected_prescriptions_own_prescriber(
    medication_class, patient, staff
):
    """Covers criterion: AC4.

    A provider enrolling straight off a note names no prescriber of their own on the form,
    so the write resolves one from the prescription being enrolled rather than refusing for
    want of one.
    """
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory

    medication = MedicationFactory(patient=patient)
    prescription = PrescriptionFactory(patient=patient, prescriber=staff, medication=medication)

    response = call("POST", "/enrollments", {
        "patient_id": patient.id,
        "medication_class_id": medication_class.dbid,
        "medication_label": "semaglutide",
        "prescription_id": str(prescription.id),
    }, caller=staff)

    assert status_of(response) == HTTPStatus.CREATED
    row = Enrollment.objects.get(medication_label="semaglutide")
    assert row.prescriber_staff_id == staff.dbid


def test_the_panel_summarises_a_step_of_every_kind(staff, enrolment, add_step):
    """Covers scenario: AC15, the Follow ups control opens the Ongoing tab showing every program a patient is on. Covers criterion: AC15."""
    add_step(kind=StepKind.MESSAGE, day_offset=0, message_body="Day zero, how are you finding it")
    add_step(kind=StepKind.TASK, day_offset=7, sequence=1, task_title="Phone the patient")
    add_step(kind=StepKind.QUESTIONNAIRE, day_offset=14, sequence=2, message_body="")

    shown = json_body(
        call("GET", f"/enrollments?patient_id={enrolment.patient.id}", caller=staff)
    )["enrollments"][0]

    # A task reads as its title and a questionnaire that carries no wording of its own still
    # says what it is, rather than showing a practice an empty row.
    assert [step["summary"] for step in shown["steps"]] == [
        "Day zero, how are you finding it",
        "Phone the patient",
        "Questionnaire to the patient",
    ]


# --- Naming a prescription, and refusing to enrol on one that cannot be named
#
# A real instance served two prescriptions on one note with no medication behind either. They
# read as unnamed, the first enrolled under an empty label, and the second was then refused for
# already having a program while the row above it still said no program yet. The label is what
# the duplicate check compares, so empty collapses every unnamed drug on that patient into one.


def test_a_prescription_with_no_coding_falls_back_to_its_sig(patient, staff):
    """Covers criterion: AC4."""
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory

    medication = MedicationFactory(patient=patient)
    prescription = PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication,
        sig_original_input="Inject 0.25 mg subcutaneously once weekly",
    )

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.id}", caller=staff)
    )["prescriptions"]

    assert offered[0]["label"] == "Inject 0.25 mg subcutaneously once weekly"


def test_a_prescription_with_nothing_to_name_it_reports_no_label(patient, staff):
    """Covers criterion: AC4.

    No medication and no sig, which is the state that did the damage. The endpoint says so
    plainly rather than inventing a name, and the write below refuses it.
    """
    from canvas_sdk.test_utils.factories import PrescriptionFactory

    prescription = PrescriptionFactory(
        patient=patient, prescriber=staff, medication=None, sig_original_input="",
    )

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.id}", caller=staff)
    )["prescriptions"]

    assert offered[0]["label"] == ""
    # And it does not claim a program is running, which is what the early return used to do.
    assert offered[0]["running_enrollment"] is None


def test_enrolling_on_a_medication_with_no_name_is_refused(medication_class, patient, staff):
    """Covers criterion: AC4.

    Stored empty, the label makes every unnamed prescription on this patient collide into one
    program, so the first blocks the rest. Refused at the write, where it costs nothing.
    """
    response = call("POST", "/enrollments", {
        "patient_id": patient.id,
        "medication_class_id": medication_class.dbid,
        "medication_label": "   ",
        "sender_staff_id": staff.id,
    }, caller=staff)

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    assert not Enrollment.objects.exists()


def test_a_prescription_with_no_prescriber_is_blocked_with_a_reason(patient, staff):
    """Covers criterion: AC4.

    A prescription typed into a note but never given a prescriber. Canvas leaves that field
    empty until the command is committed, so this is the ordinary state of a draft, and the
    panel used to offer it a start button that could only ever come back refused.
    """
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory
    from canvas_sdk.v1.data import MedicationCoding

    from tests.conftest import make

    medication = MedicationFactory(patient=patient)
    make(MedicationCoding, medication=medication, display="atorvastatin 40 mg tablet",
         system="http://www.nlm.nih.gov/research/umls/rxnorm", code="617311")
    prescription = PrescriptionFactory(
        patient=patient, prescriber=None, medication=medication
    )

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.id}", caller=staff)
    )["prescriptions"]

    assert offered[0]["label"] == "atorvastatin 40 mg tablet"
    assert "names no prescriber" in offered[0]["blocked_reason"]
    # The reason says what to do rather than telling a provider to go and look.
    assert "commit" in offered[0]["blocked_reason"]


def test_a_prescription_ready_to_enrol_carries_no_blocked_reason(patient, staff):
    """Covers criterion: AC4."""
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory
    from canvas_sdk.v1.data import MedicationCoding

    from tests.conftest import make

    medication = MedicationFactory(patient=patient)
    make(MedicationCoding, medication=medication, display="lisinopril 10 mg tablet",
         system="http://www.nlm.nih.gov/research/umls/rxnorm", code="314076")
    prescription = PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication
    )

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.id}", caller=staff)
    )["prescriptions"]

    assert offered[0]["blocked_reason"] == ""


def test_a_prescription_with_no_name_is_blocked_on_the_name_rather_than_the_prescriber(
    patient, staff
):
    """Covers criterion: AC4.

    Both blockers at once, and the name is the one reported, because naming the drug is what
    a provider has to fix first and one reason at a time is what a card can act on.
    """
    from canvas_sdk.test_utils.factories import PrescriptionFactory

    prescription = PrescriptionFactory(
        patient=patient, prescriber=None, medication=None, sig_original_input=""
    )

    offered = json_body(
        call("GET", f"/prescriptions?note_id={prescription.note.id}", caller=staff)
    )["prescriptions"]

    assert "no medication name" in offered[0]["blocked_reason"]


def test_a_caller_who_may_not_configure_can_still_read_the_defaults():
    """Covers criterion: AC1."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    # Every other read this page makes is open to any staff member and only the writes ask
    # for configure rights. Gating the read would 403 somebody who may look at the page
    # without changing it, leaving a console error under a page that rendered correctly.
    viewer = StaffFactory(active=True)
    viewer.roles.all().delete()
    StaffRoleFactory(staff=viewer, domain="ADM", domain_privilege_level=100000)

    stored = json_body(call("GET", "/defaults", caller=viewer))

    assert stored == {"sender_staff_id": "", "owner_team_id": ""}


# --- Names have to differ, and a class can be cloned
#
# AC1's When is a staff member creating a medication class, so what the create refuses is
# part of that criterion. Cloning describes behaviour no criterion covers, recorded as a
# change request in 00-inputs rather than papered over with a criterion that does not fit.


def test_a_class_cannot_take_a_name_another_class_already_has(lead, medication_class):
    """Covers criterion: AC1."""
    response = call("POST", "/classes", {"name": "GLP-1"}, caller=lead)

    assert status_of(response) == HTTPStatus.CONFLICT
    assert MedicationClass.objects.filter(name__iexact="GLP-1").count() == 1


def test_a_name_that_differs_only_in_capitals_is_the_same_name(lead, medication_class):
    """Covers criterion: AC1."""
    # Two classes a reader cannot tell apart are the same name, and the enrolment duplicate
    # check compares a label rather than an identifier, so near duplicates are a hazard.
    response = call("POST", "/classes", {"name": "  glp-1  "}, caller=lead)

    assert status_of(response) == HTTPStatus.CONFLICT
    assert MedicationClass.objects.count() == 1


def test_renaming_a_class_onto_another_name_is_refused(lead, medication_class):
    """Covers criterion: AC1."""
    other = MedicationClass.objects.create(name="Statins")

    response = call("PATCH", f"/classes/{other.dbid}", {"name": "GLP-1"}, caller=lead)

    assert status_of(response) == HTTPStatus.CONFLICT
    other.refresh_from_db()
    assert other.name == "Statins"


def test_saving_a_class_under_its_own_name_is_allowed(lead, medication_class):
    """Covers criterion: AC1."""
    # The rename check excludes the row being written, or saving a class without touching
    # its name would be refused for clashing with itself.
    response = call(
        "PATCH", f"/classes/{medication_class.dbid}",
        {"name": "GLP-1", "owner_team_id": ""}, caller=lead,
    )

    assert status_of(response) == HTTPStatus.OK


def test_cloning_a_class_copies_every_choice_and_every_step(lead, medication_class):
    """Covers criterion: AC1."""
    sender = StaffFactory(active=True)
    team = TeamFactory(name="Nursing")
    medication_class.sender_staff_id = str(sender.id)
    medication_class.owner_team_id = str(team.id)
    medication_class.save()
    ProgramStep.objects.create(
        medication_class=medication_class, sequence=0, day_offset=14,
        kind=StepKind.MESSAGE, message_body="Time to book", attach_booking_link=True,
        condition="recheck_not_booked",
    )
    ProgramStep.objects.create(
        medication_class=medication_class, sequence=0, day_offset=42,
        kind=StepKind.TASK, task_title="Escalate", task_body="Ring them",
        assignee_team_id=str(team.id),
    )

    response = call(
        "POST", f"/classes/{medication_class.dbid}/clone",
        {"name": "GLP-1 (Clone)"}, caller=lead,
    )

    assert status_of(response) == HTTPStatus.CREATED
    copy = MedicationClass.objects.get(name="GLP-1 (Clone)")
    assert copy.dbid != medication_class.dbid
    assert copy.description == medication_class.description
    assert copy.recheck_note_type_id == medication_class.recheck_note_type_id
    assert copy.sender_staff_id == str(sender.id)
    assert copy.owner_team_id == str(team.id)

    copied = list(ProgramStep.objects.filter(medication_class=copy).order_by("day_offset"))
    assert [s.day_offset for s in copied] == [14, 42]
    assert copied[0].message_body == "Time to book"
    assert copied[0].attach_booking_link is True
    assert copied[0].condition == "recheck_not_booked"
    assert copied[1].task_title == "Escalate"
    assert copied[1].assignee_team_id == str(team.id)
    # The original keeps its own steps rather than handing them over.
    assert ProgramStep.objects.filter(medication_class=medication_class).count() == 2


def test_a_clone_cannot_take_a_name_that_is_already_used(lead, medication_class):
    """Covers criterion: AC1."""
    response = call(
        "POST", f"/classes/{medication_class.dbid}/clone", {"name": "GLP-1"}, caller=lead,
    )

    assert status_of(response) == HTTPStatus.CONFLICT
    assert MedicationClass.objects.count() == 1


def test_cloning_a_class_that_is_gone_is_reported_rather_than_creating_one(lead):
    """Covers criterion: AC1."""
    response = call("POST", "/classes/99999/clone", {"name": "Orphan"}, caller=lead)

    assert status_of(response) == HTTPStatus.NOT_FOUND
    assert not MedicationClass.objects.exists()


def test_a_caller_who_may_not_configure_cannot_clone(medication_class):
    """Covers criterion: AC1."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)

    response = call(
        "POST", f"/classes/{medication_class.dbid}/clone",
        {"name": "Sneaky copy"}, caller=administrator,
    )

    assert status_of(response) == HTTPStatus.FORBIDDEN
    assert MedicationClass.objects.count() == 1


# --- Who is on a program.
#
# The class card carries two counts and a link, and the page behind that link pages through
# the patients. The counts are what the refusal to remove a class is really about, so they
# are tested against the same statuses the refusal counts.


def _enrol(medication_class, patient, staff, label, status=EnrollmentStatus.ACTIVE, start=None):
    """One enrolment on a class, in whichever state the test needs it."""
    return Enrollment.objects.create(
        patient_id=patient.dbid,
        medication_class=medication_class,
        medication_label=label,
        prescriber_staff_id=staff.dbid,
        start_date=start or datetime.date(2026, 8, 1),
        status=status,
    )


def test_the_class_listing_counts_the_programs_running_and_the_ones_ever_started(
    lead, medication_class, patient, staff
):
    """Running says the class is live, the total says whether it can ever be removed."""
    _enrol(medication_class, patient, staff, "one")
    _enrol(medication_class, patient, staff, "two")
    _enrol(medication_class, patient, staff, "three", status=EnrollmentStatus.STOPPED)
    _enrol(medication_class, patient, staff, "four", status=EnrollmentStatus.COMPLETED)

    listed = json_body(call("GET", "/classes", caller=lead))["classes"][0]

    assert listed["running_count"] == 2
    assert listed["total_count"] == 4


def test_a_class_nobody_was_ever_started_on_counts_zero_rather_than_missing(lead, medication_class):
    """The page reads both keys unconditionally, so a class with no enrolments needs them."""
    listed = json_body(call("GET", "/classes", caller=lead))["classes"][0]

    assert listed["running_count"] == 0
    assert listed["total_count"] == 0


def test_a_caller_who_may_not_configure_cannot_read_who_is_enrolled(medication_class):
    """An administrative list of patients answers to the floor the writes answer to."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    # The staff factory grants a clinical role by default, so the existing one is cleared
    # before an administrative one is put in its place, the same way the write side test
    # builds a caller who does not clear the floor.
    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)

    response = call(
        "GET", f"/class-enrollments?class_id={medication_class.dbid}", caller=administrator
    )

    assert status_of(response) == HTTPStatus.FORBIDDEN


def test_the_enrolled_list_returns_the_running_programs_by_default(
    lead, medication_class, patient, staff
):
    """Running is the tab the page opens on, so it is what an unqualified read answers."""
    _enrol(medication_class, patient, staff, "running one")
    _enrol(medication_class, patient, staff, "ended one", status=EnrollmentStatus.STOPPED)

    listed = json_body(
        call("GET", f"/class-enrollments?class_id={medication_class.dbid}", caller=lead)
    )

    assert listed["scope"] == "running"
    assert listed["running_count"] == 1
    assert listed["ended_count"] == 1
    assert [row["medication_label"] for row in listed["rows"]] == ["running one"]


def test_the_ended_tab_carries_stopped_and_completed_together(
    lead, medication_class, patient, staff
):
    """Both are done, and a reader who wants them apart reads the status column."""
    _enrol(medication_class, patient, staff, "still going")
    _enrol(medication_class, patient, staff, "stopped one", status=EnrollmentStatus.STOPPED)
    _enrol(medication_class, patient, staff, "finished one", status=EnrollmentStatus.COMPLETED)

    listed = json_body(
        call(
            "GET",
            f"/class-enrollments?class_id={medication_class.dbid}&scope=ended",
            caller=lead,
        )
    )

    assert listed["total"] == 2
    assert {row["medication_label"] for row in listed["rows"]} == {"stopped one", "finished one"}
    assert {row["status"] for row in listed["rows"]} == {
        EnrollmentStatus.STOPPED,
        EnrollmentStatus.COMPLETED,
    }


def test_the_enrolled_list_pages_rather_than_returning_everything(
    lead, medication_class, patient, staff
):
    """A practice can have thousands on one class, which is why this is a page at all."""
    for index in range(30):
        _enrol(medication_class, patient, staff, f"drug {index:02d}")

    first = json_body(
        call(
            "GET",
            f"/class-enrollments?class_id={medication_class.dbid}&page=1&page_size=25",
            caller=lead,
        )
    )
    second = json_body(
        call(
            "GET",
            f"/class-enrollments?class_id={medication_class.dbid}&page=2&page_size=25",
            caller=lead,
        )
    )

    assert first["total"] == 30
    assert len(first["rows"]) == 25
    assert len(second["rows"]) == 5
    # No row appears on both pages, which is what the tiebreak in the ordering is for.
    assert not {row["id"] for row in first["rows"]} & {row["id"] for row in second["rows"]}


def test_a_page_size_beyond_the_ceiling_is_capped_rather_than_honoured(
    lead, medication_class, patient, staff
):
    """A hand edited address must not be able to ask for every row on the instance."""
    _enrol(medication_class, patient, staff, "one")

    listed = json_body(
        call(
            "GET",
            f"/class-enrollments?class_id={medication_class.dbid}&page_size=9999",
            caller=lead,
        )
    )

    assert listed["page_size"] == ProgramAPI.ENROLLED_PAGE_SIZE_MAX


def test_a_page_number_that_is_not_a_number_falls_back_to_the_first_page(
    lead, medication_class, patient, staff
):
    """A paged page reached by a mangled address shows its first page, never a 500."""
    _enrol(medication_class, patient, staff, "one")

    listed = json_body(
        call(
            "GET",
            f"/class-enrollments?class_id={medication_class.dbid}&page=banana",
            caller=lead,
        )
    )

    assert listed["page"] == 1
    assert len(listed["rows"]) == 1


def test_an_unknown_scope_falls_back_to_running(lead, medication_class, patient, staff):
    """Two tabs exist and anything else is read as the one the page opens on."""
    _enrol(medication_class, patient, staff, "one")

    listed = json_body(
        call(
            "GET",
            f"/class-enrollments?class_id={medication_class.dbid}&scope=sideways",
            caller=lead,
        )
    )

    assert listed["scope"] == "running"


def test_reading_who_is_enrolled_on_a_class_that_does_not_exist_is_refused(lead):
    """The page is reached by an address carrying an identifier, so it can be a wrong one."""
    response = call("GET", "/class-enrollments?class_id=987654", caller=lead)

    assert status_of(response) == HTTPStatus.NOT_FOUND


def test_an_enrolled_row_carries_how_far_through_it_is_and_what_happens_next(
    lead, medication_class, enrolment, add_step
):
    """The two columns a reader scans, worked out on the server rather than in the page."""
    add_step(kind=StepKind.MESSAGE, day_offset=0, message_body="First message")
    add_step(kind=StepKind.TASK, day_offset=21, task_title="Review the result")
    EnrolledStep.objects.filter(enrollment=enrolment, day_offset=0).update(
        status=StepStatus.FIRED
    )

    row = json_body(
        call("GET", f"/class-enrollments?class_id={medication_class.dbid}", caller=lead)
    )["rows"][0]

    assert row["span"] == 21
    assert row["steps_done"] == 1
    assert row["steps_total"] == 2
    # Read live off the class, which is why the wording is the task title rather than a copy.
    assert row["next_summary"] == "Review the result"
    assert row["next_due"] == (enrolment.start_date + datetime.timedelta(days=21)).isoformat()


def test_an_enrolled_row_with_nothing_left_waiting_says_so_rather_than_guessing(
    lead, medication_class, enrolment, add_step
):
    """A program whose steps have all settled has no next step, and the page reads that key."""
    add_step(kind=StepKind.MESSAGE, day_offset=0, message_body="Only message")
    EnrolledStep.objects.filter(enrollment=enrolment).update(status=StepStatus.FIRED)

    row = json_body(
        call("GET", f"/class-enrollments?class_id={medication_class.dbid}", caller=lead)
    )["rows"][0]

    assert row["next_due"] == ""
    assert row["next_summary"] == ""


def test_an_enrolled_row_names_the_patient_and_the_key_the_chart_address_takes(
    lead, medication_class, enrolment, patient
):
    """The chart route takes the public key, so a row carrying a database id links nowhere."""
    row = json_body(
        call("GET", f"/class-enrollments?class_id={medication_class.dbid}", caller=lead)
    )["rows"][0]

    assert row["patient_name"] == f"{patient.first_name} {patient.last_name}"
    assert row["patient_key"] == str(patient.id)
    assert row["mrn"] == str(patient.mrn)


# --- The full step timeline behind one row of the patients table.
#
# The list read above answers what a reader scans a page of rows for. This is the detail
# behind one row, read lazily when that row's chevron opens rather than carried on every
# page. It serves no numbered acceptance criterion, since the specification never named
# this endpoint, it exists to satisfy the approved redesign of the enrolled patients table.


def test_the_step_timeline_carries_every_step_in_order(
    lead, medication_class, enrolment, add_step
):
    """The panel reads the whole programme, oldest step first."""
    add_step(kind=StepKind.MESSAGE, day_offset=7, message_body="Second message")
    add_step(kind=StepKind.MESSAGE, day_offset=0, message_body="First message")

    payload = json_body(
        call("GET", f"/enrollments/{enrolment.dbid}/steps", caller=lead)
    )

    assert payload["id"] == enrolment.dbid
    assert payload["medication_label"] == enrolment.medication_label
    assert payload["start_date"] == enrolment.start_date.isoformat()
    assert [step["day_offset"] for step in payload["steps"]] == [0, 7]
    assert [step["summary"] for step in payload["steps"]] == [
        "First message", "Second message",
    ]


def test_a_task_step_in_the_timeline_carries_who_it_is_assigned_to(
    lead, medication_class, enrolment, add_step
):
    """A task step names its assignee, the way the class editor's own table does."""
    team = TeamFactory(name="Nursing")
    add_step(kind=StepKind.TASK, day_offset=14, task_title="Check tolerability",
              assignee_team_id=str(team.id))

    step = json_body(
        call("GET", f"/enrollments/{enrolment.dbid}/steps", caller=lead)
    )["steps"][0]

    assert step["kind"] == StepKind.TASK
    assert step["assignee_name"] == "Nursing"


def test_a_message_step_in_the_timeline_carries_no_assignee(
    lead, medication_class, enrolment, add_step
):
    """A step that is not a task points at nobody, the same rule the editor table follows."""
    add_step(kind=StepKind.MESSAGE, day_offset=0, message_body="Only message")

    step = json_body(
        call("GET", f"/enrollments/{enrolment.dbid}/steps", caller=lead)
    )["steps"][0]

    assert step["assignee_name"] == ""


def test_the_step_timeline_carries_the_condition_and_the_state_of_each_step(
    lead, medication_class, enrolment, add_step
):
    """The panel names what a step is waiting on and what became of it."""
    add_step(kind=StepKind.MESSAGE, day_offset=0, message_body="Recheck reminder",
              condition="recheck_not_booked")
    EnrolledStep.objects.filter(enrollment=enrolment).update(
        status=StepStatus.FIRED, failure_reason="",
    )

    step = json_body(
        call("GET", f"/enrollments/{enrolment.dbid}/steps", caller=lead)
    )["steps"][0]

    assert step["condition"] == "recheck_not_booked"
    assert step["status"] == StepStatus.FIRED


def test_reading_the_step_timeline_of_a_program_that_does_not_exist_is_refused(lead):
    """The panel is opened by an identifier, so it can be a wrong one."""
    response = call("GET", "/enrollments/987654/steps", caller=lead)

    assert status_of(response) == HTTPStatus.NOT_FOUND


def test_a_caller_who_may_not_configure_cannot_read_the_step_timeline(enrolment):
    """The detail behind the list answers to the same floor the list itself answers to."""
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)

    response = call(
        "GET", f"/enrollments/{enrolment.dbid}/steps", caller=administrator
    )

    assert status_of(response) == HTTPStatus.FORBIDDEN


# --- The note a program was started from.


def test_enrolling_records_the_note_the_program_was_started_from(
    medication_class, patient, staff
):
    """Kept so the enrolled patients page can carry a reader back to that note."""
    from canvas_sdk.test_utils.factories import (
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )

    note = NoteFactory(patient=patient, provider=staff)
    medication = MedicationFactory(patient=patient)
    prescription = PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note
    )

    call(
        "POST",
        "/enrollments",
        {
            "patient_id": str(patient.id),
            "medication_class_id": medication_class.dbid,
            "medication_label": "semaglutide",
            "prescription_id": str(prescription.id),
            "prescriber_staff_id": str(staff.id),
            "note_id": str(note.dbid),
        },
        caller=staff,
    )

    enrolment = Enrollment.objects.get(patient__dbid=patient.dbid)
    assert enrolment.start_note_dbid == note.dbid


def test_enrolling_resolves_a_note_public_key_to_the_database_id_the_permalink_needs(
    medication_class, patient, staff
):
    """The footer button hands over an integer and the form can hand over a key, both arrive."""
    from canvas_sdk.test_utils.factories import (
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )

    note = NoteFactory(patient=patient, provider=staff)
    medication = MedicationFactory(patient=patient)
    prescription = PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note
    )

    call(
        "POST",
        "/enrollments",
        {
            "patient_id": str(patient.id),
            "medication_class_id": medication_class.dbid,
            "medication_label": "semaglutide",
            "prescription_id": str(prescription.id),
            "prescriber_staff_id": str(staff.id),
            "note_id": str(note.id),
        },
        caller=staff,
    )

    enrolment = Enrollment.objects.get(patient__dbid=patient.dbid)
    # Stored as the database id whichever shape arrived, because the chart permalink is read
    # as a note primary key and a public key there scrolls to nothing.
    assert enrolment.start_note_dbid == note.dbid


def test_enrolling_without_a_note_leaves_the_link_off_rather_than_guessing(
    medication_class, patient, staff
):
    """An enrolment written before this field existed gets no link, and neither does this."""
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory

    medication = MedicationFactory(patient=patient)
    prescription = PrescriptionFactory(patient=patient, prescriber=staff, medication=medication)

    call(
        "POST",
        "/enrollments",
        {
            "patient_id": str(patient.id),
            "medication_class_id": medication_class.dbid,
            "medication_label": "semaglutide",
            "prescription_id": str(prescription.id),
            "prescriber_staff_id": str(staff.id),
        },
        caller=staff,
    )

    assert Enrollment.objects.get(patient__dbid=patient.dbid).start_note_dbid is None


def test_the_note_line_carries_both_identifiers_the_chart_permalink_needs(patient, staff):
    """The address is /patient/<key>#noteId=<database id>, two kinds in the one link."""
    from canvas_sdk.test_utils.factories import (
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )

    note = NoteFactory(patient=patient, provider=staff)
    medication = MedicationFactory(patient=patient)
    PrescriptionFactory(patient=patient, prescriber=staff, medication=medication, note=note)

    offered = json_body(call("GET", f"/prescriptions?note_id={note.id}", caller=staff))["note"]

    assert offered["dbid"] == note.dbid
    assert offered["patient_key"] == str(patient.id)


# --- Coverage entries, which are what decide whether a class covers a prescription
#
# A class matches nothing until it carries at least one entry, so these are the rows the
# note header control ultimately stands on.


def _search_returning(results, taxonomy=None, catalogue=None):
    """Patch the ontologies catalogue to answer each of the search's three reads.

    The endpoint reads up to three routes per query, the product search, the class
    path taxonomy, and, only when the taxonomy is empty, the whole grouped table as
    the fallback the group name match folds candidates from. One patch routing on the
    url keeps a test honest about which read produced which row, where a single
    return value would feed the product rows to every call.
    """
    from unittest.mock import MagicMock, patch

    from medication_followup_protocol.api import program_api

    def answer(url):
        response = MagicMock()
        if url.startswith("/fdb/class-path/"):
            response.json.return_value = taxonomy or []
        elif "search=" in url:
            response.json.return_value = {"results": results}
        else:
            response.json.return_value = {"results": catalogue or []}
        return response

    return patch.object(program_api.ontologies_http, "get_json", side_effect=answer)


def _matching_path(path):
    """Patch the ontologies classification lookup to answer with this path.

    program_api.py and services/eligibility.py both import the one ontologies_http
    singleton, so patching it here through program_api reaches eligibility.py's own
    _classification_path too, which is what the criteria below that drive matching
    through this API, rather than through eligibility.py directly, need patched.
    """
    from unittest.mock import MagicMock, patch

    from medication_followup_protocol.api import program_api

    response = MagicMock()
    response.json.return_value = {"etc_path_id": path}
    return patch.object(program_api.ontologies_http, "get_json", return_value=response)


#: The two lisinopril products the local catalogue carries, which share one path.
LISINOPRIL_ROWS = [
    {
        "med_medication_id": 244899,
        "description_and_quantity": "lisinopril 10 mg tablet",
        "etc_path_id": [2549, 3050, 24, 3064],
        "etc_path_name": [
            "Cardiovascular Agents",
            "ACE Inhibitors",
            "Antihypertensives",
            "ACE Inhibitors",
        ],
    },
    {
        "med_medication_id": 183474,
        "description_and_quantity": "lisinopril 20 mg tablet",
        "etc_path_id": [2549, 3050, 24, 3064],
        "etc_path_name": [
            "Cardiovascular Agents",
            "ACE Inhibitors",
            "Antihypertensives",
            "ACE Inhibitors",
        ],
    },
]


def test_the_combo_box_lists_medication_groups(lead):
    """Covers scenario: AC29, the coverage combo box lists medication groups and a picked group stores its classification path. Covers criterion: AC29.

    The search form of the ontologies endpoint answers with a results list, which is a
    different shape from the single code form eligibility.py reads, so this asserts the
    list is what gets unwrapped.
    """
    with _search_returning(LISINOPRIL_ROWS[:1]):
        body = json_body(call("GET", "/medication-search?query=lisinopril", caller=lead))

    assert len(body["results"]) == 1
    assert body["results"][0]["etc_path_id"] == [2549, 3050, 24, 3064]


def test_a_row_is_named_by_its_group_rather_than_by_a_product(lead):
    """Covers scenario: AC29, the coverage combo box lists medication groups and a picked group stores its classification path. Covers criterion: AC29.

    The criterion asks for groups and the catalogue answers with products, so the name
    on a row is the most specific step of the classification path rather than the
    product description. A row reading lisinopril 10 mg tablet says a single strength
    was chosen when what was stored covers the whole group.
    """
    with _search_returning(LISINOPRIL_ROWS[:1]):
        body = json_body(call("GET", "/medication-search?query=lisinopril", caller=lead))

    assert body["results"][0]["display_name"] == "ACE Inhibitors"


def test_products_sharing_one_path_are_one_row(lead):
    """Covers scenario: AC29, the coverage combo box lists medication groups and a picked group stores its classification path. Covers criterion: AC29.

    Both lisinopril strengths carry the same classification path, so offering both
    offered the same group twice and picking either stored the identical entry. The
    products that matched travel with the row instead, which is what tells somebody who
    typed a drug name that the group in front of them is the right one.
    """
    with _search_returning(LISINOPRIL_ROWS):
        body = json_body(call("GET", "/medication-search?query=lisinopril", caller=lead))

    assert len(body["results"]) == 1
    assert body["results"][0]["matched_products"] == [
        "lisinopril 10 mg tablet",
        "lisinopril 20 mg tablet",
    ]


def test_two_paths_stay_two_rows(lead):
    """Covers criterion: AC29.

    The folding is by path, so genuinely different groups are never collapsed into one.
    Without this the test above would still pass against code that answered with a
    single row whatever it was given.
    """
    rows = LISINOPRIL_ROWS[:1] + [
        {
            "med_medication_id": 155744,
            "description_and_quantity": "metformin 500 mg tablet",
            "etc_path_id": [1117, 1218, 4538, 4539],
            "etc_path_name": [
                "Endocrine and Metabolic Agents",
                "Antidiabetic Agents",
                "Biguanides",
                "Biguanides",
            ],
        }
    ]

    with _search_returning(rows):
        body = json_body(call("GET", "/medication-search?query=in", caller=lead))

    assert [result["display_name"] for result in body["results"]] == [
        "ACE Inhibitors",
        "Biguanides",
    ]


def test_a_product_with_no_classification_is_no_group(lead):
    """Covers criterion: AC29.

    A row the catalogue carries no path for cannot become a group entry, since the
    matching rule reads a stored empty path as covering nothing. Offering it would put a
    row on the page that looks like coverage and silently is not.
    """
    rows = [
        {
            "med_medication_id": 999999,
            "description_and_quantity": "compounded cream",
            "etc_path_id": [],
            "etc_path_name": [],
        }
    ]

    with _search_returning(rows):
        body = json_body(call("GET", "/medication-search?query=compound", caller=lead))

    assert body["results"] == []


def test_an_empty_query_searches_nothing(lead):
    """Covers criterion: AC29.

    The combo box fires as somebody types, so an empty query answers with nothing rather
    than asking the catalogue for everything it has.
    """
    body = json_body(call("GET", "/medication-search?query=", caller=lead))

    assert body["results"] == []


#: The slice of the ETC taxonomy the class path route answers with, ids and the node's
#: own name only, ancestor names resolved by joining rows the way the endpoint does.
STATIN_TAXONOMY = [
    {"name": "Cardiovascular Agents", "path_ids": [2549]},
    {"name": "Antihyperlipidemics", "path_ids": [2549, 2545]},
    {"name": "HMG CoA Reductase Inhibitors", "path_ids": [2549, 2545, 2546]},
    {"name": "Statins", "path_ids": [2549, 2545, 2546, 2547]},
]


def test_a_group_name_finds_the_group(lead):
    """Covers criterion: AC29.

    The catalogue's own search runs over a product search term table, so typing
    statins returns no products, and a person setting up a statin program thinks in
    the group before the drug. The group name match against the class path taxonomy is
    what answers, with the path resolved by joining taxonomy rows on their ids.
    """
    with _search_returning([], taxonomy=STATIN_TAXONOMY):
        body = json_body(call("GET", "/medication-search?query=statins", caller=lead))

    assert len(body["results"]) == 1
    assert body["results"][0]["display_name"] == "Statins"
    assert body["results"][0]["etc_path_id"] == [2549, 2545, 2546, 2547]
    assert body["results"][0]["etc_path_name"] == [
        "Cardiovascular Agents",
        "Antihyperlipidemics",
        "HMG CoA Reductase Inhibitors",
        "Statins",
    ]
    assert body["results"][0]["matched_products"] == []


def test_the_group_name_match_is_a_containment_not_a_prefix(lead):
    """Covers criterion: AC29.

    Statin has to find Statins and coagul has to find Anticoagulants, since nobody
    types a taxonomy name exactly, so the match is case insensitive containment
    against each node's own name.
    """
    with _search_returning([], taxonomy=STATIN_TAXONOMY):
        body = json_body(call("GET", "/medication-search?query=STATIN", caller=lead))

    assert [result["display_name"] for result in body["results"]] == ["Statins"]


def test_a_group_found_both_ways_is_one_row_carrying_its_products(lead):
    """Covers criterion: AC29.

    A drug name whose group name also contains the query must not list the group
    twice. The product row wins the merge because it carries the matched products, the
    evidence line that tells somebody they found the right group.
    """
    taxonomy = [
        {"name": "Cardiovascular Agents", "path_ids": [2549]},
        {"name": "ACE Inhibitors", "path_ids": [2549, 3050]},
        {"name": "Antihypertensives", "path_ids": [2549, 3050, 24]},
        {"name": "ACE Inhibitors", "path_ids": [2549, 3050, 24, 3064]},
    ]
    with _search_returning(LISINOPRIL_ROWS, taxonomy=taxonomy):
        body = json_body(call("GET", "/medication-search?query=ace", caller=lead))

    named_ace = [r for r in body["results"] if r["display_name"] == "ACE Inhibitors"]
    assert named_ace[0]["matched_products"] == [
        "lisinopril 10 mg tablet",
        "lisinopril 20 mg tablet",
    ]


def test_a_name_repeated_down_one_branch_is_offered_once_at_the_top(lead):
    """Covers criterion: AC29.

    The FDB tree repeats a name where a leaf is the only member of its own class, so
    matching antiarrhythmics naively offers Class III Antiarrhythmics twice at two
    depths. The shallower node wins because the coverage prefix rule makes it cover
    everything the deeper one covers.
    """
    taxonomy = [
        {"name": "Cardiovascular Agents", "path_ids": [2549]},
        {"name": "Antiarrhythmic Agents", "path_ids": [2549, 700]},
        {"name": "Class III Antiarrhythmics", "path_ids": [2549, 700, 701]},
        {"name": "Class III Antiarrhythmics", "path_ids": [2549, 700, 701, 702]},
    ]
    with _search_returning([], taxonomy=taxonomy):
        body = json_body(call("GET", "/medication-search?query=class iii", caller=lead))

    assert [result["etc_path_id"] for result in body["results"]] == [[2549, 700, 701]]


def test_an_empty_taxonomy_falls_back_to_folding_the_grouped_table(lead):
    """Covers criterion: AC29.

    A local instance carries the class path table empty, a fixture gap, while its
    grouped medication rows still carry their paths. The fallback folds every prefix
    of every distinct path into a candidate group, so typing an ancestor's name offers
    the ancestor, here Antihypertensives truncated out of the lisinopril path.
    """
    with _search_returning([], taxonomy=[], catalogue=LISINOPRIL_ROWS):
        body = json_body(
            call("GET", "/medication-search?query=antihypertensives", caller=lead)
        )

    assert len(body["results"]) == 1
    assert body["results"][0]["display_name"] == "Antihypertensives"
    assert body["results"][0]["etc_path_id"] == [2549, 3050, 24]
    assert body["results"][0]["etc_path_name"] == [
        "Cardiovascular Agents",
        "ACE Inhibitors",
        "Antihypertensives",
    ]


def test_a_picked_group_stores_its_classification_path(lead, medication_class):
    """Covers scenario: AC29, the coverage combo box lists medication groups and a picked group stores its classification path. Covers criterion: AC29."""
    from medication_followup_protocol.models import MedicationClassCoverage

    response = call(
        "POST",
        f"/classes/{medication_class.dbid}/coverage",
        {
            "kind": "group",
            "display_name": "lisinopril 10 mg tablet",
            "etc_path_id": [2549, 3050, 24, 3064],
            "etc_path_name": ["Cardiovascular Agents", "ACE Inhibitors", "Lisinopril", "Lisinopril"],
        },
        caller=lead,
    )

    assert status_of(response) == HTTPStatus.CREATED
    entry = MedicationClassCoverage.objects.get(medication_class=medication_class)
    assert entry.etc_path_id == [2549, 3050, 24, 3064]
    assert entry.kind == "group"


def test_a_group_entry_needs_a_path(lead, medication_class):
    """Covers criterion: AC29.

    A group with no path would match every prescription, since a zero length prefix is a
    prefix of anything, so it is refused rather than stored.
    """
    from medication_followup_protocol.models import MedicationClassCoverage

    response = call(
        "POST",
        f"/classes/{medication_class.dbid}/coverage",
        {"kind": "group", "display_name": "nothing"},
        caller=lead,
    )

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    assert not MedicationClassCoverage.objects.exists()


def test_an_unknown_kind_of_entry_is_refused(lead, medication_class):
    """Covers criterion: AC29."""
    from medication_followup_protocol.models import MedicationClassCoverage

    response = call(
        "POST",
        f"/classes/{medication_class.dbid}/coverage",
        {"kind": "whatever", "display_name": "x"},
        caller=lead,
    )

    assert status_of(response) == HTTPStatus.BAD_REQUEST
    assert not MedicationClassCoverage.objects.exists()


def test_a_class_lists_and_loses_its_coverage_entries(lead, medication_class):
    """Covers criterion: AC29."""
    from medication_followup_protocol.models import MedicationClassCoverage

    created = json_body(
        call(
            "POST",
            f"/classes/{medication_class.dbid}/coverage",
            {
                "kind": "group",
                "display_name": "lisinopril 10 mg tablet",
                "etc_path_id": [2549, 3050],
                "etc_path_name": ["Cardiovascular Agents", "ACE Inhibitors"],
            },
            caller=lead,
        )
    )

    listed = json_body(call("GET", f"/classes/{medication_class.dbid}/coverage", caller=lead))
    assert len(listed["coverage"]) == 1

    call("DELETE", f"/coverage/{created['id']}", caller=lead)
    assert not MedicationClassCoverage.objects.exists()


def test_a_caller_below_the_role_floor_cannot_add_coverage(medication_class):
    """Covers criterion: AC29.

    Coverage decides which prescriptions a programme catches, so it answers to the same
    floor every other write on the configuration page does.
    """
    from canvas_sdk.test_utils.factories import StaffRoleFactory

    from medication_followup_protocol.models import MedicationClassCoverage

    administrator = StaffFactory(active=True)
    administrator.roles.all().delete()
    StaffRoleFactory(staff=administrator, domain="ADM", domain_privilege_level=100000)

    response = call(
        "POST",
        f"/classes/{medication_class.dbid}/coverage",
        {"kind": "group", "etc_path_id": [1, 2], "display_name": "x"},
        caller=administrator,
    )

    assert status_of(response) == HTTPStatus.FORBIDDEN
    assert not MedicationClassCoverage.objects.exists()


def test_cloning_a_class_copies_its_coverage(lead, medication_class):
    """Covers criterion: AC29.

    A clone that copied the steps and left the coverage behind would look complete on the
    configuration page and match no prescription at all, and the symptom would be a note
    header control that never appears, a long way from the cause.
    """
    from medication_followup_protocol.models import MedicationClassCoverage

    call(
        "POST",
        f"/classes/{medication_class.dbid}/coverage",
        {
            "kind": "group",
            "display_name": "lisinopril 10 mg tablet",
            "etc_path_id": [2549, 3050, 24, 3064],
            "etc_path_name": ["Cardiovascular Agents", "ACE Inhibitors", "Lisinopril", "Lisinopril"],
        },
        caller=lead,
    )

    clone = json_body(
        call("POST", f"/classes/{medication_class.dbid}/clone", {"name": "A copy"}, caller=lead)
    )

    copied = MedicationClassCoverage.objects.filter(medication_class__dbid=clone["id"])
    assert copied.count() == 1
    assert copied.first().etc_path_id == [2549, 3050, 24, 3064]


# --- AC31 through AC50, the widened patient scoped eligibility and what it unlocks
#
# Every criterion below either depends on services/eligibility.py's patient scoped
# query or on a write path no earlier test drove with a real prescription_id, per
# 04-delivery/WORK-LEDGER.md's own reconciliation notes for spec version 3.


def test_two_classes_may_both_run_on_the_same_medication_at_once(
    medication_class, patient, staff, enrolment
):
    """Covers scenario: AC31, two classes may both run on the same medication at once. Covers criterion: AC31.

    enrolment already carries an active Enrollment on medication_class for this patient
    and this medication_label, per the conftest fixture. A second class covering the
    same medication is what this criterion says may run alongside it.
    """
    second_class = MedicationClass.objects.create(
        name="Second GLP-1 program",
        active=True,
        recheck_note_type_id=medication_class.recheck_note_type_id,
    )

    response = call(
        "POST",
        "/enrollments",
        {
            "patient_id": patient.id,
            "medication_class_id": second_class.dbid,
            "medication_label": enrolment.medication_label,
            "prescriber_staff_id": staff.id,
        },
        caller=staff,
    )

    assert status_of(response) == HTTPStatus.CREATED, json_body(response)
    active = Enrollment.objects.filter(
        patient__dbid=patient.dbid,
        medication_label=enrolment.medication_label,
        status=EnrollmentStatus.ACTIVE,
    )
    assert active.count() == 2
    assert set(active.values_list("medication_class_id", flat=True)) == {
        medication_class.dbid,
        second_class.dbid,
    }


def test_the_note_scoped_pane_shows_one_card_per_matched_class_ordered_by_name(patient, staff):
    """Covers scenario: AC32, the note scoped pane shows one card per matched class with no dropdown. Covers criterion: AC32.

    Whether the page draws a dropdown or a row of cards, and whether one arrives
    preselected, are rendering facts the AC32 browser spec confirms live. What this
    proves is the data contract that rendering reads from, one classes entry per
    matched class, ordered by class name.
    """
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from tests.conftest import make

    beta = MedicationClass.objects.create(name="Beta class", active=True)
    alpha = MedicationClass.objects.create(name="Alpha class", active=True)
    path = [2549, 3050, 24, 3064]
    for medication_class in (beta, alpha):
        MedicationClassCoverage.objects.create(
            medication_class=medication_class,
            kind=CoverageKind.GROUP,
            etc_path_id=path,
            etc_path_name=["a", "b", "c", "d"],
            display_name="lisinopril 10 mg tablet",
        )

    note = NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    make(
        MedicationCoding, medication=medication, display="lisinopril 20 mg tablet",
        system="http://www.fdbhealth.com/", code="fdb-lisinopril-20",
    )
    PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note,
        committer=CanvasUserFactory(),
    )

    with _matching_path(path):
        shown = json_body(call("GET", f"/prescriptions?note_id={note.id}", caller=staff))

    names = [c["name"] for c in shown["prescriptions"][0]["classes"]]
    assert names == ["Alpha class", "Beta class"]


def test_an_overlapping_coverage_entry_is_not_refused(lead, medication_class):
    """Covers scenario: AC33, an overlapping coverage entry is warned about rather than refused. Covers criterion: AC33.

    The warning itself is drawn client side, confirmed live by the AC33 browser spec.
    What a pytest can prove is the server half of this criterion, that saving a
    coverage entry whose classification path overlaps a different class's own entry
    succeeds rather than being refused.
    """
    path = [2549, 3050, 24, 3064]
    other_class = MedicationClass.objects.create(name="Other class", active=True)
    call(
        "POST", f"/classes/{other_class.dbid}/coverage",
        {
            "kind": "group", "display_name": "lisinopril 10 mg tablet",
            "etc_path_id": path, "etc_path_name": ["a", "b", "c", "d"],
        },
        caller=lead,
    )

    response = call(
        "POST", f"/classes/{medication_class.dbid}/coverage",
        {
            "kind": "group", "display_name": "lisinopril 10 mg tablet",
            "etc_path_id": path, "etc_path_name": ["a", "b", "c", "d"],
        },
        caller=lead,
    )

    assert status_of(response) == HTTPStatus.CREATED


def test_a_card_names_another_program_already_running_on_the_medication(
    medication_class, patient, staff, enrolment
):
    """Covers scenario: AC34, a card names another program already running on the same medication. Covers criterion: AC34."""
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from tests.conftest import make

    second_class = MedicationClass.objects.create(name="Second class", active=True)
    path = [2549, 3050, 24, 3064]
    for target in (medication_class, second_class):
        MedicationClassCoverage.objects.create(
            medication_class=target, kind=CoverageKind.GROUP,
            etc_path_id=path, etc_path_name=["a", "b", "c", "d"],
            display_name="semaglutide",
        )

    note = NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    # Labelled to match enrolment.medication_label exactly, since it is that match, one
    # patient already running semaglutide under medication_class, that makes second_class's
    # own card need to say so.
    make(
        MedicationCoding, medication=medication, display=enrolment.medication_label,
        system="http://www.fdbhealth.com/", code="fdb-semaglutide",
    )
    PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note,
        committer=CanvasUserFactory(),
    )

    with _matching_path(path):
        shown = json_body(call("GET", f"/prescriptions?note_id={note.id}", caller=staff))

    second_card = next(
        c for c in shown["prescriptions"][0]["classes"] if c["id"] == second_class.dbid
    )
    assert second_card.get("already_running"), (
        "the second class's own card carries nothing naming that a program is already "
        f"running on this medication under {medication_class.name}"
    )


def test_a_late_enrolment_offers_and_applies_the_catch_up_choice(medication_class, staff):
    """Covers scenario: AC38, a late enrolment lists its already due steps for the practitioner to tick. Covers criterion: AC38.

    No earlier test in this suite ever passed a real prescription_id whose written_date
    falls before the day of submission, so the catch up branch in create_enrollment,
    behaviour steps 22 to 24, has never actually run. This drives both halves, ticked
    and left unticked, against a prescription written ten days before it is enrolled.
    """
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PatientFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from medication_followup_protocol.services.practice_time import today as plugin_today
    from tests.conftest import make

    due_step = ProgramStep.objects.create(
        medication_class=medication_class, sequence=0, day_offset=0, kind=StepKind.MESSAGE,
        message_body="Welcome",
    )
    future_step = ProgramStep.objects.create(
        medication_class=medication_class, sequence=1, day_offset=30, kind=StepKind.MESSAGE,
        message_body="Later",
    )
    path = [2549, 3050, 24, 3064]
    MedicationClassCoverage.objects.create(
        medication_class=medication_class, kind=CoverageKind.GROUP,
        etc_path_id=path, etc_path_name=["a", "b", "c", "d"],
        display_name="lisinopril 10 mg tablet",
    )

    def _late_prescription(owner):
        note = NoteFactory(patient=owner)
        medication = MedicationFactory(patient=owner)
        make(
            MedicationCoding, medication=medication, display="lisinopril 20 mg tablet",
            system="http://www.fdbhealth.com/", code="fdb-lisinopril-20",
        )
        written = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)
        prescription = PrescriptionFactory(
            patient=owner, prescriber=staff, medication=medication, note=note,
            committer=CanvasUserFactory(), written_date=written,
        )
        return note, prescription

    # --- First half, the preview lists the already due step unticked, then it is ticked
    ticked_patient = PatientFactory(active=True, deceased=False)
    note, prescription = _late_prescription(ticked_patient)

    with _matching_path(path):
        preview = json_body(call("GET", f"/prescriptions?note_id={note.id}", caller=staff))
    card = preview["prescriptions"][0]["classes"][0]
    assert due_step.dbid in card["due_step_ids"]
    assert future_step.dbid not in card["due_step_ids"]

    response = call(
        "POST", "/enrollments",
        {
            "patient_id": ticked_patient.id,
            "medication_class_id": medication_class.dbid,
            "medication_label": "lisinopril 20 mg tablet",
            "prescription_id": str(prescription.id),
            "prescriber_staff_id": str(staff.id),
            "catch_up_step_ids": [due_step.dbid],
        },
        caller=staff,
    )
    assert status_of(response) == HTTPStatus.CREATED, json_body(response)
    enrolled = Enrollment.objects.get(patient__dbid=ticked_patient.dbid)
    ticked_row = enrolled.steps.get(program_step=due_step)
    assert ticked_row.due_date == plugin_today()
    assert ticked_row.day_offset == 0
    assert ticked_row.status == StepStatus.PENDING

    # --- Second half, the same due step left unticked is written skipped instead
    skipped_patient = PatientFactory(active=True, deceased=False)
    _note2, prescription2 = _late_prescription(skipped_patient)

    response = call(
        "POST", "/enrollments",
        {
            "patient_id": skipped_patient.id,
            "medication_class_id": medication_class.dbid,
            "medication_label": "lisinopril 20 mg tablet",
            "prescription_id": str(prescription2.id),
            "prescriber_staff_id": str(staff.id),
        },
        caller=staff,
    )
    assert status_of(response) == HTTPStatus.CREATED, json_body(response)
    enrolled2 = Enrollment.objects.get(patient__dbid=skipped_patient.dbid)
    skipped_row = enrolled2.steps.get(program_step=due_step)
    assert skipped_row.status == StepStatus.SKIPPED
    assert "was not selected" in skipped_row.failure_reason


def test_the_ongoing_tab_lists_history_when_none_are_active(patient, staff, medication_class):
    """Covers scenario: AC39, the Ongoing tab lists finished and stopped enrolments as history when none are active. Covers criterion: AC39."""
    stopped = Enrollment.objects.create(
        patient_id=patient.dbid, medication_class=medication_class,
        medication_label="warfarin", sender_staff_id=staff.dbid, prescriber_staff_id=staff.dbid,
        start_date=datetime.date(2026, 7, 1), status=EnrollmentStatus.STOPPED,
        stopped_reason="No longer needed",
    )

    shown = json_body(call("GET", f"/enrollments?patient_id={patient.id}", caller=staff))

    assert not any(e["status"] == "active" for e in shown["enrollments"])
    assert any(
        e["id"] == stopped.dbid and e["status"] == "stopped" for e in shown["enrollments"]
    )


def test_an_uncovered_prescriptions_card_names_its_therapeutic_group(patient, staff):
    """Covers scenario: AC44, an uncovered prescription's card names its therapeutic group. Covers criterion: AC44."""
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from tests.conftest import make

    note = NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    make(
        MedicationCoding, medication=medication, display="warfarin 2.5 mg tablet",
        system="http://www.fdbhealth.com/", code="fdb-warfarin",
    )
    PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note,
        committer=CanvasUserFactory(),
    )
    path = [2549, 3054, 28, 3068]

    with _matching_path(path):
        shown = json_body(call("GET", f"/prescriptions?note_id={note.id}", caller=staff))

    card = shown["prescriptions"][0]
    assert card["classes"] == []
    assert card.get("therapeutic_group"), (
        "the card for an uncovered prescription carries nothing naming its therapeutic "
        "group, so the note scoped pane has no group name left to show beside it"
    )


def test_a_new_class_has_no_coverage_and_an_existing_one_lists_its_entries(lead, medication_class):
    """Covers scenario: AC45, a new class shows a bare picker and an existing class shows its coverage as removable chips. Covers criterion: AC45.

    Whether the picker renders bare or the chips render at all is the client's own
    concern, confirmed live by the AC45 browser spec. What this proves is the data
    contract that rendering choice reads from, an empty coverage list for a freshly
    created class and, for one already carrying entries, the full list, each row
    carrying its own id, which is what a removable chip needs to call DELETE.
    """
    created = json_body(call("POST", "/classes", {"name": "Fresh class"}, caller=lead))
    fresh_coverage = json_body(call("GET", f"/classes/{created['id']}/coverage", caller=lead))
    assert fresh_coverage["coverage"] == []

    call(
        "POST", f"/classes/{medication_class.dbid}/coverage",
        {
            "kind": "group", "display_name": "lisinopril 10 mg tablet",
            "etc_path_id": [1, 2, 3], "etc_path_name": ["a", "b", "c"],
        },
        caller=lead,
    )
    call(
        "POST", f"/classes/{medication_class.dbid}/coverage",
        {"kind": "product", "display_name": "atorvastatin 40 mg tablet", "med_medication_id": "fdb-atorva-40"},
        caller=lead,
    )

    existing_coverage = json_body(
        call("GET", f"/classes/{medication_class.dbid}/coverage", caller=lead)
    )
    assert len(existing_coverage["coverage"]) == 2
    assert all(entry["id"] for entry in existing_coverage["coverage"])


def _admin_template_source() -> str:
    """The raw markup of the configuration page template, read off disk.

    GET /admin runs render_to_string, and render_to_string calls a plugin runner
    utility that raises outside a real plugin context, which is what every other test
    in this suite avoids by never driving a page route at all. Reading the template
    file directly proves the same content with no such dependency, and it is what the
    page actually serves, since render_to_string performs no templating on this file
    beyond the two Django variables substituted at its very top.
    """
    from pathlib import Path

    import medication_followup_protocol as package

    return (
        Path(package.__file__).parent / "templates" / "program_admin.html"
    ).read_text()


def test_the_admin_page_ships_the_name_field_the_focus_rule_targets(lead):
    """Covers scenario: AC46, opening the class form focuses the Name field and a coverage pick does not move it. Covers criterion: AC46.

    Focus is a runtime fact only a browser can observe, which the AC46 browser spec
    drives live. Pytest runs no DOM at all, so what this checks is the one thing it can,
    that the page served to that browser still carries the element the focus rule
    targets, id class-name, so a rename of that field fails here first rather than only
    inside a browser trace months later.
    """
    assert "id='class-name'" in _admin_template_source()


def test_the_admin_page_ships_the_searching_rows_own_wording(lead):
    """Covers scenario: AC47, the coverage search field keeps typed text and shows a loading row while a search is in flight. Covers criterion: AC47.

    Typed text staying in the field during a live search is a runtime fact only a
    browser can observe, which the AC47 browser spec drives live. What a pytest can
    check on its own is whether the page it is served even carries the loading row's
    own wording, since a page that never mentions it cannot show it no matter what the
    browser does.
    """
    assert "Searching medication groups" in _admin_template_source()


def test_a_class_card_names_its_coverage_or_shows_no_coverage(lead, medication_class):
    """Covers scenario: AC49, a class card names its coverage or shows a No coverage badge when it has none. Covers criterion: AC49.

    The badge and the sentence are drawn client side off exactly this data, one fetch of
    GET /classes and one of GET /classes/<id>/coverage per card, per program_admin.html's
    own loadCoverage. What this proves is that data, both entries' display_name for a
    class carrying two, and an empty list for a class carrying none.
    """
    call(
        "POST", f"/classes/{medication_class.dbid}/coverage",
        {
            "kind": "group", "display_name": "lisinopril 10 mg tablet",
            "etc_path_id": [1, 2, 3], "etc_path_name": ["a", "b", "c"],
        },
        caller=lead,
    )
    call(
        "POST", f"/classes/{medication_class.dbid}/coverage",
        {"kind": "product", "display_name": "atorvastatin 40 mg tablet", "med_medication_id": "fdb-atorva-40"},
        caller=lead,
    )

    covered = json_body(call("GET", f"/classes/{medication_class.dbid}/coverage", caller=lead))
    names = {entry["display_name"] for entry in covered["coverage"]}
    assert names == {"lisinopril 10 mg tablet", "atorvastatin 40 mg tablet"}

    bare = MedicationClass.objects.create(name="Nothing covered yet", active=True)
    bare_coverage = json_body(call("GET", f"/classes/{bare.dbid}/coverage", caller=lead))
    assert bare_coverage["coverage"] == []


def test_the_enrolment_anchors_to_the_prescriptions_written_date(medication_class, patient, staff):
    """Covers scenario: AC50, the enrolment start date and every step's due date anchor to the prescription's written date. Covers criterion: AC50.

    Both program steps carry a positive day offset, matching this criterion's own Given
    of no step already due, so nothing here exercises the late enrolment catch up branch
    AC38 owns. Every earlier enrolling test in this suite either passed no prescription_id
    at all, which falls back to today() and never exercises
    to_practice_date(selected_prescription.written_date), or reused the enrolment
    fixture's own hardcoded start date, so this is the first to drive that branch with a
    real prescription end to end.

    written_date is set five days in the past rather than to the moment the test runs.
    A prescription written today makes written_date and the submission day the same
    value, so a test built on today would still pass if the code quietly fell back to
    start_date = today() instead of reading the prescription's own written_date, which
    is exactly the defect this criterion exists to rule out. Anchoring the assertion to
    a written_date that provably differs from today is what tells the two apart, and
    five days keeps every offset below well clear of due, so no step already due still
    holds.
    """
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )

    for offset in (7, 14):
        ProgramStep.objects.create(
            medication_class=medication_class, sequence=offset, day_offset=offset,
            kind=StepKind.MESSAGE, message_body=f"Day {offset}",
        )

    note = NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    written = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)
    prescription = PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note,
        committer=CanvasUserFactory(), written_date=written,
    )

    response = call(
        "POST", "/enrollments",
        {
            "patient_id": patient.id,
            "medication_class_id": medication_class.dbid,
            "medication_label": "semaglutide",
            "prescription_id": str(prescription.id),
            "prescriber_staff_id": str(staff.id),
        },
        caller=staff,
    )

    assert status_of(response) == HTTPStatus.CREATED, json_body(response)
    enrolled = Enrollment.objects.get(patient__dbid=patient.dbid, medication_label="semaglutide")
    expected_start = written.date()
    assert enrolled.start_date == expected_start
    for step in enrolled.steps.all():
        assert step.due_date == expected_start + datetime.timedelta(days=step.day_offset)


# --- The follow ups pane, one answer in two scopes
#
# GET /followups is what both the note header control and the chart header control read,
# the note scope filtering to one note and the patient scope carrying every note the
# patient has. The pane draws groups and cards straight out of this, so what a card says
# and which group it lands in are settled here rather than in the page.


def _covered_prescription(patient, staff, class_names, path, display, note=None, written=None):
    """One committed prescription, and one class per name covering its classification."""
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from tests.conftest import make

    classes = []
    for name in class_names:
        medication_class = MedicationClass.objects.create(name=name, active=True)
        MedicationClassCoverage.objects.create(
            medication_class=medication_class,
            kind=CoverageKind.GROUP,
            etc_path_id=path,
            etc_path_name=["a", "b", "c", "d"],
            display_name=display,
        )
        classes.append(medication_class)

    note = note or NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    make(
        MedicationCoding, medication=medication, display=display,
        system="http://www.fdbhealth.com/", code=f"fdb-{display}",
    )
    extra = {"written_date": written} if written is not None else {}
    prescription = PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note,
        committer=CanvasUserFactory(), **extra,
    )
    return note, prescription, classes


def test_the_followups_pane_lists_one_card_per_matched_class_under_its_note(patient, staff):
    """Covers scenario: AC32, the note scoped pane shows one card per matched class with no dropdown. Covers criterion: AC32.

    The pane the note header control opens has no chooser on a card any more, so the
    thing it draws has to arrive already split, one card per prescription and class
    pair, ordered by class name. This is that contract.
    """
    path = [2549, 3050, 24, 3064]
    note, _, _ = _covered_prescription(
        patient, staff, ["Beta class", "Alpha class"], path, "lisinopril 20 mg tablet"
    )

    with _matching_path(path):
        shown = json_body(call("GET", f"/followups?note_id={note.id}", caller=staff))

    assert len(shown["notes"]) == 1
    group = shown["notes"][0]
    assert group["dbid"] == note.dbid
    assert [card["class_name"] for card in group["programs"]] == ["Alpha class", "Beta class"]
    assert {card["state"] for card in group["programs"]} == {"startable"}
    assert all(card["medication_label"] == "lisinopril 20 mg tablet" for card in group["programs"])


def test_the_followups_pane_groups_the_patients_cards_by_note(patient, staff):
    """Covers scenario: AC15, the Follow ups control shows every program a patient is on. Covers criterion: AC15.

    The chart wide scope is the note scope repeated, one group per note carrying that
    note's own cards, which is what lets one page serve both controls.
    """
    from canvas_sdk.test_utils.factories import NoteFactory

    # One class covering the path both prescriptions classify to, so what this proves is
    # the grouping rather than the matching. Two classes over one path would put both of
    # them on both cards, which is correct and would say nothing about which note a card
    # landed under.
    path = [2549, 3050, 24, 3064]
    first_note, _, _ = _covered_prescription(
        patient, staff, ["Alpha class"], path, "lisinopril 20 mg tablet"
    )
    second_note = NoteFactory(patient=patient)
    _covered_prescription(
        patient, staff, [], path, "ramipril 5 mg capsule", note=second_note
    )

    with _matching_path(path):
        shown = json_body(call("GET", f"/followups?patient_id={patient.id}", caller=staff))

    by_dbid = {group["dbid"]: group for group in shown["notes"]}
    assert set(by_dbid) == {first_note.dbid, second_note.dbid}
    assert [c["medication_label"] for c in by_dbid[first_note.dbid]["programs"]] == [
        "lisinopril 20 mg tablet"
    ]
    assert [c["medication_label"] for c in by_dbid[second_note.dbid]["programs"]] == [
        "ramipril 5 mg capsule"
    ]
    assert [c["class_name"] for c in by_dbid[first_note.dbid]["programs"]] == ["Alpha class"]
    assert [c["class_name"] for c in by_dbid[second_note.dbid]["programs"]] == ["Alpha class"]


def test_a_startable_card_carries_the_steps_already_due_on_its_own_start_date(patient, staff):
    """Covers scenario: AC38, a late enrolment lists its already due steps for the practitioner to tick. Covers criterion: AC38.

    The pane asks about these in a dialog before it writes anything, so each one has to
    arrive naming what it actually does rather than only when it falls due.
    """
    path = [2549, 3050, 24, 3064]
    written = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    note, _, classes = _covered_prescription(
        patient, staff, ["Late class"], path, "amiodarone 200 mg tablet", written=written
    )
    ProgramStep.objects.create(
        medication_class=classes[0], sequence=0, day_offset=0, kind=StepKind.MESSAGE,
        message_body="Check in on how it is going",
    )
    ProgramStep.objects.create(
        medication_class=classes[0], sequence=1, day_offset=90, kind=StepKind.MESSAGE,
        message_body="Book the bloods",
    )

    with _matching_path(path):
        shown = json_body(call("GET", f"/followups?note_id={note.id}", caller=staff))

    card = shown["notes"][0]["programs"][0]
    assert card["state"] == "startable"
    assert card["step_count"] == 2
    assert [step["summary"] for step in card["due_steps"]] == ["Check in on how it is going"]


def test_a_card_names_another_class_already_running_on_the_same_medication(patient, staff):
    """Covers scenario: AC34, a card names another program already running on the same medication. Covers criterion: AC34."""
    path = [2549, 3050, 24, 3064]
    note, prescription, classes = _covered_prescription(
        patient, staff, ["Alpha class", "Beta class"], path, "lisinopril 20 mg tablet"
    )
    alpha = [c for c in classes if c.name == "Alpha class"][0]
    Enrollment.objects.create(
        patient=patient, medication_class=alpha, medication_label="lisinopril 20 mg tablet",
        prescription_id=str(prescription.id), start_date=datetime.date.today(),
        status=EnrollmentStatus.ACTIVE, start_note_dbid=note.dbid,
        prescriber_staff_id=staff.dbid,
    )

    with _matching_path(path):
        shown = json_body(call("GET", f"/followups?note_id={note.id}", caller=staff))

    by_name = {card["class_name"]: card for card in shown["notes"][0]["programs"]}
    assert by_name["Alpha class"]["state"] == "running"
    assert by_name["Beta class"]["state"] == "startable"
    assert by_name["Beta class"]["already_running"] == "Alpha class"


def test_an_uncovered_prescription_gets_one_card_naming_its_therapeutic_group(patient, staff):
    """Covers scenario: AC44, an uncovered prescription's card names its therapeutic group. Covers criterion: AC44."""
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from tests.conftest import make

    note = NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    make(
        MedicationCoding, medication=medication, display="warfarin 2.5 mg tablet",
        system="http://www.fdbhealth.com/", code="fdb-warfarin",
    )
    PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note,
        committer=CanvasUserFactory(),
    )

    with _matching_path([2549, 3054, 28, 3068]):
        shown = json_body(call("GET", f"/followups?note_id={note.id}", caller=staff))

    card = shown["notes"][0]["programs"][0]
    assert card["state"] == "uncovered"
    assert card["class_id"] is None
    assert card["therapeutic_group"]


def test_a_running_cards_enrollment_carries_its_steps(patient, staff):
    """Covers scenario: AC42, the note scoped and patient scoped panes render the same section for one enrolment. Covers criterion: AC42.

    One renderer answers both scopes now because there is one page, so a running card
    carries the same section shape whichever query parameter asked for it.
    """
    path = [2549, 3050, 24, 3064]
    note, prescription, classes = _covered_prescription(
        patient, staff, ["Alpha class"], path, "lisinopril 20 mg tablet"
    )
    program_step = ProgramStep.objects.create(
        medication_class=classes[0], sequence=0, day_offset=7, kind=StepKind.MESSAGE,
        message_body="Check in on how it is going",
    )
    enrollment = Enrollment.objects.create(
        patient=patient, medication_class=classes[0],
        medication_label="lisinopril 20 mg tablet", prescription_id=str(prescription.id),
        start_date=datetime.date.today(), status=EnrollmentStatus.ACTIVE,
        start_note_dbid=note.dbid, prescriber_staff_id=staff.dbid,
    )
    EnrolledStep.objects.create(
        enrollment=enrollment, program_step=program_step, sequence=0, day_offset=7,
        kind=StepKind.MESSAGE, due_date=datetime.date.today() + datetime.timedelta(days=7),
        status=StepStatus.PENDING,
    )

    with _matching_path(path):
        by_note = json_body(call("GET", f"/followups?note_id={note.id}", caller=staff))
        by_patient = json_body(call("GET", f"/followups?patient_id={patient.id}", caller=staff))

    note_card = by_note["notes"][0]["programs"][0]
    patient_card = by_patient["notes"][0]["programs"][0]
    assert note_card["state"] == "running"
    assert note_card["enrollment"] == patient_card["enrollment"]
    assert [step["status_label"] for step in note_card["enrollment"]["steps"]] == ["To come"]


def test_the_followups_pane_is_empty_when_nothing_was_named(staff):
    """Covers criterion: AC15."""
    assert json_body(call("GET", "/followups", caller=staff))["notes"] == []


# --- A program with no steps is never running
#
# A class is created before it has a step or a coverage entry, so at the moment it exists
# it does nothing. Created active it spent that window looking like a program the practice
# was relying on, and activating one that still has no step produces an enrolment that
# schedules nothing and says nothing on the chart. Both are refused here rather than only
# in the configuration page, since the rule belongs to the state change.


def test_a_new_class_starts_inactive(lead):
    """Covers criterion: AC1."""
    created = json_body(call("POST", "/classes", {"name": "Fresh and empty"}, caller=lead))

    assert created["active"] is False
    assert MedicationClass.objects.get(dbid=created["id"]).active is False


def test_a_class_with_no_steps_cannot_be_activated(lead):
    """Covers criterion: AC1."""
    created = json_body(call("POST", "/classes", {"name": "Still empty"}, caller=lead))

    refused = call("PATCH", f"/classes/{created['id']}", {"active": True}, caller=lead)

    assert status_of(refused) == HTTPStatus.BAD_REQUEST
    assert "step" in json_body(refused)["error"].lower()
    assert MedicationClass.objects.get(dbid=created["id"]).active is False


def test_a_class_carrying_a_step_may_be_activated(lead):
    """Covers criterion: AC1."""
    created = json_body(call("POST", "/classes", {"name": "Has a step"}, caller=lead))
    call(
        "POST", f"/classes/{created['id']}/steps",
        {"day_offset": 0, "kind": "message", "message_body": "Welcome."},
        caller=lead,
    )

    activated = call("PATCH", f"/classes/{created['id']}", {"active": True}, caller=lead)

    assert status_of(activated) == HTTPStatus.OK
    assert MedicationClass.objects.get(dbid=created["id"]).active is True


def test_an_active_class_may_always_be_deactivated(lead, medication_class):
    """Covers criterion: AC1.

    The refusal is one directional on purpose. Turning a program off is what a staff member
    reaches for when it is misconfigured, so a rule about its steps must never stand in the
    way of stopping it.
    """
    MedicationClass.objects.filter(dbid=medication_class.dbid).update(active=True)
    ProgramStep.objects.filter(medication_class__dbid=medication_class.dbid).delete()

    stopped = call("PATCH", f"/classes/{medication_class.dbid}", {"active": False}, caller=lead)

    assert status_of(stopped) == HTTPStatus.OK
    assert MedicationClass.objects.get(dbid=medication_class.dbid).active is False


# --- The chart keeps up with the pane
#
# A banner reaches the chart on its own, because saving a BannerAlert broadcasts on the
# patient's chart subscription. An action button does not. The chart asks the plugin for
# its button set when it mounts and after that only reacts to a pushed reload, so without
# these the Follow ups control showed whatever it showed when the chart was opened.


def test_starting_a_program_pushes_a_chart_button_reload(patient, staff, medication_class):
    """Covers criterion: AC26."""
    from canvas_sdk.test_utils.factories import MedicationFactory, PrescriptionFactory

    medication = MedicationFactory(patient=patient)
    prescription = PrescriptionFactory(patient=patient, prescriber=staff, medication=medication)

    effects = _effects(
        "POST", "/enrollments",
        {
            "patient_id": str(patient.id), "prescription_id": str(prescription.id),
            "prescriber_staff_id": str(staff.id), "medication_class_id": medication_class.dbid,
            "medication_label": "apixaban",
        },
        caller=staff,
    )

    assert _reload_targets(effects) == [str(patient.id)]


def test_stopping_a_program_pushes_a_chart_button_reload(patient, staff, medication_class):
    """Covers criterion: AC26."""
    enrollment = Enrollment.objects.create(
        patient=patient, medication_class=medication_class, medication_label="apixaban",
        prescriber_staff_id=staff.dbid, start_date=datetime.date.today(),
        status=EnrollmentStatus.ACTIVE,
    )

    effects = _effects(
        "POST", f"/enrollments/{enrollment.dbid}/stop", {"reason": "Done"}, caller=staff
    )

    assert _reload_targets(effects) == [str(patient.id)]


def test_a_stopped_program_reads_as_stopped_and_can_be_started_again(patient, staff):
    """Covers criterion: AC17.

    A stopped enrolment is what the pane has to show and it is also what a practitioner
    may want to run again. Reading the enrolment lookup as the answer to both questions
    left a stopped card carrying the Running badge with no way to start it.
    """
    path = [2549, 3050, 24, 3064]
    note, prescription, classes = _covered_prescription(
        patient, staff, ["Alpha class"], path, "lisinopril 20 mg tablet"
    )
    Enrollment.objects.create(
        patient=patient, medication_class=classes[0],
        medication_label="lisinopril 20 mg tablet", prescription_id=str(prescription.id),
        start_date=datetime.date.today(), status=EnrollmentStatus.STOPPED,
        stopped_reason="The patient asked us to stop.", start_note_dbid=note.dbid,
        prescriber_staff_id=staff.dbid,
    )

    with _matching_path(path):
        shown = json_body(call("GET", f"/followups?note_id={note.id}", caller=staff))

    card = shown["notes"][0]["programs"][0]
    assert card["state"] == "startable"
    assert card["enrollment"]["status"] == "stopped"
    assert card["enrollment"]["stopped_reason"] == "The patient asked us to stop."
