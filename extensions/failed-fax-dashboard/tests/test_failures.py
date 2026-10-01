from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from canvas_sdk.test_utils.factories import (
    CanvasUserFactory,
    FaxFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates

from failed_fax_dashboard.models import FaxDismissal
from failed_fax_dashboard.services.failures import (
    failed_fax_page,
    normalize_number,
    person_name,
    sender_name,
)
from tests.helpers import make_event

pytestmark = pytest.mark.django_db


def test_failed_note_fax_row_has_all_columns() -> None:
    staff = StaffFactory.create()
    event = make_event("note", originator=staff.user, reason="Line busy")
    note = event.note

    result = failed_fax_page()

    expected = {
        "key": f"note:{event.id}",
        "type": "note",
        "type_label": "Note",
        "direction": "sent",
        "source_id": str(event.id),
        "patient_name": f"{note.patient.first_name} {note.patient.last_name}",
        "fax_number": "+15555550100",
        "sender": f"{staff.first_name} {staff.last_name}",
        "occurred_at": event.created.isoformat(),
        "pages": event.fax.fax_pages,
        "reason": "Line busy",
        "link_url": f"/patient/{note.patient.id}?noteId={note.dbid}",
        "link_label": "Open note",
        "can_resend": True,
    }
    assert result["rows"] == [expected]
    assert result["total"] == 1
    assert result["window_days"] == 90


@pytest.mark.parametrize("delivered", [None, True])
def test_pending_and_delivered_faxes_are_not_listed(delivered: bool | None) -> None:
    make_event("note", delivered=delivered)

    result = failed_fax_page()

    assert result["rows"] == []
    assert result["total"] == 0
    assert result["total_pages"] == 1


def test_printed_events_are_not_listed() -> None:
    make_event("note", event_type="PRINTED")

    assert failed_fax_page()["rows"] == []


def test_failures_older_than_90_days_are_not_listed() -> None:
    make_event("note", age_days=91)
    recent = make_event("note", age_days=89)

    result = failed_fax_page()

    assert [row["source_id"] for row in result["rows"]] == [str(recent.id)]


@pytest.mark.parametrize(
    ("type_key", "label", "can_resend"),
    [
        ("note", "Note", True),
        ("referral", "Referral", False),
        ("imaging_order", "Imaging order", False),
        ("lab_order", "Lab order", False),
        ("letter", "Letter", False),
        ("integration_task", "Data Integration document", False),
    ],
)
def test_every_item_type_is_listed(type_key: str, label: str, can_resend: bool) -> None:
    event = make_event(type_key)

    result = failed_fax_page()

    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["type"] == type_key
    assert row["type_label"] == label
    assert row["can_resend"] is can_resend
    assert row["source_id"] == str(event.id)
    assert row["patient_name"]


@pytest.mark.parametrize(
    ("type_key", "label"),
    [
        ("referral", "Open note"),
        ("imaging_order", "Open note"),
        ("lab_order", "Open note"),
        ("letter", "Open letter"),
    ],
)
def test_order_and_letter_rows_link_to_the_note(type_key: str, label: str) -> None:
    event = make_event(type_key)
    item = getattr(event, type_key)
    note = item.note
    patient = note.patient if type_key == "letter" else item.patient

    row = failed_fax_page()["rows"][0]

    assert row["link_url"] == f"/patient/{patient.id}?noteId={note.dbid}"
    assert row["link_label"] == label


def test_data_integration_row_links_to_the_queue() -> None:
    make_event("integration_task")

    row = failed_fax_page()["rows"][0]

    assert row["link_url"] == "/data-integration"
    assert row["link_label"] == "Open Data Integration"


def test_lab_order_without_a_note_has_no_link() -> None:
    event = make_event("lab_order")
    event.lab_order.note = None
    event.lab_order.save()

    assert failed_fax_page()["rows"][0]["link_url"] is None


def test_later_delivery_to_same_number_clears_the_row() -> None:
    failed = make_event("note", age_days=2)
    make_event("note", delivered=True, age_days=1, note=failed.note)

    assert failed_fax_page()["rows"] == []


def test_later_delivery_matches_number_ignoring_formatting() -> None:
    failed = make_event("note", number="+1 (555) 555-0100", age_days=2)
    make_event("note", delivered=True, number="15555550100", age_days=1, note=failed.note)

    assert failed_fax_page()["rows"] == []


def test_delivery_to_a_different_number_does_not_clear_the_row() -> None:
    failed = make_event("note", age_days=2)
    make_event("note", delivered=True, number="+15555559999", age_days=1, note=failed.note)

    assert len(failed_fax_page()["rows"]) == 1


def test_delivery_for_a_different_item_does_not_clear_the_row() -> None:
    make_event("note", age_days=2)
    make_event("note", delivered=True, age_days=1)

    assert len(failed_fax_page()["rows"]) == 1


def test_delivery_before_the_failure_does_not_clear_the_row() -> None:
    failed = make_event("note", age_days=1)
    make_event("note", delivered=True, age_days=2, note=failed.note)

    assert len(failed_fax_page()["rows"]) == 1


def test_dismissed_rows_are_hidden() -> None:
    event = make_event("referral")
    FaxDismissal.objects.create(
        source_type="referral",
        source_id=str(event.id),
        dismissed_by="staff-1",
        dismissed_at=datetime.now(timezone.utc),
    )

    assert failed_fax_page()["rows"] == []


def test_dismissal_of_one_type_does_not_hide_another_type() -> None:
    event = make_event("referral")
    FaxDismissal.objects.create(
        source_type="note",
        source_id=str(event.id),
        dismissed_by="staff-1",
        dismissed_at=datetime.now(timezone.utc),
    )

    assert len(failed_fax_page()["rows"]) == 1


def test_entered_in_error_referral_is_hidden() -> None:
    event = make_event("referral")
    event.referral.entered_in_error = CanvasUserFactory.create()
    event.referral.save()

    assert failed_fax_page()["rows"] == []


def test_deleted_order_is_hidden() -> None:
    event = make_event("imaging_order")
    event.imaging_order.deleted = True
    event.imaging_order.save()

    assert failed_fax_page()["rows"] == []


def test_fax_on_a_deleted_note_is_hidden() -> None:
    event = make_event("note")
    CurrentNoteStateEvent.objects.create(note=event.note, state=NoteStates.DELETED)

    assert failed_fax_page()["rows"] == []


def test_letter_fax_on_a_deleted_note_is_hidden() -> None:
    event = make_event("letter")
    CurrentNoteStateEvent.objects.create(note=event.letter.note, state=NoteStates.DELETED)

    assert failed_fax_page()["rows"] == []


def test_fax_on_a_live_note_stays_visible() -> None:
    event = make_event("note")
    CurrentNoteStateEvent.objects.create(note=event.note, state=NoteStates.LOCKED)

    assert len(failed_fax_page()["rows"]) == 1


def test_event_without_a_fax_record_still_lists() -> None:
    event = make_event("note")
    type(event).objects.filter(pk=event.pk).update(fax=None)

    row = failed_fax_page()["rows"][0]

    assert row["fax_number"] == ""
    assert row["pages"] is None


def test_sender_name_is_empty_without_originator_or_staff_record() -> None:
    no_originator = make_event("note", originator=None)
    patient_user = make_event("note", originator=CanvasUserFactory.create())

    rows = {row["source_id"]: row for row in failed_fax_page()["rows"]}

    assert rows[str(no_originator.id)]["sender"] == ""
    assert rows[str(patient_user.id)]["sender"] == ""


def test_received_failures_are_listed() -> None:
    failed = FaxFactory.create(direction="I", success=False, from_fax_number="+15555550111", fax_pages=3)

    result = failed_fax_page()

    assert result["rows"] == [
        {
            "key": f"received_fax:{failed.id}",
            "type": "received_fax",
            "type_label": "Received fax",
            "direction": "received",
            "source_id": str(failed.id),
            "patient_name": "",
            "fax_number": "+15555550111",
            "sender": "",
            "occurred_at": failed.date_utc.isoformat(),
            "pages": 3,
            "reason": "",
            "link_url": "/data-integration",
            "link_label": "Open Data Integration",
            "can_resend": False,
        }
    ]


def test_received_fax_without_a_receive_time_uses_created() -> None:
    failed = FaxFactory.create(direction="I", success=False, date_utc=None)

    row = failed_fax_page()["rows"][0]

    assert row["occurred_at"] == failed.created.isoformat()


def test_successful_received_and_outbound_faxes_are_not_listed_as_received() -> None:
    FaxFactory.create(direction="I", success=True)
    FaxFactory.create(direction="O", success=False)

    assert failed_fax_page()["rows"] == []


def test_dismissed_received_fax_is_hidden() -> None:
    failed = FaxFactory.create(direction="I", success=False)
    FaxDismissal.objects.create(
        source_type="received_fax",
        source_id=str(failed.id),
        dismissed_by="staff-1",
        dismissed_at=datetime.now(timezone.utc),
    )

    assert failed_fax_page()["rows"] == []


def test_rows_are_newest_first_across_types_and_paginate() -> None:
    oldest = make_event("note", age_days=5)
    middle = make_event("referral", age_days=3)
    newest = make_event("letter", age_days=1)

    first = failed_fax_page(page=1, page_size=2)
    second = failed_fax_page(page=2, page_size=2)

    assert [row["source_id"] for row in first["rows"]] == [str(newest.id), str(middle.id)]
    assert [row["source_id"] for row in second["rows"]] == [str(oldest.id)]
    assert first["total"] == 3
    assert first["total_pages"] == 2
    assert second["page"] == 2


def test_page_and_page_size_are_clamped() -> None:
    make_event("note")

    result = failed_fax_page(page=0, page_size=5000)

    assert result["page"] == 1
    assert result["page_size"] == 100


def test_listing_uses_a_bounded_number_of_queries(django_assert_max_num_queries: Any) -> None:
    for _ in range(5):
        make_event("referral")
        make_event("note")

    with django_assert_max_num_queries(25):
        result = failed_fax_page()

    assert result["total"] == 10


def test_helpers() -> None:
    assert normalize_number("+1 (555) 555-0100") == "15555550100"
    assert normalize_number(None) == ""
    assert person_name(None) == ""
    assert sender_name(make_event("note", originator=None)) == ""
    staff = StaffFactory.create()
    assert person_name(staff) == f"{staff.first_name} {staff.last_name}"


def test_failed_fax_page_accepts_a_reference_time() -> None:
    make_event("note", age_days=10)
    future = datetime.now(timezone.utc) + timedelta(days=85)

    assert failed_fax_page(now=future)["rows"] == []

