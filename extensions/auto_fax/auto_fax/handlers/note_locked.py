"""Fax a note to the recipients the practice's rules name when the note locks.

Every note state change in the instance reaches this handler, so it bails out
before touching the database unless the plugin is switched on and some rule
fires on this state. After that, the work is a fixed number of queries per
note: the note itself, the recipients (see ``services/recipients.py``), and the
note's earlier faxes.
"""

from datetime import UTC, date, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.fax import FaxNoteEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Note, NoteActionEvent
from logger import log

from auto_fax.services.config import (
    MODE_DRY_RUN,
    MODE_OFF,
    STATE_RELOCKED,
    TRIGGER_STATES,
    load_config,
)
from auto_fax.services.fax_number import e164, for_fax_effect, masked
from auto_fax.services.recipients import Recipient, resolve_recipients

# Every fax a plugin sends is recorded with Canvas Bot as its originator. The id
# is the same on every instance (see the SDK's "Faxes sent by a plugin" docs).
CANVAS_BOT_STAFF_ID = "5eede137ecfe4124b8b773040e33be14"


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

        recipients = resolve_recipients(str(note.patient.id), rules, self._today(note))
        sendable = self._sendable(recipients, note_id)
        if not sendable:
            return []

        # On a first lock or a signature, skip numbers this note was already
        # faxed to (and not failed), so a second rule or a replayed lock/sign
        # event can't double-send. A relock is an amended note, so it always
        # goes again (a replayed relock event therefore re-sends too).
        if state != STATE_RELOCKED:
            already = self._already_faxed(str(note.id))
            sendable = [
                r
                for r in sendable
                if e164(self._destination(r, config.test_fax_digits)) not in already
            ]

        effects: list[Effect] = []
        for recipient in sendable:
            digits = self._destination(recipient, config.test_fax_digits)
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
    def _today(note: Note) -> date:
        """Today in the note provider's last known time zone, or UTC without one.

        Facility addresses end on a calendar date, so "today" must be the
        practice's date, not the server's UTC date (which runs a day ahead
        every US evening).
        """
        tz = note.provider.last_known_timezone if note.provider else None
        return datetime.now(tz or UTC).date()

    @staticmethod
    def _sendable(recipients: list[Recipient], note_id: str) -> list[Recipient]:
        """Recipients with a fax number, one per number. Logs the rest."""
        seen: set[str] = set()
        sendable: list[Recipient] = []
        for recipient in recipients:
            if recipient.problem or not recipient.fax_digits:
                log.warning(
                    f"[auto_fax] note {note_id} rule {recipient.rule.name!r}: skipped "
                    f"{recipient.kind}: {recipient.problem}"
                )
                continue
            if recipient.fax_digits in seen:
                continue
            seen.add(recipient.fax_digits)
            sendable.append(recipient)
        return sendable

    @staticmethod
    def _destination(recipient: Recipient, test_digits: str | None) -> str:
        return test_digits or recipient.fax_digits or ""

    @staticmethod
    def _already_faxed(note_id: str) -> set[str]:
        """E.164 numbers this note was faxed to by a plugin, excluding failed faxes."""
        numbers = (
            NoteActionEvent.objects.filter(
                note__id=note_id,
                event_type="FAXED",
                originator__staff__id=CANVAS_BOT_STAFF_ID,
            )
            .exclude(delivered_by_fax=False)
            .values_list("fax__to_fax_number", flat=True)
        )
        return {number for number in numbers if number}

    @staticmethod
    def _fax_effect(
        note_id: str, recipient: Recipient, digits: str, location_id: str | None
    ) -> Effect:
        cover = recipient.rule.cover_sheet
        if cover is not None and location_id is None:
            log.warning(
                f"[auto_fax] note {note_id} has no practice location; sending rule "
                f"{recipient.rule.name!r} without its coversheet"
            )
            cover = None
        if cover is None:
            return FaxNoteEffect(
                note_id=note_id,
                recipient_name=recipient.name,
                recipient_fax_number=for_fax_effect(digits),
            ).apply()
        return FaxNoteEffect(
            note_id=note_id,
            recipient_name=recipient.name,
            recipient_fax_number=for_fax_effect(digits),
            include_coversheet=True,
            subject=cover.subject,
            comment=cover.comment,
            location_id=location_id,
        ).apply()
