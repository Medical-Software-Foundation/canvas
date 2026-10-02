import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.test_utils.factories import FaxFactory, StaffFactory, TaskFactory, TeamFactory
from canvas_sdk.v1.data import Task

from failed_fax_dashboard.models import FaxAlert, FaxDismissal, FaxResend
from failed_fax_dashboard.services.actions import (
    ActionError,
    build_comment,
    build_reassign,
    build_resend,
    build_resend_takeover,
)
from failed_fax_dashboard.services.handoff import to_team
from tests.helpers import make_alert, make_event, make_staff

pytestmark = pytest.mark.django_db


def data(effect: Any) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(effect.payload)["data"]
    return payload


def resend_body(event: Any, **overrides: Any) -> dict[str, Any]:
    body = {"event_id": str(event.id), "recipient_name": "Dr. Ada", "recipient_fax_number": "(555) 555-0123"}
    body.update(overrides)
    return body


def test_resend_remembers_who_clicked_and_returns_the_note_fax_effect() -> None:
    clicker = make_staff("Marcus", "Bell")
    event = make_event("note")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    effect = build_resend(resend_body(event), staff_id=clicker.id, now=now)

    assert effect.type == EffectType.FAX_NOTE
    sent = data(effect)
    assert (sent["note_id"], sent["recipient_name"], sent["recipient_fax_number"]) == (
        str(event.note.id),
        "Dr. Ada",
        "(555) 555-0123",
    )
    saved = FaxResend.objects.get()
    assert (saved.note_id, saved.staff_id, saved.fax_number, saved.resent_at) == (
        event.note.dbid,
        clicker.dbid,
        "+15555550123",
        now,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"recipient_name": "  "}, "Recipient name is required"),
        ({"recipient_fax_number": "n/a"}, "A valid fax number is required"),
        ({"event_id": "nope"}, "Invalid id"),
    ],
)
def test_resend_rejects_bad_input_without_saving(overrides: dict[str, Any], message: str) -> None:
    clicker = make_staff()
    event = make_event("note")

    with pytest.raises(ActionError) as caught:
        build_resend(resend_body(event, **overrides), staff_id=clicker.id)

    assert caught.value.message == message
    assert FaxResend.objects.count() == 0


def test_resend_rejects_a_missing_fax_a_delivered_fax_and_a_stranger() -> None:
    clicker = make_staff()
    delivered = make_event("note", delivered=True)
    referral = make_event("referral")

    with pytest.raises(ActionError, match="Only a fax that was not delivered"):
        build_resend(resend_body(delivered), staff_id=clicker.id)
    with pytest.raises(ActionError, match="Fax record not found"):
        build_resend(resend_body(referral), staff_id=clicker.id)
    with pytest.raises(ActionError, match="Staff member not found"):
        build_resend(resend_body(make_event("note")), staff_id="nobody")
    assert FaxResend.objects.count() == 0


def test_resend_is_refused_once_the_fax_was_sent_again() -> None:
    clicker = make_staff()
    failed = make_event("note", age_days=2)
    make_event("note", note=failed.note, delivered=None, age_days=1)

    with pytest.raises(ActionError) as caught:
        build_resend(resend_body(failed), staff_id=clicker.id)

    assert caught.value.message == "This fax was already sent again"
    assert FaxResend.objects.count() == 0


def test_a_send_to_another_number_does_not_block_resend() -> None:
    clicker = make_staff()
    failed = make_event("note", age_days=2)
    make_event("note", note=failed.note, number="+15555550199", age_days=1)

    assert build_resend(resend_body(failed), staff_id=clicker.id).type == EffectType.FAX_NOTE


def alerted_task(**task_fields: Any) -> Any:
    event = make_event("note")
    task = TaskFactory.create(**task_fields)
    make_alert(event, "note", task)
    return task


