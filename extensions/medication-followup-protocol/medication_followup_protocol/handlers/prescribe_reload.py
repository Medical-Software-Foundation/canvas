"""Reloads a note's action buttons after a prescribe command commits.

An ordinary action button never recomputes on its own. The note's own plugin context asks
for its button set once, on mount, and after that only reacts to a pushed reload rather
than polling, so without this handler EnrollmentButton's header control would stay exactly
as it was when the note first mounted, even once a matching prescription is committed.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadNoteActionButtonsEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Command


class PrescribeCommandReload(BaseHandler):
    """Push a header reload the moment a prescribe command commits on a note."""

    RESPONDS_TO = EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        """Reload the committed command's own note, so EnrollmentButton.visible() recomputes.

        The event's own target is the committed command's database id, resolved here
        rather than assumed, since a command with no note attached, if the platform ever
        hands one over, has nothing to reload and is skipped rather than raised on.
        ReloadNoteActionButtonsEffect is keyed by the note's own external id, command.note.id,
        a different value from the note_id a SHOW_*_BUTTON context carries, which is the
        note's database id instead, so the two are never interchanged here.
        """
        command = Command.objects.filter(id=self.event.target.id).first()
        if command is None or not command.note:
            return []
        return [ReloadNoteActionButtonsEffect(id=str(command.note.id)).apply()]
