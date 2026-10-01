import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from uuid import uuid4

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.test_utils.factories import (
    FaxFactory,
    ServiceProviderFactory,
    StaffFactory,
    TeamFactory,
)

from failed_fax_dashboard.models import FaxDismissal
from failed_fax_dashboard.services.actions import (
    ActionError,
    build_resend,
    build_task,
    dismiss_row,
    load_received_fax,
    load_sent_event,
    resend_prefill,
    task_options,
)
from tests.helpers import make_event

pytestmark = pytest.mark.django_db


def values(effect: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(effect.payload)["data"]
    return data


# --- loading ---------------------------------------------------------------


def test_load_sent_event_rejects_unknown_type_bad_id_and_missing_row() -> None:
    with pytest.raises(ActionError, match="Unknown item type"):
        load_sent_event("bogus", str(uuid4()))
    with pytest.raises(ActionError, match="Invalid id"):
        load_sent_event("note", "not-a-uuid")
    with pytest.raises(ActionError) as missing:
        load_sent_event("note", str(uuid4()))
    assert missing.value.status == HTTPStatus.NOT_FOUND


def test_load_received_fax_only_returns_inbound_faxes() -> None:
    inbound = FaxFactory.create(direction="I", success=False)
    outbound = FaxFactory.create(direction="O")

    assert load_received_fax(str(inbound.id)).id == inbound.id
    with pytest.raises(ActionError):
        load_received_fax(str(outbound.id))


# --- resend ----------------------------------------------------------------


def test_prefill_uses_the_single_matching_directory_contact() -> None:
    ServiceProviderFactory.create(
        first_name="Dr. Ada", last_name="Lovelace", business_fax="(555) 555-0100"
    )
    event = make_event("note", number="+15555550100")

    tested = resend_prefill(str(event.id))

    assert tested == {"fax_number": "+15555550100", "recipient_name": "Dr. Ada Lovelace"}


def test_prefill_name_is_blank_for_organizations_without_a_last_name() -> None:
    ServiceProviderFactory.create(first_name="Mercy Clinic", last_name="", business_fax="555-555-0100")
    event = make_event("note", number="+15555550100")

    assert resend_prefill(str(event.id))["recipient_name"] == "Mercy Clinic"


def test_prefill_name_is_blank_when_two_contacts_share_the_number() -> None:
    ServiceProviderFactory.create(business_fax="555-555-0100")
    ServiceProviderFactory.create(business_fax="(555) 555-0100")
    event = make_event("note", number="+15555550100")

    assert resend_prefill(str(event.id))["recipient_name"] == ""


def test_prefill_name_is_blank_with_no_match_or_only_inactive_matches() -> None:
    ServiceProviderFactory.create(business_fax="555-555-0100", is_active=False)
    event = make_event("note", number="+15555550100")
    other = make_event("note", number="+15555550999")

    assert resend_prefill(str(event.id))["recipient_name"] == ""
    assert resend_prefill(str(other.id))["recipient_name"] == ""


def test_prefill_name_is_blank_for_a_too_short_number() -> None:
    event = make_event("note", number="123")

    assert resend_prefill(str(event.id)) == {"fax_number": "123", "recipient_name": ""}


def test_prefill_handles_an_event_without_a_fax_record() -> None:
    event = make_event("note")
    type(event).objects.filter(pk=event.pk).update(fax=None)

    assert resend_prefill(str(event.id)) == {"fax_number": "", "recipient_name": ""}


@pytest.mark.parametrize("delivered", [None, True])
def test_only_failed_faxes_can_be_resent(delivered: bool | None) -> None:
    event = make_event("note", delivered=delivered)

    with pytest.raises(ActionError, match="not delivered"):
        resend_prefill(str(event.id))


def test_build_resend_targets_the_note_of_the_failed_fax() -> None:
    event = make_event("note")

    effect = build_resend(
        {
            "event_id": str(event.id),
            "recipient_name": "  Dr. Ada Lovelace ",
            "recipient_fax_number": " +15555550123 ",
        }
    )

    assert effect.type == EffectType.FAX_NOTE
    data = values(effect)
    assert data["note_id"] == str(event.note.id)
    assert data["recipient_name"] == "Dr. Ada Lovelace"
    assert data["recipient_fax_number"] == "+15555550123"


def test_build_resend_requires_name_and_number() -> None:
    event = make_event("note")
    base = {"event_id": str(event.id), "recipient_name": "Dr. Ada", "recipient_fax_number": "+15555550123"}

    with pytest.raises(ActionError, match="Recipient name"):
        build_resend({**base, "recipient_name": "  "})
    with pytest.raises(ActionError, match="fax number"):
        build_resend({**base, "recipient_fax_number": "abc"})
    with pytest.raises(ActionError, match="fax number"):
        build_resend({**base, "recipient_fax_number": 5})


def test_build_resend_rejects_events_that_are_not_failed_notes() -> None:
    referral = make_event("referral")

    with pytest.raises(ActionError):
        build_resend({"event_id": str(referral.id), "recipient_name": "x", "recipient_fax_number": "1"})


# --- tasks -----------------------------------------------------------------


def test_task_options_list_active_staff_and_teams() -> None:
    active = StaffFactory.create(active=True)
    StaffFactory.create(active=False)
    team = TeamFactory.create(name="Referrals")

    tested = task_options()

    assert {"id": active.id, "name": f"{active.first_name} {active.last_name}"} in tested["staff"]
    assert len(tested["staff"]) == 1
    assert tested["teams"] == [{"id": str(team.id), "name": "Referrals"}]


def test_task_for_a_referral_links_the_referral_and_sets_the_patient() -> None:
    event = make_event("referral")
    assignee = StaffFactory.create()
    author = StaffFactory.create()

    effect = build_task(
        {
            "source_type": "referral",
            "source_id": str(event.id),
            "assignee_type": "staff",
            "assignee_id": assignee.id,
            "title": "Failed fax: Referral to +15555550100",
            "due": "2026-10-15",
            "priority": "urgent",
        },
        author_id=author.id,
    )

    assert effect.type == EffectType.CREATE_TASK
    data = values(effect)
    assert data["title"] == "Failed fax: Referral to +15555550100"
    assert data["assignee"] == {"id": assignee.id}
    assert data["team"] == {"id": None}
    assert data["patient"] == {"id": event.referral.patient.id}
    assert data["linked_object"] == {"id": str(event.referral.id), "type": "REFERRAL"}
    assert data["author_id"] == author.id
    assert data["priority"] == "urgent"
    assert datetime.fromisoformat(data["due"]) == datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def test_task_for_an_imaging_order_links_the_imaging_order() -> None:
    event = make_event("imaging_order")
    assignee = StaffFactory.create()

    data = values(
        build_task(
            {
                "source_type": "imaging_order",
                "source_id": str(event.id),
                "assignee_type": "staff",
                "assignee_id": assignee.id,
                "title": "t",
            },
            author_id="author",
        )
    )

    assert data["linked_object"] == {"id": str(event.imaging_order.id), "type": "IMAGING"}
    assert data["due"] is None
    assert data["priority"] is None


def test_task_for_a_team_on_an_unlinkable_item_has_a_patient_but_no_link() -> None:
    event = make_event("lab_order")
    team = TeamFactory.create()

    data = values(
        build_task(
            {
                "source_type": "lab_order",
                "source_id": str(event.id),
                "assignee_type": "team",
                "assignee_id": str(team.id),
                "title": "t",
            },
            author_id="author",
        )
    )

    assert data["team"] == {"id": str(team.id)}
    assert data["assignee"] == {"id": None}
    assert data["patient"] == {"id": event.lab_order.patient.id}
    assert data["linked_object"] == {"id": None, "type": None}


def test_task_for_a_data_integration_document_without_a_patient() -> None:
    event = make_event("integration_task")
    event.integration_task.patient = None
    event.integration_task.save()
    assignee = StaffFactory.create()

    data = values(
        build_task(
            {
                "source_type": "integration_task",
                "source_id": str(event.id),
                "assignee_type": "staff",
                "assignee_id": assignee.id,
                "title": "t",
            },
            author_id="author",
        )
    )

    assert data["patient"] == {"id": None}


def test_task_for_a_received_fax_has_no_patient_or_link() -> None:
    failed = FaxFactory.create(direction="I", success=False)
    assignee = StaffFactory.create()

    data = values(
        build_task(
            {
                "source_type": "received_fax",
                "source_id": str(failed.id),
                "assignee_type": "staff",
                "assignee_id": assignee.id,
                "title": "t",
            },
            author_id="author",
        )
    )

    assert data["patient"] == {"id": None}
    assert data["linked_object"] == {"id": None, "type": None}


def test_task_validation_errors() -> None:
    event = make_event("referral")
    assignee = StaffFactory.create()
    inactive = StaffFactory.create(active=False)
    base = {
        "source_type": "referral",
        "source_id": str(event.id),
        "assignee_type": "staff",
        "assignee_id": assignee.id,
        "title": "t",
    }

    cases = [
        ({"source_type": "bogus"}, "Unknown item type"),
        ({"title": " "}, "Title is required"),
        ({"assignee_type": "other"}, "Choose a staff member"),
        ({"assignee_id": ""}, "Choose a staff member"),
        ({"priority": "whenever"}, "Unknown priority"),
        ({"due": "10/15/2026"}, "YYYY-MM-DD"),
        ({"assignee_id": inactive.id}, "Assignee not found"),
        ({"assignee_type": "team", "assignee_id": str(uuid4())}, "Team not found"),
        ({"assignee_type": "team", "assignee_id": "nope"}, "Invalid team id"),
        ({"source_id": str(uuid4())}, "Fax record not found"),
    ]
    for override, message in cases:
        with pytest.raises(ActionError, match=message):
            build_task({**base, **override}, author_id="author")


# --- dismissals ------------------------------------------------------------


def test_dismiss_records_who_and_when_and_is_idempotent() -> None:
    event = make_event("letter")
    payload = {"source_type": "letter", "source_id": str(event.id)}

    dismiss_row(payload, staff_id="staff-1")
    dismiss_row(payload, staff_id="staff-2")

    rows = list(FaxDismissal.objects.all())
    assert len(rows) == 1
    assert rows[0].source_type == "letter"
    assert rows[0].source_id == str(event.id)
    assert rows[0].dismissed_by == "staff-1"
    assert rows[0].dismissed_at is not None


def test_dismiss_a_received_fax() -> None:
    failed = FaxFactory.create(direction="I", success=False)

    dismiss_row({"source_type": "received_fax", "source_id": str(failed.id)}, staff_id="staff-1")

    assert FaxDismissal.objects.filter(source_type="received_fax", source_id=str(failed.id)).exists()


def test_dismiss_rejects_unknown_types_and_missing_records() -> None:
    with pytest.raises(ActionError, match="Unknown item type"):
        dismiss_row({"source_type": "bogus", "source_id": str(uuid4())}, staff_id="s")
    with pytest.raises(ActionError, match="not found"):
        dismiss_row({"source_type": "note", "source_id": str(uuid4())}, staff_id="s")
    assert FaxDismissal.objects.count() == 0
