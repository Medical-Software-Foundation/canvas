import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.test_utils.factories import (
    FaxFactory,
    ImagingOrderFactory,
    IntegrationTaskFactory,
    ReferralFactory,
    TaskFactory,
    TeamFactory,
)
from canvas_sdk.v1.data import FaxDirection, IntegrationTask

from failed_fax_dashboard.handlers.fax_alert_cron import FaxAlertCron
from failed_fax_dashboard.models import AlertStart, FaxAlert, FaxDismissal, FaxResend
from failed_fax_dashboard.services.alerts import alert_effects
from tests.helpers import make_bot, make_event, make_staff

pytestmark = pytest.mark.django_db

ENVIRONMENT = {"CUSTOMER_IDENTIFIER": "acme", "INSTALLATION_TIME_ZONE": "America/New_York"}
NOW = datetime.now(timezone.utc)


def decode(effects: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(EffectType.Name(effect.type), json.loads(effect.payload)["data"]) for effect in effects]


def run(secrets: dict[str, str] | None = None, now: datetime | None = None) -> list[tuple[str, dict[str, Any]]]:
    return decode(alert_effects(secrets or {}, ENVIRONMENT, now or NOW))


def started(hours_ago: float = 1) -> None:
    AlertStart.objects.all().delete()
    AlertStart.objects.create(started_at=NOW - timedelta(hours=hours_ago))


def touch(event: Any, hours_ago: float) -> None:
    type(event).objects.filter(pk=event.pk).update(modified=NOW - timedelta(hours=hours_ago))


def test_first_run_records_the_start_and_makes_no_task_for_older_failures() -> None:
    event = make_event("note", originator=make_staff().user)
    touch(event, 3)

    assert run() == []

    assert AlertStart.objects.count() == 1
    assert FaxAlert.objects.count() == 0
    assert run() == []
    assert AlertStart.objects.count() == 1


def test_a_failure_after_the_start_makes_a_task_for_the_sender_with_a_linked_comment() -> None:
    sender = make_staff("Dana", "Whitfield")
    event = make_event("note", originator=sender.user, reason="No answer.", fax=FaxFactory.create(fax_pages=3, to_fax_number="+15555550100"))
    started()

    effects = run()

    kinds = [kind for kind, _ in effects]
    assert kinds == ["CREATE_TASK", "CREATE_TASK_COMMENT"]
    task, comment = effects[0][1], effects[1][1]
    assert task["title"] == "Fax didn't go through: Note to +15555550100"
    assert task["assignee"] == {"id": sender.id}
    assert task["team"] == {"id": None}
    assert task["patient"] == {"id": event.note.patient.id}
    assert task["labels"] == ["Failed fax"]
    assert task["status"] == "OPEN"
    assert task["author_id"] is None
    assert task["linked_object"] == {"id": None, "type": None}
    assert task["due"]
    assert comment["task"] == {"id": task["id"]}
    assert comment["author_id"] is None
    link = f"https://acme.canvasmedical.com/patient/{event.note.patient.id}?noteId={event.note.dbid}"
    assert comment["body"].startswith("No answer. Sent ")
    assert ", 3 pages. Open the note: " + link in comment["body"]
    assert comment["body"].endswith(link)
    alert = FaxAlert.objects.get()
    assert (alert.source_type, alert.item_id, alert.fax_number) == ("note", str(event.note.id), "+15555550100")
    assert alert.task_id == task["id"]
    assert alert.last_handled_event_id == str(event.id)
    assert alert.assignee == f"staff:{sender.id}"
    assert alert.closed is False


def test_comment_uses_singular_page_and_generic_reason() -> None:
    make_event("note", originator=make_staff().user, reason="", fax=FaxFactory.create(fax_pages=1, to_fax_number="+15555550100"))
    started()

    body = run()[1][1]["body"]

    assert body.startswith("The fax was not delivered. Sent ")
    assert ", 1 page. Open" in body


def test_a_failure_is_handled_once() -> None:
    make_event("note", originator=make_staff().user)
    started()

    assert len(run()) == 2
    assert run() == []
    assert FaxAlert.objects.count() == 1


