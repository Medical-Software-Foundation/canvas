"""Pure selection logic for the note picker.

Sort open notes by date-of-service descending and mark the newest as the
default. The newest DOS may be in the near future (a scheduled visit) - that
is expected and correct.
"""

from __future__ import annotations

import arrow


def _label(row: dict) -> str:
    when = arrow.get(row["dos"]).format("M/D/YYYY")
    title = row.get("title") or "Note"
    return f"{when} - {title}"


def choose_notes(rows: list[dict]) -> list[dict]:
    """Return rows sorted by dos desc, each with a display label and a
    `default` flag set True only on the first (newest) item.
    """
    ordered = sorted(rows, key=lambda r: r["dos"], reverse=True)
    out = []
    for i, row in enumerate(ordered):
        out.append({**row, "label": _label(row), "default": i == 0})
    return out
