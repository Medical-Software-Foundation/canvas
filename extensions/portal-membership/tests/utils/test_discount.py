"""Unit tests for discount code parsing and application."""
import json
from datetime import date, timedelta

import pytest

from portal_membership.utils.discount import (
    apply_discount,
    build_record_fields,
    describe,
    find_code,
    parse_codes,
)


# ---------------------------------------------------------------------------
# parse_codes
# ---------------------------------------------------------------------------

class TestParseCodes:
    def test_valid_json_array(self) -> None:
        raw = json.dumps([
            {"code": "WELCOME10", "type": "percent", "value": 10, "months": 3},
            {"code": "SAVE20", "type": "fixed", "value": 2000, "months": 1},
        ])
        codes = parse_codes(raw)
        assert len(codes) == 2
        assert codes[0]["code"] == "WELCOME10"

    def test_empty_string_returns_empty(self) -> None:
        assert parse_codes("") == []

    def test_none_returns_empty(self) -> None:
        assert parse_codes(None) == []

    def test_invalid_json_returns_empty(self) -> None:
        assert parse_codes("{not json") == []

    def test_non_list_returns_empty(self) -> None:
        assert parse_codes('{"code": "X"}') == []

    def test_entries_without_code_filtered_out(self) -> None:
        raw = json.dumps([{"type": "percent", "value": 10}, {"code": "X", "type": "percent", "value": 5, "months": 1}])
        codes = parse_codes(raw)
        assert len(codes) == 1
        assert codes[0]["code"] == "X"


# ---------------------------------------------------------------------------
# find_code
# ---------------------------------------------------------------------------

def _secrets_with(codes: list[dict]) -> dict[str, str]:
    return {"DISCOUNT_CODES": json.dumps(codes)}


class TestFindCode:
    def test_exact_match(self) -> None:
        secrets = _secrets_with([{"code": "WELCOME10", "type": "percent", "value": 10, "months": 3}])
        entry = find_code(secrets, "WELCOME10")
        assert entry is not None
        assert entry["code"] == "WELCOME10"

    def test_case_insensitive(self) -> None:
        secrets = _secrets_with([{"code": "WELCOME10", "type": "percent", "value": 10, "months": 3}])
        assert find_code(secrets, "welcome10") is not None
        assert find_code(secrets, "Welcome10") is not None

    def test_trims_whitespace(self) -> None:
        secrets = _secrets_with([{"code": "SAVE20", "type": "fixed", "value": 2000, "months": 1}])
        assert find_code(secrets, "  SAVE20  ") is not None

    def test_missing_code_returns_none(self) -> None:
        secrets = _secrets_with([{"code": "X", "type": "percent", "value": 10, "months": 1}])
        assert find_code(secrets, "NOPE") is None

    def test_empty_input_returns_none(self) -> None:
        secrets = _secrets_with([{"code": "X", "type": "percent", "value": 10, "months": 1}])
        assert find_code(secrets, "") is None

    def test_expired_code_returns_none(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        secrets = _secrets_with(
            [{"code": "OLD", "type": "percent", "value": 10, "months": 1, "expires_at": yesterday}]
        )
        assert find_code(secrets, "OLD") is None

    def test_expires_today_returns_none(self) -> None:
        today = date.today().isoformat()
        secrets = _secrets_with(
            [{"code": "LAST", "type": "percent", "value": 10, "months": 1, "expires_at": today}]
        )
        assert find_code(secrets, "LAST") is None

    def test_future_expiry_still_valid(self) -> None:
        future = (date.today() + timedelta(days=30)).isoformat()
        secrets = _secrets_with(
            [{"code": "FUTURE", "type": "percent", "value": 10, "months": 1, "expires_at": future}]
        )
        assert find_code(secrets, "FUTURE") is not None

    def test_invalid_expiry_string_treated_as_no_expiry(self) -> None:
        secrets = _secrets_with(
            [{"code": "WEIRD", "type": "percent", "value": 10, "months": 1, "expires_at": "not-a-date"}]
        )
        assert find_code(secrets, "WEIRD") is not None

    def test_bad_type_rejected(self) -> None:
        secrets = _secrets_with([{"code": "BAD", "type": "magic", "value": 50, "months": 1}])
        assert find_code(secrets, "BAD") is None

    def test_percent_over_100_rejected(self) -> None:
        secrets = _secrets_with([{"code": "OVER", "type": "percent", "value": 150, "months": 1}])
        assert find_code(secrets, "OVER") is None

    def test_negative_value_rejected(self) -> None:
        secrets = _secrets_with([{"code": "NEG", "type": "fixed", "value": -100, "months": 1}])
        assert find_code(secrets, "NEG") is None

    def test_zero_months_rejected(self) -> None:
        secrets = _secrets_with([{"code": "ZERO", "type": "percent", "value": 10, "months": 0}])
        assert find_code(secrets, "ZERO") is None

    def test_no_secret_configured(self) -> None:
        assert find_code({}, "ANY") is None


# ---------------------------------------------------------------------------
# apply_discount
# ---------------------------------------------------------------------------

class TestApplyDiscount:
    def test_percent_off(self) -> None:
        assert apply_discount(10000, "percent", 10) == 9000

    def test_percent_rounds_down(self) -> None:
        # 9900 * 10 // 100 = 990 → 9900 - 990 = 8910
        assert apply_discount(9900, "percent", 10) == 8910

    def test_percent_100_floors_at_zero(self) -> None:
        assert apply_discount(9900, "percent", 100) == 0

    def test_fixed_cents_off(self) -> None:
        assert apply_discount(9900, "fixed", 2000) == 7900

    def test_fixed_larger_than_amount_floors_at_zero(self) -> None:
        assert apply_discount(5000, "fixed", 9999) == 0

    def test_none_type_returns_amount_unchanged(self) -> None:
        assert apply_discount(9900, None, None) == 9900

    def test_unknown_type_returns_amount_unchanged(self) -> None:
        assert apply_discount(9900, "magic", 50) == 9900


# ---------------------------------------------------------------------------
# build_record_fields
# ---------------------------------------------------------------------------

class TestBuildRecordFields:
    def test_produces_expected_fields(self) -> None:
        entry = {"code": "welcome10", "type": "percent", "value": 10, "months": 3}
        fields = build_record_fields(entry)
        assert fields == {
            "discount_code": "WELCOME10",
            "discount_type": "percent",
            "discount_value": 10,
            "discount_cycles_remaining": 3,
        }


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------

class TestDescribe:
    def test_none_when_absent(self) -> None:
        assert describe({"plan": "gold"}) is None

    def test_summary_when_present(self) -> None:
        record = {
            "discount_code": "WELCOME10",
            "discount_type": "percent",
            "discount_value": 10,
            "discount_cycles_remaining": 2,
        }
        assert describe(record) == {
            "code": "WELCOME10",
            "type": "percent",
            "value": 10,
            "cycles_remaining": 2,
        }
