from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from chart_command_search.searchers.constants import (
    COMMAND_ABBREVIATIONS,
    _LABEL_TO_KEYS,
)
from chart_command_search.searchers.types import Result


def resolve_command_query(q: str) -> tuple[str, set[str]]:
    """Return (original query, set of schema_keys matched by abbreviation/label)."""
    q_lower = q.lower()
    matched: set[str] = set()
    if q_lower in COMMAND_ABBREVIATIONS:
        matched |= COMMAND_ABBREVIATIONS[q_lower]
    for label, keys in _LABEL_TO_KEYS.items():
        if q_lower in label:
            matched |= keys
    return q, matched


def parse_multi(value: str) -> set[str]:
    """Split a comma-separated param into a set of non-empty values."""
    return {v.strip() for v in value.split(",") if v.strip()} if value and value != "all" else set()


def detail(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value.strip()}


def make_result(
    *,
    category: str,
    type_label: str,
    summary: str,
    details: list[dict[str, str]],
    state: str = "",
    state_class: str = "",
    permalink: str = "",
    date: str = "",
    source: str = "",
) -> Result:
    return {
        "category": category,
        "type_label": type_label,
        "summary": summary,
        "details": [d for d in details if d.get("value", "").strip()],
        "state": state,
        "state_class": state_class,
        "permalink": permalink,
        "date": date,
        "source": source,
    }


def fmt_date(dt: Any) -> str:
    if dt is None:
        return ""
    if not hasattr(dt, "strftime"):
        return str(dt)
    if not hasattr(dt, "hour"):
        return str(dt.strftime("%b %d, %Y"))
    try:
        from zoneinfo import ZoneInfo

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    except Exception:
        pass
    return dt.isoformat()


def fmt_datetime(dt: Any) -> str:
    return fmt_date(dt)


def staff_name(staff: Any) -> str:
    if staff is None:
        return ""
    first = getattr(staff, "first_name", "") or ""
    last = getattr(staff, "last_name", "") or ""
    return f"{first} {last}".strip()


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def note_type_name(note: Any) -> str:
    ntv = getattr(note, "note_type_version", None)
    if ntv:
        display = str(getattr(ntv, "display", "") or "")
        name = str(getattr(ntv, "name", "") or "")
        return display or name
    return ""


def extract_body_text(body: Any) -> str:
    if not body or not isinstance(body, list):
        return ""
    texts = []
    for item in body:
        if isinstance(item, dict) and item.get("type") == "text":
            value = item.get("value", "")
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
    return " ".join(texts)


def match_snippet(q: str, text: str, max_len: int = 120) -> str:
    if not q or not text:
        return ""
    lower = text.lower()
    idx = lower.find(q.lower())
    if idx < 0:
        return ""
    start = max(0, idx - 40)
    end = min(len(text), idx + len(q) + 80)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet[:max_len]


def build_note_link(patient_id: str, note: Any) -> str:
    dbid = getattr(note, "dbid", None)
    if not dbid:
        return ""
    return f"/patient/{quote(patient_id)}#noteId={dbid}"


def build_command_link(patient_id: str, cmd: Any) -> str:
    note = getattr(cmd, "note", None)
    note_dbid = getattr(note, "dbid", None) if note else None
    anchor_dbid = getattr(cmd, "anchor_object_dbid", None)
    schema_key = getattr(cmd, "schema_key", "") or ""

    if note_dbid and anchor_dbid and schema_key:
        return (
            f"/patient/{quote(patient_id)}"
            f"#noteId={note_dbid}"
            f"&commandType={quote(schema_key)}"
            f"&commandId={anchor_dbid}"
        )

    if not note_dbid:
        return ""
    return f"/patient/{quote(patient_id)}#noteId={note_dbid}"