def test_a_new_failure_moves_the_same_task_to_the_new_sender_and_reopens_it() -> None:
    first_sender = make_staff("Dana", "Whitfield")
    second_sender = make_staff("Marcus", "Bell")
    first = make_event("note", originator=first_sender.user, age_days=1)
    started()
    created = run()
    task_id = created[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=first_sender, team=None, status="CLOSED", patient=first.note.patient)
    second = make_event("note", note=first.note, originator=second_sender.user, reason="Busy")

    effects = run()

    assert [kind for kind, _ in effects] == ["UPDATE_TASK", "CREATE_TASK_COMMENT"]
    update, comment = effects[0][1], effects[1][1]
    assert update["id"] == task_id
    assert update["assignee"] == {"id": second_sender.id}
    assert "team" not in update
    assert update["status"] == "OPEN"
    assert update["due"]
    assert comment["task"] == {"id": task_id}
    assert comment["body"].startswith("Busy. Sent ")
    assert "Moved from Dana Whitfield to Marcus Bell." in comment["body"]
    assert comment["body"].index("Moved from") < comment["body"].index("Open the note")
    alert = FaxAlert.objects.get()
    assert alert.last_handled_event_id == str(second.id)
    assert alert.assignee == f"staff:{second_sender.id}"
    assert FaxAlert.objects.count() == 1


def test_a_new_failure_by_the_same_sender_does_not_say_moved() -> None:
    sender = make_staff()
    first = make_event("note", originator=sender.user, age_days=1)
    started()
    task_id = run()[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=sender, team=None)
    make_event("note", note=first.note, originator=sender.user)

    body = run()[1][1]["body"]

    assert "Moved" not in body


def test_someone_who_took_the_task_by_hand_is_overridden_and_named_in_the_comment() -> None:
    sender = make_staff("Dana", "Whitfield")
    other = make_staff("Cy", "Clark")
    first = make_event("note", originator=sender.user, age_days=1)
    started()
    task_id = run()[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=other, team=None)
    make_event("note", note=first.note, originator=sender.user)

    effects = run()

    assert effects[0][1]["assignee"] == {"id": sender.id}
    assert "Moved from Cy Clark to Dana Whitfield." in effects[1][1]["body"]


def test_a_task_that_no_longer_exists_is_made_again() -> None:
    sender = make_staff()
    first = make_event("note", originator=sender.user, age_days=1)
    started()
    old_id = run()[0][1]["id"]
    make_event("note", note=first.note, originator=sender.user)

    effects = run()

    assert [kind for kind, _ in effects] == ["CREATE_TASK", "CREATE_TASK_COMMENT"]
    assert effects[0][1]["id"] != old_id
    assert FaxAlert.objects.get().task_id == effects[0][1]["id"]


def test_two_new_failures_in_one_run_make_one_task_and_one_update() -> None:
    sender = make_staff()
    first = make_event("note", originator=sender.user, age_days=2)
    make_event("note", note=first.note, originator=sender.user, age_days=1)
    started()

    kinds = [kind for kind, _ in run()]

    assert kinds == ["CREATE_TASK", "CREATE_TASK_COMMENT", "UPDATE_TASK", "CREATE_TASK_COMMENT"]
    assert FaxAlert.objects.count() == 1


def test_a_later_delivery_closes_the_task_once() -> None:
    sender = make_staff()
    first = make_event("note", originator=sender.user, age_days=1)
    started()
    task_id = run()[0][1]["id"]
    make_event("note", note=first.note, originator=sender.user, delivered=True)

    effects = run()

    assert [kind for kind, _ in effects] == ["UPDATE_TASK", "CREATE_TASK_COMMENT"]
    assert effects[0][1] == {"id": task_id, "status": "COMPLETED"}
    assert effects[1][1]["task"] == {"id": task_id}
    assert effects[1][1]["body"].startswith("Delivered ") and effects[1][1]["body"].endswith(".")
    assert FaxAlert.objects.get().closed is True
    assert run() == []


def test_a_delivery_to_another_number_or_before_the_failure_does_not_close_the_task() -> None:
    sender = make_staff()
    before = make_event("note", originator=sender.user, delivered=True, age_days=3)
    failed = make_event("note", note=before.note, originator=sender.user, age_days=2)
    started()
    run()
    make_event("note", note=failed.note, originator=sender.user, delivered=True, number="+15555550199")

    assert run() == []
    assert FaxAlert.objects.get().closed is False


def test_a_failure_after_a_close_reopens_the_task() -> None:
    sender = make_staff()
    first = make_event("note", originator=sender.user, age_days=2)
    started()
    task_id = run()[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=sender, team=None)
    make_event("note", note=first.note, originator=sender.user, delivered=True, age_days=1)
    run()
    make_event("note", note=first.note, originator=sender.user)

    effects = run()

    assert effects[0][1]["status"] == "OPEN"
    assert FaxAlert.objects.get().closed is False


