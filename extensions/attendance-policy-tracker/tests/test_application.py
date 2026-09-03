"""Tests for the top bar application entry point.

Application.on_open is the whole surface of this class, one modal launched
against the review route. Nothing here decides policy, so the only thing
worth pinning is that the effect actually opens the right route as a modal
that leaves the page underneath in place.
"""

from canvas_sdk.effects import EffectType
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.events import Event, EventRequest, EventType

from attendance_policy_tracker.applications.tracker_application import (
    AttendancePolicyTrackerApplication,
)


def _on_open_event() -> Event:
    """An APPLICATION__ON_OPEN event. on_open() itself never reads it, the
    application shell above it is what checks the target before delegating,
    so a minimal event is all a direct call to on_open() needs.
    """
    return Event(EventRequest(type=EventType.APPLICATION__ON_OPEN, target=None))


class TestOnOpen:
    def test_it_launches_the_review_surface_as_a_default_modal(self) -> None:
        effect = AttendancePolicyTrackerApplication(_on_open_event()).on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        assert "/app/index" in effect.payload
        assert f'"target": "{LaunchModalEffect.TargetType.DEFAULT_MODAL.value}"' in effect.payload

    def test_the_url_carries_a_cache_busting_query_parameter(self) -> None:
        # Without this a browser holding a cached copy of the modal's own
        # page would never ask for a newly deployed version's assets.
        effect = AttendancePolicyTrackerApplication(_on_open_event()).on_open()

        assert "?v=" in effect.payload
