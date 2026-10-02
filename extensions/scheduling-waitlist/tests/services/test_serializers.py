"""Turning an entry into a roster row."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from scheduling_waitlist.constants import PREFERENCE_ANY, PREFERENCE_SPECIFIC
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.serializers import (
    days_waiting,
    is_past_shelf_life,
    serialize_entry,
)

TODAY = date(2026, 8, 3)
CONFIG = WaitlistConfig.from_secrets({})


def make_entry(**overrides):
    entry = MagicMock()
    entry.dbid = 42
    entry.patient_id = 55
    entry.patient.id = "patient-key"
    entry.patient.first_name = "Jordan"
    entry.patient.last_name = "Lee"
    entry.note_type_id = 7
    entry.note_type.name = "Established Visit"
    entry.note_type.code = "estab"
    entry.provider_preference = PREFERENCE_SPECIFIC
    entry.desired_provider_id = 101
    entry.desired_provider.first_name = "Alice"
    entry.desired_provider.last_name = "Chen"
    entry.location_preference = PREFERENCE_SPECIFIC
    entry.desired_location_id = 3
    entry.desired_location.full_name = "Riverside Clinic"
    entry.desired_location.short_name = "Riverside"
    entry.priority_label = "High"
    entry.priority_rank = 0
    entry.preferred_windows = []
    entry.preferred_windows_timezone = ""
    entry.preferred_window_note = ""
    entry.note = "Needs an interpreter"
    entry.status = "waiting"
    entry.status_reason = ""
    entry.created_at = datetime(2026, 6, 2, 14, 31, tzinfo=timezone.utc)
    entry.created_by_id = 101
    entry.created_by.first_name = "Alice"
    entry.created_by.last_name = "Chen"
    entry.expires_on = date(2026, 9, 1)
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def serialize(entry, **kwargs):
    kwargs.setdefault("config", CONFIG)
    kwargs.setdefault("today", TODAY)
    return serialize_entry(entry, **kwargs)


class TestDaysWaiting:
    def test_counts_whole_days_since_the_entry_was_added(self):
        created = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)

        assert days_waiting(created, TODAY) == 2

    def test_same_day_reads_as_zero(self):
        created = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)

        assert days_waiting(created, TODAY) == 0

    def test_a_future_creation_date_never_reads_as_negative(self):
        created = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

        assert days_waiting(created, TODAY) == 0

    def test_a_missing_creation_date_reads_as_zero(self):
        assert days_waiting(None, TODAY) == 0

    def test_a_plain_date_is_accepted(self):
        assert days_waiting(date(2026, 8, 1), TODAY) == 2


class TestShelfLife:
    def test_an_entry_before_its_expiry_date_is_live(self):
        assert is_past_shelf_life(date(2026, 9, 1), TODAY) is False

    def test_an_entry_exactly_on_its_expiry_date_is_still_live(self):
        # expires_on is the last valid day, so the entry lapses the day after.
        assert is_past_shelf_life(TODAY, TODAY) is False

    def test_an_entry_past_its_expiry_date_has_lapsed(self):
        assert is_past_shelf_life(date(2026, 8, 2), TODAY) is True

    def test_an_entry_with_no_expiry_date_never_lapses(self):
        # The schema pipeline emits no column defaults, so rows written before
        # this column existed carry null and must not silently disappear.
        assert is_past_shelf_life(None, TODAY) is False


class TestSerializeEntry:
    def test_patient_name_is_joined_for_display(self):
        assert serialize(make_entry())["patient"]["name"] == "Jordan Lee"

    def test_a_specific_provider_is_named(self):
        assert serialize(make_entry())["provider"]["name"] == "Alice Chen"

    def test_any_provider_reads_as_any_rather_than_a_blank(self):
        entry = make_entry(provider_preference=PREFERENCE_ANY)

        result = serialize(entry)

        assert result["provider"]["name"] == "Any provider"
        assert result["provider"]["is_any"] is True
        assert result["provider"]["dbid"] is None

    def test_any_location_reads_as_any(self):
        entry = make_entry(location_preference=PREFERENCE_ANY)

        assert serialize(entry)["location"]["name"] == "Any location"

    def test_an_entry_with_no_appointment_type_reads_as_any_type(self):
        entry = make_entry(note_type=None, note_type_id=None)

        assert serialize(entry)["appointment_type"]["name"] == "Any appointment type"

    def test_any_appointment_type_is_stated_not_left_to_be_inferred(self):
        # The edit dialog reselects "any" from this flag, the same way it does for
        # provider and location, rather than reading a missing identifier as one.
        entry = make_entry(note_type=None, note_type_id=None)

        assert serialize(entry)["appointment_type"]["is_any"] is True

    def test_a_specific_appointment_type_is_not_marked_any(self):
        assert serialize(make_entry())["appointment_type"]["is_any"] is False

    def test_a_configured_priority_is_reported_as_known(self):
        assert serialize(make_entry())["priority"]["is_known"] is True

    def test_a_priority_orphaned_by_reconfiguration_is_flagged(self):
        # The roster can then explain why an entry sorts oddly instead of just
        # showing an unfamiliar word.
        entry = make_entry(priority_label="Yesterday")

        assert serialize(entry)["priority"]["is_known"] is False

    def test_an_empty_note_serializes_as_a_string_not_none(self):
        # This lands straight in a table cell; "None" would be a visible bug.
        entry = make_entry(note=None)

        assert serialize(entry)["note"] == ""

    def test_a_missing_preferred_window_serializes_as_an_empty_list(self):
        entry = make_entry(preferred_windows=None)

        assert serialize(entry)["preferred_window"]["windows"] == []

    def test_dates_are_serialized_as_iso_strings(self):
        result = serialize(make_entry())

        assert result["created_at"].startswith("2026-06-02")
        assert result["expires_on"] == "2026-09-01"

    def test_a_missing_date_serializes_as_an_empty_string(self):
        entry = make_entry(expires_on=None)

        assert serialize(entry)["expires_on"] == ""

    def test_days_waiting_is_included(self):
        assert serialize(make_entry())["days_waiting"] == 62

    def test_the_creator_may_edit_their_own_entry(self):
        viewer = MagicMock(dbid=101)

        result = serialize(make_entry(), viewer=viewer, manages_all=False)

        assert result["can_edit"] is True
        assert result["can_remove"] is True

    def test_another_staff_member_may_not_edit_without_a_manager_role(self):
        viewer = MagicMock(dbid=999)

        result = serialize(make_entry(), viewer=viewer, manages_all=False)

        assert result["can_edit"] is False

    def test_a_manager_may_edit_anyone_s_entry(self):
        viewer = MagicMock(dbid=999)

        result = serialize(make_entry(), viewer=viewer, manages_all=True)

        assert result["can_edit"] is True

    def test_no_viewer_means_no_edit_rights(self):
        assert serialize(make_entry())["can_edit"] is False


class TestTheNextAppointment:
    """Passed in rather than looked up.

    ``services/appointments.py`` answers it for a whole page in one query.
    Fetching it here would be one query per row, and would make the one place
    the roster's shape is defined depend on the database.
    """

    def test_it_is_carried_through_untouched(self):
        booked = {
            "start": "2026-08-30T09:00:00+00:00",
            "type": "Office visit",
            "provider": "Ada Chen",
            "state": "upcoming",
        }

        assert serialize(make_entry(), next_appointment=booked)["next_appointment"] is booked

    def test_a_patient_with_nothing_booked_reports_nothing(self):
        # None rather than an empty object: having no appointment is the normal
        # state for somebody waiting, and the roster leaves the cell blank.
        assert serialize(make_entry())["next_appointment"] is None

    def test_the_field_is_always_present(self):
        # The roster reads it on every row; an absent key would be a crash
        # rather than an empty cell.
        assert "next_appointment" in serialize(make_entry())
