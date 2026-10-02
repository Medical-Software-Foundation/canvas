"""FaxRecord and FaxLabel, read back after the route call that is each criterion's own
When clause.

Both criteria homed here name a model read as their observable form in section 5 of
SPEC.md, so the request is driven the same way tests/handlers/test_api.py drives every
other route, through FaxQueueAPI.compute(), and the assertion reads the row afterward.
"""

import base64
import json
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from canvas_sdk.test_utils.factories import IntegrationTaskFactory, StaffFactory

from fax_queue_inboxes.handlers.api import FaxQueueAPI
from fax_queue_inboxes.models import FaxLabel, FaxRecord, PracticeLabel

if TYPE_CHECKING:
    # canvas_sdk ships no py.typed marker, so these two names resolve to Any under
    # mypy rather than to real types, the same fact mypy.ini documents for the
    # model files. They are still imported honestly, under the standard guard, so
    # the annotations below name the real runtime types rather than a guess.
    from canvas_sdk.events import Event
    from canvas_sdk.v1.data import Staff

PREFIX = "/fax-queue-inboxes"

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


def call(
    method: str, path: str, body: dict | None = None, caller: "Staff | None" = None
) -> dict:
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
    effects = FaxQueueAPI(event).compute()
    assert effects, f"{method} {path} produced no response"
    return cast(dict, json.loads(effects[0].payload))


def json_body(response: dict) -> dict:
    """The JSON a response carries."""
    return cast(dict, json.loads(base64.b64decode(response["body"])))


def status_of(response: dict) -> int:
    """The status code a response carries."""
    return int(response["status_code"])


def test_a_fax_carries_several_labels_and_each_records_who_set_it_and_when(db: None) -> None:
    """Covers scenario: AC10, a fax carries several labels and each records who set it and when. Covers criterion: AC10."""
    task = IntegrationTaskFactory(service_provider=None)
    referral = PracticeLabel.objects.create(name="Referral")
    insurance = PracticeLabel.objects.create(name="Insurance")
    staff = StaffFactory(active=True)

    first_response = call(
        "POST", f"/tasks/{task.id}/label", {"label_id": referral.dbid}, caller=staff
    )
    second_response = call(
        "POST", f"/tasks/{task.id}/label", {"label_id": insurance.dbid}, caller=staff
    )

    assert status_of(first_response) == HTTPStatus.OK
    assert status_of(second_response) == HTTPStatus.OK
    rows = list(FaxLabel.objects.filter(task_id=task.dbid).order_by("label__name"))
    assert [row.label_id for row in rows] == [insurance.dbid, referral.dbid]
    for row in rows:
        assert row.set_by_id == staff.dbid
        assert row.set_at is not None

    repeated_response = call(
        "POST", f"/tasks/{task.id}/label", {"label_id": referral.dbid}, caller=staff
    )

    assert status_of(repeated_response) == HTTPStatus.OK
    assert FaxLabel.objects.filter(task_id=task.dbid, label_id=referral.dbid).count() == 1
    assert sorted(entry["name"] for entry in json_body(repeated_response)["labels"]) == [
        "Insurance",
        "Referral",
    ]

    removed_response = call(
        "DELETE", f"/tasks/{task.id}/label/{referral.dbid}", caller=staff
    )

    assert status_of(removed_response) == HTTPStatus.OK
    assert not FaxLabel.objects.filter(task_id=task.dbid, label_id=referral.dbid).exists()
    assert FaxLabel.objects.filter(task_id=task.dbid, label_id=insurance.dbid).exists()
    assert [entry["name"] for entry in json_body(removed_response)["labels"]] == ["Insurance"]


def test_a_new_note_overwrites_rather_than_appends_to_the_existing_one(db: None) -> None:
    """Covers scenario: AC11, a new note overwrites rather than appends to the existing one. Covers criterion: AC11."""
    task = IntegrationTaskFactory(service_provider=None)
    first_author = StaffFactory(active=True)
    second_author = StaffFactory(active=True)
    FaxRecord.objects.create(
        task_id=task.dbid, note="The first note", note_written_by=first_author
    )

    response = call(
        "POST", f"/tasks/{task.id}/note", {"note": "The corrected note"}, caller=second_author
    )

    assert status_of(response) == HTTPStatus.OK
    record = FaxRecord.objects.get(task_id=task.dbid)
    assert record.note == "The corrected note"
    assert record.note_written_by_id == second_author.dbid
