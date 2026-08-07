"""The wording a scheduler actually reads."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from scheduling_waitlist.services.slot import FreedSlot
from scheduling_waitlist.services.task_composer import (
    TITLE_MAX,
    compose_body,
    compose_title,
    format_slot_time,
)

TODAY = date(2026, 8, 12)


def slot(**overrides):
    values = {
        "appointment_dbid": 900,
        "appointment_id": "appt-key",
        "start_time": datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "note_type_dbid": 7,
        "note_type_label": "Established Visit",
        "provider_dbid": 101,
        "provider_label": "Alice Chen",
        "location_dbid": 3,
        "location_label": "Riverside Clinic",
        "vacating_patient_dbid": 55,
        "source_event": "APPOINTMENT_CANCELED",
    }
    values.update(overrides)
    return FreedSlot(**values)


def entry(name="Jordan Lee", priority="High", windows=None, window_note="", note=""):
    record = MagicMock()
    first, _, last = name.partition(" ")
    record.patient.first_name = first
    record.patient.last_name = last
    record.priority_label = priority
    record.preferred_windows = windows or []
    record.preferred_window_note = window_note
    record.note = note
    record.note_type.name = "Established Visit"
    record.provider_preference = "specific"
    record.desired_provider.first_name = "Alice"
    record.desired_provider.last_name = "Chen"
    record.location_preference = "specific"
    record.desired_location.full_name = "Riverside Clinic"
    record.created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    return record


class TestFormatSlotTime:
    def test_renders_the_local_time_with_its_zone(self):
        text = format_slot_time(slot(), timezone_name="UTC")

        assert "3:30 PM" in text
        assert "UTC" in text

    def test_converts_into_the_configured_zone(self):
        text = format_slot_time(slot(), timezone_name="America/Denver")

        assert "9:30 AM" in text

    def test_always_shows_the_zone_so_a_wrong_setting_is_visible(self):
        # Locations carry no timezone of their own, so this is one instance-wide
        # setting; a mistake has to be readable rather than silently shifting.
        assert "MDT" in format_slot_time(slot(), timezone_name="America/Denver")

    def test_includes_the_duration(self):
        assert "(30 min)" in format_slot_time(slot(), timezone_name="UTC")

    def test_an_unusable_zone_falls_back_to_utc(self):
        assert "UTC" in format_slot_time(slot(), timezone_name="Mars/Olympus")

    def test_a_slot_without_a_start_time_says_so(self):
        assert format_slot_time(slot(start_time=None), timezone_name="UTC") == "Time unknown"


class TestComposeTitle:
    def test_a_single_match_reads_in_the_singular(self):
        assert "1 waitlisted patient match" in compose_title(slot(), 1, timezone_name="UTC")

    def test_several_matches_read_in_the_plural(self):
        assert "3 waitlisted patients match" in compose_title(slot(), 3, timezone_name="UTC")

    def test_the_service_and_provider_are_named(self):
        title = compose_title(slot(), 2, timezone_name="UTC")

        assert "Established Visit" in title
        assert "Alice Chen" in title

    def test_an_overlong_title_is_shortened(self):
        long_slot = slot(note_type_label="A" * 200)

        title = compose_title(long_slot, 2, timezone_name="UTC")

        assert len(title) <= TITLE_MAX


class TestComposeBody:
    def _body(self, entries=None, **kwargs):
        return compose_body(
            slot(), entries or [entry()], timezone_name="UTC", today=TODAY, **kwargs
        )

    def test_the_slot_details_are_listed(self):
        body = self._body()

        assert "Established Visit" in body
        assert "Riverside Clinic" in body

    def test_the_triggering_event_is_named(self):
        assert "APPOINTMENT_CANCELED" in self._body()

    def test_patients_are_numbered_in_order(self):
        body = self._body([entry("Jordan Lee"), entry("Sam Poe")])

        assert "1. [High] Jordan Lee" in body
        assert "2. [High] Sam Poe" in body

    def test_each_patient_shows_what_they_asked_for(self):
        assert "Wants: Established Visit - Alice Chen - Riverside Clinic" in self._body()

    def test_a_patient_with_no_stored_window_reads_as_any_time(self):
        assert "Prefers: Any time" in self._body()

    def test_a_structured_window_is_described_in_words(self):
        body = self._body(
            [entry(windows=[{"days": [1], "start": "08:00", "end": "12:00"}])]
        )

        assert "Prefers: Tue 08:00-12:00" in body

    def test_free_text_takes_precedence_over_the_structured_window(self):
        body = self._body(
            [
                entry(
                    windows=[{"days": [1], "start": "08:00", "end": "12:00"}],
                    window_note="after school only",
                )
            ]
        )

        assert "Prefers: after school only" in body

    def test_how_long_they_have_waited_is_shown(self):
        assert "Waiting 10 days" in self._body()

    def test_a_staff_note_is_carried_through(self):
        assert "Note: needs an interpreter" in self._body(
            [entry(note="needs an interpreter")]
        )

    def test_the_preferred_time_is_labelled_a_hint(self):
        assert "hint only" in self._body()

    def test_the_body_states_that_nobody_was_booked(self):
        # The single most important sentence: staff must not assume the slot is
        # filled.
        assert "Nobody has been booked" in self._body()

    def test_the_body_explains_how_the_entry_closes_itself(self):
        assert "becomes 'scheduled' on its own" in self._body()
