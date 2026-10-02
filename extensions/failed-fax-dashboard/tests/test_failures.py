from datetime import timedelta
from typing import Any

import pytest
from canvas_sdk.test_utils.factories import (
    CanvasUserFactory,
    FaxFactory,
    ImagingOrderFactory,
    LabOrderFactory,
    ReferralFactory,
    ServiceProviderFactory,
)
from canvas_sdk.v1.data import FaxDirection
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates

from failed_fax_dashboard.models import FaxAlert, FaxDismissal, FaxResend
from failed_fax_dashboard.services.failures import (
    attach_tasks,
    collect_received,
    collect_sent,
    cutoff_for,
)
from tests.helpers import make_alert, make_bot, make_event, make_staff
from canvas_sdk.test_utils.factories import TaskFactory

pytestmark = pytest.mark.django_db


def rows() -> list[Any]:
    return collect_sent(cutoff_for(None))


def test_failed_note_fax_row_has_the_facts_the_dashboard_shows() -> None:
    sender = make_staff()
    event = make_event("note", originator=sender.user, reason="Line busy")
    note = event.note

    tested = rows()

    assert len(tested) == 1
    row = tested[0]
    assert row.key == f"note:{event.id}"
    assert row.patient_name == f"{note.patient.first_name} {note.patient.last_name}"
    assert row.number == "+15555550100"
    assert row.latest.sender.label == "Dana Whitfield"
    assert row.problem_text == "Line busy"
    assert row.pages == event.fax.fax_pages
    assert row.link_url == f"/patient/{note.patient.id}?noteId={note.dbid}"
    assert [attempt.outcome for attempt in row.attempts] == ["failed"]


@pytest.mark.parametrize("delivered", [None, True])
def test_pending_and_delivered_faxes_are_not_rows(delivered: bool | None) -> None:
    make_event("note", delivered=delivered)

    assert rows() == []


def test_printed_events_are_not_rows() -> None:
    make_event("note", event_type="PRINTED")

    assert rows() == []


def test_failures_older_than_90_days_are_not_rows() -> None:
    make_event("note", age_days=91)
    recent = make_event("note", age_days=89)

    assert [row.event.id for row in rows()] == [recent.id]


@pytest.mark.parametrize(
    ("type_key", "label"),
    [
        ("note", "Note"),
        ("referral", "Referral"),
        ("imaging_order", "Imaging order"),
        ("lab_order", "Lab order"),
        ("letter", "Letter"),
        ("integration_task", "Data Integration document"),
    ],
)
def test_every_item_type_is_a_row(type_key: str, label: str) -> None:
    event = make_event(type_key)

    tested = rows()

    assert [(row.spec.type_key, row.spec.label, row.event.id) for row in tested] == [
        (type_key, label, event.id)
    ]
    assert tested[0].patient_name


@pytest.mark.parametrize("type_key", ["referral", "imaging_order", "lab_order", "letter"])
def test_order_and_letter_rows_link_to_the_note(type_key: str) -> None:
    event = make_event(type_key)
    item = getattr(event, type_key)
    note = item.note
    patient = note.patient if type_key == "letter" else item.patient

    assert rows()[0].link_url == f"/patient/{patient.id}?noteId={note.dbid}"


@pytest.mark.parametrize(
    ("type_key", "schema_key", "anchor_type", "command_type"),
    [
        ("referral", "refer", "referral", "refer"),
        ("imaging_order", "imagingOrder", "imagingorder", "imagingOrder"),
        ("lab_order", "labOrder", "laborder", "labOrder"),
    ],
)
def test_order_rows_link_to_their_command_inside_the_note(
    type_key: str, schema_key: str, anchor_type: str, command_type: str
) -> None:
    from canvas_sdk.v1.data import Command

    event = make_event(type_key)
    item = getattr(event, type_key)
    command = Command.objects.create(
        note=item.note,
        patient=item.patient,
        schema_key=schema_key,
        state="committed",
        data={},
        anchor_object_type=anchor_type,
        anchor_object_dbid=item.dbid,
    )

    assert rows()[0].link_url == (
        f"/patient/{item.patient.id}?noteId={item.note.dbid}"
        f"&commandType={command_type}&commandId={item.dbid}&commandUuid={command.id}"
    )


