"""Swap typed codes for phrase text, and keep unfinished commands from being recorded."""

from __future__ import annotations

from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Command, Staff
from logger import log

from dot_phrases.catalog import ALL_COMMANDS, COMMAND_LABELS, RX_FIELDS, RX_KEYS, CommandSpec, spec_for_event
from dot_phrases.expansion import combined_length, combined_rx_length, expand_note_field, expand_rx_field, limit_for
from dot_phrases.library import phrase_fits_rx, placeholder_values, record_use, usable_phrases
from dot_phrases.text import CODE_PATTERN, codes_in, fill, placeholder_names, rx_field_name, rx_issue

# An edit that doesn't take re-fires POST_UPDATE with the same text. Remember each attempt for 10
# minutes so it is never retried in a loop.
ATTEMPT_MEMORY_SECONDS = 600


def leftovers_key(command_uuid: str) -> str:
    """Cache key for the [brackets] and {placeholders} a swap left in a command."""
    return f"dot-phrases:leftovers:{command_uuid}"


def _owner_dbid(command: Any) -> int | None:
    # Command lifecycle events carry no actor, so the command's creator decides whose personal
    # phrases apply. In a note shared by two providers, the creator's phrases are used.
    originator_id = getattr(command, "originator_id", None)
    if not originator_id:
        return None
    dbid: int | None = Staff.objects.filter(user_id=originator_id).values_list("dbid", flat=True).first()
    return dbid


