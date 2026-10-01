"""Datetime parsing, mg/dL conversion, and relative-time formatting."""

from __future__ import annotations

import datetime as dt

from dexcom_cgm_viewer.services.time_utils import (
    age_seconds,
    parse_iso8601,
    relative_time,
    to_mgdl,
)


def test_parse_iso8601_handles_zulu_and_naive() -> None:
    parsed = parse_iso8601("2026-04-13T08:00:00Z")
    assert parsed == dt.datetime(2026, 4, 13, 8, 0, tzinfo=dt.timezone.utc)
    naive = parse_iso8601("2026-04-13T08:00:00")
    assert naive is not None and naive.tzinfo is dt.timezone.utc


def test_parse_iso8601_returns_none_on_garbage() -> None:
    assert parse_iso8601(None) is None
    assert parse_iso8601("") is None
    assert parse_iso8601("not a timestamp") is None


def test_to_mgdl_converts_mmol() -> None:
    assert to_mgdl(7.0, "mmol/L") == 126
    assert to_mgdl("8", "mmol/l") == 144


def test_to_mgdl_passes_mgdl_through() -> None:
    assert to_mgdl(142, "mg/dL") == 142
    assert to_mgdl(None, "mg/dL") is None
    assert to_mgdl("not a number", "mg/dL") is None


def test_relative_time_buckets() -> None:
    now = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)
    assert relative_time(None) == ""
    assert relative_time(now, now=now) == "just now"
    assert relative_time(now - dt.timedelta(seconds=30), now=now) == "just now"
    assert relative_time(now - dt.timedelta(minutes=1), now=now) == "1 minute ago"
    assert relative_time(now - dt.timedelta(minutes=30), now=now) == "30 minutes ago"
    assert relative_time(now - dt.timedelta(hours=1), now=now) == "1 hour ago"
    assert relative_time(now - dt.timedelta(hours=2), now=now) == "2 hours ago"
    assert relative_time(now - dt.timedelta(days=1), now=now) == "1 day ago"
    assert relative_time(now - dt.timedelta(days=3), now=now) == "3 days ago"
    # Future timestamps clamp to "just now" rather than going negative.
    assert relative_time(now + dt.timedelta(seconds=10), now=now) == "just now"


def test_relative_time_handles_naive_input() -> None:
    now = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)
    naive = (now - dt.timedelta(minutes=10)).replace(tzinfo=None)
    assert relative_time(naive, now=now) == "10 minutes ago"


def test_age_seconds_clamps_negative_to_zero() -> None:
    now = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)
    assert age_seconds(None) is None
    assert age_seconds(now, now=now) == 0
    assert age_seconds(now - dt.timedelta(seconds=42), now=now) == 42
    naive_past = (now - dt.timedelta(minutes=2)).replace(tzinfo=None)
    assert age_seconds(naive_past, now=now) == 120
    assert age_seconds(now + dt.timedelta(seconds=5), now=now) == 0
