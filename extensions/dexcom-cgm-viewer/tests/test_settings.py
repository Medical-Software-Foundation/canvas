"""Plugin-wide constants and tiny pure helpers."""

from __future__ import annotations

import pytest

from dexcom_cgm_viewer.lib.settings import (
    DEFAULT_RANGE_DAYS,
    RANGE_OPTIONS,
    dexcom_base_url,
    parse_range_days,
)


def test_dexcom_base_url_defaults_to_sandbox() -> None:
    assert dexcom_base_url("sandbox") == "https://sandbox-api.dexcom.com"
    assert dexcom_base_url("") == "https://sandbox-api.dexcom.com"
    assert dexcom_base_url("anything-else") == "https://sandbox-api.dexcom.com"


def test_dexcom_base_url_picks_production_only_for_exact_match() -> None:
    assert dexcom_base_url("production") == "https://api.dexcom.com"
    assert dexcom_base_url("PRODUCTION") == "https://api.dexcom.com"
    assert dexcom_base_url("  Production ") == "https://api.dexcom.com"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7", 7),
        ("14", 14),
        ("30", 30),
        ("90", 90),
        ("7d", 7),
        ("14D", 14),
        ("", DEFAULT_RANGE_DAYS),
        (None, DEFAULT_RANGE_DAYS),
        ("garbage", DEFAULT_RANGE_DAYS),
        ("12", DEFAULT_RANGE_DAYS),
    ],
)
def test_parse_range_days_clamps_to_supported_options(raw: str | None, expected: int) -> None:
    assert parse_range_days(raw) == expected
    assert parse_range_days(raw) in RANGE_OPTIONS or parse_range_days(raw) == DEFAULT_RANGE_DAYS
