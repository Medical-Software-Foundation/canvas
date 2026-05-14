"""Tests for the shared rule helpers."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from lab_order_validation.rules._helpers import (
    has_meaningful_content,
    is_active_coverage,
    sanitize_for_display,
)


def _coverage(*, state="active", start=None, end=None):
    cov = MagicMock()
    cov.state = state
    cov.coverage_start_date = start
    cov.coverage_end_date = end
    return cov


class TestIsActiveCoverage:
    def test_active_state_with_no_dates_is_active(self):
        assert is_active_coverage(_coverage(state="active")) is True

    def test_deleted_state_is_not_active(self):
        assert is_active_coverage(_coverage(state="deleted")) is False

    def test_active_string_case_insensitive(self):
        assert is_active_coverage(_coverage(state="ACTIVE")) is True

    def test_active_enum_with_value_attribute(self):
        enum_like = MagicMock()
        enum_like.value = "active"
        assert is_active_coverage(_coverage(state=enum_like)) is True

    def test_deleted_enum_with_value_attribute_is_not_active(self):
        enum_like = MagicMock()
        enum_like.value = "deleted"
        assert is_active_coverage(_coverage(state=enum_like)) is False

    def test_unknown_state_is_not_active(self):
        assert is_active_coverage(_coverage(state="cancelled")) is False

    def test_expired_end_date_is_not_active(self):
        assert (
            is_active_coverage(
                _coverage(state="active", end=date.today() - timedelta(days=1))
            )
            is False
        )

    def test_future_start_date_is_not_active(self):
        assert (
            is_active_coverage(
                _coverage(state="active", start=date.today() + timedelta(days=1))
            )
            is False
        )

    def test_active_state_overrides_dates_only_when_dates_valid(self):
        """state=active alone is not enough; dates still have to make sense."""
        assert (
            is_active_coverage(
                _coverage(
                    state="active",
                    start=date.today() - timedelta(days=30),
                    end=date.today() + timedelta(days=30),
                )
            )
            is True
        )


class TestHasMeaningfulContent:
    def test_alphanumeric_passes(self):
        assert has_meaningful_content("Boston") is True

    def test_short_state_code_passes(self):
        assert has_meaningful_content("MA") is True

    def test_single_alphanumeric_fails_default_min(self):
        assert has_meaningful_content("A") is False

    def test_dashes_only_fails(self):
        assert has_meaningful_content("---") is False

    def test_dot_only_fails(self):
        assert has_meaningful_content(".") is False

    def test_whitespace_only_fails(self):
        assert has_meaningful_content("   ") is False

    def test_empty_string_fails(self):
        assert has_meaningful_content("") is False

    def test_none_fails(self):
        assert has_meaningful_content(None) is False

    def test_zip_code_passes(self):
        assert has_meaningful_content("02101") is True

    def test_phone_with_min_7(self):
        assert has_meaningful_content("617-555-0100", min_alnum=7) is True

    def test_phone_too_short_fails_min_7(self):
        assert has_meaningful_content("123-45", min_alnum=7) is False

    def test_punctuation_with_two_alnum_passes(self):
        # "1A" buried in punctuation still has two alnums - allowed by default
        assert has_meaningful_content("-1-A-") is True


class TestSanitizeForDisplay:
    def test_plain_name_unchanged(self):
        assert sanitize_for_display("Acme Health") == "Acme Health"

    def test_none_becomes_empty(self):
        assert sanitize_for_display(None) == ""

    def test_strips_control_characters(self):
        assert sanitize_for_display("Acme\x00Health\x1f") == "AcmeHealth"

    def test_strips_delete_character(self):
        assert sanitize_for_display("Acme\x7fHealth") == "AcmeHealth"

    def test_collapses_internal_whitespace(self):
        assert sanitize_for_display("Acme   Health") == "Acme Health"

    def test_collapses_newlines_and_tabs(self):
        assert sanitize_for_display("Acme\n\tHealth") == "Acme Health"

    def test_strips_leading_trailing_whitespace(self):
        assert sanitize_for_display("  Acme Health  ") == "Acme Health"

    def test_collapses_nbsp(self):
        assert sanitize_for_display("Acme Health") == "Acme Health"

    def test_truncates_long_strings(self):
        name = "A" * 200
        result = sanitize_for_display(name)
        assert len(result) == 80
        assert result.endswith("...")

    def test_quotes_are_preserved(self):
        # Single quotes appear in error messages; preserve them so the message reads naturally
        assert sanitize_for_display("O'Brien") == "O'Brien"

    def test_html_chars_passed_through(self):
        # Canvas UI is responsible for HTML-escaping; we only strip control chars
        assert sanitize_for_display("<script>") == "<script>"
