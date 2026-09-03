"""Live updates for the review surface.

Observer, with the platform's own change events as the notification source. One
channel carries a bare signal, and every page that hears it refetches through the
ordinary authenticated route.

The emptiness of that signal is the design, not laziness. A broadcast reaches
every client subscribed to the channel regardless of who they are, so putting a
patient name or a total into the message would fan patient data out to every open
modal on the instance. A message carrying nothing cannot leak anything, and it
also leaves exactly one place that computes a total, the read that already did.

Two classes live here because they are two halves of one question, who may listen
and when to speak. Neither needs the counting engine.
"""

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI

from attendance_policy_tracker.canvas.settings_store import NamespaceSettingsStore
from attendance_policy_tracker.canvas.states import (
    BOOKED_STATES,
    CANCELLED_STATES,
    NO_SHOW_STATES,
)
from attendance_policy_tracker.composition import build
from logger import log

# The one channel the review surface listens on, shared by every viewer because
# the surface is a shared worklist rather than one person's view. The platform
# namespaces it by plugin, so this name cannot collide with another plugin's.
CHANNEL = "attendance"

# States worth waking a page for. The two counted outcomes, plus a booking,
# because a reschedule writes a booking rather than a cancellation and that is
# how a late move completes.
NOTIFYING_STATES = frozenset(NO_SHOW_STATES + CANCELLED_STATES + BOOKED_STATES)

STATE_EVENT = "NOTE_STATE_CHANGE_EVENT_CREATED"


def state_matters(context: dict[str, Any]) -> bool:
    """Whether a note state change could move a total.

    Every note save writes a state, so an unfiltered handler would wake every
    open page constantly. Pure, so it tests without an instance.
    """
    return context.get("state") in NOTIFYING_STATES


def label_matters(context: dict[str, Any], clinic_tag: str | None) -> bool:
    """Whether a label change could move a total.

    Only the configured clinic tag decides who a visit counts against. Any other
    label leaves every total exactly where it was. A `clinic_tag` of None means
    the policy could not be read, which errs toward speaking, because a stale
    total is worse than a wasted refetch.
    """
    label = context.get("label")
    if not label:
        return False
    if clinic_tag is None:
        return True
    return f"{label}" == f"{clinic_tag}"


class AttendanceChannel(WebSocketAPI):
    """Decides who may watch the channel."""

    def accept_event(self) -> bool:
        """Answer only for this surface's channel, not for any other."""
        return bool(self.event.context.get("channel_name") == CHANNEL)

    def authenticate(self) -> bool:
        """Any staff member may watch, the same reach the review tab already has.

        The platform sets the logged in user headers from the session and drops
        any copy a client sent, so this cannot be forged. Configuration is not
        reachable through here at all, it stays gated on its own route.
        """
        user = self.websocket.logged_in_user
        if not user:
            return False
        return user.get("type") == "Staff" and bool(user.get("id"))


class AttendanceNotifier(BaseHandler):
    """Turns a change that could move a total into one signal on the channel."""

    RESPONDS_TO = [
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_LABEL_ADDED),
        EventType.Name(EventType.APPOINTMENT_LABEL_REMOVED),
    ]

    def compute(self) -> list[Effect]:
        """Speak once when this change matters, stay silent otherwise."""
        context = dict(self.event.context or {})

        if f"{self.event.name}" == STATE_EVENT:
            speak = state_matters(context)
        else:
            # The tag is read only for a label event, so note traffic never pays
            # for a query it cannot use.
            speak = label_matters(context, self._clinic_tag())

        if not speak:
            return []
        return [Broadcast(channel=CHANNEL, message={"reason": "attendance-changed"}).apply()]

    def _clinic_tag(self) -> str | None:
        """The configured clinic tag, or None when policy cannot be read."""
        try:
            config = build(NamespaceSettingsStore())["config"]
        except Exception:
            log.exception("attendance notifier could not read policy, signalling anyway")
            return None
        return f"{config.clinic_tag}"
