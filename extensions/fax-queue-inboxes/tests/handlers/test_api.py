"""The whole HTTP surface of Fax Queue Inboxes, driven the way the platform drives it.

Every request goes through FaxQueueAPI.compute(), never through a route method called
directly, because StaffSessionAuthMixin, the SIMPLE_API_AUTHENTICATE and SIMPLE_API_REQUEST
dispatch, and the response envelope are all part of what a criterion asks this surface to
do.
"""

import base64
import json
import pathlib
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.test_utils.factories import (
    IntegrationTaskFactory,
    IntegrationTaskReviewFactory,
    StaffFactory,
    TeamFactory,
)
from canvas_sdk.v1.data import IntegrationTaskStatus, Staff

# Event is only ever built inside make_event, through a local import that keeps the
# protobuf module out of the top level import graph, so its name is brought in here
# purely for the return annotation, under TYPE_CHECKING so nothing runtime changes.
if TYPE_CHECKING:
    from canvas_sdk.events import Event

from fax_queue_inboxes.handlers.api import FaxQueueAPI
from fax_queue_inboxes.models import FaxLabel, FaxRecord, PracticeLabel

PREFIX = "/fax-queue-inboxes"

# The five starter labels the specification's Behaviour step 12 names, spelled exactly as
# the feature file spells them, so a change to either one is caught here rather than only
# on a running instance.
STARTER_LABELS = ("Referral", "Insurance", "Lab Result", "Prior Authorization", "Other")

# The table creation fixture every test here relying on FaxRecord or PracticeLabel needs
# lives at tests/conftest.py, autouse, so nothing in this file has to ask for it by name.


def make_event(event_type: str, target: str = "", context: dict | None = None) -> "Event":
    """A real Event, built the way the platform builds one, for driving a handler."""
    from canvas_generated.messages.events_pb2 import Event as EventRequest
    from canvas_generated.messages.events_pb2 import EventType

    from canvas_sdk.events import Event

    return Event(
        EventRequest(
            type=EventType.Value(event_type),
            target=target,
            context=json.dumps(context or {}),
        )
    )


def raw_call(
    method: str, path: str, body: dict | None = None, caller: Staff | None = None
) -> list[Effect]:
    """Drive one request all the way through the API, as the platform would, and hand back
    the whole effects list rather than only the response, since a scenario sometimes asks
    what rides alongside the response rather than only what the response itself carries.
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
    return list(FaxQueueAPI(event).compute())


def call(
    method: str, path: str, body: dict | None = None, caller: Staff | None = None
) -> dict[str, Any]:
    """Drive one request and hand back its response only."""
    effects = raw_call(method, path, body, caller=caller)
    assert effects, f"{method} {path} produced no response"
    return dict(json.loads(effects[0].payload))


def authenticate(headers: dict) -> dict[str, Any]:
    """Drive the authenticate phase the platform runs before it ever sends a request."""
    event = make_event(
        "SIMPLE_API_AUTHENTICATE",
        context={
            "method": "GET",
            "path": f"{PREFIX}/tasks",
            "query_string": "",
            "body": "",
            "headers": headers,
        },
    )
    effects = FaxQueueAPI(event).compute()
    assert len(effects) == 1
    return dict(json.loads(effects[0].payload))


def json_body(response: dict[str, Any]) -> dict:
    """The JSON a response carries."""
    return dict(json.loads(base64.b64decode(response["body"])))


def status_of(response: dict[str, Any]) -> int:
    """The status code a response carries."""
    return int(response["status_code"])


# --- AC1 is covered at tests/handlers/test_application.py, which is FaxQueueDashboard's
# own home rather than FaxQueueAPI's.


def test_a_request_with_no_staff_session_is_refused() -> None:
    """Covers scenario: AC2, a request with no staff session is refused. Covers criterion: AC2. Driven at the authenticate phase itself, because that is the one place StaffSessionAuthMixin's own check runs, per Behaviour step 3. The route body is patched out and asserted never called, which is what proves the second half of the criterion, that an unauthenticated call never reaches a route at all."""
    with patch.object(FaxQueueAPI, "list_tasks") as route_body:
        response = authenticate({})
        route_body.assert_not_called()

    assert status_of(response) == HTTPStatus.UNAUTHORIZED


