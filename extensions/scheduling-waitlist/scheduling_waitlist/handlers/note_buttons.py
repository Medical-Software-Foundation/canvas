"""Redraw a note's buttons when its state changes.

An ActionButton decides whether to appear at the moment the note renders. Marking
no-show changes the note's state but does not redraw its header, so "Add to
waitlist" stayed absent until the page was reloaded -- which is exactly the moment
a scheduler wants it, standing in front of a slot that has just gone to waste.

**Subscribed to the note state change, not to ``APPOINTMENT_NO_SHOWED``.** Marking
no-show in the UI does not emit the appointment event at all: on a test instance,
a UI no-show moved the note to ``NSW`` while ``SlotFreedHandler`` -- which does
subscribe to ``APPOINTMENT_NO_SHOWED`` -- never ran. The state change is the only
signal that arrives, which is the same asymmetry ``handlers/appointment_button.py``
already documents from the other direction.

Companion to ``services/chart_buttons.py``: that redraws buttons after a *waitlist*
write, this redraws them after a *note* change. Both exist because nothing in the
platform redraws an action button on its own.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadNoteActionButtonsEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Appointment
from canvas_sdk.v1.data.note import Note, NoteStateChangeEvent
from logger import log

from scheduling_waitlist.services.event_payload import resolve_note_state_change_id


class NoteButtonsRefreshHandler(BaseHandler):
    """Asks a note to redraw its buttons after its state moves."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)  # type: ignore[attr-defined]

    def compute(self) -> list[Effect]:
        """Redraw the buttons on the note whose state just changed."""
        note = self._note()
        if note is None:
            return []

        # Only an appointment note can carry the button, so a progress note being
        # signed is none of this handler's business. One indexed existence check
        # is the price of not emitting an effect for every note in the instance.
        note_dbid = getattr(note, "dbid", None)
        if note_dbid is None or not Appointment.objects.filter(
            note__dbid=note_dbid, entered_in_error__isnull=True
        ).exists():
            return []

        note_id = getattr(note, "id", None)
        if not note_id:
            return []

        return [ReloadNoteActionButtonsEffect(id=note_id).apply()]

    def _note(self) -> Any | None:
        """The note behind this event.

        The identifier may name either the state-change row or the note itself --
        nothing documents which, and the payload shape is not something to guess
        at, so both are tried and the one that resolves wins. The state-change row
        is tried first because that is what a ``..._EVENT_CREATED`` event is about.

        Logged when neither resolves, because a silent return here looks exactly
        like a button that is merely slow.
        """
        raw = resolve_note_state_change_id(self.event)
        if not raw:
            log.warning(
                "scheduling_waitlist: a note state change carried no identifier, so "
                "no note buttons were redrawn"
            )
            return None

        change = (
            NoteStateChangeEvent.objects.filter(id=raw).select_related("note").first()
        )
        if change is not None:
            return getattr(change, "note", None)

        note = Note.objects.filter(id=raw).first()
        if note is None:
            log.warning(
                f"scheduling_waitlist: note state change {raw} matched neither a "
                "state-change record nor a note; no buttons were redrawn"
            )
        return note

    # Deliberately no filter on *which* state was entered.
    #
    # The button's answer changes both on the way in to cancelled/no-showed and on
    # the way back out -- Reverted, Restored, Undeleted, and whatever the platform
    # adds next. Enumerating the second half is the kind of list that goes stale
    # without anything failing, and the two mistakes are not symmetric: an extra
    # redraw costs an idempotent re-render, while a missing one leaves a button
    # that lies until the page is reloaded. So every state change on an
    # appointment note redraws.
