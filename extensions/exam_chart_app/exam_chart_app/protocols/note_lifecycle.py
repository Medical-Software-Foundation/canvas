"""Note-lifecycle cleanup for Exam tab draft state.

The plugin persists per-note draft form state in AttributeHub keyed by
note_uuid. Canvas doesn't cascade-delete plugin storage when a Note is
removed (AttributeHub isn't FK-linked to Note), so without this hook
deleted-note drafts pile up forever.

Subscribes to `NOTE_STATE_CHANGE_EVENT_CREATED` (fires on every note
state transition) and acts only when the new state is `DELETED`. All
other transitions short-circuit to a no-op so we don't churn on
NEW / LOCKED / UNLOCKED etc.
"""
from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import NoteStateChangeEvent, NoteStates
from logger import log

from exam_chart_app.data.draft_state import clear_draft


class ExamNoteLifecycle(BaseHandler):
    """Deletes the plugin's per-note draft row when a Note is deleted."""

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
        clear_draft(note_uuid)
        log.info(
            f"[ExamNoteLifecycle] cleared draft state for deleted note {note_uuid}"
        )
        return []