def test_a_request_with_a_patient_session_is_refused() -> None:
    """Covers criterion: AC2."""
    with patch.object(FaxQueueAPI, "list_tasks") as route_body:
        response = authenticate(
            {
                "canvas-logged-in-user-type": "Patient",
                "canvas-logged-in-user-id": "a-patient-id",
            }
        )
        route_body.assert_not_called()

    assert status_of(response) == HTTPStatus.UNAUTHORIZED


def test_a_staff_session_is_accepted() -> None:
    """Covers criterion: AC2. The negative half is what the criterion names, and this is the positive control that proves the two refusals above are about the session's type rather than about the authenticate phase refusing everything."""
    staff = StaffFactory(active=True)

    response = authenticate(
        {
            "canvas-logged-in-user-type": "Staff",
            "canvas-logged-in-user-id": str(staff.id),
        }
    )

    assert status_of(response) == HTTPStatus.OK


def test_the_unassigned_tab_shows_only_the_task_with_no_assignment_of_any_kind(
    db: None,
) -> None:
    """Covers scenario: AC3, the unassigned tab shows only the task with no assignment of any kind. Covers criterion: AC3."""
    unassigned = IntegrationTaskFactory(service_provider=None)
    team_reviewed = IntegrationTaskFactory(service_provider=None)
    IntegrationTaskReviewFactory(
        task=team_reviewed, reviewer=None, team_reviewer=TeamFactory(), junked=False
    )
    staff_assigned = IntegrationTaskFactory(service_provider=None)
    FaxRecord.objects.create(
        task_id=staff_assigned.dbid, assigned_staff=StaffFactory(active=True)
    )

    response = call("GET", "/tasks?tab=unassigned")

    assert status_of(response) == HTTPStatus.OK
    assert [task["id"] for task in json_body(response)["tasks"]] == [str(unassigned.id)]


def test_the_my_team_tab_includes_a_task_when_the_staff_member_belongs_to_its_team(
    db: None,
) -> None:
    """Covers scenario: AC4, the my team tab includes a task only when the staff member belongs to its assigned team. Covers criterion: AC4."""
    team = TeamFactory()
    member = StaffFactory(active=True)
    team.members.add(member)
    task = IntegrationTaskFactory(service_provider=None)
    FaxRecord.objects.create(task_id=task.dbid, assigned_team=team)

    response = call("GET", "/tasks?tab=my-team", caller=member)

    assert [t["id"] for t in json_body(response)["tasks"]] == [str(task.id)]


def test_the_my_team_tab_excludes_a_task_when_the_staff_member_does_not_belong_to_its_team(
    db: None,
) -> None:
    """Covers scenario: AC4, the my team tab includes a task only when the staff member belongs to its assigned team. Covers criterion: AC4."""
    team = TeamFactory()
    outsider = StaffFactory(active=True)
    task = IntegrationTaskFactory(service_provider=None)
    FaxRecord.objects.create(task_id=task.dbid, assigned_team=team)

    response = call("GET", "/tasks?tab=my-team", caller=outsider)

    assert json_body(response)["tasks"] == []


def test_the_all_tab_shows_every_task_with_no_narrowing_and_its_count_can_exceed_the_cap(
    db: None,
) -> None:
    """Covers scenario: AC5, the all tab shows every task with no narrowing by assignment and its count can exceed the page cap. Covers criterion: AC5. Fifty five tasks against a stated page cap of fifty, half of them carrying a FaxRecord assignment, so the all tab's own refusal to narrow by assignment is what this asserts rather than a coincidence of an unfiltered query."""
    tasks = [
        IntegrationTaskFactory(service_provider=None, patient=None) for _ in range(55)
    ]
    staff = StaffFactory(active=True)
    for task in tasks[:20]:
        FaxRecord.objects.create(task_id=task.dbid, assigned_staff=staff)

    response = call("GET", "/tasks?tab=all")

    assert status_of(response) == HTTPStatus.OK
    body = json_body(response)
    assert body["count"] == 55
    assert body["cap"] == 50
    assert body["count"] > body["cap"]
    assert len(body["tasks"]) == 50