def test_data_integration_row_links_to_its_own_document() -> None:
    event = make_event("integration_task")

    assert rows()[0].link_url == f"/data-integration/{event.integration_task.dbid}"


def test_a_later_delivery_to_the_same_number_clears_the_row() -> None:
    failed = make_event("note", age_days=2)
    make_event("note", delivered=True, note=failed.note, age_days=1)

    assert rows() == []


def test_a_delivery_to_another_number_does_not_clear_the_row() -> None:
    failed = make_event("note", age_days=2)
    make_event("note", delivered=True, note=failed.note, number="+15555550199", age_days=1)

    assert [row.event.id for row in rows()] == [failed.id]


def test_a_delivery_before_the_failure_does_not_clear_the_row() -> None:
    first = make_event("note", delivered=True, age_days=3)
    failed = make_event("note", note=first.note, age_days=1)

    assert [row.event.id for row in rows()] == [failed.id]


def test_formatting_of_the_number_does_not_split_attempts() -> None:
    first = make_event("note", number="(555) 555-0100", age_days=2)
    second = make_event("note", note=first.note, number="+15555550100", age_days=1)

    tested = rows()

    assert len(tested) == 1
    assert tested[0].event.id == second.id
    assert len(tested[0].attempts) == 2


def test_attempts_of_one_item_and_number_make_one_row_in_order() -> None:
    sender = make_staff()
    other = make_staff("Marcus", "Bell")
    first = make_event("note", originator=sender.user, reason="No answer", age_days=3)
    second = make_event("note", note=first.note, originator=other.user, reason="Busy", age_days=2)
    pending = make_event("note", note=first.note, originator=other.user, delivered=None, age_days=1)

    tested = rows()

    assert len(tested) == 1
    row = tested[0]
    assert row.event.id == second.id
    assert [attempt.event_id for attempt in row.attempts] == [
        str(first.id),
        str(second.id),
        str(pending.id),
    ]
    assert [attempt.outcome for attempt in row.attempts] == ["failed", "failed", "pending"]
    assert row.pending is True
    assert row.problem_text == "Resent, waiting for delivery"


def test_two_numbers_for_one_item_are_two_rows() -> None:
    first = make_event("note")
    make_event("note", note=first.note, number="+15555550199")

    assert len(rows()) == 2


def test_dismissed_row_is_hidden_until_a_newer_failure() -> None:
    event = make_event("note", age_days=2)
    FaxDismissal.objects.create(
        source_type="note",
        source_id=str(event.id),
        dismissed_by="x",
        dismissed_at=event.created + timedelta(hours=1),
    )
    assert rows() == []

    newer = make_event("note", note=event.note, age_days=1)

    assert [row.event.id for row in rows()] == [newer.id]


def test_deleted_notes_and_letters_on_deleted_notes_are_not_rows() -> None:
    note_event = make_event("note")
    letter_event = make_event("letter")
    CurrentNoteStateEvent.objects.create(note=note_event.note, state=NoteStates.DELETED)
    CurrentNoteStateEvent.objects.create(note=letter_event.letter.note, state=NoteStates.DELETED)

    assert rows() == []


def test_notes_in_a_live_state_stay_rows() -> None:
    event = make_event("note")
    CurrentNoteStateEvent.objects.create(note=event.note, state=NoteStates.LOCKED)

    assert len(rows()) == 1


def test_entered_in_error_and_deleted_orders_are_not_rows() -> None:
    referral = make_event("referral")
    referral.referral.entered_in_error = CanvasUserFactory.create()
    referral.referral.save()
    imaging = make_event("imaging_order")
    imaging.imaging_order.deleted = True
    imaging.imaging_order.save()

    assert rows() == []


def test_event_without_a_fax_record_still_makes_a_row() -> None:
    event = make_event("note")
    type(event).objects.filter(pk=event.pk).update(fax=None)

    tested = rows()

    assert len(tested) == 1
    assert tested[0].number == ""
    assert tested[0].pages is None
    assert tested[0].contact is None


def test_dismissal_of_one_item_type_does_not_hide_another() -> None:
    event = make_event("referral")
    FaxDismissal.objects.create(
        source_type="note",
        source_id=str(event.id),
        dismissed_by="x",
        dismissed_at=event.created,
    )

    assert len(rows()) == 1


