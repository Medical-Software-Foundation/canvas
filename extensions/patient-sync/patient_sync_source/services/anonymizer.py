"""Deterministic PHI anonymization.

Every replacement is keyed on HMAC(anonymization_key, source_patient_id) so
that the same source patient + same anonymization key always produces the
same fake values — required for idempotent re-sync and for the source
operator to be able to map a synced patient back to its real counterpart
offline if they need to.

Free-text content inside notes / commands / messages / documents is cleared
rather than fuzzy-anonymized for v1 — pattern-based name redaction misses
mangled or misspelled cases, and the target reconstructs note content from
the re-originated commands anyway. A future v2 NLP-scrubber pass can
revisit this if a use case demands preserving free-text on the target.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, timedelta
from typing import Any


# Small constant pools for deterministic name/address selection. Kept short
# on purpose — these are not meant to look like a population, just to look
# like recognizable, non-real PHI replacements.
_FIRST_NAMES = (
    "Alex", "Avery", "Blake", "Casey", "Drew", "Emery", "Finley", "Gray",
    "Harper", "Indigo", "Jordan", "Kai", "Lane", "Morgan", "Noor", "Oakley",
    "Parker", "Quinn", "Reese", "Sage", "Taylor", "Umi", "Vesper", "Wren",
    "Xenon", "Yael", "Zephyr",
)

_LAST_NAMES = (
    "Adler", "Brand", "Cortez", "Dunne", "Ellison", "Farr", "Gulati", "Hale",
    "Iverson", "Jurado", "Khan", "Lin", "Mariano", "Nakamura", "Okafor",
    "Park", "Quesada", "Ramos", "Sato", "Toro", "Ueno", "Vega", "Walsh",
    "Xu", "Yang", "Zhao",
)

_STREETS = (
    "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Elm Way", "Pine Ct",
    "Spruce Pl", "Willow Rd", "Birch Ter", "Aspen Blvd",
)

_CITIES = (
    "Portland", "Austin", "Denver", "Madison", "Boise", "Burlington",
    "Asheville", "Providence", "Bend", "Ithaca",
)

_STATES = ("OR", "TX", "CO", "WI", "ID", "VT", "NC", "RI", "OR", "NY")

# Field names recognized as free-text PHI to clear when nested inside a
# command/note body. Lowercase compare. Conservative — anything plausibly
# free-text by name gets nuked. Codes, ids, and structured fields are kept.
_FREE_TEXT_FIELD_NAMES = frozenset({
    "background",
    "body",
    "clinical_note",
    "comment",
    "comments",
    "content",
    "description",
    "instructions",
    "narrative",
    "notes",
    "rationale",
    "reason",
    "result",
    "summary",
    "text",
    "today_assessment",
})


class Anonymizer:
    """Deterministic PHI replacer keyed on a per-instance secret."""

    def __init__(self, anonymization_key: str, source_patient_id: str) -> None:
        self._seed = hmac.new(
            anonymization_key.encode(),
            source_patient_id.encode(),
            hashlib.sha256,
        ).digest()

    def _bucket(self, salt: str, modulo: int) -> int:
        """Stable per-(seed, salt) bucket in [0, modulo)."""
        return (
            int.from_bytes(
                hmac.new(self._seed, salt.encode(), hashlib.sha256).digest()[:4],
                "big",
            )
            % modulo
        )

    def _digits(self, salt: str, length: int) -> str:
        """Stable per-(seed, salt) digit string of the given length."""
        h = hmac.new(self._seed, salt.encode(), hashlib.sha256).hexdigest()
        n = int(h[: max(8, length)], 16)
        return str(n)[:length].zfill(length)

    # ---------- Patient-level PHI ----------

    def first_name(self, original: str) -> str:
        return _FIRST_NAMES[self._bucket("first_name", len(_FIRST_NAMES))]

    def last_name(self, original: str) -> str:
        return _LAST_NAMES[self._bucket("last_name", len(_LAST_NAMES))]

    def middle_name(self, original: str) -> str:
        if not original:
            return ""
        return _FIRST_NAMES[self._bucket("middle_name", len(_FIRST_NAMES))]

    def birth_date(self, original: date | None) -> date | None:
        """Shift by a deterministic ±30-day offset. Preserves rough age cohort."""
        if original is None:
            return None
        offset = self._bucket("birth_date", 61) - 30
        return original + timedelta(days=offset)

    def mrn(self, original: str) -> str:
        return self._digits("mrn", 9)

    def ssn(self, original: str) -> str:
        # Per spec: SSN is cleared, not faked.
        return ""

    def phone(self, original: str) -> str:
        # +1 555 0100 line is reserved for fictional use in NANP.
        return f"+15550100{self._digits('phone', 4)}"

    def email(self, original: str) -> str:
        # `example.invalid` is reserved per RFC 6761 — guaranteed unroutable.
        return f"patient-{self._digits('email', 8)}@example.invalid"

    def street(self, original: str) -> str:
        return f"{self._bucket('street_no', 9000) + 100} {_STREETS[self._bucket('street_name', len(_STREETS))]}"

    def city(self, original: str) -> str:
        return _CITIES[self._bucket("city", len(_CITIES))]

    def state(self, original: str) -> str:
        return _STATES[self._bucket("state", len(_STATES))]

    def postal_code(self, original: str) -> str:
        return self._digits("postal", 5)

    # ---------- Structural cleaners ----------

    def clear_free_text_fields(self, value: Any) -> Any:
        """Recursively walk a JSON-like value and clear free-text field values.

        Identification is purely by field name (see ``_FREE_TEXT_FIELD_NAMES``).
        Anything else passes through unchanged — codes, IDs, timestamps,
        structured fields, etc.
        """
        if isinstance(value, dict):
            return {
                k: ("" if k.lower() in _FREE_TEXT_FIELD_NAMES and isinstance(v, str) else self.clear_free_text_fields(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.clear_free_text_fields(item) for item in value]
        return value
