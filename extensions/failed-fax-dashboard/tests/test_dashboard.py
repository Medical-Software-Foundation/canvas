from datetime import timedelta
from typing import Any

import pytest
from canvas_sdk.test_utils.factories import (
    FaxFactory,
    IntegrationTaskFactory,
    PatientFactory,
    ServiceProviderFactory,
    TaskCommentFactory,
    TaskFactory,
    TeamFactory,
)
from canvas_sdk.v1.data import FaxDirection, IntegrationTask
from django.db import connection
from django.test.utils import CaptureQueriesContext

from failed_fax_dashboard.models import FaxAlert, FaxResend
from failed_fax_dashboard.services.dashboard import dashboard_page
from failed_fax_dashboard.services.preferences import save_views
from tests.helpers import make_alert, make_bot, make_event, make_staff

pytestmark = pytest.mark.django_db


def page(tab: str = "sent", staff_id: str = "me", **params: Any) -> dict[str, Any]:
    return dashboard_page(tab, params, staff_id)


def keys(result: dict[str, Any]) -> list[str]:
    return [row["source_id"] for row in result["rows"]]


def event_with_task(assignee: Any = None, team: Any = None, **kwargs: Any) -> tuple[Any, Any]:
    event = make_event("note", **kwargs)
    task = TaskFactory.create(assignee=assignee, team=team)
    make_alert(event, "note", task)
    return event, task


def received_with_task(assignee: Any = None, team: Any = None, **kwargs: Any) -> tuple[Any, Any]:
    kwargs.setdefault("from_fax_number", "+15555550111")
    fax = FaxFactory.create(direction=FaxDirection.INBOUND, success=False, **kwargs)
    task = TaskFactory.create(assignee=assignee, team=team, patient=None)
    FaxAlert.objects.create(
        source_type="received_fax",
        item_id=str(fax.id),
        fax_number=kwargs["from_fax_number"],
        task_id=str(task.id),
        last_handled_event_id=str(fax.id),
        last_handled_at=fax.created,
    )
    return fax, task


def test_sent_row_describes_everything_the_table_shows() -> None:
    sender = make_staff("Dana", "Whitfield")
    event = make_event("note", originator=sender.user, reason="No answer")
    provider = ServiceProviderFactory.create(business_fax="555-555-0100", first_name="Riverside", last_name="")

    result = page()

    row = result["rows"][0]
    assert row["key"] == f"note:{event.id}"
    assert row["source_type"] == "note"
    assert row["type_label"] == "Note"
    assert row["patient_name"] == f"{event.note.patient.first_name} {event.note.patient.last_name}"
    assert row["problem"] == {"pending": False, "text": "No answer"}
    assert row["contact"]["name"] == "Riverside"
    assert row["contact"]["fax"] == provider.business_fax
    assert row["fax_number"] == "+15555550100"
    assert row["sender"] == {"label": "Dana Whitfield", "kind": "staff"}
    assert row["pages"] == event.fax.fax_pages
    assert row["attempts"] == [
        {
            "at": event.created.isoformat(),
            "number": 1,
            "who": "Dana Whitfield",
            "outcome": "failed",
            "reason": "No answer",
        }
    ]
    assert row["can_resend"] is True
    assert row["resend_pending"] is False
    assert row["directory_name"] == "Riverside"
    assert row["task"] is None
    assert result["totals"] == {"sent": 1, "received": 0}
    assert result["window_days"] == 90


def test_only_notes_can_be_resent_and_a_pending_resend_cannot_be_repeated() -> None:
    make_event("referral")
    first = make_event("note", age_days=2)
    make_event("note", note=first.note, delivered=None, age_days=1)

    rows = {row["source_type"]: row for row in page()["rows"]}

    assert rows["referral"]["can_resend"] is False
    assert rows["note"]["can_resend"] is False
    assert rows["note"]["resend_pending"] is True
    assert rows["note"]["problem"] == {"pending": True, "text": "Resent, waiting for delivery"}