def test_a_dashboard_resend_that_fails_goes_to_the_person_who_clicked() -> None:
    bot = make_bot()
    clicker = make_staff("Marcus", "Bell")
    first = make_event("note", originator=make_staff().user, age_days=2)
    resent = make_event("note", note=first.note, originator=bot.user)
    FaxResend.objects.create(
        note_id=first.note.dbid, staff_id=clicker.dbid, fax_number="+15555550100",
        resent_at=resent.created - timedelta(minutes=1),
    )
    started(hours_ago=24 * 3)
    touch(first, 24 * 4)

    effects = run()

    assert effects[0][1]["assignee"] == {"id": clicker.id}


def test_unclaimed_bot_fax_goes_to_the_fallback_team() -> None:
    bot = make_bot()
    team = TeamFactory.create(name="Front Desk")
    make_event("note", originator=bot.user)
    started()

    effects = run({"FAILED_FAX_FALLBACK_TEAM": "Front Desk"})

    assert effects[0][1]["team"] == {"id": str(team.id)}
    assert effects[0][1]["assignee"] == {"id": None}
    assert FaxAlert.objects.get().assignee == f"team:{team.id}"


def test_no_staff_sender_and_no_fallback_team_means_no_task() -> None:
    make_event("note", originator=make_bot().user)
    make_event("note", originator=None)
    started()

    assert run({"FAILED_FAX_FALLBACK_TEAM": ""}) == []
    assert run({}) == []
    assert FaxAlert.objects.count() == 0


@pytest.mark.parametrize("duplicates", [0, 2])
def test_a_fallback_team_name_that_matches_no_single_team_makes_no_task(duplicates: int) -> None:
    for _ in range(duplicates):
        TeamFactory.create(name="Front Desk")
    make_event("note", originator=make_bot().user)
    started()

    assert run({"FAILED_FAX_FALLBACK_TEAM": "Front Desk"}) == []


def test_team_name_must_match_exactly() -> None:
    TeamFactory.create(name="Front Desk Team")
    make_event("note", originator=make_bot().user)
    started()

    assert run({"FAILED_FAX_FALLBACK_TEAM": "Front Desk"}) == []


def test_referral_and_imaging_tasks_link_the_object_and_others_do_not() -> None:
    sender = make_staff()
    referral = ReferralFactory.create()
    order = ImagingOrderFactory.create()
    make_event("referral", referral=referral, originator=sender.user)
    make_event("imaging_order", imaging_order=order, originator=sender.user)
    make_event("lab_order", originator=sender.user)
    make_event("letter", originator=sender.user)
    started()

    tasks = {data["title"].split(": ")[1].split(" to ")[0]: data for kind, data in run() if kind == "CREATE_TASK"}

    assert tasks["Referral"]["linked_object"] == {"id": str(referral.id), "type": "REFERRAL"}
    assert tasks["Imaging order"]["linked_object"] == {"id": str(order.id), "type": "IMAGING"}
    assert tasks["Lab order"]["linked_object"] == {"id": None, "type": None}
    assert tasks["Letter"]["linked_object"] == {"id": None, "type": None}


def test_data_integration_task_comment_links_the_document() -> None:
    event = make_event("integration_task", originator=make_staff().user)
    started()

    body = run()[1][1]["body"]

    assert body.endswith(f"Open the Data Integration document: https://acme.canvasmedical.com/data-integration/{event.integration_task.dbid}")


def test_a_dismissed_failure_gets_no_task() -> None:
    event = make_event("note", originator=make_staff().user)
    started()
    FaxDismissal.objects.create(source_type="note", source_id=str(event.id), dismissed_by="x", dismissed_at=NOW)

    assert run() == []


def test_pending_and_delivered_faxes_get_no_task() -> None:
    make_event("note", originator=make_staff().user, delivered=None)
    make_event("note", originator=make_staff().user, delivered=True)
    started()

    assert run() == []


def test_deleted_orders_get_no_task() -> None:
    event = make_event("imaging_order", originator=make_staff().user)
    event.imaging_order.deleted = True
    event.imaging_order.save()
    started()

    assert run() == []


