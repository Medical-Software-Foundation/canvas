"""Claims tab data builder — a sortable, filterable claim list plus CSV export.

One query per request. Every column comes from a forward FK or a one-to-one
relation (note, note patient, the patient's business line, current queue,
current coverage, claim patient snapshot, claim provider snapshot), so the
``.values()`` projection never fans out and needs no ``distinct``. Balances
come from the two stored balance fields on Claim (kept in sync by Canvas), not
from aggregating postings, so the list stays one cheap read.

Sorting is server-side so the sort applies to the whole filtered set, not just
the rows the browser received. Only keys in ``SORT_FIELDS`` are accepted; the
client never passes an ORM path.

The business-line filter (PLUGIN-223) is off unless the plugin variable
``CLAIMS_BUSINESS_LINE_FILTER`` is ``true``. When off, a ``business_line``
query parameter is ignored and no business lines are listed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import arrow
from canvas_sdk.v1.data.business_line import BusinessLine
from canvas_sdk.v1.data.claim import Claim, ClaimQueue
from canvas_sdk.v1.data.staff import Staff
from django.db.models import F

from billing_dashboard.data.claim_queue import ClaimQueueState

# Public sort key -> ORM path. The only values a client can influence.
SORT_FIELDS: dict[str, str] = {
    "date_of_service": "note__datetime_of_service",
    "patient": "patient__last_name",
    "payer": "current_coverage__payer_name",
    "queue": "current_queue__queue_sort_ordering",
    "business_line": "note__patient__business_line__name",
    "provider": "provider__provider_last_name",
    "patient_balance": "patient_balance",
    "coverage_balance": "aggregate_coverage_balance",
    "balance": "total_balance",
}
DEFAULT_SORT = "date_of_service"
DEFAULT_DIRECTION = "desc"

WINDOW_DAYS = (30, 90, 365)
DEFAULT_WINDOW_DAYS = 90

# Row caps. JSON feeds an on-screen table; CSV is the export. One extra row is
# fetched so the response can say "truncated" instead of silently cutting off.
MAX_JSON_ROWS = 500
MAX_CSV_ROWS = 5000

BUSINESS_LINE_SETTING = "CLAIMS_BUSINESS_LINE_FILTER"

_VALUE_FIELDS = (
    "id",
    "dbid",
    "note__datetime_of_service",
    "patient__first_name",
    "patient__last_name",
    "current_coverage__payer_name",
    "current_queue__name",
    "current_queue__display_name",
    "note__patient__business_line__name",
    "provider__provider_first_name",
    "provider__provider_last_name",
    "patient_balance",
    "aggregate_coverage_balance",
    "total_balance",
)

CSV_COLUMNS: tuple[tuple[str, str], ...] = (
    ("claim_number", "Claim #"),
    ("date_of_service", "Date of service"),
    ("patient", "Patient"),
    ("provider", "Provider"),
    ("payer", "Payer"),
    ("queue", "Queue"),
    ("business_line", "Business line"),
    ("patient_balance", "Patient balance"),
    ("coverage_balance", "Coverage balance"),
    ("balance", "Total balance"),
)


class ClaimsQueryError(ValueError):
    """A query parameter failed validation. Message is safe to show the user."""


@dataclass(frozen=True)
class ClaimsQuery:
    sort: str = DEFAULT_SORT
    direction: str = DEFAULT_DIRECTION
    window_days: int = DEFAULT_WINDOW_DAYS
    queue: str | None = None
    business_line: str | None = None


def business_line_filter_enabled(secrets: Any) -> bool:
    """True only when the plugin variable is explicitly ``true`` (fail closed)."""
    if not hasattr(secrets, "get"):
        return False
    return str(secrets.get(BUSINESS_LINE_SETTING) or "").strip().lower() == "true"


def parse_query(params: Any, business_line_enabled: bool) -> ClaimsQuery:
    """Validate request query params into a ClaimsQuery.

    Raises ClaimsQueryError on any value outside the allowed set. The queue
    name is checked against ClaimQueue later (in ``build_claims``) because it
    needs a DB read; everything else is checked here.
    """
    sort = (params.get("sort") or DEFAULT_SORT).strip()
    if sort not in SORT_FIELDS:
        raise ClaimsQueryError(f"Unknown sort '{sort}'.")
    if sort == "business_line" and not business_line_enabled:
        raise ClaimsQueryError("Sorting by business line is not enabled.")

    direction = (params.get("dir") or DEFAULT_DIRECTION).strip().lower()
    if direction not in ("asc", "desc"):
        raise ClaimsQueryError("dir must be 'asc' or 'desc'.")

    raw_window = (params.get("window") or str(DEFAULT_WINDOW_DAYS)).strip()
    try:
        window_days = int(raw_window)
    except ValueError:
        raise ClaimsQueryError("window must be a number of days.") from None
    if window_days not in WINDOW_DAYS:
        raise ClaimsQueryError(
            f"window must be one of {', '.join(map(str, WINDOW_DAYS))}."
        )

    queue = (params.get("queue") or "").strip() or None

    business_line = None
    if business_line_enabled:
        raw_bl = (params.get("business_line") or "").strip()
        if raw_bl:
            try:
                business_line = str(uuid.UUID(raw_bl))
            except ValueError:
                raise ClaimsQueryError(
                    "business_line must be a business line id."
                ) from None

    return ClaimsQuery(
        sort=sort,
        direction=direction,
        window_days=window_days,
        queue=queue,
        business_line=business_line,
    )


def list_queues() -> list[dict[str, str]]:
    """All claim queues, built-in and custom, in revenue-board order."""
    return [
        {"name": q["name"], "display_name": q["display_name"] or q["name"]}
        for q in ClaimQueue.objects.order_by("queue_sort_ordering", "name").values(
            "name", "display_name"
        )
    ]


def list_business_lines() -> list[dict[str, str]]:
    """Active business lines for the filter dropdown."""
    return [
        {"id": str(b["id"]), "name": b["name"]}
        for b in BusinessLine.objects.filter(active=True)
        .order_by("name")
        .values("id", "name")
    ]


def _full_name(first: str | None, last: str | None) -> str:
    return " ".join(p for p in (first, last) if p).strip()


def _money(value: Decimal | None) -> float:
    return float(value or 0)


def staff_timezone(staff_id: str | None) -> str:
    """Time zone name for date display: the viewing staff member's last known
    time zone, or "UTC" when there is none.

    Dates of service are stored in UTC; formatting them in UTC would show an
    evening visit in a US time zone on the next day.
    """
    if not staff_id:
        return "UTC"
    tz = (
        Staff.objects.filter(id=staff_id)
        .values_list("last_known_timezone", flat=True)
        .first()
    )
    if not tz:
        return "UTC"
    name = str(tz)
    try:
        arrow.now(name)
    except ValueError:  # arrow's ParserError: unknown or legacy zone name
        return "UTC"
    return name


def _row(r: dict[str, Any], tz: str) -> dict[str, Any]:
    dos = r["note__datetime_of_service"]
    return {
        "id": str(r["id"]),
        "claim_number": r["dbid"],
        "date_of_service": arrow.get(dos).to(tz).format("YYYY-MM-DD") if dos else "",
        "patient": _full_name(r["patient__first_name"], r["patient__last_name"]),
        "provider": _full_name(
            r["provider__provider_first_name"], r["provider__provider_last_name"]
        ),
        "payer": r["current_coverage__payer_name"] or "",
        "queue": r["current_queue__display_name"] or r["current_queue__name"] or "",
        "business_line": r["note__patient__business_line__name"] or "",
        "patient_balance": _money(r["patient_balance"]),
        "coverage_balance": _money(r["aggregate_coverage_balance"]),
        "balance": _money(r["total_balance"]),
    }


def fetch_claim_rows(
    query: ClaimsQuery, limit: int, now: arrow.Arrow | None = None, tz: str = "UTC"
) -> tuple[list[dict[str, Any]], bool]:
    """Run the single claim-list query. Returns (rows, truncated).

    Raises ClaimsQueryError if ``query.queue`` names no existing claim queue.
    """
    now = now if now is not None else arrow.utcnow()
    start = now.shift(days=-query.window_days)

    qs = Claim.objects.filter(
        note__datetime_of_service__gte=start.datetime,
        note__datetime_of_service__lte=now.datetime,
    )
    if query.queue:
        if not ClaimQueue.objects.filter(name=query.queue).exists():
            raise ClaimsQueryError(f"Unknown claim queue '{query.queue}'.")
        qs = qs.filter(current_queue__name=query.queue)
    else:
        # Trashed claims are noise unless the user explicitly picks Trash.
        qs = qs.exclude(current_queue__queue_sort_ordering=ClaimQueueState.TRASH)
    if query.business_line:
        qs = qs.filter(note__patient__business_line__id=query.business_line)

    order_path = SORT_FIELDS[query.sort]
    sort_expr = (
        F(order_path).desc(nulls_last=True)
        if query.direction == "desc"
        else F(order_path).asc(nulls_last=True)
    )
    # dbid tie-breaker keeps the order stable between the table and the CSV.
    tie_breaker = "-dbid" if query.direction == "desc" else "dbid"

    raw = list(
        qs.annotate(
            total_balance=F("patient_balance") + F("aggregate_coverage_balance")
        )
        .order_by(sort_expr, tie_breaker)
        .values(*_VALUE_FIELDS)[: limit + 1]
    )
    truncated = len(raw) > limit
    return [_row(r, tz) for r in raw[:limit]], truncated


def build_claims(
    query: ClaimsQuery,
    business_line_enabled: bool,
    now: arrow.Arrow | None = None,
    tz: str = "UTC",
) -> dict[str, Any]:
    """JSON payload for the Claims tab. Dates are shown in time zone ``tz``."""
    rows, truncated = fetch_claim_rows(query, MAX_JSON_ROWS, now, tz)
    return {
        "claims": rows,
        "truncated": truncated,
        "row_limit": MAX_JSON_ROWS,
        "query": {
            "sort": query.sort,
            "dir": query.direction,
            "window": query.window_days,
            "queue": query.queue or "",
            "business_line": query.business_line or "",
        },
        "filters": {
            "windows": list(WINDOW_DAYS),
            "queues": list_queues(),
            "business_line_enabled": business_line_enabled,
            "business_lines": list_business_lines() if business_line_enabled else [],
        },
    }


# --- CSV -------------------------------------------------------------------

# A spreadsheet treats a cell starting with any of these as a formula
# (OWASP "CSV injection"). Patient names, payer names and queue names are
# user-entered text, so every string cell is checked.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "|")


def sanitize_cell(value: Any) -> str:
    """Render one CSV cell, neutralizing formula injection.

    Numbers (int/float/Decimal, not bool) are written as-is so negative
    balances stay numeric. Any string whose first character could start a
    formula is prefixed with a single quote. The result is always quoted,
    with embedded quotes doubled (RFC 4180).
    """
    if value is None:
        text = ""
    elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        text = str(value)
    else:
        text = str(value)
        if text.startswith(_FORMULA_PREFIXES):
            text = "'" + text
    return '"' + text.replace('"', '""') + '"'


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    """Serialize claim rows to CSV text (CRLF line endings, header first).

    Written by hand because the plugin sandbox does not allow the ``csv`` or
    ``io`` modules.
    """
    lines = [",".join(sanitize_cell(label) for _, label in CSV_COLUMNS)]
    for row in rows:
        lines.append(",".join(sanitize_cell(row.get(key)) for key, _ in CSV_COLUMNS))
    return "\r\n".join(lines) + "\r\n"


def build_claims_csv(
    query: ClaimsQuery, now: arrow.Arrow | None = None, tz: str = "UTC"
) -> tuple[str, bool]:
    """CSV text for the export, plus whether it hit the row cap."""
    rows, truncated = fetch_claim_rows(query, MAX_CSV_ROWS, now, tz)
    return rows_to_csv(rows), truncated
