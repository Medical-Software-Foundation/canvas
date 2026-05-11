"""Note lifecycle handler — cleans up plugin form-state when a Note is deleted.

Without this hook, deleted notes leave orphan rows in the plugin's
AttributeHub namespace. AttributeHub rows are keyed by `(NAMESPACE, note_uuid)`
but the AttributeHub schema isn't FK-linked to the Note table, so Canvas
doesn't cascade-delete plugin storage when a Note is removed.

Subscribes to `NOTE_STATE_CHANGE_EVENT_CREATED` (which fires on every state
transition) and acts only when the new state is `DELETED`. All other states
short-circuit to a no-op.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import AttributeHub
from canvas_sdk.v1.data.note import NoteStateChangeEvent, NoteStates
from logger import log

from nutrition_charting.data.form_state import NAMESPACE


class NutritionChartingNoteLifecycle(BaseHandler):
    """Deletes the plugin's per-note AttributeHub row when a Note transitions
    to the DELETED state."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        state_event_id = self.event.target.id
        try:
            event = NoteStateChangeEvent.objects.select_related("note").get(
                id=state_event_id,
            )
        except NoteStateChangeEvent.DoesNotExist:
            return []

        if event.state != NoteStates.DELETED:
            return []

        note_uuid = str(event.note.id)
        deleted, _ = AttributeHub.objects.filter(
            type=NAMESPACE, id=note_uuid,
        ).delete()
        if deleted:
            log.info(
                f"[NutritionChartingNoteLifecycle] cleaned up {deleted} "
                f"attribute(s) for deleted note {note_uuid}"
            )
        return []
