"""Tests for plugin settings helpers.

These exercise the only module with no ``canvas_sdk`` dependency, which makes
them runnable before the SDK is wired into a local virtualenv. They are real
tests, not placeholders: ``parse_range_days`` takes untrusted query-string
input, so its coercion behaviour is worth pinning down early.
"""

import pytest

from oura_ring_viewer.services.settings import (
    DEFAULT_RANGE_DAYS,
    OURA_API_HOST,
    RANGE_OPTIONS,
    oura_collection_base,
    parse_range_days,
)


class TestOuraCollectionBase:
    """Environment routing between the sandbox and production collections."""

    def test_production_uses_live_collection(self) -> None:
        assert oura_collection_base("production") == f"{OURA_API_HOST}/v2/usercollection"

    def test_sandbox_uses_the_sample_collection(self) -> None:
        assert oura_collection_base("sandbox") == f"{OURA_API_HOST}/v2/sandbox/usercollection"

    @pytest.mark.parametrize("value", ["", "   ", "prod", "anything-else"])
    def test_anything_else_is_refused(self, value: str) -> None:
        """A typo must never route anywhere, least of all to sample data shown as real."""
        with pytest.raises(ValueError):
            oura_collection_base(value)

    @pytest.mark.parametrize("value", ["PRODUCTION", "Production", "  production  "])
    def test_production_match_is_case_and_space_insensitive(self, value: str) -> None:
        assert oura_collection_base(value) == f"{OURA_API_HOST}/v2/usercollection"


class TestParseRangeDays:
    """Coercion of the ``range`` query parameter."""

    @pytest.mark.parametrize("days", RANGE_OPTIONS)
    def test_allowed_values_pass_through(self, days: int) -> None:
        assert parse_range_days(str(days)) == days

    @pytest.mark.parametrize("raw", ["7d", "14D", " 30d ", "90"])
    def test_day_suffix_and_whitespace_are_tolerated(self, raw: str) -> None:
        assert parse_range_days(raw) in RANGE_OPTIONS

    @pytest.mark.parametrize(
        "raw", [None, "", "   ", "abc", "0", "-7", "365", "1e3", "7; DROP TABLE"]
    )
    def test_bad_input_falls_back_to_default(self, raw: str | None) -> None:
        """Anything unrecognized must land on the default, never raise."""
        assert parse_range_days(raw) == DEFAULT_RANGE_DAYS

    def test_default_is_itself_an_allowed_option(self) -> None:
        """Guards against a future edit desynchronizing the two constants."""
        assert DEFAULT_RANGE_DAYS in RANGE_OPTIONS
