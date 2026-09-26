"""Protocol executor: when a note is first created (its initial NEW state-change
event), resolve the note's type, load enabled rules for it, lazily gather the
signals those rules reference, evaluate, and emit ONE BatchOriginateCommandEffect
of blank staged commands.

We respond to NOTE_STATE_CHANGE_EVENT_CREATED rather than NOTE_CREATED because
NOTE_CREATED fires before the note body is initialized, so command refs inserted
then are clobbered by the body init (commands get created but never render). The
initial NEW state-change event fires after the body exists. We gate on
state == NEW so the handler fires exactly once at creation and never re-inserts on
later state changes (sign / lock / etc.) — that gate is the idempotency guard.

Never blocks the note on an *expected* error: a malformed rule config (bad JSON
or wrong shape) is caught, logged without PHI, and yields no effects. Unexpected
exceptions are NOT swallowed — they propagate so the platform surfaces them
(Sentry) instead of silently masking a real bug.

Why only builtins are caught: the parse/shape failures this path can realistically
hit raise ValueError (json.JSONDecodeError is a ValueError subclass), KeyError, or
TypeError. We do NOT catch a Django DB base error here because the sandbox import
allowlist does not expose one (only IntegrityError, a write error, is allowlisted),
and the read queries use .first()/.values() which return None rather than raising
DoesNotExist. A genuine DB-layer fault is therefore treated as unexpected and is
allowed to propagate to Sentry."""

import json
import uuid

from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import Note, NoteStates
from logger import log

from note_protocol_automation.lib.catalog import COMMAND_MAP
from note_protocol_automation.lib.matching import matched_command_keys
from note_protocol_automation.lib.signals import gather_signals
from note_protocol_automation.models.rule import Rule


class ProtocolExecutor(BaseHandler):
    """Bulk-insert configured protocol commands when a note is first created."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    # Test seam: inject the event context dict without constructing a full Event.
    # The NOTE_STATE_CHANGE_EVENT_CREATED context is {note_id, patient_id, state}.
    _event_context: dict | None = None

    def _context(self) -> dict:
        """The state-change event context: {note_id, patient_id, state}."""
        if self._event_context is not None:
            return self._event_context
        return self.event.context or {}

    def compute(self) -> list[Effect]:
        """On the note's initial NEW state event, match rules and emit one
        batch-originate effect of blank staged commands."""
        try:
            ctx = self._context()
            # Only act at note creation (the NEW state). Ignoring later state
            # changes (sign / lock / revert / etc.) means commands are inserted
            # exactly once and are never duplicated.
            if ctx.get("state") != NoteStates.NEW:
                return []
            note_id = ctx.get("note_id")
            patient_key = ctx.get("patient_id")
            if not note_id or not patient_key:
                return []

            row = (
                Note.objects.filter(id=note_id)
                .values_list("note_type_version__unique_identifier", flat=True)
                .first()
            )
            if not row:
                return []
            note_type_id = str(row)

            rules = list(
                Rule.objects.filter(note_type_id=note_type_id, enabled=True)
                .order_by("priority")
                .values("priority", "match", "predicates", "commands")
            )
            if not rules:
                return []

            # Parse JSON strings; compute which signal types/LOINCs are referenced.
            parsed: list[dict] = []
            need_cond = need_demo = need_ct = False
            need_loincs: set[str] = set()
            for r in rules:
                preds = json.loads(r["predicates"] or "[]")
                cmds = json.loads(r["commands"] or "[]")
                parsed.append(
                    {
                        "priority": r["priority"],
                        "match": r["match"],
                        "predicates": preds,
                        "commands": cmds,
                    }
                )
                for p in preds:
                    sig = p.get("signal")
                    if sig == "condition":
                        need_cond = True
                    elif sig in ("age", "sex"):
                        need_demo = True
                    elif sig == "care_team_role":
                        need_ct = True
                    elif sig == "lab_value" and isinstance(p.get("value"), dict):
                        loinc = p["value"].get("loinc")
                        if loinc:
                            need_loincs.add(loinc)

            signals = gather_signals(
                patient_key,
                need_conditions=need_cond,
                need_demographics=need_demo,
                need_loincs=frozenset(need_loincs),
                need_care_team=need_ct,
            )
            keys = matched_command_keys(parsed, signals)
            commands = [
                COMMAND_MAP[k](note_uuid=note_id, command_uuid=str(uuid.uuid4()))
                for k in keys
                if k in COMMAND_MAP
            ]
            if not commands:
                return []
            return [BatchOriginateCommandEffect(commands=commands).apply()]
        except (ValueError, KeyError, TypeError):
            # Expected failure modes only: a malformed rule config (bad JSON ->
            # ValueError/json.JSONDecodeError, wrong shape -> KeyError/TypeError).
            # These must never block note creation. The message carries no PHI —
            # only the static notice. Any other (unexpected) exception, including
            # a genuine DB-layer fault, deliberately propagates to reach Sentry.
            log.warning(
                "note_protocol_automation executor skipped a note due to an expected error"
            )
            return []