def test_a_task_with_no_resolved_sender_shows_the_unknown_provider_literal(db: None) -> None:
    """Covers scenario: AC6, a task with no resolved sender shows the unknown provider literal. Covers criterion: AC6."""
    task = IntegrationTaskFactory(service_provider=None)

    response = call("GET", "/tasks?tab=all")

    row = next(t for t in json_body(response)["tasks"] if t["id"] == str(task.id))
    assert row["provider"] == "Unknown Provider"


def test_a_committed_native_review_outranks_the_plugins_own_assignment(db: None) -> None:
    """Covers scenario: AC7, a committed native review outranks the plugin's own assignment. Covers criterion: AC7."""
    assigned_staff = StaffFactory(active=True, first_name="Ada", last_name="Byron")
    reviewer = StaffFactory(active=True, first_name="Grace", last_name="Hopper")
    task = IntegrationTaskFactory(service_provider=None)
    FaxRecord.objects.create(task_id=task.dbid, assigned_staff=assigned_staff)
    IntegrationTaskReviewFactory(
        task=task, reviewer=reviewer, team_reviewer=None, junked=False
    )

    response = call("GET", "/tasks?tab=all")

    row = next(t for t in json_body(response)["tasks"] if t["id"] == str(task.id))
    assert row["assignee"] == "Grace Hopper"
    assert row["assignee"] != "Ada Byron"


def test_the_first_request_creates_the_starter_labels_and_a_second_request_does_not_repeat_it(
    db: None,
) -> None:
    """Covers scenario: AC8, the first request creates the starter labels and a second request does not repeat it. Covers criterion: AC8."""
    first = json_body(call("GET", "/labels"))
    assert sorted(label["name"] for label in first["labels"]) == sorted(STARTER_LABELS)
    assert len(first["labels"]) == 5

    second = json_body(call("GET", "/labels"))

    assert sorted(label["name"] for label in second["labels"]) == sorted(STARTER_LABELS)
    assert len(second["labels"]) == 5
    assert PracticeLabel.objects.count() == 5


def test_a_submitted_label_is_created_and_never_triggers_a_document_categorisation(
    db: None,
) -> None:
    """Covers scenario: AC9, a submitted label is created and never triggers a document categorisation. Covers criterion: AC9."""
    effects = raw_call("POST", "/labels", {"name": "Referral Follow Up"})

    response = json.loads(effects[0].payload)
    assert status_of(response) == HTTPStatus.CREATED
    assert PracticeLabel.objects.filter(name="Referral Follow Up").exists()
    assert not any(effect.type == EffectType.CATEGORIZE_DOCUMENT for effect in effects)

    afterward = json_body(call("GET", "/labels"))
    assert "Referral Follow Up" in [label["name"] for label in afterward["labels"]]


def test_assigning_a_task_to_a_team_sets_the_record_and_returns_the_prefill_effect(
    db: None,
) -> None:
    """Covers scenario: AC12, assigning a task to a team sets the record and returns the prefill effect. Covers criterion: AC12."""
    task = IntegrationTaskFactory(service_provider=None)
    team = TeamFactory()
    staff = StaffFactory(active=True)

    effects = raw_call(
        "POST", f"/tasks/{task.id}/assign", {"team_id": str(team.id)}, caller=staff
    )

    record = FaxRecord.objects.get(task_id=task.dbid)
    assert record.assigned_team_id == team.dbid

    assign_effects = [e for e in effects if e.type == EffectType.ASSIGN_DOCUMENT_REVIEWER]
    assert len(assign_effects) == 1
    sent = json.loads(assign_effects[0].payload)["data"]
    assert sent["document_id"] == str(task.id)
    assert sent["team_id"] == str(team.id)


