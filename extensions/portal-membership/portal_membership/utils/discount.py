"""Discount code parsing, lookup, and application.

Pure functions over the ``DISCOUNT_CODES`` secret — JSON array of objects::

    [
        {"code": "WELCOME10", "type": "percent", "value": 10, "months": 3},
        {"code": "SAVE20", "type": "fixed", "value": 2000, "months": 1,
         "expires_at": "2026-12-31"}
    ]

Fields:
  code        — patient-entered string; matched case-insensitively
  type        — "percent" or "fixed"
  value       — percent (0-100) or fixed cents off
  months      — total billing cycles the discount applies to, counting the
                upfront signup charge as cycle 1
  expires_at  — optional ISO-8601 date; codes are rejected on/after this date

Discount state on the membership record::

    discount_code             str   — the canonical code (uppercased)
    discount_type             str   — "percent" | "fixed"
    discount_value            int   — original value (percent or cents)
    discount_cycles_remaining int   — billing cycles still to be discounted
                                      (cycle length follows the plan's cadence)
"""
import json
from datetime import date
from typing import Any


def parse_codes(raw: str | None) -> list[dict[str, Any]]:
    """Parse the ``DISCOUNT_CODES`` secret JSON. Returns [] on empty/invalid input."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [c for c in parsed if isinstance(c, dict) and c.get("code")]


def find_code(secrets: dict[str, Any], code: str) -> dict[str, Any] | None:
    """Return the matching discount code definition, or None if missing/expired/invalid.

    Matching is case-insensitive. Codes with an ``expires_at`` that is today
    or earlier are treated as not-found.
    """
    if not code:
        return None
    wanted = code.strip().upper()
    for entry in parse_codes(secrets.get("DISCOUNT_CODES")):
        if str(entry.get("code", "")).strip().upper() != wanted:
            continue
        if not _validate_shape(entry):
            return None
        if _is_expired(entry):
            return None
        return entry
    return None


def apply_discount(
    amount_cents: int,
    discount_type: str | None,
    discount_value: int | None,
) -> int:
    """Return the charge amount after applying the discount. Floored at 0."""
    if not discount_type or discount_value is None:
        return amount_cents
    if discount_type == "percent":
        pct = max(0, min(100, int(discount_value)))
        reduction = (amount_cents * pct) // 100
        return max(0, amount_cents - reduction)
    if discount_type == "fixed":
        return max(0, amount_cents - int(discount_value))
    return amount_cents


def build_record_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert a validated code entry into the fields persisted on a membership record.

    The DISCOUNT_CODES secret keeps the practice-facing key ``months`` for
    backwards compatibility, but it really means billing cycles — the cycle
    length is determined by the plan's cadence.
    """
    return {
        "discount_code": str(entry["code"]).strip().upper(),
        "discount_type": entry["type"],
        "discount_value": int(entry["value"]),
        "discount_cycles_remaining": int(entry["months"]),
    }


def describe(record: dict[str, Any]) -> dict[str, Any] | None:
    """Public-facing summary of the discount on a membership record, or None if absent."""
    code = record.get("discount_code")
    if not code:
        return None
    return {
        "code": code,
        "type": record.get("discount_type"),
        "value": record.get("discount_value"),
        "cycles_remaining": record.get("discount_cycles_remaining", 0),
    }


def _validate_shape(entry: dict[str, Any]) -> bool:
    if entry.get("type") not in ("percent", "fixed"):
        return False
    try:
        value = int(entry["value"])
        months = int(entry["months"])
    except (KeyError, TypeError, ValueError):
        return False
    if value < 0 or months < 1:
        return False
    if entry["type"] == "percent" and value > 100:
        return False
    return True


def _is_expired(entry: dict[str, Any]) -> bool:
    raw = entry.get("expires_at")
    if not raw:
        return False
    try:
        return date.fromisoformat(str(raw)) <= date.today()
    except ValueError:
        return False
