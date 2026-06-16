"""Unit tests for recent_labs.labs helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from recent_labs.labs import (
    RESULTS_PER_TEST,
    abnormal_label,
    clean_token,
    format_lab_date,
    get_recent_results_by_test,
    is_abnormal,
    lab_test_name,
    numeric_value,
    serialize_lab_value,
    sparkline_points,
)


def _value(name="Glucose", code="2345-7", value="105", units="mg/dL", flag="H",
           ref="70-99", date="2026-06-01"):
    """Build a duck-typed LabValue-like object for tests."""
    coding = SimpleNamespace(name=name, code=code)
    codings = MagicMock()
    codings.all.return_value = [coding]
    report = SimpleNamespace(original_date=date)
    return SimpleNamespace(
        codings=codings, value=value, units=units,
        abnormal_flag=flag, reference_range=ref, report=report,
    )


def _queryset(values):
    """Mock LabValue.objects whose filter()...order_by() chain yields `values`."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.select_related.return_value = qs
    qs.prefetch_related.return_value = qs
    qs.order_by.return_value = values
    return qs


class TestIsAbnormal:
    def test_high_flag_is_abnormal(self):
        assert is_abnormal("H") is True

    def test_low_flag_is_abnormal(self):
        assert is_abnormal("L") is True

    def test_empty_flag_is_normal(self):
        assert is_abnormal("") is False

    def test_none_flag_is_normal(self):
        assert is_abnormal(None) is False

    def test_normal_flag_is_normal(self):
        assert is_abnormal("N") is False

    def test_lowercase_flag_is_abnormal(self):
        assert is_abnormal("h") is True

    def test_whitespace_padded_flag_is_normalized(self):
        assert is_abnormal(" H ") is True


class TestLabTestName:
    def test_uses_coding_name(self):
        assert lab_test_name(_value(name="Hemoglobin A1c")) == "Hemoglobin A1c"

    def test_falls_back_to_code_when_no_name(self):
        assert lab_test_name(_value(name="", code="4548-4")) == "4548-4"

    def test_unknown_when_no_coding(self):
        v = _value()
        v.codings.all.return_value = []
        assert lab_test_name(v) == "Unknown test"


class TestAbnormalLabel:
    def test_high(self):
        assert abnormal_label("H") == "High"

    def test_low(self):
        assert abnormal_label("L") == "Low"

    def test_other_abnormal(self):
        assert abnormal_label("A") == "Abnormal"

    def test_normal_is_empty(self):
        assert abnormal_label("") == ""
        assert abnormal_label("N") == ""


class TestCleanToken:
    def test_keeps_real_values(self):
        assert clean_token("mg/dL") == "mg/dL"
        assert clean_token("70-99") == "70-99"

    def test_blanks_placeholders(self):
        assert clean_token("-") == ""
        assert clean_token("None") == ""
        assert clean_token(None) == ""
        assert clean_token("  ") == ""
        assert clean_token("N/A") == ""


class TestFormatLabDate:
    def test_formats_datetime(self):
        from datetime import datetime
        assert format_lab_date(datetime(2023, 3, 2, 6, 0)) == "Mar 02, 2023"

    def test_passes_through_string(self):
        assert format_lab_date("2026-06-01") == "2026-06-01"

    def test_none_is_empty(self):
        assert format_lab_date(None) == ""


class TestSerializeLabValue:
    def test_serializes_all_fields(self):
        result = serialize_lab_value(_value())
        assert result == {
            "test_name": "Glucose",
            "value": "105",
            "units": "mg/dL",
            "abnormal_flag": "H",
            "is_abnormal": True,
            "abnormal_label": "High",
            "reference_range": "70-99",
            "date": "2026-06-01",
        }

    def test_cleans_placeholder_units_and_ref(self):
        result = serialize_lab_value(_value(units="None", ref="-"))
        assert result["units"] == ""
        assert result["reference_range"] == ""

    def test_falls_back_to_code_when_no_coding_name(self):
        result = serialize_lab_value(_value(name="", code="2345-7"))
        assert result["test_name"] == "2345-7"

    def test_handles_missing_coding(self):
        value = _value()
        value.codings.all.return_value = []
        result = serialize_lab_value(value)
        assert result["test_name"] == "Unknown test"


