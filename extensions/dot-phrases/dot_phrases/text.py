"""Phrase text rules: codes, placeholders, and prescription limits.

Placeholders go in curly brackets:
- Patient: {first_name}, {age}, {subject_pronoun}, and the rest of PATIENT_PLACEHOLDERS,
  filled from the chart of the note the phrase lands in.
- Practice: {after_hours_line} and any other name an admin sets on the Practice settings tab.
- Fill-ins: {pick side: right | left}, {blank duration}, and ***. The provider fills these in. From
  the chart panel they are asked first; typed in a note they come in as [brackets] or ***, and the
  validation handler keeps the command from being recorded until each one is filled in.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

# A code starts a new word: a period, a letter, then up to 63 letters or numbers. Requiring a
# letter first keeps Sig text like ".5 mL" from being read as a code.
CODE_PATTERN = re.compile(r"(^|\s)\.([a-z][a-z0-9]{0,63})(?=\s|$)", re.IGNORECASE)
CODE_RULE = re.compile(r"[a-z][a-z0-9]{0,63}")

# {pick label: a | b}, {blank label}, {name}, or ***
PLACEHOLDER = re.compile(
    r"\{(pick|blank)\s+([a-z_ ]*?)\s*(?::\s*([^}]*))?\}|\{([a-z_]+)\}|\*\*\*",
    re.IGNORECASE,
)
PRACTICE_NAME_RULE = re.compile(r"[a-z][a-z_]{0,63}")

PATIENT_PLACEHOLDERS: dict[str, str] = {
    "first_name": "Patient's first name",
    "preferred_name": "Preferred name, if the chart has one",
    "last_name": "Last name",
    "age": "Age in years",
    "dob": "Date of birth",
    "subject_pronoun": "she / he / they, from the chart's preferred pronouns",
    "object_pronoun": "her / him / them",
    "possessive_pronoun": "her / his / their",
    "today": "Today's date",
    "provider": "The note's provider",
}

# Pronouns come only from the chart's preferred-pronouns field, never from sex at birth. A value
# outside these three stays as typed so the provider fills it in.
_PRONOUN_SETS: dict[str, tuple[str, str, str]] = {
    "she/her": ("she", "her", "her"),
    "he/him": ("he", "him", "his"),
    "they/them": ("they", "them", "their"),
}

MAX_TEXT_LENGTH = 4000


class Filled(NamedTuple):
    """A phrase with its placeholders filled for one patient."""

    text: str
    # What the provider still has to fill in: "[side: right / left]" style brackets for choices
    # and blanks, and "{name}" for placeholders the chart has no value for. *** is found by the
    # validation handler directly, so it is not listed here.
    leftovers: tuple[str, ...]


class FillIn(NamedTuple):
    """A choice or blank the chart panel asks the provider for."""

    kind: str  # "pick" or "blank"
    label: str
    options: tuple[str, ...]


def pronouns(preferred: str | None) -> tuple[str, str, str] | None:
    """Return (subject, object, possessive) for a recognized preferred-pronouns value."""
    if not preferred:
        return None
    return _PRONOUN_SETS.get(re.sub(r"\s+", "", preferred.lower()))


def _bracket(kind: str, label: str, options: str | None) -> str:
    if kind.lower() == "pick":
        opts = [o.strip() for o in (options or "").split("|") if o.strip()]
        return "[" + " / ".join(opts) + "]" if opts else "[" + (label.strip() or "choose") + "]"
    return "[" + (label.strip() or "details") + "]"


def fill_ins(text: str) -> list[FillIn]:
    """The choices and blanks in a phrase, in order, as the chart panel asks for them."""
    out: list[FillIn] = []
    blanks = 0
    for match in PLACEHOLDER.finditer(text):
        kind, label, options, name = match.group(1), match.group(2), match.group(3), match.group(4)
        if kind and kind.lower() == "pick":
            opts = tuple(o.strip() for o in (options or "").split("|") if o.strip())
            out.append(FillIn("pick", (label or "").strip() or "choose", opts))
        elif kind:
            out.append(FillIn("blank", (label or "").strip() or "details", ()))
        elif name is None:  # ***
            blanks += 1
            out.append(FillIn("blank", f"Blank {blanks}", ()))
    return out


def fill(text: str, values: dict[str, str], answers: list[str] | None = None) -> Filled:
    """Fill placeholders with patient and practice values, and fill-ins with the provider's answers.

    A placeholder with no value stays as typed, and an unanswered choice or blank becomes
    [brackets] (or stays ***), so the provider sees what is left instead of a blank or a guess.
    A value at the start of a sentence is capitalized ("She reports...").
    """
    answers = list(answers or [])
    leftovers: list[str] = []
    position = [0]  # which choice or blank comes next (the sandbox doesn't allow nonlocal)

    def replace(match: Any) -> str:
        kind, label, options, name = match.group(1), match.group(2), match.group(3), match.group(4)
        if name is not None:
            value = values.get(name.lower())
            if not value:
                leftovers.append(match.group(0))
                return str(match.group(0))
            before = text[: match.start()].rstrip()
            if not before or before[-1] in ".!?":
                value = value[0].upper() + value[1:]
            return value
        index = position[0]
        position[0] = position[0] + 1
        answer = answers[index].strip() if index < len(answers) and answers[index] else ""
        if answer:
            return answer
        if kind is None:  # ***
            return "***"
        bracket = _bracket(kind, label or "", options)
        leftovers.append(bracket)
        return bracket

    return Filled(PLACEHOLDER.sub(replace, text), tuple(leftovers))


def has_placeholders(text: str) -> bool:
    """Whether the text has any placeholder, choice, blank, or ***."""
    return PLACEHOLDER.search(text) is not None


def unknown_placeholders(text: str, practice_names: set[str]) -> list[str]:
    """Placeholders that are neither patient placeholders nor practice values."""
    unknown: list[str] = []
    for match in PLACEHOLDER.finditer(text):
        name = match.group(4)
        if name is not None and name.lower() not in PATIENT_PLACEHOLDERS and name.lower() not in practice_names:
            unknown.append(match.group(0))
    return unknown


def rx_problems(field_max: int, text: str) -> list[str]:
    """Why text can't go in a prescription field: length, line breaks, characters, placeholders."""
    problems: list[str] = []
    if len(text) > field_max:
        problems.append(f"over {field_max:,} characters")
    if "\n" in text or "\r" in text:
        problems.append("has a line break")
    elif any(not (" " <= char <= "~") for char in text):
        problems.append("has special characters")
    if has_placeholders(text):
        problems.append("has placeholders")
    return problems