def _event_text_fields(spec: CommandSpec, fields: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(event field, SDK field, text) for each of the command's text fields that holds a code."""
    found = []
    for event_field, sdk_field in spec.fields:
        text = fields.get(event_field)
        if isinstance(text, str) and CODE_PATTERN.search(text):
            found.append((event_field, sdk_field, text))
    return found


class ExpandPhrases(BaseHandler):
    """After a command saves, replace dot codes in its text fields with the phrase text."""

    RESPONDS_TO = [EventType.Name(getattr(EventType, f"{spec.event_prefix}_COMMAND__POST_UPDATE")) for spec in ALL_COMMANDS]

    def compute(self) -> list[Effect]:
        spec = spec_for_event(EventType.Name(self.event.type), "POST_UPDATE")
        if spec is None:
            return []
        fields = self.event.context.get("fields")
        candidates = _event_text_fields(spec, fields) if isinstance(fields, dict) else []
        if not candidates:
            # No code left in the command: forget the last attempt, so typing the same code again
            # later expands instead of looking like an edit that didn't take.
            if isinstance(fields, dict):
                cache = get_cache()
                attempt_key = f"dot-phrases:attempt:{self.event.target.id}"
                if cache.get(attempt_key) is not None:
                    cache.delete(attempt_key)
            return []

        command = (
            Command.objects.filter(id=self.event.target.id)
            .select_related("note__provider", "note__location", "patient")
            .defer("note___body", "note___body_content", "note___body_order", "note__related_data")
            .first()
        )
        if command is None or command.state != "staged":
            # Canvas refuses plugin edits once a command is no longer staged.
            return []
        owner = _owner_dbid(command)
        phrases = usable_phrases(owner)
        if not phrases:
            return []

        is_rx = spec.key in RX_KEYS
        typed = [code for _, _, text in candidates for code in codes_in(text)]
        needed = placeholder_names([phrases[c].text for c in typed if c in phrases])
        values = placeholder_values(command.patient, command.note, owner_dbid=owner, needed=needed)
        updates: dict[str, str] = {}
        used: list[int] = []
        leftovers: list[str] = []
        for event_field, sdk_field, text in candidates:
            if is_rx:
                result = expand_rx_field(text, phrases, event_field, values)
            else:
                result = expand_note_field(text, phrases, values, spec.key)
            if result.text != text:
                updates[sdk_field] = result.text
                used.extend(result.used)
                leftovers.extend(result.leftovers)
        if not updates:
            return []

        cache = get_cache()
        attempt_key = f"dot-phrases:attempt:{self.event.target.id}"
        attempt = repr(sorted(updates.items()))
        if cache.get(attempt_key) == attempt:
            log.info(f"dot_phrases: edit did not take on {spec.label} {sorted(updates)}, not retrying")
            return []
        cache.set(attempt_key, attempt, timeout_seconds=ATTEMPT_MEMORY_SECONDS)

        if leftovers:
            existing = cache.get(leftovers_key(str(self.event.target.id))) or []
            cache.set(leftovers_key(str(self.event.target.id)), list(existing) + leftovers)
        record_use(used)
        log.info(f"dot_phrases: expanded {len(used)} phrase(s) in {spec.label} {sorted(updates)}")
        return [spec.command_class(command_uuid=str(self.event.target.id), **updates).edit()]


class BlockUnfinished(BaseHandler):
    """Keep a command from being recorded while a code or fill-in is left in its text.

    These errors block recording in the Canvas UI only; an SDK commit is not blocked.
    """

    RESPONDS_TO = [
        EventType.Name(getattr(EventType, f"{spec.event_prefix}_COMMAND__POST_VALIDATION"))
        for spec in ALL_COMMANDS
        if spec.validates
    ]

    def compute(self) -> list[Effect]:
        spec = spec_for_event(EventType.Name(self.event.type), "POST_VALIDATION")
        if spec is None:
            return []
        fields = self.event.context.get("fields")
        if not isinstance(fields, dict):
            return []
        is_rx = spec.key in RX_KEYS
        tracked = get_cache().get(leftovers_key(str(self.event.target.id))) or []

        messages: list[str] = []
        phrases: dict[str, Any] | None = None
        values: dict[str, str] = {}
        for event_field, _sdk_field in spec.fields:
            text = fields.get(event_field)
            if not isinstance(text, str) or not text:
                continue
            prefix = f"{RX_FIELDS[event_field][0]}: " if is_rx else ""
            codes = codes_in(text)
            if codes and phrases is None:
                command = (
                    Command.objects.filter(id=self.event.target.id)
                    .select_related("note__provider", "note__location", "patient")
                    .defer("note___body", "note___body_content", "note___body_order", "note__related_data")
                    .first()
                )
                owner = _owner_dbid(command) if command else None
                phrases = usable_phrases(owner) if command else {}
                typed = [c for f, _ in spec.fields if isinstance(fields.get(f), str) for c in codes_in(fields[f])]
                needed = placeholder_names([phrases[c].text for c in typed if c in phrases])
                values = {} if command is None else placeholder_values(command.patient, command.note, owner_dbid=owner, needed=needed)
            for code in codes:
                messages.append(prefix + self._code_message(code, (phrases or {}).get(code), spec, event_field, is_rx, text, phrases or {}, values))
            # Unfilled fill-ins block recording, and for a prescription they block review and send.
            still = [left for left in tracked if left in text]
            brackets = sorted({left for left in still if left.startswith("[")}, key=still.index)
            missing = sorted({left for left in still if left.startswith("{")}, key=still.index)
            if brackets:
                messages.append(prefix + f"Fill in {', '.join(brackets)}.")
            if missing:
                messages.append(prefix + f"The chart has nothing for {', '.join(missing)}. Type it in.")
            stars = text.count("***")
            if stars:
                messages.append(prefix + ("Fill in the blank marked ***." if stars == 1 else f"Fill in the {stars} blanks marked ***."))

        if not messages:
            return []
        effect = CommandValidationErrorEffect()
        for message in messages:
            effect.add_error(message)
        return [effect.apply()]

    @staticmethod
    def _code_message(
        code: str,
        phrase: Any,
        spec: CommandSpec,
        field: str,
        is_rx: bool,
        text: str,
        phrases: dict[str, Any],
        values: dict[str, str],
    ) -> str:
        if phrase is None:
            return f".{code} is not a saved phrase. Fix or remove it."
        if is_rx:
            label, field_max = RX_FIELDS[field]
            name = rx_field_name(label)
            if not phrase_fits_rx(phrase, field):
                return f".{code} isn't set up for the {label}. Type the text instead."
            issue = rx_issue(field_max, fill(phrase.text, values).text)[0]
            if issue:
                return f".{code} can't go in the {name}: {issue}. Type the text instead."
            if combined_rx_length(text, phrases, field, values) > field_max:
                return f"Together, the phrases in the {name} are over {field_max:,} characters. Use fewer, or type the text instead."
            return f"Dot phrase .{code} is still loading. If it doesn't load, retype the code."
        command_label = COMMAND_LABELS.get(spec.key, spec.label)
        if phrase.use_in is not None and spec.key not in phrase.use_in:
            return f".{code} isn't set up for {command_label}."
        limit = limit_for(spec.key)
        if limit is not None:
            filled = len(fill(phrase.text, values).text)
            if filled > limit:
                return f".{code} is too long for {command_label}: {filled:,} characters, and the limit is {limit:,}."
            if combined_length(text, phrases, values, spec.key) > limit:
                return f"Together, the phrases here are over the {limit:,}-character limit for {command_label}. Use fewer, or shorten one."
        # The swap runs after the command saves, so a code that fits can be seen here for a moment.
        return f"Dot phrase .{code} is still loading. If it doesn't load, retype the code."
