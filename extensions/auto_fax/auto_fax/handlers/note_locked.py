"""Fax a note to the recipients the practice's rules name when the note locks.

Every note state change in the instance reaches this handler, so it bails out
before touching the database unless the plugin is switched on and some rule
fires on this state. After that, the work is a fixed number of queries per
note: the note itself, the recipients (see ``services/recipients.py``), and the
note's earlier faxes.
"""

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.fax import FaxNoteEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Note, NoteActionEvent, NoteStateChangeEvent
from logger import log

from auto_fax.services.config import (
    MODE_DRY_RUN,
    MODE_OFF,
    STATE_LOCKED,
    STATE_RELOCKED,
    STATE_SIGNED,
    TRIGGER_STATES,
    load_config,
)
from auto_fax.services.delivery import (
    already_faxed,
    cover_kwargs,
    destination,
    sendable,
    skip_already_faxed,
    today_for,
)
from auto_fax.services.fax_number import for_fax_effect, masked
from auto_fax.services.recipients import Recipient, resolve_recipients


class AutoFaxOnNoteLock(BaseHandler):
    """On note lock (or sign / relock, per rule), fax the note per the configured rules."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        """Return one FaxNoteEffect per recipient, or nothing."""
        context = self.event.context or {}
        note_id = context.get("note_id")
        state = context.get("state")
        if not note_id or state not in TRIGGER_STATES:
            return []

        config = load_config(self.secrets)
        if config.mode == MODE_OFF:
            return []
        rules = [rule for rule in config.rules if state in rule.trigger_states]
        if not rules:
            return []

        note = (
            Note.objects.select_related(
                "note_type_version", "patient", "location", "provider"
            )
            .filter(id=note_id)
            .first()
        )
        if note is None or note.patient is None:
            log.info(f"[auto_fax] note {note_id}: no note or no patient, skipping")
            return []

        note_type_code = note.note_type_version.code if note.note_type_version else None
        location_id = str(note.location.id) if note.location else None
        rules = [rule for rule in rules if rule.matches(note_type_code, location_id)]
        if not rules:
            return []

        recipients = resolve_recipients(
            str(note.patient.id), rules, today_for(note.provider)
        )
        to_send = sendable(recipients, f"note {note_id}")
        if not to_send:
            return []

        # On a first lock or a signature, skip numbers the locked note was
        # already faxed to (and not failed), so a second rule or a replayed
        # lock/sign event can't double-send. Only faxes from the note's first
        # lock or signature on count: a **Fax orders** fax of the unsigned
        # note must not stop the finished note from going out. A relock is an
        # amended note, so it always goes again (a replayed relock event
        # therefore re-sends too).
        if state != STATE_RELOCKED:
            already = already_faxed(self._faxes_since_first_lock(note_id))
            to_send = skip_already_faxed(to_send, config.test_fax_digits, already)

        effects: list[Effect] = []
        for recipient in to_send:
            digits = destination(recipient, config.test_fax_digits)
            label = (
                f"note {note_id} rule {recipient.rule.name!r} -> {recipient.kind} "
                f"at {masked(digits)}"
                + (" (test number)" if config.test_fax_digits else "")
            )
            if config.mode == MODE_DRY_RUN:
                log.info(f"[auto_fax] dry run, would fax {label}")
                continue
            effects.append(
                self._fax_effect(str(note.id), recipient, digits, location_id)
            )
            log.info(f"[auto_fax] faxing {label}")
        return effects

    @staticmethod
    def _faxes_since_first_lock(note_id: str) -> Any:
        """The note's action events from its first lock or signature on.

        Without a recorded lock (not expected, since this runs on one), every
        fax of the note counts, which errs toward not sending twice.
        """
        events = NoteActionEvent.objects.filter(note__id=note_id)
        first_lock = (
            NoteStateChangeEvent.objects.filter(
                note__id=note_id, state__in=[STATE_LOCKED, STATE_SIGNED]
            )
            .order_by("created")
            .values_list("created", flat=True)
            .first()
        )
        return events.filter(created__gte=first_lock) if first_lock else events

    @staticmethod
    def _fax_effect(
        note_id: str, recipient: Recipient, digits: str, location_id: str | None
    ) -> Effect:
        return FaxNoteEffect(
            note_id=note_id,
            recipient_name=recipient.name,
            recipient_fax_number=for_fax_effect(digits),
            **cover_kwargs(recipient.rule, location_id, f"note {note_id}"),
        ).apply()