def test_task_payload_has_status_due_assignee_link_and_comments() -> None:
    me = make_staff("Me", "Myself")
    bot = make_bot()
    other = make_staff("Cy", "Clark")
    event, task = event_with_task(assignee=other)
    TaskCommentFactory.create(task=task, creator=bot, body="No answer. Open the note: https://x/y")
    TaskCommentFactory.create(task=task, creator=me, body="Called them")
    TaskCommentFactory.create(task=task, creator=other, body="Seen")

    row = page(staff_id=me.id)["rows"][0]

    payload = row["task"]
    assert payload["id"] == str(task.id)
    assert payload["title"] == task.title
    assert payload["is_open"] is True
    assert payload["assignee"] == {"kind": "staff", "id": other.id, "name": "Cy Clark"}
    assert payload["url"] == f"/patient/{task.patient.id}?taskId={task.id}"
    assert [(c["author"], c["automatic"], c["mine"]) for c in payload["comments"]] == [
        ("Automatic", True, False),
        ("Me Myself", False, True),
        ("Cy Clark", False, False),
    ]
    assert payload["comments"][0]["body"].startswith("No answer.")


def test_closed_task_reports_its_status() -> None:
    event, task = event_with_task(assignee=make_staff())
    type(task).objects.filter(pk=task.pk).update(status="CLOSED")

    payload = page()["rows"][0]["task"]

    assert payload["status"] == "CLOSED"
    assert payload["is_open"] is False


def test_task_with_line_names_whoever_holds_the_task_besides_the_latest_sender() -> None:
    sender = make_staff("Dana", "Whitfield")
    holder = make_staff("Cy", "Clark")
    team = TeamFactory.create(name="Front Desk")
    with_sender, _ = event_with_task(assignee=sender, originator=sender.user)
    elsewhere, _ = event_with_task(assignee=holder, originator=sender.user)
    on_team, _ = event_with_task(assignee=None, team=team, originator=sender.user)

    rows = {row["source_id"]: row for row in page()["rows"]}

    assert rows[str(with_sender.id)]["task_with"] is None
    assert rows[str(elsewhere.id)]["task_with"] == {"name": "Cy Clark", "team": False}
    assert rows[str(on_team.id)]["task_with"] == {"name": "Front Desk", "team": True}


def test_sections_split_my_rows_from_the_rest() -> None:
    me = make_staff("Me", "Myself")
    my_team = TeamFactory.create(name="Mine")
    my_team.members.add(me)
    other_team = TeamFactory.create(name="Theirs")
    other = make_staff("Cy", "Clark")
    mine, _ = event_with_task(assignee=me, age_days=5)
    via_team, _ = event_with_task(assignee=None, team=my_team, age_days=4)
    theirs, _ = event_with_task(assignee=other, age_days=3)
    their_team, _ = event_with_task(assignee=None, team=other_team, age_days=2)
    untasked = make_event("note", age_days=1)

    result = page(staff_id=me.id)

    assert result["counts"] == {"mine": 2, "rest": 3}
    assert [(row["source_id"], row["mine"]) for row in result["rows"]] == [
        (str(via_team.id), True),
        (str(mine.id), True),
        (str(untasked.id), False),
        (str(their_team.id), False),
        (str(theirs.id), False),
    ]
    assert result["me"] == {"id": me.id, "name": "Me Myself", "team_ids": [str(my_team.id)]}


def test_a_fax_i_sent_whose_task_moved_to_someone_else_is_in_everything_else() -> None:
    me = make_staff("Me", "Myself")
    other = make_staff("Cy", "Clark")
    event_with_task(assignee=other, originator=me.user)

    assert page(staff_id=me.id)["counts"] == {"mine": 0, "rest": 1}


def test_collapsed_sections_leave_the_page_and_the_paging() -> None:
    me = make_staff("Me", "Myself")
    mine, _ = event_with_task(assignee=me, age_days=2)
    rest = make_event("note", age_days=1)

    assert keys(page(staff_id=me.id, collapsed="rest")) == [str(mine.id)]
    assert keys(page(staff_id=me.id, collapsed="mine")) == [str(rest.id)]
    both = page(staff_id=me.id, collapsed="mine,rest")
    assert both["rows"] == []
    assert both["counts"] == {"mine": 1, "rest": 1}
    assert both["total_pages"] == 1


