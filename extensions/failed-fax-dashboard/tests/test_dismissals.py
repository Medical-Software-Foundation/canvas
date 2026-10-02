import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.test_utils.factories import FaxFactory, TaskFactory

from failed_fax_dashboard.models import FaxAlert, FaxDismissal
from failed_fax_dashboard.services.actions import ActionError, dismiss_rows, restore_rows
from failed_fax_dashboard.services.dashboard import dashboard_page
from tests.helpers import make_alert, make_event, make_staff

pytestmark = pytest.mark.django_db


def decoded(effects: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(EffectType.Name(effect.type), json.loads(effect.payload)["data"]) for effect in effects]


def failed_with_task(status: str = "OPEN", **kwargs: Any) -> tuple[Any, Any]:
    event = make_event("note", **kwargs)
    task = TaskFactory.create(status=status, patient=event.note.patient)
    make_alert(event, "note", task)
    return event, task


def key(event: Any) -> str:
    return f"note:{event.id}"


def test_dismiss_closes_the_open_task_with_a_comment_naming_who_dismissed_it() -> None:
    dana = make_staff("Dana", "Whitfield")
    event, task = failed_with_task()

    effects = decoded(dismiss_rows({"keys": [key(event)]}, staff_id=dana.id))

    assert effects == [
        ("UPDATE_TASK", {"id": str(task.id), "status": "CLOSED"}),
        (
            "CREATE_TASK_COMMENT",
            {
                "task": {"id": str(task.id)},
                "body": "Dismissed from the Failed Faxes dashboard by Dana Whitfield.",
                "author_id": dana.id,
            },
        ),
    ]
    dismissal = FaxDismissal.objects.get()
    assert (dismissal.source_id, dismissal.dismissed_by, dismissal.closed_task_id) == (str(event.id), dana.id, str(task.id))
    assert dismissal.dismissed_at > datetime.now(timezone.utc) - timedelta(minutes=1)
    assert FaxAlert.objects.get().closed is True


def test_bulk_dismiss_handles_every_row_and_skips_tasks_already_closed() -> None:
    dana = make_staff()
    first, first_task = failed_with_task()
    second, _ = failed_with_task(status="CLOSED")
    third = make_event("note")  # no task yet

    effects = decoded(dismiss_rows({"keys": [key(first), key(second), key(third)]}, staff_id=dana.id))

    assert [kind for kind, _ in effects] == ["UPDATE_TASK", "CREATE_TASK_COMMENT"]
    assert effects[0][1]["id"] == str(first_task.id)
    assert FaxDismissal.objects.count() == 3
    assert FaxDismissal.objects.get(source_id=str(second.id)).closed_task_id == ""


def test_dismissing_twice_closes_nothing_the_second_time() -> None:
    dana = make_staff()
    event, _ = failed_with_task()
    dismiss_rows({"keys": [key(event)]}, staff_id=dana.id)

    assert dismiss_rows({"keys": [key(event)]}, staff_id=make_staff("Other", "Person").id) == []
    assert FaxDismissal.objects.get().dismissed_by == dana.id


def test_a_received_fax_can_be_dismissed() -> None:
    fax = FaxFactory.create(direction="I", success=False)

    dismiss_rows({"keys": [f"received_fax:{fax.id}"]}, staff_id=make_staff().id)

    assert FaxDismissal.objects.get().source_id == str(fax.id)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "Choose at least one row"),
        ({"keys": []}, "Choose at least one row"),
        ({"keys": "note:1"}, "Choose at least one row"),
        ({"keys": ["bogus:1"]}, "Unknown item type"),
        ({"keys": ["note:nope"]}, "Invalid id"),
        ({"keys": ["note:5c6e0f4a-5d3e-4f4e-8f27-0f5f4b1b2c3d"]}, "Fax record not found"),
        ({"keys": ["received_fax:5c6e0f4a-5d3e-4f4e-8f27-0f5f4b1b2c3d"]}, "Fax record not found"),
        ({"keys": ["note:x"] * 201}, "Choose at most 200 rows at a time"),
    ],
)
def test_bad_input_is_rejected(payload: dict[str, Any], message: str) -> None:
    with pytest.raises(ActionError) as caught:
        dismiss_rows(payload, staff_id=make_staff().id)

    assert caught.value.message == message


