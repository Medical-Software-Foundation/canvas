"""Tests for billing_dashboard.data.claims — Claims tab list, filters, CSV."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import arrow
import pytest

from billing_dashboard.data import claims
from billing_dashboard.data.claim_queue import ClaimQueueState
from billing_dashboard.data.claims import (
    MAX_CSV_ROWS,
    MAX_JSON_ROWS,
    ClaimsQuery,
    ClaimsQueryError,
    build_claims,
    build_claims_csv,
    business_line_filter_enabled,
    parse_query,
    rows_to_csv,
    sanitize_cell,
)

BL_ID = "6f1c2e0a-5b7d-4c1e-9a3b-2d4e6f8a0b1c"


class FakeQuerySet:
    """Chainable stand-in for a Claim queryset that records every call."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple, dict]] = []
        self.slice: slice | None = None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> FakeQuerySet:
        self.calls.append((name, args, kwargs))
        return self

    def filter(self, *a: Any, **kw: Any) -> FakeQuerySet:
        return self._record("filter", *a, **kw)

    def exclude(self, *a: Any, **kw: Any) -> FakeQuerySet:
        return self._record("exclude", *a, **kw)

    def annotate(self, *a: Any, **kw: Any) -> FakeQuerySet:
        return self._record("annotate", *a, **kw)

    def order_by(self, *a: Any, **kw: Any) -> FakeQuerySet:
        return self._record("order_by", *a, **kw)

    def values(self, *a: Any, **kw: Any) -> FakeQuerySet:
        return self._record("values", *a, **kw)

    def __getitem__(self, item: slice) -> list[dict[str, Any]]:
        self.slice = item
        return self.rows[item]

    def kwargs_of(self, name: str) -> list[dict]:
        return [kw for n, _, kw in self.calls if n == name]


def _db_row(n: int, **overrides: Any) -> dict[str, Any]:
    row = {
        "id": f"00000000-0000-0000-0000-{n:012d}",
        "dbid": n,
        "note__datetime_of_service": dt.datetime(2026, 4, 1, 15, 0, tzinfo=dt.UTC),
        "patient__first_name": "Pat",
        "patient__last_name": f"Test{n}",
        "current_coverage__payer_name": "Payer A",
        "current_queue__name": "NeedsCodingReview",
        "current_queue__display_name": "Needs coding review",
        "note__patient__business_line__name": "Line One",
        "provider__provider_first_name": "Doc",
        "provider__provider_last_name": "Tor",
        "patient_balance": Decimal("10.00"),
        "aggregate_coverage_balance": Decimal("90.50"),
        "total_balance": Decimal("100.50"),
    }
    row.update(overrides)
    return row


@pytest.fixture
def fixed_now() -> arrow.Arrow:
    return arrow.get(2026, 4, 15, 12, 0, 0)


@pytest.fixture
def mock_models():
    """Patch Claim, ClaimQueue and BusinessLine in the claims module."""
    with (
        patch.object(claims, "Claim") as claim,
        patch.object(claims, "ClaimQueue") as queue,
        patch.object(claims, "BusinessLine") as bl,
    ):
        queue.objects.filter.return_value.exists.return_value = True
        queue.objects.order_by.return_value.values.return_value = [
            {"name": "NeedsCodingReview", "display_name": "Needs coding review"},
            {"name": "CashPay", "display_name": ""},
        ]
        bl.objects.filter.return_value.order_by.return_value.values.return_value = [
            {"id": BL_ID, "name": "Line One"},
        ]
        yield claim, queue, bl


def _wire(claim_mock: MagicMock, rows: list[dict[str, Any]]) -> FakeQuerySet:
    qs = FakeQuerySet(rows)
    claim_mock.objects.filter.side_effect = lambda **kw: qs._record("filter", **kw)
    return qs


# ---------------------------------------------------------------------------
# Setting
# ---------------------------------------------------------------------------


class TestBusinessLineSetting:
    @pytest.mark.parametrize("value", ["true", "TRUE", " true "])
    def test_enabled_only_for_true(self, value: str) -> None:
        assert business_line_filter_enabled({"CLAIMS_BUSINESS_LINE_FILTER": value})

    @pytest.mark.parametrize("value", ["", "false", "yes", "1", None])
    def test_anything_else_is_off(self, value: str | None) -> None:
        assert not business_line_filter_enabled({"CLAIMS_BUSINESS_LINE_FILTER": value})

    def test_missing_or_non_dict_is_off(self) -> None:
        assert not business_line_filter_enabled({})
        assert not business_line_filter_enabled(None)


# ---------------------------------------------------------------------------
# parse_query
# ---------------------------------------------------------------------------