def test_clearing_an_assignment_empties_the_record_and_returns_no_effect(db: None) -> None:
    """Covers scenario: AC13, clearing an assignment empties the record and returns no effect. Covers criterion: AC13."""
    task = IntegrationTaskFactory(service_provider=None)
    team = TeamFactory()
    FaxRecord.objects.create(task_id=task.dbid, assigned_team=team)

    effects = raw_call("DELETE", f"/tasks/{task.id}/assign")

    record = FaxRecord.objects.get(task_id=task.dbid)
    assert record.assigned_team_id is None
    assert record.assigned_staff_id is None
    assert len(effects) == 1
    assert effects[0].type == EffectType.SIMPLE_API_RESPONSE


def test_the_link_route_resolves_the_tasks_own_database_primary_key_rather_than_its_id(
    db: None,
) -> None:
    """Covers scenario: AC14, the link route resolves the task's own database primary key rather than its id. Covers criterion: AC14. A task's id is a uuid and its dbid is a small integer, so the two are guaranteed to differ in shape as well as in value, which is exactly the Given this criterion asks for."""
    task = IntegrationTaskFactory(service_provider=None)
    assert str(task.dbid) != str(task.id)

    response = call("GET", f"/tasks/{task.id}/link")

    assert status_of(response) == HTTPStatus.OK
    assert json_body(response)["url"] == f"/data-integration/{task.dbid}"
    assert str(task.id) not in json_body(response)["url"]


def test_the_link_route_never_calls_raw_sql() -> None:
    """Covers scenario: AC14, the link route resolves the task's own database primary key rather than its id. Covers criterion: AC14. A static check over the package's own production code, since the criterion's second half asserts that an action is never taken anywhere this codebase runs a request, rather than one call's outcome. IntegrationTask.objects.raw is refused unconditionally inside the plugin runner sandbox, so a route calling it could never have run in the first place, per PLUGINS at b4ab54db, canvas_sdk/__init__.py lines 21 to 25."""
    this_file = pathlib.Path(__file__).resolve()
    package_root = this_file.parents[2] / "fax_queue_inboxes"

    for path in package_root.rglob("*.py"):
        text = path.read_text()
        assert ".raw(" not in text, f"{path} calls raw"


def test_the_plugin_never_junks_a_document_and_never_removes_one_from_a_patient() -> None:
    """Covers scenario: AC15, the plugin never junks a document and never removes one from a patient. Covers criterion: AC15. A static check over every module this project owns, production and test alike, rather than a call driven at a running instance, because the criterion is about an action never being taken anywhere in this codebase rather than about one call's outcome. This file is excluded from its own scan, since naming the two effects in an assertion is not exercising them."""
    this_file = pathlib.Path(__file__).resolve()
    package_root = this_file.parents[2] / "fax_queue_inboxes"
    tests_root = this_file.parents[1]
    forbidden = ("JunkDocument", "RemoveDocumentFromPatient")

    for root in (package_root, tests_root):
        for path in root.rglob("*.py"):
            if path == this_file:
                continue
            text = path.read_text()
            for name in forbidden:
                assert name not in text, f"{path} names {name}"


def test_a_task_leaving_the_queue_stops_appearing_while_its_record_survives_untouched(
    db: None,
) -> None:
    """Covers scenario: AC16, a task leaving the queue stops appearing while its record survives untouched. Covers criterion: AC16. The only task on the instance in this test, so once its status leaves the pending range the all tab's own queryset is empty, which is what proves the task is gone from the response rather than merely absent from a page that happened not to include it."""
    task = IntegrationTaskFactory(service_provider=None)
    staff = StaffFactory(active=True)
    record = FaxRecord.objects.create(
        task_id=task.dbid, note="Reviewed already", note_written_by=staff
    )

    task.status = IntegrationTaskStatus.REVIEWED
    task.save()

    response = call("GET", "/tasks?tab=all")

    assert json_body(response)["tasks"] == []
    record.refresh_from_db()
    assert record.note == "Reviewed already"
    assert record.note_written_by_id == staff.dbid


