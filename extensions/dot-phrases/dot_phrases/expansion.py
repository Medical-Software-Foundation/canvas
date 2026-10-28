"""Swapping dot codes in a command's text for the phrase they stand for."""

from __future__ import annotations

from typing import Any, NamedTuple

from dot_phrases.catalog import FIELD_LIMITS, RX_FIELDS, works_in
from dot_phrases.library import phrase_fits_rx
from dot_phrases.text import CODE_PATTERN, fill, rx_problems


class Expanded(NamedTuple):
    """The result of expanding the codes in one field."""

    text: str
    used: tuple[int, ...]  # phrase dbids that went in
    leftovers: tuple[str, ...]  # [brackets] and {placeholders} the provider still has to fill in


def _allowed_in(phrase: Any, command_key: str) -> bool:
    return works_in(phrase.use_in, command_key)


def expand_note_field(
    text: str,
    phrases: dict[str, Any],
    values: dict[str, str],
    command_key: str,
) -> Expanded:
    """Expand codes in a note command's text field.

    A code stays as typed when the phrase isn't set up for this command, or when the filled text is
    too long for the field. The validation handler then explains why it stayed. Fill-ins expand
    everywhere the phrase is set up for. The review commands, which can't block recording, are
    left out unless the phrase lists them.
    """
    used: list[int] = []
    leftovers: list[str] = []

    def replace(match: Any) -> str:
        lead, code = str(match.group(1)), str(match.group(2)).lower()
        phrase = phrases.get(code)
        if phrase is None or not _allowed_in(phrase, command_key):
            return str(match.group(0))
        filled = fill(phrase.text, values)
        limit = FIELD_LIMITS.get(command_key)
        if limit is not None and len(filled.text) > limit:
            return str(match.group(0))
        used.append(phrase.dbid)
        leftovers.extend(filled.leftovers)
        return lead + filled.text

    expanded = CODE_PATTERN.sub(replace, text)
    field_limit = limit_for(command_key)
    if field_limit is not None and len(expanded) > field_limit:
        # Each phrase fits, but together they don't: leave every code as typed and say so.
        return Expanded(text, (), ())
    return Expanded(expanded, tuple(used), tuple(leftovers))


def limit_for(command_key: str) -> int | None:
    """The character limit on a command's text fields, or None when there isn't one."""
    return FIELD_LIMITS.get(command_key)


def combined_length(text: str, phrases: dict[str, Any], values: dict[str, str], command_key: str) -> int:
    """How long a note field would be with every phrase set up for it expanded, ignoring limits."""

    def replace(match: Any) -> str:
        phrase = phrases.get(str(match.group(2)).lower())
        if phrase is None or not _allowed_in(phrase, command_key):
            return str(match.group(0))
        return str(match.group(1)) + fill(phrase.text, values).text

    return len(CODE_PATTERN.sub(replace, text))


def combined_rx_length(text: str, phrases: dict[str, Any], field: str, values: dict[str, str] | None = None) -> int:
    """How long a Sig or note to pharmacist would be with every phrase checked for it expanded and filled."""

    def replace(match: Any) -> str:
        phrase = phrases.get(str(match.group(2)).lower())
        if phrase is None or not phrase_fits_rx(phrase, field):
            return str(match.group(0))
        return str(match.group(1)) + fill(phrase.text, values or {}).text

    return len(CODE_PATTERN.sub(replace, text))


def expand_rx_field(text: str, phrases: dict[str, Any], field: str, values: dict[str, str] | None = None) -> Expanded:
    """Expand codes in a Sig or note to pharmacist.

    Only phrases checked for this field expand. Placeholders fill in first, and the filled text
    must still fit the Surescripts limits: one line of printable ASCII within the field's length.
    Anything else stays as typed. Fill-ins come in as [brackets] or ***, and the validation
    handler keeps the prescription from being reviewed or sent until they are filled in.
    """
    used: list[int] = []
    leftovers: list[str] = []
    field_max = RX_FIELDS[field][1]

    def replace(match: Any) -> str:
        lead, code = str(match.group(1)), str(match.group(2)).lower()
        phrase = phrases.get(code)
        if phrase is None or not phrase_fits_rx(phrase, field):
            return str(match.group(0))
        filled = fill(phrase.text, values or {})
        if rx_problems(field_max, filled.text):
            return str(match.group(0))
        used.append(phrase.dbid)
        leftovers.extend(filled.leftovers)
        return lead + filled.text

    expanded = CODE_PATTERN.sub(replace, text)
    if len(expanded) > field_max:
        return Expanded(text, (), ())
    return Expanded(expanded, tuple(used), tuple(leftovers))