def rx_field_name(label: str) -> str:
    """How a prescription field reads mid-sentence: "Sig" stays capitalized, the note to pharmacist doesn't."""
    return label if label == "Sig" else label[0].lower() + label[1:]


def rx_issue(field_max: int, text: str) -> tuple[str, str]:
    """What's wrong with text for a prescription field, in words, and what to do about it.

    Returns ("", "") when the text fits. Names the actual length and the actual special characters.
    """
    parts: list[str] = []
    kinds: list[str] = []
    if len(text) > field_max:
        parts.append(f"it's over {field_max:,} characters ({len(text):,})")
        kinds.append("Shorten it")
    if "\n" in text or "\r" in text:
        parts.append("it has a line break")
        kinds.append("Remove it")
    else:
        bad: list[str] = []
        for char in text:
            if not (" " <= char <= "~") and char not in bad:
                bad.append(char)
        if bad:
            parts.append(f"it has special characters ({', '.join(bad[:5])}{', …' if len(bad) > 5 else ''})")
            kinds.append("Replace them")
    if has_placeholders(text):
        parts.append("it has placeholders")
        kinds.append("Remove them")
    if not parts:
        return "", ""
    return " and ".join(parts), kinds[0] if len(kinds) == 1 else "Fix these"


def rx_message(label: str, field_max: int, text: str) -> str:
    """The editor's message for a phrase that can't go in a prescription field, or "" when it fits."""
    issue, fix = rx_issue(field_max, text)
    if not issue:
        return ""
    name = rx_field_name(label)
    return f"Can't use in the {name}: {issue}. {fix}, or uncheck Use in {name}."


def codes_in(text: str) -> list[str]:
    """The dot codes typed in a piece of text, lowercased, without the leading period."""
    return [match.group(2).lower() for match in CODE_PATTERN.finditer(text or "")]


def is_valid_code(code: str) -> bool:
    """Codes start with a letter, then letters and numbers, lowercase, up to 64 characters."""
    return CODE_RULE.fullmatch(code or "") is not None