def test_the_assignees_route_offers_the_teams_and_people_a_fax_can_go_to(db: None) -> None:
    """Covers scenario: AC17, the assignees route offers the teams and people a fax can go to. Covers criterion: AC17. Team.id is a UUID field rather than the CharField Staff.id already is, per PLUGINS at b4ab54db, canvas_sdk/v1/data/base.py's IdentifiableModel, which is why both a team and a person are asserted here rather than only one."""
    team = TeamFactory(name="Nursing")
    member = StaffFactory(active=True, first_name="Marie", last_name="Curie")
    inactive = StaffFactory(active=False, first_name="Retired", last_name="Colleague")

    response = call("GET", "/assignees")

    assert status_of(response) == HTTPStatus.OK
    body = json_body(response)
    assert {"id": str(team.id), "name": "Nursing"} in body["teams"]
    assert {"id": str(member.id), "name": "Marie Curie"} in body["staff"]
    assert not any(entry["id"] == str(inactive.id) for entry in body["staff"])

    team_entry = next(entry for entry in body["teams"] if entry["name"] == "Nursing")
    task = IntegrationTaskFactory(service_provider=None)

    raw_call("POST", f"/tasks/{task.id}/assign", {"team_id": team_entry["id"]})

    record = FaxRecord.objects.get(task_id=task.dbid)
    assert record.assigned_team_id == team.dbid


def test_a_practice_label_can_be_renamed_and_removed_without_a_redeploy(db: None) -> None:
    """Covers scenario: AC18, a practice label can be renamed and removed without a redeploy. Covers criterion: AC18."""
    label = PracticeLabel.objects.create(name="Referral")
    task = IntegrationTaskFactory(service_provider=None)
    FaxLabel.objects.create(task_id=task.dbid, label=label)

    try:
        rename_response = call("PUT", f"/labels/{label.dbid}", {"name": "Referrals"})
        assert status_of(rename_response) == HTTPStatus.OK

        after_rename = json_body(call("GET", "/labels"))
        names_after_rename = [entry["name"] for entry in after_rename["labels"]]
        assert "Referrals" in names_after_rename
        assert "Referral" not in names_after_rename

        delete_response = call("DELETE", f"/labels/{label.dbid}")
        assert status_of(delete_response) == HTTPStatus.NO_CONTENT

        after_delete = json_body(call("GET", "/labels"))
        assert "Referrals" not in [entry["name"] for entry in after_delete["labels"]]

        assert FaxLabel.objects.filter(task_id=task.dbid, label_id=label.dbid).exists()

        tasks_response = call("GET", "/tasks?tab=all")
        assert status_of(tasks_response) == HTTPStatus.OK
        row = next(t for t in json_body(tasks_response)["tasks"] if t["id"] == str(task.id))
        assert row["labels"] == []
    finally:
        # The criterion's own Given leaves a FaxLabel row pointing at a PracticeLabel
        # that no longer exists, and sqlite's own foreign key check at test teardown raises
        # on exactly that state, which this test put there on purpose rather than a second
        # defect. Deleting the row here keeps that teardown check about a real leak in some
        # other test rather than about the state this one means to exercise.
        FaxLabel.objects.filter(task_id=task.dbid, label_id=label.dbid).delete()


def test_a_tasks_row_document_url_agrees_with_the_link_route(db: None) -> None:
    """Covers scenario: AC19, the row carries the document address so the link needs no request of its own. Covers criterion: AC19."""
    task = IntegrationTaskFactory(service_provider=None)

    tasks_response = call("GET", "/tasks?tab=all")
    link_response = call("GET", f"/tasks/{task.id}/link")

    assert status_of(tasks_response) == HTTPStatus.OK
    assert status_of(link_response) == HTTPStatus.OK
    row = next(t for t in json_body(tasks_response)["tasks"] if t["id"] == str(task.id))
    assert row["document_url"] == json_body(link_response)["url"]


def test_the_my_team_tab_includes_a_task_a_committed_review_assigns_to_my_team(
    db: None,
) -> None:
    """Covers scenario: AC4, the my team tab includes a task only when the staff member belongs to its assigned team. Covers criterion: AC4, reached through the committed review rather than through the plugin's own record, which is the half criterion 7 says outranks it and which nothing exercised until the tab began narrowing on keys."""
    team = TeamFactory()
    member = StaffFactory(active=True)
    team.members.add(member)
    task = IntegrationTaskFactory(service_provider=None)
    IntegrationTaskReviewFactory(task=task, reviewer=None, team_reviewer=team, junked=False)

    response = call("GET", "/tasks?tab=my-team", caller=member)

    assert [t["id"] for t in json_body(response)["tasks"]] == [str(task.id)]