def test_paging_covers_every_row_in_the_window() -> None:
    events = [make_event("note", age_days=index) for index in range(5)]

    first = page(page_size="2", page="1")
    third = page(page_size="2", page="3")
    beyond = page(page_size="2", page="9")

    assert keys(first) == [str(events[0].id), str(events[1].id)]
    assert keys(third) == [str(events[4].id)]
    assert (first["total_pages"], first["shown"]) == (3, 5)
    assert beyond["page"] == 3


def test_page_size_is_capped_and_bad_numbers_fall_back() -> None:
    make_event("note")

    capped = page(page_size="5000")
    junk = page(page_size="abc", page="x")

    assert capped["page_size"] == 100
    assert (junk["page_size"], junk["page"]) == (25, 1)


def test_default_sort_is_when_newest_first_and_dir_reverses_it() -> None:
    old = make_event("note", age_days=5)
    new = make_event("note", age_days=1)

    assert keys(page()) == [str(new.id), str(old.id)]
    assert keys(page(sort="when", dir="1")) == [str(old.id), str(new.id)]


def test_patient_sorts_by_last_name_then_first_name() -> None:
    zed_adams = make_event("note", note__patient=PatientFactory.create(first_name="Zed", last_name="Adams"))
    amy_zimmer = make_event("note", note__patient=PatientFactory.create(first_name="Amy", last_name="Zimmer"))
    abe_adams = make_event("note", note__patient=PatientFactory.create(first_name="Abe", last_name="Adams"))

    ascending = keys(page(sort="patient", dir="1"))

    assert ascending == [str(abe_adams.id), str(zed_adams.id), str(amy_zimmer.id)]
    assert keys(page(sort="patient", dir="-1")) == ascending[::-1]


def test_sent_by_sorts_by_staff_last_name_and_ignores_resent_by_wording() -> None:
    bot = make_bot()
    zoe_able = make_staff("Zoe", "Able")
    al_zane = make_staff("Al", "Zane")
    clicker = make_staff("Cy", "Baker")
    by_zane = make_event("note", originator=al_zane.user, age_days=3)
    by_able = make_event("note", originator=zoe_able.user, age_days=2)
    start = make_event("note", originator=al_zane.user, age_days=6, number="+15555550177")
    resent = make_event("note", note=start.note, number="+15555550177", originator=bot.user, age_days=1)
    FaxResend.objects.create(
        note_id=start.note.dbid, staff_id=clicker.dbid, fax_number="+15555550177",
        resent_at=resent.created - timedelta(minutes=1),
    )

    ordered = keys(page(sort="sender", dir="1"))

    assert ordered == [str(by_able.id), str(resent.id), str(by_zane.id)]


def test_item_problem_pages_attempts_and_recipient_sorts() -> None:
    letter = make_event("letter", reason="B reason", age_days=1, fax=FaxFactory.create(fax_pages=5, to_fax_number="+15555550101"))
    note = make_event("note", reason="A reason", age_days=2, fax=FaxFactory.create(fax_pages=9, to_fax_number="+15555550102"))
    first = make_event("referral", reason="C reason", age_days=3, fax=FaxFactory.create(fax_pages=1, to_fax_number="+15555550103"))
    second = make_event("referral", referral=first.referral, reason="C reason", age_days=2, fax=FaxFactory.create(fax_pages=1, to_fax_number="+15555550103"))
    ServiceProviderFactory.create(first_name="Zebra", last_name="", business_fax="555-555-0101")
    ServiceProviderFactory.create(first_name="Aardvark", last_name="", business_fax="555-555-0103")

    assert [row["type_label"] for row in page(sort="item", dir="1")["rows"]] == ["Letter", "Note", "Referral"]
    assert [row["problem"]["text"] for row in page(sort="problem", dir="1")["rows"]] == [
        "A reason", "B reason", "C reason"
    ]
    assert keys(page(sort="pages", dir="-1")) == [str(note.id), str(letter.id), str(second.id)]
    assert page(sort="attempts", dir="-1")["rows"][0]["type_label"] == "Referral"
    # A bare number sorts before names; organizations (Aardvark, Zebra) sort by full name.
    assert [row["type_label"] for row in page(sort="recipient", dir="1")["rows"]] == [
        "Note",
        "Referral",
        "Letter",
    ]