def test_one_bad_key_dismisses_nothing() -> None:
    event, _ = failed_with_task()

    with pytest.raises(ActionError):
        dismiss_rows({"keys": [key(event), "note:5c6e0f4a-5d3e-4f4e-8f27-0f5f4b1b2c3d"]}, staff_id=make_staff().id)

    assert FaxDismissal.objects.count() == 0


def test_someone_who_is_not_staff_cannot_dismiss() -> None:
    event, _ = failed_with_task()

    with pytest.raises(ActionError) as caught:
        dismiss_rows({"keys": [key(event)]}, staff_id="nobody")

    assert caught.value.message == "Staff member not found"


def test_restore_reopens_the_task_the_dismissal_closed() -> None:
    dana = make_staff("Dana", "Whitfield")
    event, task = failed_with_task()
    dismiss_rows({"keys": [key(event)]}, staff_id=dana.id)

    effects = decoded(restore_rows({"keys": [key(event)]}, staff_id=dana.id))

    assert effects == [
        ("UPDATE_TASK", {"id": str(task.id), "status": "OPEN"}),
        ("CREATE_TASK_COMMENT", {"task": {"id": str(task.id)}, "body": "Task reopened by Dana Whitfield.", "author_id": dana.id}),
    ]
    assert FaxDismissal.objects.count() == 0
    assert FaxAlert.objects.get().closed is False


def test_restore_leaves_a_task_that_was_closed_before_the_dismissal() -> None:
    event, _ = failed_with_task(status="CLOSED")
    dismiss_rows({"keys": [key(event)]}, staff_id=make_staff().id)

    assert restore_rows({"keys": [key(event)]}, staff_id=make_staff("A", "B").id) == []
    assert FaxDismissal.objects.count() == 0


def test_restore_of_an_older_dismissal_brings_the_row_back_without_reopening_anything() -> None:
    # Dismissals saved before closed_task_id existed read it as None.
    event, _ = failed_with_task()
    FaxDismissal.objects.create(
        source_type="note", source_id=str(event.id), dismissed_by="x", dismissed_at=datetime.now(timezone.utc)
    )
    FaxDismissal.objects.update(closed_task_id=None)

    assert restore_rows({"keys": [key(event)]}, staff_id=make_staff().id) == []
    assert FaxDismissal.objects.count() == 0


def test_restore_of_a_row_that_is_not_dismissed_does_nothing() -> None:
    event, _ = failed_with_task()

    assert restore_rows({"keys": [key(event)]}, staff_id=make_staff().id) == []


def test_show_dismissed_lists_recent_dismissals_with_who_and_when() -> None:
    dana = make_staff("Dana", "Whitfield")
    live, _ = failed_with_task()
    recent, _ = failed_with_task()
    old, _ = failed_with_task()
    dismiss_rows({"keys": [key(recent), key(old)]}, staff_id=dana.id)
    FaxDismissal.objects.filter(source_id=str(old.id)).update(dismissed_at=datetime.now(timezone.utc) - timedelta(days=31))

    shown = dashboard_page("sent", {"dismissed": "1"}, dana.id)
    normal = dashboard_page("sent", {}, dana.id)

    assert [row["source_id"] for row in shown["rows"]] == [str(recent.id)]
    assert shown["rows"][0]["dismissed"]["by"] == "Dana Whitfield"
    assert shown["view"]["dismissed"] is True
    assert shown["totals"]["sent"] == 1
    assert [row["source_id"] for row in normal["rows"]] == [str(live.id)]
    assert "dismissed" not in normal["rows"][0]
    assert normal["view"]["dismissed"] is False