def test_a_committed_review_naming_another_team_keeps_a_task_out_of_my_team_tab(
    db: None,
) -> None:
    """Covers scenario: AC7, a committed native review outranks the plugin's own assignment. Covers criterion: AC7. The record names my team and the review names another, so a fax appearing here would prove the record had won."""
    mine = TeamFactory()
    theirs = TeamFactory()
    member = StaffFactory(active=True)
    mine.members.add(member)
    task = IntegrationTaskFactory(service_provider=None)
    IntegrationTaskReviewFactory(task=task, reviewer=None, team_reviewer=theirs, junked=False)
    FaxRecord.objects.create(task_id=task.dbid, assigned_team=mine)

    response = call("GET", "/tasks?tab=my-team", caller=member)

    assert json_body(response)["tasks"] == []


def test_a_review_naming_only_a_staff_member_keeps_a_task_out_of_every_team_tab(
    db: None,
) -> None:
    """Covers scenario: AC7, a committed native review outranks the plugin's own assignment. Covers criterion: AC7. A review naming a person and no team carries no team at all, so it belongs to nobody's team tab while still counting as assigned, which is what keeps it off the unassigned tab too."""
    team = TeamFactory()
    member = StaffFactory(active=True)
    team.members.add(member)
    task = IntegrationTaskFactory(service_provider=None)
    IntegrationTaskReviewFactory(
        task=task, reviewer=StaffFactory(active=True), team_reviewer=None, junked=False
    )

    assert json_body(call("GET", "/tasks?tab=my-team", caller=member))["tasks"] == []
    assert json_body(call("GET", "/tasks?tab=unassigned"))["tasks"] == []


def test_a_record_naming_only_a_staff_member_keeps_a_task_out_of_every_team_tab(
    db: None,
) -> None:
    """Covers scenario: AC3, the unassigned tab shows only the task with no assignment of any kind. Covers criterion: AC3. The mirror of the review case, a record naming a person and no team is assigned, so it leaves the unassigned tab without joining any team tab."""
    team = TeamFactory()
    member = StaffFactory(active=True)
    team.members.add(member)
    task = IntegrationTaskFactory(service_provider=None)
    FaxRecord.objects.create(task_id=task.dbid, assigned_staff=StaffFactory(active=True))

    assert json_body(call("GET", "/tasks?tab=my-team", caller=member))["tasks"] == []
    assert json_body(call("GET", "/tasks?tab=unassigned"))["tasks"] == []


def test_an_unknown_tab_is_read_as_the_all_tab(db: None) -> None:
    """Covers scenario: AC5, the all tab shows every task with no narrowing by assignment and its count can exceed the page cap. Covers criterion: AC5. Behaviour step 5 names three tabs and no fourth, and a request naming something else is answered as all rather than refused, so the surface cannot be sent a tab that returns nothing."""
    task = IntegrationTaskFactory(service_provider=None)
    staff = StaffFactory(active=True)
    FaxRecord.objects.create(task_id=task.dbid, assigned_staff=staff)

    response = call("GET", "/tasks?tab=nonsense")

    body = json_body(response)
    assert body["tab"] == "all"
    assert [t["id"] for t in body["tasks"]] == [str(task.id)]


def test_a_narrowed_tab_counts_every_match_and_still_returns_one_page(db: None) -> None:
    """Covers scenario: AC5, the all tab shows every task with no narrowing by assignment and its count can exceed the page cap. Covers criterion: AC5, asserted here for a narrowed tab, which reaches its page by a different path. The unassigned tab decides on keys and hydrates only the page it returns, so this is what proves the count stayed exact rather than becoming the size of a window."""
    for _ in range(55):
        IntegrationTaskFactory(service_provider=None, patient=None)

    body = json_body(call("GET", "/tasks?tab=unassigned"))

    assert body["count"] == 55
    assert body["cap"] == 50
    assert len(body["tasks"]) == 50


