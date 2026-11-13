"""The diagnoses a quickpick or order set is for.

Each pick is either one code ("E11.9" matches E11.9 only) or a code and
everything under it ("N18" matches N18.1 through N18.9). On save the picks are
expanded and every covered code is stored, dot-stripped, so the in-command
panel compares the charted code against the stored list and never waits on
UMLS. Re-saving re-expands, which picks up codes from a yearly ICD-10-CM update.
"""

from typing import Any

from charting_tools.icd10 import normalize_icd10
from charting_tools.umls import MAX_CODES, expand_icd10

MAX_SOURCES = 40


def clean_sources(raw: Any) -> list[dict[str, Any]]:
    """``[{"code", "display", "include_children"}]`` from a request, de-duplicated by code."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "code": code,
                "display": str(entry.get("display") or "").strip(),
                "include_children": bool(entry.get("include_children")),
            }
        )
    return out[:MAX_SOURCES]


def needs_umls(sources: list[dict[str, Any]]) -> bool:
    """Only "and everything under it" picks need the UMLS hierarchy."""
    return any(source.get("include_children") for source in sources)


def expand_sources(sources: list[dict[str, Any]], key: str) -> list[str]:
    """Every code the picks cover, dot-stripped, in pick order.

    Raises ``UmlsError`` when a pick needs the hierarchy and UMLS can't answer.
    """
    codes: list[str] = []
    seen: set[str] = set()
    for source in sources:
        code = str(source.get("code") or "")
        expanded = (
            expand_icd10(code, key) if source.get("include_children") else [normalize_icd10(code)]
        )
        for normal in expanded:
            if normal and normal not in seen:
                seen.add(normal)
                codes.append(normal)
    return codes[:MAX_CODES]


def source_label(source: dict[str, Any]) -> str:
    """How a pick reads in lists: "N18 (all)" or "E11.9"."""
    code = str(source.get("code") or "")
    return f"{code} (all)" if source.get("include_children") else code


def matches(match_codes: list[str] | None, charted: str) -> bool:
    """Whether a charted ICD-10 code is covered by a stored match list."""
    normal = normalize_icd10(charted)
    return bool(normal) and normal in (match_codes or [])
