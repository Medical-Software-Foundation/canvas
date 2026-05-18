"""Test that scheduling_with_rooms.models exports everything in __all__."""

from scheduling_with_rooms import models


def test_models_exports():
    expected = {
        "StaffSlotConfig",
        "VisitTypeDuration",
        "VisitTypeRoomEvent",
        "VisitTypeRoomMapping",
        "get_concurrent_limit",
        "get_durations_for",
        "get_room_event_code_for",
        "replace_concurrent_limits",
        "replace_durations",
        "replace_room_event_codes",
    }
    assert set(models.__all__) == expected
    for name in expected:
        assert hasattr(models, name)
