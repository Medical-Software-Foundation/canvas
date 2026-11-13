"""Helpers for loading and normalizing the expired ICD-10 code list."""

from __future__ import annotations

import importlib.resources
import json


def normalize_icd10_code(code: str | None) -> str:
    """Return an ICD-10 code in a comparison-friendly form: trimmed, uppercase, no periods."""
    return code.strip().replace(".", "").upper() if code else ""


def _load_bundled_codes() -> set[str]:
    """Load the default expired-codes list bundled with the plugin."""
    resource = (
        importlib.resources.files("expired_icd10_alert.data")
        / "expired_icd10_codes.json"
    )
    with resource.open(encoding="utf-8") as f:
        data = json.load(f)
    return {normalize_icd10_code(item["code"]) for item in data["expired_codes"]}


def get_expired_codes(override: str | None) -> set[str]:
    """Return the set of expired ICD-10 codes, normalized.

    If `override` is a non-empty comma-separated string, it replaces the bundled
    list. Otherwise the bundled list is returned.
    """
    if override and override.strip():
        return {
            normalize_icd10_code(part)
            for part in override.split(",")
            if part.strip()
        }
    return _load_bundled_codes()
