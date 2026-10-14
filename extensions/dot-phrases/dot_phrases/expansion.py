"""Swapping dot codes in a command's text for the phrase they stand for."""

from __future__ import annotations

from typing import Any, NamedTuple

from dot_phrases.catalog import FIELD_LIMITS, RX_FIELDS
from dot_phrases.text import CODE_PATTERN, fill, rx_problems


class Expanded(NamedTuple):
    """The result of expanding the codes in one field."""

    text: str
    used: tuple[int, ...]  # phrase dbids that went in
    leftovers: tuple[str, ...]  # [brackets] and {placeholders} the provider still has to fill in


def _allowed_in(phrase: Any, command_key: str) -> bool:
    use_in = phrase.use_in
    return use_in is None or command_key in use_in


def expand_note_field(
    text: str,
    phrases: dict[str, Any],
    values: dict[str, str],
    command_key: str,
) -> Expanded:
    """Expand codes in a note command's text field.

    A code stays as typed when the phrase isn't set up for this command, or when the filled text is
    too long for the field. The validation handler then explains why it stayed. Fill-ins expand
    everywhere the phrase is set up for, including the review commands, which can't block recording;
    an admin who doesn't want that leaves the review commands out of the phrase's commands.
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

    return Expanded(CODE_PATTERN.sub(replace, text), tuple(used), tuple(leftovers))


def expand_rx_field(text: str, phrases: dict[str, Any], field: str) -> Expanded:
    """Expand codes in a Sig or note to pharmacist.

    Only phrases checked for this field expand, as plain text with no placeholders, within the
    Surescripts length limit and printable ASCII. Anything else stays as typed, and the
    validation handler keeps the prescription from being reviewed until it is fixed.
    """
    used: list[int] = []
    field_max = RX_FIELDS[field][1]

    def replace(match: Any) -> str:
        lead, code = str(match.group(1)), str(match.group(2)).lower()
        phrase = phrases.get(code)
        if phrase is None:
            return str(match.group(0))
        fits = phrase.rx_sig if field == "sig" else phrase.rx_note_to_pharmacist
        if not fits or rx_problems(field_max, phrase.text):
            return str(match.group(0))
        used.append(phrase.dbid)
        return lead + str(phrase.text)

    expanded = CODE_PATTERN.sub(replace, text)
    if len(expanded) > field_max:
        return Expanded(text, (), ())
    return Expanded(expanded, tuple(used), ())