class TestParseQuery:
    def test_defaults(self) -> None:
        q = parse_query({}, business_line_enabled=False)
        assert q == ClaimsQuery(
            sort="date_of_service", direction="desc", window_days=90
        )

    def test_accepts_every_whitelisted_sort(self) -> None:
        for key in claims.SORT_FIELDS:
            q = parse_query({"sort": key}, business_line_enabled=True)
            assert q.sort == key

    @pytest.mark.parametrize(
        "sort", ["note__patient__social_security_number", "-created", "dbid", "id;drop"]
    )
    def test_rejects_unknown_sort(self, sort: str) -> None:
        with pytest.raises(ClaimsQueryError, match="Unknown sort"):
            parse_query({"sort": sort}, business_line_enabled=True)

    def test_business_line_sort_rejected_when_setting_off(self) -> None:
        with pytest.raises(ClaimsQueryError, match="not enabled"):
            parse_query({"sort": "business_line"}, business_line_enabled=False)

    @pytest.mark.parametrize("direction", ["up", "ascending", "1"])
    def test_rejects_bad_direction(self, direction: str) -> None:
        with pytest.raises(ClaimsQueryError):
            parse_query({"dir": direction}, business_line_enabled=False)

    def test_direction_is_case_insensitive(self) -> None:
        assert (
            parse_query({"dir": "ASC"}, business_line_enabled=False).direction == "asc"
        )

    @pytest.mark.parametrize("window", ["7", "abc", "-90", "100000"])
    def test_rejects_window_outside_allowed_set(self, window: str) -> None:
        with pytest.raises(ClaimsQueryError, match="window"):
            parse_query({"window": window}, business_line_enabled=False)

    def test_business_line_ignored_when_setting_off(self) -> None:
        q = parse_query({"business_line": BL_ID}, business_line_enabled=False)
        assert q.business_line is None

    def test_business_line_kept_when_setting_on(self) -> None:
        q = parse_query({"business_line": BL_ID.upper()}, business_line_enabled=True)
        assert q.business_line == BL_ID

    def test_business_line_must_be_uuid(self) -> None:
        with pytest.raises(ClaimsQueryError, match="business line id"):
            parse_query({"business_line": "Line One"}, business_line_enabled=True)

    def test_blank_queue_means_no_queue_filter(self) -> None:
        assert parse_query({"queue": "  "}, business_line_enabled=False).queue is None


# ---------------------------------------------------------------------------
# build_claims (query shape + row mapping)
# ---------------------------------------------------------------------------


