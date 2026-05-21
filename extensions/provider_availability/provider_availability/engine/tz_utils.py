"""Timezone utilities for provider availability.

Uses zoneinfo.ZoneInfo for timezone conversions. Schedule times are
interpreted in the provider's timezone, then converted to UTC for Canvas events.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from provider_availability.engine.storage import get_practice_timezone, get_provider_timezone


COMMON_TIMEZONES: list[str] = [
    "US/Eastern",
    "US/Central",
    "US/Mountain",
    "America/Phoenix",
    "US/Pacific",
    "US/Alaska",
    "US/Hawaii",
    "UTC",
]


def practice_tz() -> ZoneInfo:
    """Return the practice timezone as a ZoneInfo object."""
    return ZoneInfo(get_practice_timezone())


def provider_tz(provider_id: str) -> ZoneInfo:
    """Return the timezone for the given provider.

    Checks for a per-provider timezone first, then falls back to the
    practice-level timezone.
    """
    tz_name = get_provider_timezone(provider_id)
    if tz_name:
        return ZoneInfo(tz_name)
    return practice_tz()


def practice_now() -> datetime:
    """Return the current time in the practice timezone."""
    return datetime.now(practice_tz())


def provider_now(provider_id: str) -> datetime:
    """Return the current time in the provider's timezone."""
    return datetime.now(provider_tz(provider_id))


def to_provider_naive(dt_val: datetime, provider_id: str) -> datetime:
    """Convert any datetime to a naive provider-TZ datetime.

    - If aware: convert to provider TZ, then strip tzinfo.
    - If naive: return as-is (assumed already in provider TZ).
    """
    if dt_val.tzinfo is not None:
        return dt_val.astimezone(provider_tz(provider_id)).replace(tzinfo=None)
    return dt_val


def to_utc(dt_aware: datetime) -> datetime:
    """Convert a timezone-aware datetime to UTC."""
    return dt_aware.astimezone(UTC)


def localize_naive(dt_naive: datetime, tz: ZoneInfo | None = None) -> datetime:
    """Attach a timezone to a naive datetime.

    If tz is None, uses the practice timezone.
    """
    if tz is None:
        tz = practice_tz()
    return dt_naive.replace(tzinfo=tz)


def to_practice_naive(dt_val: datetime) -> datetime:
    """Convert any datetime to a naive practice-TZ datetime.

    - If aware: convert to practice TZ, then strip tzinfo.
    - If naive: return as-is (assumed already in practice TZ).
    """
    if dt_val.tzinfo is not None:
        return dt_val.astimezone(practice_tz()).replace(tzinfo=None)
    return dt_val
