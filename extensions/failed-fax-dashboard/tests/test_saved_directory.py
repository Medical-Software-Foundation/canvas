from typing import Any

import pytest
from canvas_sdk.test_utils.factories import (
    FaxFactory,
    LabOrderFactory,
    ReferralFactory,
    ServiceProviderFactory,
)
from canvas_sdk.v1.data import FaxDirection
from requests import RequestException

from failed_fax_dashboard.services.failures import collect_received, collect_sent, cutoff_for
from failed_fax_dashboard.services.saved_directory import MAX_LOOKUPS_PER_LOAD, saved_matches
from tests.conftest import FakeSavedDirectory
from tests.helpers import make_event

pytestmark = pytest.mark.django_db


def saved(fax: str = "(888) 444-1111", **fields: Any) -> dict[str, Any]:
    """A Saved Directory contact as the service returns it."""
    return {
        "firstName": "Generic Lab",
        "lastName": "",
        "practiceName": "Generic Lab Inc",
        "specialty": "Laboratory",
        "businessPhone": "8884440000",
        "businessFax": fax,
        "businessAddress": "1 Main St, Omaha NE",
        **fields,
    }


def rows() -> list[Any]:
    return collect_sent(cutoff_for(None))


def test_note_fax_with_no_instance_match_takes_the_saved_directory_contact(
    saved_directory_service: FakeSavedDirectory,
) -> None:
    saved_directory_service.contacts = [saved()]
    make_event("note", number="+18884441111")

    contact = rows()[0].contact

    assert contact is not None
    assert (contact.name, contact.practice, contact.phone, contact.address) == (
        "Generic Lab",
        "Generic Lab Inc",
        "8884440000",
        "1 Main St, Omaha NE",
    )
    assert contact.source == "Matched in the Saved Directory"
    assert saved_directory_service.paths == [
        "/contacts/?business_fax=8884441111&format=json&limit=10"
    ]


def test_lab_card_names_the_saved_directory_contact_not_the_placeholder_lab(
    saved_directory_service: FakeSavedDirectory,
) -> None:
    saved_directory_service.contacts = [saved(firstName="Generic Lab - Omaha")]
    make_event("lab_order", number="+18884441111", lab_order=LabOrderFactory.create(ontology_lab_partner="Generic Lab"))

    contact = rows()[0].contact

    assert contact is not None
    assert (contact.name, contact.phone, contact.specialty) == ("Generic Lab - Omaha", "8884440000", "Laboratory")
    assert contact.source == "Matched in the Saved Directory"


def test_instance_match_wins_and_the_saved_directory_is_not_asked(
    saved_directory_service: FakeSavedDirectory,
) -> None:
    ServiceProviderFactory.create(first_name="Riverside", last_name="Clinic", business_fax="8884441111")
    saved_directory_service.contacts = [saved()]
    make_event("note", number="+18884441111")

    contact = rows()[0].contact

    assert contact is not None
    assert contact.name == "Riverside Clinic"
    assert contact.source == "Matched in your contact directory"
    assert saved_directory_service.paths == []


def test_item_that_names_its_recipient_is_not_looked_up(saved_directory_service: FakeSavedDirectory) -> None:
    provider = ServiceProviderFactory.create(first_name="Lakeview Orthopedics", last_name="")
    make_event("referral", number="+18884441111", referral=ReferralFactory.create(service_provider=provider))

    contact = rows()[0].contact

    assert contact is not None
    assert contact.source == "From the referral"
    assert saved_directory_service.paths == []


def test_two_saved_directory_contacts_with_the_number_means_no_contact(
    saved_directory_service: FakeSavedDirectory,
) -> None:
    saved_directory_service.contacts = [saved(), saved(firstName="Other Lab", fax="+1 888 444 1111")]
    make_event("note", number="+18884441111")

    row = rows()[0]

    assert row.contact is None
    assert row.party_name == "+18884441111"


def test_a_contact_with_a_different_fax_number_is_ignored(saved_directory_service: FakeSavedDirectory) -> None:
    saved_directory_service.contacts = [saved(fax="8884442222")]
    make_event("note", number="+18884441111")

    assert rows()[0].contact is None


def test_a_failed_lookup_shows_the_number_and_is_tried_again_next_load(
    saved_directory_service: FakeSavedDirectory,
) -> None:
    saved_directory_service.error = RequestException("timed out")
    make_event("note", number="+18884441111")

    assert rows()[0].contact is None

    saved_directory_service.error = None
    saved_directory_service.contacts = [saved()]

    assert rows()[0].contact is not None
    assert len(saved_directory_service.paths) == 2


def test_an_error_status_shows_the_number_and_is_not_saved(saved_directory_service: FakeSavedDirectory) -> None:
    saved_directory_service.status_code = 503
    saved_directory_service.contacts = [saved()]

    assert saved_matches(["+18884441111"]) == {}
    assert saved_matches(["+18884441111"]) == {}
    assert len(saved_directory_service.paths) == 2


def test_answers_are_saved_including_no_match(saved_directory_service: FakeSavedDirectory) -> None:
    saved_directory_service.contacts = [saved()]
    first = saved_matches(["+18884441111", "+15555550199"])

    saved_directory_service.contacts = []
    second = saved_matches(["+18884441111", "+15555550199"])

    assert set(first) == set(second) == {"8884441111"}
    assert len(saved_directory_service.paths) == 2


def test_lookups_per_load_are_capped(saved_directory_service: FakeSavedDirectory) -> None:
    numbers = [f"+1555555{index:04d}" for index in range(MAX_LOOKUPS_PER_LOAD + 5)]

    saved_matches(numbers)
    assert len(saved_directory_service.paths) == MAX_LOOKUPS_PER_LOAD

    saved_matches(numbers)
    assert len(saved_directory_service.paths) == MAX_LOOKUPS_PER_LOAD + 5


def test_received_fax_sender_is_matched_in_the_saved_directory(
    saved_directory_service: FakeSavedDirectory,
) -> None:
    saved_directory_service.contacts = [saved()]
    FaxFactory.create(direction=FaxDirection.INBOUND, success=False, from_fax_number="18884441111")

    contact = collect_received(cutoff_for(None))[0].contact

    assert contact is not None
    assert contact.name == "Generic Lab"
    assert contact.source == "Matched in the Saved Directory"