# --- Why the deleted label branch has no test here
#
# handlers/api.py drops a FaxLabel whose PracticeLabel is gone rather than
# raising, which is the forgiveness criterion 18 asks for. That state cannot be
# built in this suite. The tests run on sqlite with foreign keys enforced, so
# deleting a PracticeLabel that a FaxLabel still points at fails the constraint
# check at the end of the transaction, while the platform's own DDL declares
# the relation DO_NOTHING and leaves the orphan in place, which is the state
# the branch exists for. Writing the row through raw SQL to dodge the
# constraint would test sqlite rather than the plugin, so the branch is left
# uncovered and named here instead.


# --- Why the three routes that render a template have no test here
#
# get_app, plugin_ui_css and plugin_ui_js all answer through
# render_to_string, and outside the plugin runner that loader resolves
# nothing, so all three answer 500 with an empty body in this suite rather
# than the markup they serve in production. Driven and measured before this
# was written, not assumed. The page is covered instead by the browser gate,
# where 03-acceptance/browser/01-ac1 navigates to the real route on a real
# instance and asserts what comes back, which is the stronger claim anyway.
#
def test_a_fax_carrying_only_a_note_is_still_unassigned(db: None) -> None:
    """Covers scenario: AC3, the unassigned tab shows only the task with no assignment of any kind. Covers criterion: AC3. A FaxRecord exists the moment somebody writes a note, so a record on its own is not an assignment, and a fax that has only been annotated has to stay in the unassigned tab with no assignee on its row."""
    task = IntegrationTaskFactory(service_provider=None)
    FaxRecord.objects.create(task_id=task.dbid, note="Called the sender to confirm")

    body = json_body(call("GET", "/tasks?tab=unassigned"))

    assert [t["id"] for t in body["tasks"]] == [str(task.id)]
    assert body["tasks"][0]["assignee"] is None
    assert body["tasks"][0]["note"] == "Called the sender to confirm"


# --- Criteria 20 to 23, the guarantees the specification gained at version 8.
# They describe behaviour the plugin already had. The coverage gate is what found
# that none of it was written down, so none of it could be traced or tested.

MISSING_TASK = "00000000-0000-4000-8000-000000000000"
MISSING_LABEL = 987654321


def test_every_task_route_answers_not_found_for_a_task_that_is_not_there(db: None) -> None:
    """Covers criterion: AC20. Six routes resolve a task id and every one of them has to refuse the same way, so this drives all six rather than a representative one, which is the only way a route added later without the guard is caught."""
    label = PracticeLabel.objects.create(name="Referral")
    # The assign route validates its body before it resolves the task, measured
    # rather than assumed, so it is handed a real team id. Sent an empty body it
    # answers 400 for the missing field and never reaches the lookup this asserts.
    team = TeamFactory()
    calls = [
        ("GET", f"/tasks/{MISSING_TASK}/link", None),
        ("POST", f"/tasks/{MISSING_TASK}/label", {"label_id": label.dbid}),
        ("DELETE", f"/tasks/{MISSING_TASK}/label/{label.dbid}", None),
        ("POST", f"/tasks/{MISSING_TASK}/note", {"note": "anything"}),
        ("POST", f"/tasks/{MISSING_TASK}/assign", {"team_id": str(team.id)}),
        ("DELETE", f"/tasks/{MISSING_TASK}/assign", None),
    ]
    for method, path, body in calls:
        response = call(method, path, body)
        assert status_of(response) == HTTPStatus.NOT_FOUND, f"{method} {path}"
        assert json_body(response)["error"] == "Task not found", f"{method} {path}"

    assert FaxRecord.objects.count() == 0, "a refused route still wrote a record"
    assert FaxLabel.objects.count() == 0, "a refused route still wrote a label row"


