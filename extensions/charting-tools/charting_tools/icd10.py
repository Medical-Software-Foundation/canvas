"""ICD-10 code helpers."""

from typing import Any


def normalize_icd10(code: str) -> str:
    """Canvas stores ICD-10 codes upper-case without the decimal point."""
    return (code or "").replace(".", "").strip().upper()


def condition_id_of(value: Any) -> int | None:
    """An Assess's condition as a Condition id, or None when it isn't one.

    An Assess on an existing condition holds the condition's id; one that
    diagnoses a new condition holds that condition's ICD-10 code instead.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None
