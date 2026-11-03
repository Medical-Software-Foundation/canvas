"""Fax number normalization.

Fax numbers on file are free text ("(555) 555-0100", "+1 555.555.0100 ext 2").
Every number goes through here before it is used. Anything that is not a
dialable US number is treated as missing rather than guessed at, so a bad
number turns into a logged skip instead of a misdirected fax.
"""

import re

_EXTENSION = re.compile(r"\s*(?:x|ext\.?|extension)\s*\d+\s*$", re.IGNORECASE)


def ten_digits(raw: str | None) -> str | None:
    """Return the 10-digit US number in ``raw``, or None when there isn't one."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", _EXTENSION.sub("", raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01":
        return None
    return digits


def for_fax_effect(digits: str) -> str:
    """The form ``FaxNoteEffect`` takes: country code plus 10 digits."""
    return f"1{digits}"


def e164(digits: str) -> str:
    """The form Canvas stores sent fax numbers in (``Fax.to_fax_number``)."""
    return f"+1{digits}"


def masked(digits: str) -> str:
    """The number with all but the last four digits hidden, for logs."""
    return f"***-***-{digits[-4:]}"