def test_received_tab_rows_and_sorts() -> None:
    team = TeamFactory.create(name="Medical Records")
    zed = make_staff("Zed", "Zimmer")
    amy = make_staff("Amy", "Adams")
    ServiceProviderFactory.create(first_name="Westend", last_name="", business_fax="555-555-0111")
    one, _ = received_with_task(assignee=zed, from_fax_number="+15555550111", fax_pages=3)
    two, _ = received_with_task(assignee=amy, from_fax_number="+15555550122", fax_pages=1)
    three, _ = received_with_task(assignee=None, team=team, from_fax_number="+15555550133", fax_pages=2)

    result = page("received", sort="task", dir="1")

    assert [row["source_id"] for row in result["rows"]] == [str(two.id), str(three.id), str(one.id)]
    assert result["totals"] == {"sent": 0, "received": 3}
    first = result["rows"][2]
    assert first["problem"] == {"pending": False, "text": "Only part of the fax arrived"}
    assert first["contact"]["name"] == "Westend"
    assert first["pages"] == 3
    assert first["link_url"] == "/data-integration"
    assert [r["source_id"] for r in page("received", sort="pages", dir="1")["rows"]] == [
        str(two.id), str(three.id), str(one.id)
    ]
    by_sender = [r["source_id"] for r in page("received", sort="recipient", dir="1")["rows"]]
    assert by_sender == [str(two.id), str(three.id), str(one.id)] or by_sender[-1] == str(one.id)


def test_search_matches_patient_recipient_item_and_digits_only_numbers() -> None:
    target = make_event("note", number="+15555550142", note__patient=PatientFactory.create(first_name="Maria", last_name="Delgado"))
    make_event("note", number="+15555550199")
    ServiceProviderFactory.create(first_name="Lakeview", last_name="Ortho", business_fax="555-555-0199")

    assert keys(page(q="delgado")) == [str(target.id)]
    assert keys(page(q="(555) 555-0142")) == [str(target.id)]
    assert len(page(q="lakeview")["rows"]) == 1
    assert len(page(q="note")["rows"]) == 2
    assert page(q="zzz")["rows"] == []
    assert len(page(q="55")["rows"]) == 0  # two digits is too short to count as a number
    assert page(q="delgado")["shown"] == 1
    assert page(q="delgado")["totals"]["sent"] == 2


def test_item_type_filter_takes_several_values() -> None:
    note = make_event("note")
    letter = make_event("letter")
    make_event("referral")

    assert sorted(keys(page(kinds="note,letter"))) == sorted([str(note.id), str(letter.id)])
    assert page("received", kinds="note")["rows"] == []


def test_person_filter_matches_latest_sender_or_task_assignee_or_me() -> None:
    me = make_staff("Me", "Myself")
    dana = make_staff("Dana", "Whitfield")
    cy = make_staff("Cy", "Clark")
    team = TeamFactory.create(name="Front Desk")
    sent_by_dana = make_event("note", originator=dana.user)
    held_by_dana, _ = event_with_task(assignee=dana, originator=cy.user)
    held_by_team, _ = event_with_task(assignee=None, team=team, originator=cy.user)
    mine, _ = event_with_task(assignee=me, originator=cy.user)
    unrelated = make_event("note", originator=cy.user)

    assert sorted(keys(page(staff_id=me.id, people=f"staff:{dana.id}"))) == sorted(
        [str(sent_by_dana.id), str(held_by_dana.id)]
    )
    assert keys(page(staff_id=me.id, people=f"team:{team.id}")) == [str(held_by_team.id)]
    assert keys(page(staff_id=me.id, people="__me")) == [str(mine.id)]
    both = keys(page(staff_id=me.id, people=f"__me,team:{team.id}"))
    assert sorted(both) == sorted([str(mine.id), str(held_by_team.id)])
    assert str(unrelated.id) not in both
    assert keys(page(staff_id=me.id, people="junk")) == []


