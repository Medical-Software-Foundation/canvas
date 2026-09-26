"""Describing a freed slot, and identifying it stably."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from scheduling_waitlist.services.slot import FreedSlot

NOW = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)


def appointment(**overrides):
    record = MagicMock()
    record.dbid = 900
    record.id = "appt-key"
    record.start_time = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    record.duration_minutes = 30
    record.note_type_id = 7
    record.note_type.name = "Established Visit"
    record.note_type.code = "estab"
    record.provider_id = 101
    record.provider.first_name = "Alice"
    record.provider.last_name = "Chen"
    record.location_id = 3
    record.location.full_name = "Riverside Clinic"
    record.location.short_name = "Riverside"
    record.patient_id = 55
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


class TestFromAppointment:
    def test_reads_the_slot_attributes(self):
        slot = FreedSlot.from_appointment(appointment(), source_event="APPOINTMENT_CANCELED")

        assert slot.appointment_dbid == 900
        assert slot.duration_minutes == 30
        assert slot.note_type_dbid == 7
        assert slot.provider_dbid == 101
        assert slot.location_dbid == 3

    def test_labels_are_human_readable(self):
        slot = FreedSlot.from_appointment(appointment())

        assert slot.note_type_label == "Established Visit"
        assert slot.provider_label == "Alice Chen"
        assert slot.location_label == "Riverside Clinic"

    def test_missing_related_records_never_render_as_none(self):
        slot = FreedSlot.from_appointment(
            appointment(note_type=None, provider=None, location=None)
        )

        assert slot.note_type_label == "Unspecified"
        assert slot.provider_label == "Unspecified"
        assert slot.location_label == "Unspecified"

    def test_records_who_vacated_the_slot(self):
        assert FreedSlot.from_appointment(appointment()).vacating_patient_dbid == 55


class TestFingerprint:
    def test_the_same_slot_fingerprints_identically(self):
        first = FreedSlot.from_appointment(appointment(), source_event="APPOINTMENT_CANCELED")
        second = FreedSlot.from_appointment(appointment(), source_event="APPOINTMENT_CANCELED")

        assert first.fingerprint() == second.fingerprint()

    def test_the_event_type_is_not_part_of_the_identity(self):
        # A cancellation and a no-show recorded against the same booking are the
        # same freed slot, and must not each raise their own task.
        cancelled = FreedSlot.from_appointment(
            appointment(), source_event="APPOINTMENT_CANCELED"
        )
        no_showed = FreedSlot.from_appointment(
            appointment(), source_event="APPOINTMENT_NO_SHOWED"
        )

        assert cancelled.fingerprint() == no_showed.fingerprint()

    def test_moving_the_appointment_makes_it_a_different_slot(self):
        original = FreedSlot.from_appointment(appointment())
        moved = FreedSlot.from_appointment(
            appointment(start_time=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc))
        )

        assert original.fingerprint() != moved.fingerprint()

    def test_a_different_provider_makes_it_a_different_slot(self):
        assert (
            FreedSlot.from_appointment(appointment()).fingerprint()
            != FreedSlot.from_appointment(appointment(provider_id=999)).fingerprint()
        )

    def test_equivalent_times_in_other_zones_fingerprint_the_same(self):
        eastern = datetime(2026, 8, 12, 5, 0, tzinfo=timezone(timedelta(hours=-4)))

        assert (
            FreedSlot.from_appointment(appointment(start_time=eastern)).fingerprint()
            == FreedSlot.from_appointment(appointment()).fingerprint()
        )

    def test_a_slot_without_a_start_time_still_fingerprints(self):
        assert FreedSlot.from_appointment(appointment(start_time=None)).fingerprint()


class TestTiming:
    def test_a_slot_beyond_the_lead_time_is_fillable(self):
        slot = FreedSlot.from_appointment(appointment())

        assert slot.starts_within(2, now=NOW) is False

    def test_a_slot_inside_the_lead_time_is_too_soon(self):
        soon = NOW + timedelta(hours=1)

        assert FreedSlot.from_appointment(appointment(start_time=soon)).starts_within(
            2, now=NOW
        )

    def test_a_slot_with_no_start_time_counts_as_too_soon(self):
        # Nothing can be scheduled against it, so it is not worth interrupting
        # anyone about.
        assert FreedSlot.from_appointment(appointment(start_time=None)).starts_within(
            2, now=NOW
        )

    def test_a_past_slot_has_passed(self):
        past = NOW - timedelta(hours=1)

        assert FreedSlot.from_appointment(appointment(start_time=past)).has_passed(now=NOW)

    def test_a_future_slot_has_not_passed(self):
        assert FreedSlot.from_appointment(appointment()).has_passed(now=NOW) is False
