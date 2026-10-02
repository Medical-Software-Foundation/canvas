"""Readable names for half-populated records.

Every one of these guards the same small bug: rendering a bare "None" into a
roster cell or a task body, which reads as a broken plugin.
"""

from unittest.mock import MagicMock

from scheduling_waitlist.services.display import (
    location_name,
    note_type_name,
    patient_name,
    staff_name,
)


def record(**attrs):
    item = MagicMock()
    for key, value in attrs.items():
        setattr(item, key, value)
    return item


class TestStaffName:
    def test_first_and_last_are_joined(self):
        assert staff_name(record(first_name="Alice", last_name="Chen")) == "Alice Chen"

    def test_surrounding_whitespace_is_trimmed(self):
        assert staff_name(record(first_name=" Alice ", last_name=" Chen ")) == "Alice Chen"

    def test_a_first_name_alone_is_used(self):
        assert staff_name(record(first_name="Alice", last_name="")) == "Alice"

    def test_a_nameless_record_gets_a_readable_placeholder(self):
        assert staff_name(record(first_name="", last_name="")) == "Unnamed staff member"

    def test_null_names_get_the_placeholder(self):
        assert staff_name(record(first_name=None, last_name=None)) == "Unnamed staff member"

    def test_a_missing_record_gets_the_placeholder(self):
        assert staff_name(None) == "Unnamed staff member"


class TestPatientName:
    def test_first_and_last_are_joined(self):
        assert patient_name(record(first_name="Jordan", last_name="Lee")) == "Jordan Lee"

    def test_a_missing_record_gets_a_placeholder(self):
        assert patient_name(None) == "Unnamed patient"

    def test_a_nameless_patient_gets_a_placeholder(self):
        assert patient_name(record(first_name="", last_name="")) == "Unnamed patient"


class TestLocationName:
    def test_the_full_name_is_preferred(self):
        location = record(full_name="Riverside Clinic", short_name="Riverside")

        assert location_name(location) == "Riverside Clinic"

    def test_the_short_name_is_the_fallback(self):
        assert location_name(record(full_name="", short_name="Riverside")) == "Riverside"

    def test_a_nameless_location_gets_a_placeholder(self):
        assert location_name(record(full_name="", short_name="")) == "Unnamed location"

    def test_a_missing_record_gets_a_placeholder(self):
        assert location_name(None) == "Unnamed location"


class TestNoteTypeName:
    def test_the_name_is_preferred(self):
        assert note_type_name(record(name="Established Visit", code="estab")) == (
            "Established Visit"
        )

    def test_the_code_is_the_fallback(self):
        assert note_type_name(record(name="", code="estab")) == "estab"

    def test_an_unlabelled_type_reads_as_unspecified(self):
        assert note_type_name(record(name="", code="")) == "Unspecified"

    def test_a_missing_record_reads_as_unspecified(self):
        assert note_type_name(None) == "Unspecified"