def test_filters_combine_with_and() -> None:
    dana = make_staff("Dana", "Whitfield")
    make_event("letter", originator=dana.user)
    target = make_event("note", originator=dana.user)

    assert keys(page(kinds="note", people=f"staff:{dana.id}", q="note")) == [str(target.id)]


def test_saved_settings_apply_when_asked_and_explicit_params_win_otherwise() -> None:
    me = make_staff("Me", "Myself")
    old = make_event("note", age_days=5)
    new = make_event("note", age_days=1)
    save_views(me.id, {"sent": {"sort": {"key": "when", "dir": 1}, "q": "note"}})

    saved = page(staff_id=me.id, saved="1")
    explicit = page(staff_id=me.id)

    assert keys(saved) == [str(old.id), str(new.id)]
    assert saved["view"]["q"] == "note"
    assert keys(explicit) == [str(new.id), str(old.id)]
    assert saved["views"]["sent"]["sort"] == {"key": "when", "dir": 1}
    assert saved["views"]["received"]["sort"] == {"key": "when", "dir": -1}


def test_unknown_sort_key_falls_back_to_when() -> None:
    old = make_event("note", age_days=5)
    new = make_event("note", age_days=1)

    result = page(sort="nonsense", dir="-1")

    assert keys(result) == [str(new.id), str(old.id)]
    assert result["view"]["sort"] == {"key": "when", "dir": -1}


def received_fax_at(offset_seconds: float, **kwargs: Any) -> Any:
    fax = FaxFactory.create(direction=FaxDirection.INBOUND, success=False, **kwargs)
    type(fax).objects.filter(pk=fax.pk).update(created=fax.created + timedelta(seconds=offset_seconds))
    fax.refresh_from_db()
    return fax


def test_received_row_links_to_the_document_created_just_after_the_fax() -> None:
    provider = ServiceProviderFactory.create(first_name="Doc", last_name="Provider")
    fax = received_fax_at(0)
    document = IntegrationTaskFactory.create(service_provider=provider)
    IntegrationTask.objects.filter(pk=document.pk).update(created=fax.created + timedelta(seconds=2))

    row = page("received")["rows"][0]

    assert row["link_url"] == f"/data-integration/{document.dbid}"
    assert row["contact"]["name"] == "Doc Provider"


def test_received_row_links_to_the_queue_when_the_match_is_unclear() -> None:
    fax = received_fax_at(0)
    for seconds in (1, 3):
        document = IntegrationTaskFactory.create()
        IntegrationTask.objects.filter(pk=document.pk).update(created=fax.created + timedelta(seconds=seconds))

    assert page("received")["rows"][0]["link_url"] == "/data-integration"


def test_page_load_query_count_does_not_grow_with_the_number_of_rows() -> None:
    def load() -> int:
        with CaptureQueriesContext(connection) as queries:
            page(page_size="100")
            page("received", page_size="100")
        return len(queries)

    for type_key in ("note", "referral", "imaging_order", "lab_order", "letter", "integration_task"):
        make_event(type_key, number="+15555550001")
    event_with_task(assignee=make_staff())
    received_with_task(assignee=make_staff())
    small = load()

    for index in range(8):
        sender = make_staff(f"S{index}", f"L{index}")
        for type_key in ("note", "referral", "imaging_order", "lab_order", "letter", "integration_task"):
            make_event(type_key, originator=sender.user, number=f"+1555555{index:04d}")
        event_with_task(assignee=sender, originator=sender.user, number=f"+1555556{index:04d}")
        received_with_task(assignee=sender, from_fax_number=f"+1555557{index:04d}")
    large = load()

    assert large == small
    assert small < 60


def test_a_task_with_no_assignee_has_no_owner_and_no_patient_link() -> None:
    from failed_fax_dashboard.services.tasks import is_mine, task_info

    task = TaskFactory.create(assignee=None, team=None, patient=None)

    info = task_info(task)

    assert (info.assignee_kind, info.assignee_name, info.assignee_sort, info.url) == ("", "", "", None)
    assert is_mine(info, "me", set()) is False
    assert is_mine(None, "me", set()) is False