def test_reassign_to_a_person_updates_the_task_and_comments_as_the_clicker() -> None:
    clicker = make_staff("Dana", "Whitfield")
    target = make_staff("Cy", "Clark")
    task = alerted_task()

    effects = build_reassign({"task_id": str(task.id), "assignee": f"staff:{target.id}"}, staff_id=clicker.id)

    assert [effect.type for effect in effects] == [EffectType.UPDATE_TASK, EffectType.CREATE_TASK_COMMENT]
    # Only the side being set: the SDK sends a cleared side as {"id": None}, which Canvas rejects.
    assert data(effects[0]) == {"id": str(task.id), "assignee": {"id": target.id}}
    assert data(effects[1]) == {
        "task": {"id": str(task.id)},
        "body": "Reassigned to Cy Clark by Dana Whitfield.",
        "author_id": clicker.id,
    }
    assert FaxAlert.objects.get().assignee == f"staff:{target.id}"


def test_reassign_to_a_team_sets_only_the_team_when_no_person_holds_the_task() -> None:
    clicker = make_staff()
    team = TeamFactory.create(name="Front Desk")
    task = alerted_task(assignee=None, team=TeamFactory.create(name="Medical Records"))

    effects = build_reassign({"task_id": str(task.id), "assignee": f"team:{team.id}"}, staff_id=clicker.id)

    assert [effect.type for effect in effects] == [EffectType.UPDATE_TASK, EffectType.CREATE_TASK_COMMENT]
    assert data(effects[0]) == {"id": str(task.id), "team": {"id": str(team.id)}}
    assert data(effects[1])["body"].startswith("Reassigned to Front Desk by ")
    assert FaxAlert.objects.get().assignee == f"team:{team.id}"


def test_reassign_from_a_person_to_a_team_closes_their_task_and_opens_one_for_the_team() -> None:
    clicker = make_staff("Dana", "Whitfield")
    holder = make_staff("Thomas", "Pickles")
    team = TeamFactory.create(name="Front Desk")
    task = alerted_task(assignee=holder, team=None, title="Fax didn't go through: Note to +15555550100")

    effects = build_reassign({"task_id": str(task.id), "assignee": f"team:{team.id}"}, staff_id=clicker.id)

    assert [effect.type for effect in effects] == [
        EffectType.UPDATE_TASK,
        EffectType.CREATE_TASK_COMMENT,
        EffectType.CREATE_TASK,
        EffectType.CREATE_TASK_COMMENT,
    ]
    close, old_note, new_task, new_note = (data(effect) for effect in effects)
    assert close == {"id": str(task.id), "status": "CLOSED"}
    assert old_note["body"] == "Handed to Front Desk by Dana Whitfield. Continued in a new task assigned to Front Desk."
    assert new_task["title"] == "Fax didn't go through: Note to +15555550100"
    assert new_task["team"] == {"id": str(team.id)}
    assert new_task.get("assignee") in (None, {"id": None})  # creating a task reads an empty id as no one
    assert new_note["task"] == {"id": new_task["id"]}
    assert new_note["body"].startswith("Continued from a task that was assigned to Thomas Pickles.")
    alert = FaxAlert.objects.get()
    assert alert.task_id == new_task["id"]
    assert alert.previous_task_ids == str(task.id)
    assert alert.assignee == f"team:{team.id}"


def test_team_hand_off_works_on_an_alert_saved_before_earlier_tasks_were_recorded() -> None:
    # Alerts saved before the field existed read it as None, not "".
    holder = make_staff("Thomas", "Pickles")
    team = TeamFactory.create(name="Front Desk")
    task = alerted_task(assignee=holder, team=None)
    alert = FaxAlert.objects.get()
    alert.previous_task_ids = None

    handoff = to_team(alert, Task.objects.get(id=task.id), team, by="Dana Whitfield", author_id=holder.id)

    assert len(handoff.effects) == 4
    assert FaxAlert.objects.get().previous_task_ids == str(task.id)


@pytest.mark.parametrize(
    ("assignee", "message"),
    [
        ("", "Choose a person or a team"),
        ("person:1", "Choose a person or a team"),
        ("staff:nobody", "Assignee not found"),
        ("team:5c6e0f4a-5d3e-4f4e-8f27-0f5f4b1b2c3d", "Assignee not found"),
        ("team:nope", "Invalid team id"),
    ],
)
def test_reassign_rejects_bad_assignees(assignee: str, message: str) -> None:
    clicker = make_staff()
    task = alerted_task()

    with pytest.raises(ActionError) as caught:
        build_reassign({"task_id": str(task.id), "assignee": assignee}, staff_id=clicker.id)

    assert caught.value.message == message


