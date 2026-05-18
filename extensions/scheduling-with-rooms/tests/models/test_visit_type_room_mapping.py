"""Tests for visit_type_room_mapping.py."""

from scheduling_with_rooms.models.visit_type_room_mapping import VisitTypeRoomMapping


def test_visit_type_room_mapping_class_has_expected_fields():
    field_names = {f.name for f in VisitTypeRoomMapping._meta.get_fields()}
    assert "note_type_code" in field_names
    assert "room_staff_key" in field_names