def test_a_received_fax_makes_one_team_task_with_the_document_link() -> None:
    team = TeamFactory.create(name="Medical Records")
    fax = FaxFactory.create(direction=FaxDirection.INBOUND, success=False, from_fax_number="+15555550111", fax_pages=2)
    document = IntegrationTaskFactory.create()
    IntegrationTask.objects.filter(pk=document.pk).update(created=fax.created + timedelta(seconds=1))
    started()

    effects = run({"RECEIVED_FAX_TASK_TEAM": "Medical Records"})

    assert [kind for kind, _ in effects] == ["CREATE_TASK", "CREATE_TASK_COMMENT"]
    task, comment = effects[0][1], effects[1][1]
    assert task["title"] == "Fax arrived incomplete from +15555550111"
    assert task["team"] == {"id": str(team.id)}
    assert task["patient"] == {"id": None}
    assert task["labels"] == ["Failed fax"]
    assert comment["body"] == (
        "Only part of the fax arrived. 2 pages arrived. Ask the sender to fax again. "
        f"Open Data Integration: https://acme.canvasmedical.com/data-integration/{document.dbid}"
    )
    alert = FaxAlert.objects.get()
    assert (alert.source_type, alert.item_id, alert.fax_number) == ("received_fax", str(fax.id), "+15555550111")
    assert run({"RECEIVED_FAX_TASK_TEAM": "Medical Records"}) == []


def test_received_fax_comment_links_the_queue_when_the_document_is_unclear() -> None:
    TeamFactory.create(name="Medical Records")
    FaxFactory.create(direction=FaxDirection.INBOUND, success=False, fax_pages=1)
    started()

    body = run({"RECEIVED_FAX_TASK_TEAM": "Medical Records"})[1][1]["body"]

    assert body.startswith("Only part of the fax arrived. 1 page arrived.")
    assert body.endswith("Open Data Integration: https://acme.canvasmedical.com/data-integration")


def test_received_faxes_get_no_task_without_a_team_setting_or_when_old_or_dismissed() -> None:
    TeamFactory.create(name="Medical Records")
    old = FaxFactory.create(direction=FaxDirection.INBOUND, success=False)
    dismissed = FaxFactory.create(direction=FaxDirection.INBOUND, success=False)
    FaxFactory.create(direction=FaxDirection.INBOUND, success=True)
    started()
    type(old).objects.filter(pk=old.pk).update(modified=NOW - timedelta(days=2))
    FaxDismissal.objects.create(source_type="received_fax", source_id=str(dismissed.id), dismissed_by="x", dismissed_at=NOW)

    assert run({}) == []
    assert run({"RECEIVED_FAX_TASK_TEAM": "Medical Records"}) == []


def test_received_faxes_never_close_or_move() -> None:
    TeamFactory.create(name="Medical Records")
    FaxFactory.create(direction=FaxDirection.INBOUND, success=False)
    started()
    run({"RECEIVED_FAX_TASK_TEAM": "Medical Records"})

    assert run({"RECEIVED_FAX_TASK_TEAM": "Medical Records"}) == []
    assert FaxAlert.objects.get().closed is False


def test_the_cron_handler_runs_every_five_minutes_and_returns_the_alert_effects() -> None:
    make_event("note", originator=make_staff().user)
    started()
    on_time = datetime(2026, 10, 1, 12, 10, tzinfo=timezone.utc)
    off_time = datetime(2026, 10, 1, 12, 11, tzinfo=timezone.utc)

    def handler(moment: datetime) -> FaxAlertCron:
        event = SimpleNamespace(target=SimpleNamespace(id=moment.isoformat()))
        return FaxAlertCron(event, secrets={}, environment=ENVIRONMENT)

    assert FaxAlertCron.SCHEDULE == "*/5 * * * *"
    assert handler(off_time).compute() == []
    assert [EffectType.Name(effect.type) for effect in handler(on_time).compute()] == [
        "CREATE_TASK",
        "CREATE_TASK_COMMENT",
    ]


def test_due_date_is_today_in_the_practice_time_zone() -> None:
    make_event("note", originator=make_staff().user)
    started()
    late_evening_utc = datetime(2026, 10, 2, 2, 30, tzinfo=timezone.utc)  # still Oct 1 in New York

    task = decode(alert_effects({}, ENVIRONMENT, late_evening_utc))[0][1]

    assert task["due"] == "2026-10-01T16:00:00+00:00"  # noon in New York (EDT)