class TestBuildClaims:
    def test_default_query_window_trash_exclusion_and_order(
        self, mock_models, fixed_now
    ) -> None:
        claim, _, _ = mock_models
        qs = _wire(claim, [_db_row(1)])

        build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)

        first_filter = qs.kwargs_of("filter")[0]
        assert (
            first_filter["note__datetime_of_service__gte"]
            == fixed_now.shift(days=-90).datetime
        )
        assert first_filter["note__datetime_of_service__lte"] == fixed_now.datetime
        assert qs.kwargs_of("exclude") == [
            {"current_queue__queue_sort_ordering": ClaimQueueState.TRASH}
        ]
        order_args = next(a for n, a, _ in qs.calls if n == "order_by")
        assert order_args[0].expression.name == "note__datetime_of_service"
        assert order_args[0].descending is True
        assert order_args[1] == "-dbid"

    def test_ascending_sort_uses_ascending_tie_breaker(
        self, mock_models, fixed_now
    ) -> None:
        claim, _, _ = mock_models
        qs = _wire(claim, [])
        build_claims(
            ClaimsQuery(sort="balance", direction="asc"),
            business_line_enabled=False,
            now=fixed_now,
        )
        order_args = next(a for n, a, _ in qs.calls if n == "order_by")
        assert order_args[0].expression.name == "total_balance"
        assert order_args[0].descending is False
        assert order_args[1] == "dbid"

    def test_queue_filter_replaces_trash_exclusion(
        self, mock_models, fixed_now
    ) -> None:
        claim, queue, _ = mock_models
        qs = _wire(claim, [])
        build_claims(
            ClaimsQuery(queue="Trash"), business_line_enabled=False, now=fixed_now
        )
        queue.objects.filter.assert_called_once_with(name="Trash")
        assert {"current_queue__name": "Trash"} in qs.kwargs_of("filter")
        assert qs.kwargs_of("exclude") == []

    def test_unknown_queue_fails_clearly(self, mock_models, fixed_now) -> None:
        claim, queue, _ = mock_models
        _wire(claim, [])
        queue.objects.filter.return_value.exists.return_value = False
        with pytest.raises(ClaimsQueryError, match="Unknown claim queue 'Nope'"):
            build_claims(
                ClaimsQuery(queue="Nope"), business_line_enabled=False, now=fixed_now
            )

    def test_business_line_filter_applied(self, mock_models, fixed_now) -> None:
        claim, _, _ = mock_models
        qs = _wire(claim, [])
        build_claims(
            ClaimsQuery(business_line=BL_ID), business_line_enabled=True, now=fixed_now
        )
        assert {"note__patient__business_line__id": BL_ID} in qs.kwargs_of("filter")

    def test_business_lines_listed_only_when_enabled(
        self, mock_models, fixed_now
    ) -> None:
        claim, _, bl = mock_models
        _wire(claim, [])
        off = build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)
        assert off["filters"]["business_line_enabled"] is False
        assert off["filters"]["business_lines"] == []
        bl.objects.filter.assert_not_called()

        _wire(claim, [])
        on = build_claims(ClaimsQuery(), business_line_enabled=True, now=fixed_now)
        assert on["filters"]["business_lines"] == [{"id": BL_ID, "name": "Line One"}]
        bl.objects.filter.assert_called_once_with(active=True)

    def test_queue_display_name_falls_back_to_name(
        self, mock_models, fixed_now
    ) -> None:
        claim, _, _ = mock_models
        _wire(claim, [])
        out = build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)
        assert out["filters"]["queues"] == [
            {"name": "NeedsCodingReview", "display_name": "Needs coding review"},
            {"name": "CashPay", "display_name": "CashPay"},
        ]

    def test_row_mapping(self, mock_models, fixed_now) -> None:
        claim, _, _ = mock_models
        _wire(claim, [_db_row(7)])
        row = build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)[
            "claims"
        ][0]
        assert row == {
            "id": "00000000-0000-0000-0000-000000000007",
            "claim_number": 7,
            "date_of_service": "2026-04-01",
            "patient": "Pat Test7",
            "provider": "Doc Tor",
            "payer": "Payer A",
            "queue": "Needs coding review",
            "business_line": "Line One",
            "patient_balance": 10.0,
            "coverage_balance": 90.5,
            "balance": 100.5,
        }

    def test_date_of_service_shown_in_viewer_timezone(
        self, mock_models, fixed_now
    ) -> None:
        # 01:30 UTC on Apr 2 is still Apr 1 in New York; a UTC date would be a day late.
        claim, _, _ = mock_models
        late = dt.datetime(2026, 4, 2, 1, 30, tzinfo=dt.UTC)
        _wire(claim, [_db_row(7, note__datetime_of_service=late)])
        ny = build_claims(
            ClaimsQuery(),
            business_line_enabled=False,
            now=fixed_now,
            tz="America/New_York",
        )["claims"][0]
        assert ny["date_of_service"] == "2026-04-01"
        _wire(claim, [_db_row(7, note__datetime_of_service=late)])
        text, _ = build_claims_csv(ClaimsQuery(), now=fixed_now, tz="America/New_York")
        assert '"2026-04-01"' in text
        _wire(claim, [_db_row(7, note__datetime_of_service=late)])
        utc = build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)
        assert utc["claims"][0]["date_of_service"] == "2026-04-02"

    def test_row_mapping_handles_missing_values(self, mock_models, fixed_now) -> None:
        claim, _, _ = mock_models
        _wire(
            claim,
            [
                _db_row(
                    1,
                    note__datetime_of_service=None,
                    current_coverage__payer_name=None,
                    note__patient__business_line__name=None,
                    current_queue__display_name="",
                    provider__provider_first_name=None,
                    provider__provider_last_name=None,
                    patient_balance=None,
                    total_balance=None,
                )
            ],
        )
        row = build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)[
            "claims"
        ][0]
        assert row["date_of_service"] == ""
        assert row["payer"] == ""
        assert row["business_line"] == ""
        assert row["queue"] == "NeedsCodingReview"
        assert row["provider"] == ""
        assert row["patient_balance"] == 0.0
        assert row["balance"] == 0.0
        assert "None" not in str(row)

    def test_truncation_flag_and_cap(self, mock_models, fixed_now) -> None:
        claim, _, _ = mock_models
        qs = _wire(claim, [_db_row(i) for i in range(MAX_JSON_ROWS + 1)])
        out = build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)
        assert qs.slice == slice(None, MAX_JSON_ROWS + 1)
        assert out["truncated"] is True
        assert len(out["claims"]) == MAX_JSON_ROWS

    def test_not_truncated_at_exact_limit(self, mock_models, fixed_now) -> None:
        claim, _, _ = mock_models
        _wire(claim, [_db_row(i) for i in range(3)])
        out = build_claims(ClaimsQuery(), business_line_enabled=False, now=fixed_now)
        assert out["truncated"] is False
        assert len(out["claims"]) == 3

    def test_echoes_query(self, mock_models, fixed_now) -> None:
        claim, _, _ = mock_models
        _wire(claim, [])
        q = ClaimsQuery(sort="payer", direction="asc", window_days=30, queue="CashPay")
        out = build_claims(q, business_line_enabled=False, now=fixed_now)
        assert out["query"] == {
            "sort": "payer",
            "dir": "asc",
            "window": 30,
            "queue": "CashPay",
            "business_line": "",
        }


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


