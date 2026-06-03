"""Helpers for surfacing CPT/CVX billing codes from Canvas command coding fields.

Canvas command data stores structured codes under a coding field's
`extra.coding` list — e.g. an immunize command's ``coding``::

    {"text": "DTaP-... (CPT: 90721)",
     "extra": {"coding": [
         {"code": "90721", "system": "http://www.ama-assn.org/go/cpt", ...},
         {"code": "50",    "system": "http://hl7.org/fhir/sid/cvx", ...},
     ]}}

The display ``text`` sometimes bakes in ``(CPT: nnnnn)`` and never includes the
CVX code, so the structured ``extra.coding`` list is the dependable source.
"""

from __future__ import annotations

import re
from typing import Any

CPT_SYSTEM = "http://www.ama-assn.org/go/cpt"
CVX_SYSTEM = "http://hl7.org/fhir/sid/cvx"

# Trailing "(CPT: 90721)" that the platform bakes into some display texts.
_CPT_SUFFIX_RE = re.compile(r"\s*\(CPT:[^)]*\)\s*$", re.IGNORECASE)


def extract_billing_codes(coding_field: Any) -> list[tuple[str, str]]:
    """Return ``[("CPT", "90721"), ("CVX", "50")]`` from a coding field.

    Reads the field's ``extra.coding`` list. CPT codes are listed first, then
    CVX; duplicates are dropped preserving order. Returns ``[]`` for anything
    without recognizable codes.
    """
    if not isinstance(coding_field, dict):
        return []
    extra = coding_field.get("extra")
    codings = extra.get("coding") if isinstance(extra, dict) else None
    if not isinstance(codings, list):
        return []
    cpt: list[str] = []
    cvx: list[str] = []
    for coding in codings:
        if not isinstance(coding, dict):
            continue
        system = str(coding.get("system") or "").lower()
        code = str(coding.get("code") or "").strip()
        if not code:
            continue
        if "ama-assn.org/go/cpt" in system or system == "cpt":
            if code not in cpt:
                cpt.append(code)
        elif "cvx" in system:
            if code not in cvx:
                cvx.append(code)
    return [("CPT", c) for c in cpt] + [("CVX", c) for c in cvx]


def codes_display(coding_field: Any) -> str:
    """'CPT 90721, CVX 50' for a coding field, or '' when no codes are present."""
    return ", ".join(f"{label} {code}" for label, code in extract_billing_codes(coding_field))


def strip_cpt_suffix(text: Any) -> str:
    """Drop a trailing '(CPT: ...)' the platform appends to some display texts."""
    if not isinstance(text, str):
        return ""
    return _CPT_SUFFIX_RE.sub("", text).strip()


def coded_title(text: Any, coding_field: Any) -> str:
    """Display name with a ' (CPT 90721, CVX 50)' suffix from the structured codes.

    Strips any platform-baked '(CPT: ...)' from ``text`` first so a CPT code is
    never shown twice. Falls back to just the name when no codes are present.
    """
    name = strip_cpt_suffix(text)
    codes = codes_display(coding_field)
    if name and codes:
        return f"{name} ({codes})"
    if codes:
        return f"({codes})"
    return name
