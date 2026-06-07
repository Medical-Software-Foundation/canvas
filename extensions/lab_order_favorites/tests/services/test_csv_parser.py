"""Tests for the sandbox-safe favorites CSV parser."""

from lab_order_favorites.services import csv_parser


def test_template_round_trips_to_one_valid_row():
    template = csv_parser.generate_template_csv()
    result = csv_parser.parse_favorites_csv(template)

    assert result.total_rows == 1
    assert len(result.parsed_rows) == 1
    assert not result.error_rows

    row = result.parsed_rows[0]
    assert row.name == "Annual Wellness Panel"
    assert row.lab_partner == "LabCorp"
    assert row.order_codes == ["001453", "322000", "001065"]
    assert row.tags == ["wellness", "annual"]
    assert row.is_shared is True
    assert row.fasting_required is False
    assert row.comment == "Fasting 8h preferred"
    assert row.diagnosis_codes == ["Z00.00"]


def test_header_is_case_insensitive_and_bom_is_stripped():
    content = "﻿NAME,Lab_Partner,Test_Order_Codes\nGlucose,LabCorp,001065\n"
    result = csv_parser.parse_favorites_csv(content)

    assert len(result.parsed_rows) == 1
    assert result.parsed_rows[0].name == "Glucose"
    assert result.parsed_rows[0].order_codes == ["001065"]


def test_quoted_field_with_comma_is_preserved():
    content = (
        "name,lab_partner,test_order_codes,comment\n"
        'CBC,LabCorp,001453,"Fast 8h, then draw"\n'
    )
    result = csv_parser.parse_favorites_csv(content)

    assert result.parsed_rows[0].comment == "Fast 8h, then draw"


def test_escaped_double_quote_inside_quoted_field():
    content = (
        "name,lab_partner,test_order_codes,comment\n"
        'CBC,LabCorp,001453,"say ""hi"" now"\n'
    )
    result = csv_parser.parse_favorites_csv(content)

    assert result.parsed_rows[0].comment == 'say "hi" now'


def test_multiple_order_codes_split_and_trimmed():
    content = "name,lab_partner,test_order_codes\nPanel,LabCorp,001; 002 ;003;\n"
    result = csv_parser.parse_favorites_csv(content)

    assert result.parsed_rows[0].order_codes == ["001", "002", "003"]


def test_missing_required_columns_become_error_rows():
    content = "name,lab_partner,test_order_codes\n,LabCorp,001\nPanel,,002\nPanel,LabCorp,\n"
    result = csv_parser.parse_favorites_csv(content)

    assert result.total_rows == 3
    assert not result.parsed_rows
    assert len(result.error_rows) == 3
    assert "name is required" in result.error_rows[0].errors
    assert "lab_partner is required" in result.error_rows[1].errors
    assert "test_order_codes must contain at least one code" in result.error_rows[2].errors


def test_invalid_boolean_is_reported():
    content = "name,lab_partner,test_order_codes,is_shared\nPanel,LabCorp,001,maybe\n"
    result = csv_parser.parse_favorites_csv(content)

    assert not result.parsed_rows
    assert "is_shared must be true or false" in result.error_rows[0].errors


def test_boolean_variants_and_defaults():
    content = (
        "name,lab_partner,test_order_codes,is_shared,fasting_required\n"
        "A,LabCorp,001,false,yes\n"
        "B,LabCorp,002,,\n"
    )
    result = csv_parser.parse_favorites_csv(content)

    a, b = result.parsed_rows
    assert a.is_shared is False
    assert a.fasting_required is True
    assert b.is_shared is True
    assert b.fasting_required is False


def test_blank_lines_are_skipped():
    content = "name,lab_partner,test_order_codes\n\nPanel,LabCorp,001\n\n"
    result = csv_parser.parse_favorites_csv(content)

    assert result.total_rows == 1
    assert len(result.parsed_rows) == 1


def test_empty_content_returns_empty_result():
    result = csv_parser.parse_favorites_csv("")
    assert result.total_rows == 0
    assert not result.parsed_rows
    assert not result.error_rows


def test_header_only_returns_no_rows():
    result = csv_parser.parse_favorites_csv("name,lab_partner,test_order_codes\n")
    assert result.total_rows == 0
    assert not result.parsed_rows


def test_short_row_treats_missing_columns_as_blank():
    # Header declares 4 columns; data row only supplies 3.
    content = "name,lab_partner,test_order_codes,comment\nPanel,LabCorp,001\n"
    result = csv_parser.parse_favorites_csv(content)

    assert result.parsed_rows[0].comment == ""


def test_empty_header_column_is_ignored():
    # The blank middle header column must be skipped, not collected.
    content = "name,,lab_partner,test_order_codes\nPanel,junk,LabCorp,001\n"
    result = csv_parser.parse_favorites_csv(content)

    assert result.parsed_rows[0].name == "Panel"
    assert result.parsed_rows[0].lab_partner == "LabCorp"


def test_csv_escape_quotes_values_with_separators():
    assert csv_parser._csv_escape("plain") == "plain"
    assert csv_parser._csv_escape("a,b") == '"a,b"'
    assert csv_parser._csv_escape('say "hi"') == '"say ""hi"""'


def test_parse_csv_line_skips_embedded_newline_chars():
    # splitlines() normally strips newlines; cover the in-field guard directly.
    assert csv_parser._parse_csv_line("a\rb,c") == ["ab", "c"]