def test_moving_a_team_held_task_to_a_person_names_the_team() -> None:
    sender = make_staff("Dana", "Whitfield")
    team = TeamFactory.create(name="Front Desk")
    first = make_event("note", originator=sender.user, age_days=1)
    started()
    task_id = run()[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=None, team=team)
    make_event("note", note=first.note, originator=sender.user)

    body = run()[1][1]["body"]

    assert "Moved from Front Desk to Dana Whitfield." in body


def test_moving_an_unassigned_task_says_no_one() -> None:
    sender = make_staff("Dana", "Whitfield")
    first = make_event("note", originator=sender.user, age_days=1)
    started()
    task_id = run()[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=None, team=None)
    make_event("note", note=first.note, originator=sender.user)

    assert "Moved from no one to Dana Whitfield." in run()[1][1]["body"]


def test_moving_to_the_fallback_team_names_the_team() -> None:
    sender = make_staff("Dana", "Whitfield")
    TeamFactory.create(name="Front Desk")
    first = make_event("note", originator=sender.user, age_days=1)
    started()
    task_id = run({"FAILED_FAX_FALLBACK_TEAM": "Front Desk"})[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=sender, team=None)
    make_event("note", note=first.note, originator=make_bot().user)

    effects = run({"FAILED_FAX_FALLBACK_TEAM": "Front Desk"})

    # Dana holds the task and can't be removed, so hers is closed and a team task replaces it.
    assert [kind for kind, _ in effects] == [
        "UPDATE_TASK",
        "CREATE_TASK_COMMENT",
        "CREATE_TASK",
        "CREATE_TASK_COMMENT",
        "CREATE_TASK_COMMENT",
    ]
    assert effects[0][1] == {"id": task_id, "status": "CLOSED"}
    new_id = effects[2][1]["id"]
    assert effects[4][1]["task"] == {"id": new_id}
    assert "Moved from Dana Whitfield to Front Desk." in effects[4][1]["body"]
    assert FaxAlert.objects.get().task_id == new_id


def test_a_run_skips_failures_older_than_the_last_handled_one() -> None:
    sender = make_staff()
    older = make_event("note", originator=sender.user, age_days=2)
    make_event("note", note=older.note, originator=sender.user, age_days=1)
    started()
    run()
    touch(older, 0)

    assert run() == []


def last_ran(minutes_ago: float) -> None:
    AlertStart.objects.update(last_run_at=NOW - timedelta(minutes=minutes_ago))


def test_each_run_reads_only_failures_recorded_since_the_previous_run() -> None:
    started(hours_ago=5)
    last_ran(60)
    sender = make_staff()
    stale = make_event("note", originator=sender.user, number="+15555550101")
    touch(stale, 3)  # after the start, but long before the previous run
    fresh = make_event("note", originator=sender.user, number="+15555550102")
    touch(fresh, 0.1)

    effects = run()

    assert [name for name, _ in effects] == ["CREATE_TASK", "CREATE_TASK_COMMENT"]
    assert [alert.fax_number for alert in FaxAlert.objects.all()] == ["+15555550102"]
    assert AlertStart.objects.get().last_run_at == NOW


def test_a_failure_recorded_just_before_the_previous_run_is_still_picked_up() -> None:
    started(hours_ago=5)
    last_ran(5)
    event = make_event("note", originator=make_staff().user)
    type(event).objects.filter(pk=event.pk).update(modified=NOW - timedelta(minutes=12))

    assert [name for name, _ in run()] == ["CREATE_TASK", "CREATE_TASK_COMMENT"]


def test_the_first_run_after_an_upgrade_reads_from_the_start() -> None:
    started(hours_ago=5)  # last_run_at is empty, as on a plugin installed before this field existed
    event = make_event("note", originator=make_staff().user)
    touch(event, 3)

    assert [name for name, _ in run()] == ["CREATE_TASK", "CREATE_TASK_COMMENT"]


def test_a_task_comment_for_a_referral_links_to_the_referral_command() -> None:
    from canvas_sdk.v1.data import Command

    started()
    event = make_event("referral", originator=make_staff().user)
    referral = event.referral
    command = Command.objects.create(
        note=referral.note,
        patient=referral.patient,
        schema_key="refer",
        state="committed",
        data={},
        anchor_object_type="referral",
        anchor_object_dbid=referral.dbid,
    )

    comment = next(data for name, data in run() if name == "CREATE_TASK_COMMENT")

    assert (
        f"/patient/{referral.patient.id}?noteId={referral.note.dbid}"
        f"&commandType=refer&commandId={referral.dbid}&commandUuid={command.id}"
    ) in comment["body"]