def test_reassign_ignores_inactive_staff() -> None:
    clicker = make_staff()
    gone = make_staff("Gone", "Away", active=False)
    task = alerted_task()

    with pytest.raises(ActionError, match="Assignee not found"):
        build_reassign({"task_id": str(task.id), "assignee": f"staff:{gone.id}"}, staff_id=clicker.id)


def test_only_tasks_the_plugin_made_can_be_changed() -> None:
    clicker = make_staff()
    stranger = TaskFactory.create()
    target = StaffFactory.create()

    with pytest.raises(ActionError, match="Task not found"):
        build_reassign({"task_id": str(stranger.id), "assignee": f"staff:{target.id}"}, staff_id=clicker.id)
    with pytest.raises(ActionError, match="Task not found"):
        build_comment({"task_id": str(stranger.id), "body": "hi"}, staff_id=clicker.id)
    with pytest.raises(ActionError, match="Invalid task id"):
        build_comment({"task_id": "nope", "body": "hi"}, staff_id=clicker.id)


def test_actions_need_a_real_staff_member() -> None:
    task = alerted_task()

    with pytest.raises(ActionError, match="Staff member not found"):
        build_comment({"task_id": str(task.id), "body": "hi"}, staff_id="nobody")
    with pytest.raises(ActionError, match="Staff member not found"):
        build_reassign({"task_id": str(task.id), "assignee": "staff:x"}, staff_id="nobody")


def test_comment_is_written_under_the_logged_in_staff_member() -> None:
    clicker = make_staff()
    task = alerted_task()

    effect = build_comment({"task_id": str(task.id), "body": "  Called them  "}, staff_id=clicker.id)

    assert effect.type == EffectType.CREATE_TASK_COMMENT
    assert data(effect) == {"task": {"id": str(task.id)}, "body": "Called them", "author_id": clicker.id}


def test_comment_must_have_text_of_reasonable_length() -> None:
    clicker = make_staff()
    task = alerted_task()

    with pytest.raises(ActionError, match="Write a comment first"):
        build_comment({"task_id": str(task.id), "body": "   "}, staff_id=clicker.id)
    with pytest.raises(ActionError, match="too long"):
        build_comment({"task_id": str(task.id), "body": "x" * 5001}, staff_id=clicker.id)


def test_unknown_item_type_cannot_be_loaded() -> None:
    from failed_fax_dashboard.services.actions import load_sent_event

    with pytest.raises(ActionError, match="Unknown item type"):
        load_sent_event("bogus", "x")


def test_resending_moves_an_open_task_to_whoever_resent() -> None:
    from canvas_sdk.test_utils.factories import TaskFactory

    from tests.helpers import make_alert

    sender = make_staff("Thomas", "Pickles")
    clicker = make_staff("Dana", "Whitfield")
    event = make_event("note", originator=sender.user)
    task = TaskFactory.create(assignee=sender)
    alert = make_alert(event, "note", task, assignee=f"staff:{sender.id}")

    effects = build_resend_takeover(resend_body(event), staff_id=clicker.id)

    assert [EffectType.Name(effect.type) for effect in effects] == ["UPDATE_TASK", "CREATE_TASK_COMMENT"]
    assert data(effects[0])["assignee"]["id"] == clicker.id
    assert data(effects[1])["body"] == "Dana Whitfield resent the fax and took over this task."
    alert.refresh_from_db()
    assert alert.assignee == f"staff:{clicker.id}"
    assert build_resend_takeover(resend_body(event), staff_id=clicker.id) == []


def test_resending_leaves_closed_tasks_and_untasked_rows_alone() -> None:
    from canvas_sdk.test_utils.factories import TaskFactory

    from tests.helpers import make_alert

    clicker = make_staff("Dana", "Whitfield")
    untasked = make_event("note", number="+15555550101")
    closed = make_event("note", number="+15555550102")
    make_alert(closed, "note", TaskFactory.create(), closed=True, assignee="staff:someone")

    assert build_resend_takeover(resend_body(untasked), staff_id=clicker.id) == []
    assert build_resend_takeover(resend_body(closed), staff_id=clicker.id) == []