def test_a_label_route_answers_not_found_for_a_label_that_is_not_there(db: None) -> None:
    """Covers criterion: AC21. Two routes resolve a label id to a PracticeLabel and both refuse the same way. The delete route is deliberately not one of them, it removes unconditionally, which is why this does not assert against it."""
    task = IntegrationTaskFactory(service_provider=None)

    renamed = call("PUT", f"/labels/{MISSING_LABEL}", {"name": "Anything"})
    assert status_of(renamed) == HTTPStatus.NOT_FOUND
    assert json_body(renamed)["error"] == "Label not found"

    added = call("POST", f"/tasks/{task.id}/label", {"label_id": MISSING_LABEL})
    assert status_of(added) == HTTPStatus.NOT_FOUND
    assert json_body(added)["error"] == "Label not found"

    assert FaxLabel.objects.count() == 0, "a refused add still wrote a label row"


def test_an_id_that_cannot_be_parsed_is_refused_before_any_query_is_built(db: None) -> None:
    """Covers criterion: AC22. A task id must be a UUID and a label id must be a number, since that is what the columns behind them are, so an id that could never name a row is a malformed request rather than a miss. All eight routes that read an id are driven, because the guard is opt in per route and a route added later without it is exactly what this is here to catch."""
    calls = [
        ("GET", "/tasks/not-a-uuid/link", None),
        ("POST", "/tasks/not-a-uuid/label", {"label_id": 1}),
        ("DELETE", "/tasks/not-a-uuid/label/1", None),
        ("POST", "/tasks/not-a-uuid/note", {"note": "anything"}),
        ("POST", "/tasks/not-a-uuid/assign", {"team_id": "x"}),
        ("DELETE", "/tasks/not-a-uuid/assign", None),
    ]
    for method, path, body in calls:
        response = call(method, path, body)
        assert status_of(response) == HTTPStatus.BAD_REQUEST, f"{method} {path}"
        assert json_body(response)["error"] == "A task id must be a UUID", f"{method} {path}"

    for method, path, body in [
        ("PUT", "/labels/not-an-integer", {"name": "Anything"}),
        ("DELETE", "/labels/not-an-integer", None),
    ]:
        response = call(method, path, body)
        assert status_of(response) == HTTPStatus.BAD_REQUEST, f"{method} {path}"
        assert json_body(response)["error"] == "A label id must be a number", f"{method} {path}"

    assert FaxRecord.objects.count() == 0, "a refused route still wrote a record"
    assert FaxLabel.objects.count() == 0, "a refused route still wrote a label row"


def test_removing_a_label_the_fax_does_not_carry_is_not_an_error(db: None) -> None:
    """Covers criterion: AC23. The caller wanted the label gone and it already is, so the route answers the fax's labels rather than refusing, which is what makes the remove safe to replay and safe to double click."""
    task = IntegrationTaskFactory(service_provider=None)
    carried = PracticeLabel.objects.create(name="Referral")
    never_added = PracticeLabel.objects.create(name="Lab Result")
    FaxLabel.objects.create(task_id=task.dbid, label_id=carried.dbid)

    response = call("DELETE", f"/tasks/{task.id}/label/{never_added.dbid}")

    assert status_of(response) == HTTPStatus.OK
    assert [label["name"] for label in json_body(response)["labels"]] == ["Referral"]
    assert FaxLabel.objects.count() == 1, "the removal took the wrong row"


def test_assigning_a_task_to_a_person_sets_the_record_and_clears_any_team(db: None) -> None:
    """Covers scenario: AC12, assigning a task to a team sets the record and returns the prefill effect. Covers criterion: AC12, its other half. Behaviour step 16 says the route takes a team id or a staff id, and the criterion fixes only the team half, so the branch that assigns a person was never driven through the route at all."""
    task = IntegrationTaskFactory(service_provider=None)
    team = TeamFactory()
    person = StaffFactory(active=True, first_name="Ada", last_name="Byron")
    FaxRecord.objects.create(task_id=task.dbid, assigned_team=team)

    response = call("POST", f"/tasks/{task.id}/assign", {"staff_id": str(person.id)}, caller=person)

    assert status_of(response) == HTTPStatus.OK
    record = FaxRecord.objects.get(task_id=task.dbid)
    assert record.assigned_staff_id == person.dbid
    assert record.assigned_team_id is None, "assigning a person left the old team on the record"
