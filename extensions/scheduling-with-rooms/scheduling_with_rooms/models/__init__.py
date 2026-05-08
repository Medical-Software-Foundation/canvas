"""CustomModels for scheduling_with_rooms.

Persisted via Canvas Custom Data under the `scheduling_with_rooms`
namespace declared in CANVAS_MANIFEST.json.
"""

from scheduling_with_rooms.models.staff_slot_config import (
    StaffSlotConfig,
    get_concurrent_limit,
    replace_concurrent_limits,
)
from scheduling_with_rooms.models.visit_type_duration import (
    VisitTypeDuration,
    get_durations_for,
    replace_durations,
)
from scheduling_with_rooms.models.visit_type_room_event import (
    VisitTypeRoomEvent,
    get_room_event_code_for,
    replace_room_event_codes,
)
from scheduling_with_rooms.models.visit_type_room_mapping import VisitTypeRoomMapping

__all__ = [
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
]