def test_resend_from_the_dashboard_is_credited_to_the_person_who_clicked() -> None:
    bot = make_bot()
    clicker = make_staff("Marcus", "Bell")
    first = make_event("note", originator=make_staff().user, age_days=3)
    resent = make_event("note", note=first.note, originator=bot.user, age_days=1)
    FaxResend.objects.create(
        note_id=first.note.dbid,
        staff_id=clicker.dbid,
        fax_number="+15555550100",
        resent_at=resent.created - timedelta(minutes=1),
    )

    row = rows()[0]

    assert row.latest.sender.label == "Marcus Bell"
    assert row.latest.sender.kind == "resent"
    assert row.sender_staff_ids == {clicker.id}


def test_unclaimed_bot_fax_is_sent_automatically() -> None:
    bot = make_bot()
    make_event("note", originator=bot.user)

    row = rows()[0]

    assert row.latest.sender.label == "Sent automatically"
    assert row.sender_staff_ids == set()
    assert row.sender_sort == ""


def test_fax_with_no_staff_originator_is_an_unknown_sender() -> None:
    make_event("note", originator=None)
    make_event("note", originator=CanvasUserFactory.create())

    assert [row.latest.sender.label for row in rows()] == ["Unknown sender", "Unknown sender"]


def test_two_clicks_are_credited_in_click_order() -> None:
    bot = make_bot()
    first_click = make_staff("Ann", "Aaron")
    second_click = make_staff("Ben", "Baker")
    start = make_event("note", originator=make_staff().user, age_days=4)
    one = make_event("note", note=start.note, originator=bot.user, age_days=2)
    two = make_event("note", note=start.note, originator=bot.user, age_days=1)
    for person, minutes in ((second_click, 1), (first_click, 2)):
        FaxResend.objects.create(
            note_id=start.note.dbid,
            staff_id=person.dbid,
            fax_number="+15555550100",
            resent_at=one.created - timedelta(minutes=minutes),
        )
    attempts = rows()[0].attempts

    assert [attempt.event_id for attempt in attempts[1:]] == [str(one.id), str(two.id)]
    assert [attempt.sender.name for attempt in attempts[1:]] == ["Ann Aaron", "Ben Baker"]


def test_contact_comes_from_the_referral_provider() -> None:
    provider = ServiceProviderFactory.create(first_name="Lakeview Orthopedics", last_name="")
    referral = ReferralFactory.create(service_provider=provider)
    make_event("referral", referral=referral)

    contact = rows()[0].contact

    assert contact is not None
    assert contact.name == "Lakeview Orthopedics"
    assert contact.source == "From the referral"
    assert contact.phone == provider.business_phone


def test_contact_comes_from_the_imaging_center() -> None:
    provider = ServiceProviderFactory.create(first_name="Summit", last_name="Imaging")
    order = ImagingOrderFactory.create(imaging_center=provider)
    make_event("imaging_order", imaging_order=order)

    contact = rows()[0].contact

    assert contact is not None
    assert (contact.name, contact.source) == ("Summit Imaging", "From the imaging order")


def test_lab_contact_is_the_matched_directory_contact_not_the_order_lab() -> None:
    directory = ServiceProviderFactory.create(
        first_name="Northgate", last_name="", business_fax="(555) 555-0100", specialty="Laboratory"
    )
    order = LabOrderFactory.create(ontology_lab_partner="Northgate Labs")
    make_event("lab_order", lab_order=order, number="+15555550100")

    contact = rows()[0].contact

    assert contact is not None
    assert contact.name == "Northgate"
    assert contact.phone == directory.business_phone
    assert contact.address == directory.business_address
    assert contact.specialty == "Laboratory"
    assert contact.source == "Matched in your contact directory"


def test_lab_contact_without_a_directory_match_has_the_name_only() -> None:
    order = LabOrderFactory.create(ontology_lab_partner="Northgate Labs")
    make_event("lab_order", lab_order=order)

    contact = rows()[0].contact

    assert contact is not None
    assert (contact.name, contact.phone, contact.address) == ("Northgate Labs", "", "")
    assert contact.source == "Lab from the order"


