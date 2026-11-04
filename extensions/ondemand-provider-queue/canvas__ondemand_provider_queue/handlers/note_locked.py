"""Completes a queue entry when its visit note is locked."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from logger import log

from canvas__ondemand_provider_queue.handlers.common import notify
from canvas__ondemand_provider_queue.settings import Settings
from canvas__ondemand_provider_queue.storage import StoreUnavailableError, get_store

LOCKED_STATES = frozenset({"LKD", "RLK"})


class CompleteOnNoteLock(BaseHandler):
    """Marks the matching in-progress or paused entry complete."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        """Complete the entry for the locked note, if there is one."""
        settings = Settings.from_secrets(self.secrets)
        context = self.event.context or {}
        note_id = str(context.get("note_id") or "")
        if not settings.enabled or context.get("state") not in LOCKED_STATES or not note_id:
            return []
        try:
            store = get_store(settings)
        except StoreUnavailableError as exc:
            log.error("ondemand_provider_queue: storage unavailable: %s", exc)
            return []
        entry = store.complete_for_note(note_id, context.get("patient_id") or None)
        if entry is None:
            return []
        log.info("ondemand_provider_queue: entry %s completed by note %s", entry.id, note_id)
        return [notify("ENTRY_COMPLETED", entry)]
