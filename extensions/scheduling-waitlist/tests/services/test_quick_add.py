"""Adding a patient on the broadest terms, in one click.

The point of these tests is that the shortcut takes the same road as the form.
Assembling model fields directly here would be shorter and would quietly become a
second implementation of the priority default, the shelf life and the shape of a
preferred window -- which is how the appointment-type dropdown came to offer
services the validator then refused.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from scheduling_waitlist.constants import PREFERENCE_ANY
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.entries import DuplicateEntryError
from scheduling_waitlist.services.quick_add import (
    QuickAddRefused,
    general_payload,
    quick_add,
)

MODULE = "scheduling_waitlist.services.quick_add"

TODAY = date(2026, 8, 26)
CONFIG = WaitlistConfig.from_secrets({"WAITLIST_TTL_DAYS": "60"})


@pytest.fixture
def lookups():
    """The one model the general submission still has to resolve.

    Nothing else is queried, which is the point: every other field answered
    "any", so there is no provider, location or appointment type to look up.
    """
    with patch("scheduling_waitlist.services.validation.Patient") as patient_model:
        patient_model.objects.filter.return_value.first.return_value = MagicMock(dbid=55)
        yield patient_model


def _created(**captured):
    """Stand in for the writer, recording the fields it was handed."""
    created = MagicMock()
    created.dbid = 900
    return created


class TestTheGeneralSubmission:
    def test_it_asks_for_any_appointment_type(self):
        assert general_payload("p-1")["appointment_type_id"] == PREFERENCE_ANY

    def test_it_asks_for_any_provider_and_any_location(self):
        payload = general_payload("p-1")

        assert payload["provider_preference"] == PREFERENCE_ANY
        assert payload["location_preference"] == PREFERENCE_ANY

    def test_it_leaves_priority_to_the_configured_default(self):
        # Blank, not a hard-coded band: a practice that renames its priorities
        # should not have to re-teach this module.
        assert general_payload("p-1")["priority"] == ""

    def test_it_expresses_no_time_preference(self):
        assert general_payload("p-1")["preferred_window"] == "any"

    def test_it_names_the_patient_as_text(self):
        # The validator resolves a patient key, not a row id.
        assert general_payload(12345)["patient_id"] == "12345"

    def test_it_carries_no_note(self):
        # Nobody typed anything, and inventing a note would put words a
        # scheduler never wrote in front of the next reader.
        assert general_payload("p-1")["note"] == ""


class TestWhatItWrites:
    def _quick_add(self):
        with patch(f"{MODULE}.create_entry", side_effect=_created) as writer:
            entry = quick_add(
                "p-1", created_by_dbid=101, config=CONFIG, today=TODAY
            )
        return entry, writer.call_args.kwargs

    def test_the_entry_is_created(self, lookups):
        entry, _ = self._quick_add()

        assert entry.dbid == 900

    def test_it_passes_validation(self, lookups):
        # The broadest possible request must survive the same rules the form
        # posts through; if it cannot, the shortcut is unusable.
        _, fields = self._quick_add()

        assert fields["patient_id"] == 55

    def test_the_service_is_stored_as_no_service(self, lookups):
        # A null appointment type is how "any" is stored, and it is what makes
        # the entry match every freed slot.
        _, fields = self._quick_add()

        assert fields["note_type_id"] is None

    def test_provider_and_location_are_stored_as_any(self, lookups):
        _, fields = self._quick_add()

        assert fields["provider_preference"] == PREFERENCE_ANY
        assert fields["desired_provider_id"] is None
        assert fields["location_preference"] == PREFERENCE_ANY
        assert fields["desired_location_id"] is None

    def test_the_configured_default_priority_is_applied(self, lookups):
        _, fields = self._quick_add()

        assert fields["priority_label"] == CONFIG.default_priority_label

    def test_the_shelf_life_is_applied(self, lookups):
        # An entry nobody chose the terms of is exactly the kind that should
        # lapse on its own rather than sit on the list forever.
        _, fields = self._quick_add()

        assert fields["expires_on"] == date(2026, 10, 25)

    def test_the_clicking_staff_member_is_recorded(self, lookups):
        _, fields = self._quick_add()

        assert fields["created_by_dbid"] == 101


class TestWhenItCannot:
    def test_an_unknown_patient_is_refused(self, lookups):
        lookups.objects.filter.return_value.first.return_value = None

        with pytest.raises(QuickAddRefused) as refusal:
            quick_add("nobody", created_by_dbid=101, config=CONFIG, today=TODAY)

        assert "patient_id" in refusal.value.errors

    def test_the_refusal_says_which_rule_objected(self, lookups):
        # It reaches a log, not a form: the broadest possible request being
        # refused is a fault to investigate rather than a typo to correct.
        lookups.objects.filter.return_value.first.return_value = None

        with pytest.raises(QuickAddRefused, match="patient_id"):
            quick_add("nobody", created_by_dbid=101, config=CONFIG, today=TODAY)

    def test_nothing_is_written_when_validation_refuses(self, lookups):
        lookups.objects.filter.return_value.first.return_value = None

        with patch(f"{MODULE}.create_entry") as writer:
            with pytest.raises(QuickAddRefused):
                quick_add("nobody", created_by_dbid=101, config=CONFIG, today=TODAY)

        assert writer.call_count == 0

    def test_a_duplicate_is_left_to_the_caller(self, lookups):
        # A button and an API answer this differently, so it is raised rather
        # than swallowed here.
        with patch(f"{MODULE}.create_entry", side_effect=DuplicateEntryError):
            with pytest.raises(DuplicateEntryError):
                quick_add("p-1", created_by_dbid=101, config=CONFIG, today=TODAY)