def test_matched_lab_row_is_still_found_by_the_order_lab_name() -> None:
    ServiceProviderFactory.create(first_name="Northgate", last_name="", business_fax="(555) 555-0100")
    make_event("lab_order", lab_order=LabOrderFactory.create(ontology_lab_partner="Generic Lab"))

    assert "generic lab" in rows()[0].search_text


def test_note_contact_is_matched_in_the_directory_on_the_last_ten_digits() -> None:
    provider = ServiceProviderFactory.create(business_fax="1 (555) 555-0100")
    make_event("note", number="+15555550100")

    row = rows()[0]

    assert row.contact is not None
    assert row.contact.source == "Matched in your contact directory"
    assert row.contact.name == f"{provider.first_name} {provider.last_name}"
    assert row.directory is not None


def test_two_directory_matches_means_no_contact() -> None:
    ServiceProviderFactory.create(business_fax="555-555-0100")
    ServiceProviderFactory.create(business_fax="(555) 555 0100")
    make_event("note", number="+15555550100")

    row = rows()[0]

    assert row.contact is None
    assert row.party_name == "+15555550100"


def test_inactive_directory_entries_are_ignored() -> None:
    ServiceProviderFactory.create(business_fax="555-555-0100", is_active=False)
    make_event("note", number="+15555550100")

    assert rows()[0].contact is None


def test_received_rows_are_inbound_faxes_that_failed() -> None:
    bad = FaxFactory.create(direction=FaxDirection.INBOUND, success=False, from_fax_number="+15555550111")
    FaxFactory.create(direction=FaxDirection.INBOUND, success=True)
    FaxFactory.create(direction=FaxDirection.OUTBOUND, success=False)

    tested = collect_received(cutoff_for(None))

    assert [row.fax.id for row in tested] == [bad.id]
    assert tested[0].key == f"received_fax:{bad.id}"
    assert tested[0].problem_text == "Only part of the fax arrived"
    assert tested[0].pages == bad.fax_pages
    assert tested[0].when == bad.date_utc


def test_received_rows_skip_old_and_dismissed_faxes() -> None:
    old = FaxFactory.create(direction=FaxDirection.INBOUND, success=False)
    type(old).objects.filter(pk=old.pk).update(created=old.created - timedelta(days=100))
    dismissed = FaxFactory.create(direction=FaxDirection.INBOUND, success=False)
    FaxDismissal.objects.create(
        source_type="received_fax",
        source_id=str(dismissed.id),
        dismissed_by="x",
        dismissed_at=dismissed.created,
    )
    kept = FaxFactory.create(direction=FaxDirection.INBOUND, success=False)

    assert [row.fax.id for row in collect_received(cutoff_for(None))] == [kept.id]


def test_received_sender_comes_from_the_directory() -> None:
    provider = ServiceProviderFactory.create(business_fax="555-555-0111")
    FaxFactory.create(direction=FaxDirection.INBOUND, success=False, from_fax_number="+15555550111")

    row = collect_received(cutoff_for(None))[0]

    assert row.contact is not None
    assert row.contact.name == f"{provider.first_name} {provider.last_name}"
    assert row.party_name == row.contact.name


def test_tasks_attach_to_sent_and_received_rows() -> None:
    event = make_event("note")
    task = TaskFactory.create(title="Fax didn't go through: Note to +15555550100")
    make_alert(event, "note", task)
    fax = FaxFactory.create(direction=FaxDirection.INBOUND, success=False, from_fax_number="+15555550111")
    received_task = TaskFactory.create(patient=None)
    FaxAlert.objects.create(
        source_type="received_fax",
        item_id=str(fax.id),
        fax_number="+15555550111",
        task_id=str(received_task.id),
        last_handled_event_id=str(fax.id),
        last_handled_at=fax.created,
    )
    sent = rows()
    received = collect_received(cutoff_for(None))

    attach_tasks(sent, received)

    assert sent[0].task is not None and sent[0].task.id == str(task.id)
    assert received[0].task is not None and received[0].task.id == str(received_task.id)
    assert received[0].task.url is None


def test_rows_without_an_alert_have_no_task() -> None:
    make_event("note")
    sent = rows()

    attach_tasks(sent, [])

    assert sent[0].task is None


