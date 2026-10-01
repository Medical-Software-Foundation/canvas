"""Datetime parsing, mmol/L → mg/dL conversion, relative-time formatting."""

import datetime as dt

from dexcom_cgm_viewer.services.settings import MMOL_TO_MGDL


def parse_iso8601(value: str | None) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp from Dexcom into a tz-aware UTC datetime."""
    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def to_mgdl(value: float | int | None, unit: str | None) -> int | None:
    """Convert a Dexcom egv value to integer mg/dL. Returns None if unparseable."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if (unit or "").lower() == "mmol/l":
        numeric = numeric * MMOL_TO_MGDL
    return int(round(numeric))


def relative_time(target: dt.datetime | None, *, now: dt.datetime | None = None) -> str:
    """Render a 'just now / N minutes ago / N hours ago / N days ago' string."""
    if target is None:
        return ""
    reference = now or dt.datetime.now(dt.timezone.utc)
    if target.tzinfo is None:
        target = target.replace(tzinfo=dt.timezone.utc)
    delta = reference - target
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def age_seconds(target: dt.datetime | None, *, now: dt.datetime | None = None) -> int | None:
    """Return integer seconds between now and target. None when target is None."""
    if target is None:
        return None
    reference = now or dt.datetime.now(dt.timezone.utc)
    if target.tzinfo is None:
        target = target.replace(tzinfo=dt.timezone.utc)
    return max(0, int((reference - target).total_seconds()))