class TestSanitizeCell:
    @pytest.mark.parametrize(
        "value",
        [
            '=HYPERLINK("http://x","y")',
            "+1+1",
            "-2+3",
            "@SUM(A1)",
            "\tTAB",
            "\rCR",
            "|cmd",
        ],
    )
    def test_formula_prefixes_are_neutralized(self, value: str) -> None:
        cell = sanitize_cell(value)
        assert cell.startswith("\"'")

    def test_plain_text_untouched(self) -> None:
        assert sanitize_cell("Payer A") == '"Payer A"'

    def test_embedded_quotes_doubled(self) -> None:
        assert sanitize_cell('Say "hi"') == '"Say ""hi"""'

    def test_numbers_stay_numeric_even_when_negative(self) -> None:
        assert sanitize_cell(-12.5) == '"-12.5"'
        assert sanitize_cell(Decimal("-3.10")) == '"-3.10"'
        assert sanitize_cell(42) == '"42"'

    def test_negative_number_as_text_is_neutralized(self) -> None:
        assert sanitize_cell("-12.5") == '"\'-12.5"'

    def test_none_is_empty(self) -> None:
        assert sanitize_cell(None) == '""'

    def test_bool_is_text(self) -> None:
        assert sanitize_cell(True) == '"True"'


class TestRowsToCsv:
    def test_header_and_rows_in_column_order(self) -> None:
        rows = [
            {
                "claim_number": 7,
                "date_of_service": "2026-04-01",
                "patient": "=cmd|' /C calc'!A0",
                "provider": "Doc Tor",
                "payer": "Payer, Inc",
                "queue": "Needs coding review",
                "business_line": "",
                "patient_balance": 10.0,
                "coverage_balance": -5.0,
                "balance": 5.0,
            }
        ]
        text = rows_to_csv(rows)
        lines = text.split("\r\n")
        assert lines[0] == (
            '"Claim #","Date of service","Patient","Provider","Payer","Queue",'
            '"Business line","Patient balance","Coverage balance","Total balance"'
        )
        assert lines[1] == (
            '"7","2026-04-01","\'=cmd|\' /C calc\'!A0","Doc Tor","Payer, Inc",'
            '"Needs coding review","","10.0","-5.0","5.0"'
        )
        assert text.endswith("\r\n")
        assert len(lines) == 3  # header, row, trailing empty after final CRLF

    def test_empty_rows_gives_header_only(self) -> None:
        assert rows_to_csv([]).count("\r\n") == 1


class TestBuildClaimsCsv:
    def test_uses_csv_cap_and_reports_truncation(self, mock_models, fixed_now) -> None:
        claim, _, _ = mock_models
        qs = _wire(claim, [_db_row(i) for i in range(5)])
        text, truncated = build_claims_csv(ClaimsQuery(), now=fixed_now)
        assert qs.slice == slice(None, MAX_CSV_ROWS + 1)
        assert truncated is False
        assert text.count("\r\n") == 6  # header + 5 rows
        assert '"Pat Test4"' in text


class TestStaffTimezone:
    def test_uses_staff_last_known_timezone(self) -> None:
        with patch.object(claims, "Staff") as staff:
            staff.objects.filter.return_value.values_list.return_value.first.return_value = "America/Chicago"
            assert claims.staff_timezone("s1") == "America/Chicago"
            staff.objects.filter.assert_called_once_with(id="s1")

    def test_falls_back_to_utc(self) -> None:
        with patch.object(claims, "Staff") as staff:
            staff.objects.filter.return_value.values_list.return_value.first.return_value = None
            assert claims.staff_timezone("s1") == "UTC"
        assert claims.staff_timezone(None) == "UTC"

    def test_unknown_zone_name_falls_back_to_utc(self) -> None:
        with patch.object(claims, "Staff") as staff:
            staff.objects.filter.return_value.values_list.return_value.first.return_value = "Not/AZone"
            assert claims.staff_timezone("s1") == "UTC"