class TestGetRecentResultsByTest:
    def test_groups_by_code_keeps_three_newest_per_test_ordered_by_recency(self):
        # Newest-first, as the query returns. A1c seen first, then Covid.
        unidentified = _value(name="", code="", value="2314", date="2022-04-10")
        values = [
            _value(name="Hemoglobin A1c", code="4548-4", value="6", date="2023-03-02"),
            _value(name="SARS-CoV-2", code="94558-4", value="POSITIVE", date="2022-07-05"),
            unidentified,
            _value(name="Hemoglobin A1c", code="4548-4", value="5.8", date="2022-09-01"),
            _value(name="Hemoglobin A1c", code="4548-4", value="6.1", date="2022-03-04"),
            _value(name="Hemoglobin A1c", code="4548-4", value="5.5", date="2021-03-04"),
        ]
        qs = _queryset(values)
        with patch("recent_labs.labs.LabValue") as mock_lv:
            mock_lv.objects = qs
            groups = get_recent_results_by_test("p1")

        qs.filter.assert_called_once_with(report__patient__id="p1", report__junked=False)
        qs.order_by.assert_called_once_with("-report__original_date", "-dbid")
        # Group order follows most-recent-result (first-seen): A1c, then Covid.
        # The unidentified value (no name/code) is omitted entirely.
        assert [g["test_name"] for g in groups] == ["Hemoglobin A1c", "SARS-CoV-2"]
        # A1c capped at 3 newest; the 4th (oldest) result is dropped
        assert [r["value"] for r in groups[0]["results"]] == ["6", "5.8", "6.1"]
        assert len(groups[1]["results"]) == 1
        assert groups[1]["results"][0]["value"] == "POSITIVE"
        # A1c has 3 numeric results -> a sparkline; Covid is qualitative -> none
        assert isinstance(groups[0]["sparkline"], str)
        assert groups[1]["sparkline"] is None

    def test_falls_back_to_name_grouping_when_no_code(self):
        values = [
            _value(name="Custom Panel", code="", value="1", date="2023-01-01"),
            _value(name="Custom Panel", code="", value="2", date="2022-01-01"),
        ]
        qs = _queryset(values)
        with patch("recent_labs.labs.LabValue") as mock_lv:
            mock_lv.objects = qs
            groups = get_recent_results_by_test("p1")

        assert len(groups) == 1
        assert groups[0]["test_name"] == "Custom Panel"
        assert [r["value"] for r in groups[0]["results"]] == ["1", "2"]

    def test_empty_when_no_values(self):
        qs = _queryset([])
        with patch("recent_labs.labs.LabValue") as mock_lv:
            mock_lv.objects = qs
            assert get_recent_results_by_test("p1") == []

    def test_results_per_test_is_three(self):
        assert RESULTS_PER_TEST == 3


class TestNumericValue:
    def test_parses_int_and_float(self):
        assert numeric_value("6") == 6.0
        assert numeric_value("5.8") == 5.8
        assert numeric_value(" 7 ") == 7.0

    def test_none_for_non_numeric(self):
        assert numeric_value("POSITIVE") is None
        assert numeric_value("") is None
        assert numeric_value(None) is None
        assert numeric_value(">90") is None


class TestSparklinePoints:
    def test_returns_points_oldest_to_newest(self):
        # results are newest-first; plotted oldest (x=0) to newest (x=width)
        results = [{"value": "6"}, {"value": "5.8"}, {"value": "6.1"}]
        pts = sparkline_points(results, width=64, height=18)
        coords = pts.split(" ")
        assert len(coords) == 3
        assert float(coords[0].split(",")[0]) == 0
        assert float(coords[-1].split(",")[0]) == 64

    def test_none_when_fewer_than_two_numeric(self):
        assert sparkline_points([{"value": "6"}]) is None
        assert sparkline_points([{"value": "POSITIVE"}]) is None

    def test_none_for_qualitative_results(self):
        assert sparkline_points([{"value": "POSITIVE"}, {"value": "NEGATIVE"}]) is None

    def test_flat_line_when_all_values_equal(self):
        pts = sparkline_points([{"value": "5"}, {"value": "5"}], height=18)
        ys = [c.split(",")[1] for c in pts.split(" ")]
        assert ys[0] == ys[1]
