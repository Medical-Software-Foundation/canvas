"""The application entry point, opened from the app drawer with no patient in context."""

import json
from typing import TYPE_CHECKING, Any

from fax_queue_inboxes.handlers.application import FaxQueueDashboard

if TYPE_CHECKING:
    from canvas_sdk.effects import Effect
    from canvas_sdk.events import Event


def make_event(event_type: str, target: str = "", context: dict | None = None) -> "Event":
    """A real Event, built the way the platform builds one, for driving a handler."""
    from canvas_generated.messages.events_pb2 import Event as EventRequest
    from canvas_generated.messages.events_pb2 import EventType
    from canvas_sdk.events import Event

    return Event(
        EventRequest(
            type=EventType.Value(event_type),
            target=target,
            context=json.dumps(context or {}),
        )
    )


def payload(effect: "Effect") -> Any:
    """The data an effect carries."""
    return json.loads(effect.payload)["data"]


def test_opening_the_application_returns_exactly_one_page_launch_effect() -> None:
    """Covers scenario: AC1, opening the application returns exactly one page launch effect. Covers criterion: AC1. The Given, a staff member with an authenticated session, is what lets the event reach the handler at all, since an unauthenticated request never reaches APPLICATION__ON_OPEN. Nothing inside on_open reads the session itself, so the criterion is proven at the handler's own boundary, exactly one effect, targeting a page, with url set and content unset."""
    identifier = f"{FaxQueueDashboard.__module__}:{FaxQueueDashboard.__qualname__}"
    event = make_event("APPLICATION__ON_OPEN", target=identifier)

    effects = FaxQueueDashboard(event).compute()

    assert len(effects) == 1
    opened = payload(effects[0])
    assert opened["target"] == "page"
    assert opened["url"]
    assert opened["content"] is None
