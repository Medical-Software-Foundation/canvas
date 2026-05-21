"""Handler for APPOINTMENT__SLOTS__POST_SEARCH — currently disabled.

POST_SEARCH_RESULTS only supplements native slots (cannot remove them),
so slot injection cannot enforce buffers. Buffer enforcement is handled
by appointment_buffer.py which creates blocking calendar events.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol


class SlotAvailabilityProvider(BaseProtocol):
    """Disabled: POST_SEARCH_RESULTS can only add slots, not remove them."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT__SLOTS__POST_SEARCH)

    def compute(self) -> list[Effect]:
        return []
