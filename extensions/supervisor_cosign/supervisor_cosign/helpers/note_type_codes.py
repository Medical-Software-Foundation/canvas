"""Which note types enter the co-sign flow.

``COSIGN_NOTE_TYPE_CODES`` holds a JSON array or a comma-separated list of
``NoteType.code`` values. Without it every locked note from a supervised provider generates a
co-sign task, including phone notes, letters and chart reviews that nobody
needs to attest to.

Kept free of any Canvas SDK import so it is unit-testable outside the sandbox.
"""

from __future__ import annotations

import json
from typing import Any

SECRET_KEY = "COSIGN_NOTE_TYPE_CODES"

# Dropped during normalization so a value typed ``Office Visit``, ``office-visit``
# or ``office_visit`` still matches the ``officevisit`` code. Matching is exact
# after normalization, never substring: ``visit`` must not match
# ``officevisit``.
_SEPARATORS = ("_", "-", " ", ".")


def normalize_note_type_code(code: Any) -> str:
    """Lowercase ``code`` and drop separators. Never raises."""
    if not code:
        return ""
    text = str(code).strip().lower()
    for sep in _SEPARATORS:
        text = text.replace(sep, "")
    return text


def note_type_code_of(note: Any) -> str:
    """Defensive ``note.note_type_version.code``, falling back to ``name``.

    ``Coding.code`` is ``blank=True``, so a note type can legitimately carry no
    code, and ``name`` is the fallback for that case. ``name`` is operator-editable and ``code`` is not, which is why it is
    only ever the fallback. Returns ``""`` for a missing note, a missing note
    type or an unreadable attribute.
    """
    try:
        version = getattr(note, "note_type_version", None)
    except Exception:
        return ""
    if not version:
        return ""
    try:
        code = str(getattr(version, "code", "") or "").strip()
    except Exception:
        code = ""
    if code:
        return code
    try:
        return str(getattr(version, "name", "") or "").strip()
    except Exception:
        return ""


def _split_codes(raw: str) -> list:
    """The entries of ``raw``, read as a JSON array or a comma-separated string.

    A value starting with ``[`` that parses as a JSON array yields its items. A
    value that does not parse falls back to the comma split with brackets and
    quotes stripped, so ``[office_visit, follow_up]`` and ``['office_visit']`` still
    resolve to their codes.
    """
    text = raw.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        text = text.strip("[]")
    return [part.strip().strip("'\"") for part in text.split(",")]


def parse_cosign_note_type_codes(secrets: Any) -> frozenset[str]:
    """The normalized code set held in ``COSIGN_NOTE_TYPE_CODES``.

    Accepts a JSON array (``["office_visit", "follow_up"]``) or a comma-separated
    string (``office_visit, follow_up``). A missing secrets dict, a ``None`` value,
    an empty string, stray whitespace and doubled commas all yield a clean set.
    """
    if not hasattr(secrets, "get"):
        return frozenset()
    try:
        raw = secrets.get(SECRET_KEY, "") or ""
    except Exception:
        return frozenset()
    codes = set()
    for part in _split_codes(str(raw)):
        normalized = normalize_note_type_code(part)
        if normalized:
            codes.add(normalized)
    return frozenset(codes)


def note_type_eligible(note: Any, secrets: Any) -> bool:
    """True when this note's type may enter the co-sign flow.

    **Unset or blank means every note type is eligible**, which keeps the
    behavior of co-signing everything. Installing
    this version onto a configured instance must change nothing until somebody
    sets the variable.

    A note whose type carries neither a code nor a name is ineligible once a
    list is configured — an unidentifiable note type cannot be shown to be on
    the list — and eligible while the list is unset, which is just the rule
    above.
    """
    wanted = parse_cosign_note_type_codes(secrets)
    if not wanted:
        return True
    return normalize_note_type_code(note_type_code_of(note)) in wanted
