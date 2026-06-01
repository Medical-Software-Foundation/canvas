from __future__ import annotations

import json
from typing import Any

from chart_command_search.searchers.types import Result


def serialize_results(results: list[Result]) -> str:
    """Compact serialization of results for the Claude prompt."""
    compact = []
    for i, r in enumerate(results):
        entry: dict[str, Any] = {
            "i": i,
            "cat": r["category"],
            "type": r["type_label"],
            "date": r.get("date", ""),
        }
        if r.get("summary"):
            entry["summary"] = r["summary"]
        if r.get("state"):
            entry["state"] = r["state"]
        if r.get("source"):
            entry["source"] = r["source"]
        if r.get("details"):
            entry["details"] = {
                d["label"]: d["value"] for d in r["details"] if d.get("value")
            }
        compact.append(entry)
    return json.dumps(compact, separators=(",", ":"))
