"""Tests for the bulk availability CSV import engine."""

from provider_availability.engine.csv_import import (
    ParseResult,
    build_records,
    generate_template_csv,
    parse_csv,
    validate_row,
)

HEADER = (
    "type,staff_key,location,visit_type,day,start,end,all_day,date,reason,"
    "hold_type,buffer_pre,buffer_post,min_lead_hours,slot_minutes,"
    "recurrence_frequency,recurrence_interval,effective_start,effective_end,group_key"
)


def _rule_row(**over):
    row = {
        "type": "rule",
        "staff_key": "1234567890",
        "location": "Main Clinic",
        "visit_type": "",
        "day": "monday",
        "start": "09:00",
        "end": "12:00",
        "recurrence_frequency": "weekly",
    }
    row.update(over)
    return row


# -- validate_row ------------------------------------------------------------


def test_validate_row_rejects_unknown_type():
    assert validate_row({"type": "widget", "staff_key": "1"}) == [
        "type must be one of: rule, block, rblock"
    ]


def test_validate_row_requires_staff_key():
    assert validate_row({"type": "rule", "staff_key": ""}) == ["staff_key is required"]


def test_validate_rule_row_valid_has_no_errors():
    assert validate_row(_rule_row()) == []


def test_validate_rule_row_bad_day():
    errors = validate_row(_rule_row(day="funday"))
    assert any("day must be one of" in e for e in errors)


def test_validate_rule_row_daily_ignores_day():
    row = _rule_row(recurrence_frequency="daily", day="")
    assert validate_row(row) == []


def test_validate_rule_row_bad_time_format():
    errors = validate_row(_rule_row(start="9am"))
    assert "start must be HH:MM (24-hour)" in errors


def test_validate_rule_row_start_after_end():
    errors = validate_row(_rule_row(start="17:00", end="09:00"))
    assert any("start must be before end" in e for e in errors)


def test_validate_rule_row_bad_integer_field():
    errors = validate_row(_rule_row(buffer_post="lots"))
    assert "buffer_post must be a whole number" in errors


def test_validate_rule_row_negative_lead_hours():
    errors = validate_row(_rule_row(min_lead_hours="-1"))
    assert "min_lead_hours must be >= 0" in errors


def test_validate_rule_row_slot_minutes_minimum_one():
    errors = validate_row(_rule_row(slot_minutes="0"))
    assert "slot_minutes must be >= 1" in errors


def test_validate_rule_row_bad_effective_date():
    errors = validate_row(_rule_row(effective_start="07/01/2026"))
    assert "effective_start must be YYYY-MM-DD" in errors


def test_validate_rule_row_bad_recurrence_frequency():
    errors = validate_row(_rule_row(recurrence_frequency="monthly"))
    assert any("recurrence_frequency must be one of" in e for e in errors)


def test_validate_rule_row_bad_recurrence_interval():
    errors = validate_row(_rule_row(recurrence_interval="0"))
    assert "recurrence_interval must be >= 1" in errors


def test_validate_block_row_requires_date():
    row = {"type": "block", "staff_key": "1", "all_day": "true", "date": ""}
    assert "date is required for a block row" in validate_row(row)


def test_validate_block_row_bad_date():
    row = {"type": "block", "staff_key": "1", "all_day": "true", "date": "nope"}
    assert "date must be YYYY-MM-DD" in validate_row(row)


def test_validate_block_row_all_day_needs_no_window():
    row = {"type": "block", "staff_key": "1", "all_day": "true", "date": "2026-07-04"}
    assert validate_row(row) == []


def test_validate_block_row_timed_needs_window():
    row = {"type": "block", "staff_key": "1", "all_day": "false", "date": "2026-07-04",
           "start": "09:00", "end": "10:00"}
    assert validate_row(row) == []


def test_validate_block_row_timed_missing_window():
    row = {"type": "block", "staff_key": "1", "all_day": "false", "date": "2026-07-04"}
    assert "start must be HH:MM (24-hour)" in validate_row(row)


def test_validate_rblock_row_valid():
    row = {"type": "rblock", "staff_key": "1", "day": "monday", "start": "12:00",
           "end": "13:00", "hold_type": "same_day"}
    assert validate_row(row) == []


def test_validate_rblock_row_bad_hold_type():
    row = {"type": "rblock", "staff_key": "1", "day": "monday", "start": "12:00",
           "end": "13:00", "hold_type": "maybe"}
    assert any("hold_type must be one of" in e for e in validate_row(row))


# -- parse_csv ---------------------------------------------------------------


def test_parse_csv_empty_returns_empty_result():
    result = parse_csv("")
    assert isinstance(result, ParseResult)
    assert result.total_rows == 0
    assert result.valid_rows == []


def test_parse_csv_header_only():
    result = parse_csv(HEADER + "\n")
    assert result.total_rows == 0


def test_parse_csv_valid_and_error_rows():
    body = (
        HEADER + "\n"
        + "rule,1234567890,Main Clinic,,monday,09:00,12:00,,,,,,,,,weekly,1,,,\n"
        + "rule,1234567890,Main Clinic,,funday,09:00,12:00,,,,,,,,,weekly,1,,,\n"
    )
    result = parse_csv(body)
    assert result.total_rows == 2
    assert len(result.valid_rows) == 1
    assert len(result.error_rows) == 1
    assert result.error_rows[0].row_number == 3


def test_parse_csv_skips_blank_lines():
    body = HEADER + "\n\n" + "rule,1234567890,Main Clinic,,monday,09:00,12:00,,,,,,,,,weekly,1,,,\n\n"
    result = parse_csv(body)
    assert result.total_rows == 1
    assert len(result.valid_rows) == 1


def test_parse_csv_strips_bom():
    body = "﻿" + HEADER + "\nrule,1234567890,Main Clinic,,monday,09:00,12:00,,,,,,,,,weekly,1,,,\n"
    result = parse_csv(body)
    assert len(result.valid_rows) == 1


def test_parse_csv_handles_quoted_reason_with_comma():
    body = (
        HEADER + "\n"
        + 'block,1234567890,,,,,,true,2026-07-04,"Closed, all day",,,,,,,,,,\n'
    )
    result = parse_csv(body)
    assert len(result.valid_rows) == 1
    assert result.valid_rows[0].data["reason"] == "Closed, all day"


def test_parse_csv_short_row_pads_missing_fields():
    body = HEADER + "\n" + "rule,1234567890,Main Clinic,,monday,09:00,12:00\n"
    result = parse_csv(body)
    assert len(result.valid_rows) == 1


# -- build_records -----------------------------------------------------------

VALID_STAFF = {"1234567890", "9999999999"}
LOCATION_MAP = {"main clinic": "loc-1", "east clinic": "loc-2"}
VISIT_MAP = {"new patient": "vt-1"}


def _valid_rows(rows):
    """Build a ParseResult's valid_rows from raw dicts, asserting each is valid."""
    result = parse_csv(HEADER + "\n" + "\n".join(
        ",".join(_line(r)) for r in rows
    ))
    assert result.error_rows == [], [e.errors for e in result.error_rows]
    return result.valid_rows


def _line(row):
    order = HEADER.split(",")
    return [row.get(col, "") for col in order]


def test_build_records_groups_windows_into_one_rule():
    rows = [
        _rule_row(day="monday", start="09:00", end="12:00"),
        _rule_row(day="monday", start="13:00", end="17:00"),
        _rule_row(day="wednesday", start="09:00", end="12:00"),
    ]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    assert len(records) == 1
    rule = records[0]
    assert rule["kind"] == "rule"
    assert rule["provider_id"] == "1234567890"
    assert rule["location_ids"] == ["loc-1"]
    assert rule["weekly_schedule"]["monday"] == [
        {"start": "09:00", "end": "12:00"},
        {"start": "13:00", "end": "17:00"},
    ]
    assert rule["weekly_schedule"]["wednesday"] == [{"start": "09:00", "end": "12:00"}]
    assert sorted(rule["source_rows"]) == [2, 3, 4]


def test_build_records_separate_rules_for_different_locations():
    rows = [
        _rule_row(location="Main Clinic"),
        _rule_row(location="East Clinic"),
    ]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    assert len(records) == 2


def test_build_records_group_key_forces_merge():
    rows = [
        _rule_row(location="Main Clinic", group_key="k1", day="monday"),
        _rule_row(location="East Clinic", group_key="k1", day="tuesday"),
    ]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    assert len(records) == 1


def test_build_records_defaults_buffer_and_booking():
    records, _ = build_records(_valid_rows([_rule_row()]), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    rule = records[0]
    assert rule["buffer_minutes"] == {"pre": 0, "post": 15}
    assert rule["booking_interval"] == {"min_lead_hours": 24, "slot_granularity_minutes": 15}


def test_build_records_custom_buffer_and_booking():
    rows = [_rule_row(buffer_pre="10", buffer_post="20", min_lead_hours="48", slot_minutes="30")]
    records, _ = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    rule = records[0]
    assert rule["buffer_minutes"] == {"pre": 10, "post": 20}
    assert rule["booking_interval"] == {"min_lead_hours": 48, "slot_granularity_minutes": 30}


def test_build_records_resolves_visit_type():
    rows = [_rule_row(visit_type="New Patient")]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    assert records[0]["visit_types"] == ["vt-1"]


def test_build_records_unknown_provider_is_error():
    rows = [_rule_row(staff_key="0000000000")]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert records == []
    assert len(errors) == 1
    assert "not found" in errors[0].errors[0]


def test_build_records_unknown_location_is_error():
    rows = [_rule_row(location="Mian Clinic")]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert records == []
    assert "location 'Mian Clinic' not found" in errors[0].errors


def test_build_records_unknown_visit_type_is_error():
    rows = [_rule_row(visit_type="Telehealth")]
    _, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert "visit_type 'Telehealth' not found" in errors[0].errors


def test_build_records_empty_location_means_all():
    rows = [_rule_row(location="")]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    assert records[0]["location_ids"] == []


def test_build_records_multiple_locations_pipe_separated():
    rows = [_rule_row(location="Main Clinic|East Clinic")]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    assert sorted(records[0]["location_ids"]) == ["loc-1", "loc-2"]


def test_build_records_intra_group_window_overlap_is_error():
    rows = [
        _rule_row(day="monday", start="09:00", end="12:00"),
        _rule_row(day="monday", start="11:00", end="13:00"),
    ]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert len(errors) == 1
    assert "overlaps another monday window" in errors[0].errors[0]
    # First window still recorded on the rule
    assert records[0]["weekly_schedule"]["monday"] == [{"start": "09:00", "end": "12:00"}]


def test_build_records_daily_rule_uses_time_windows():
    rows = [
        _rule_row(recurrence_frequency="daily", day="", start="09:00", end="12:00"),
        _rule_row(recurrence_frequency="daily", day="", start="13:00", end="17:00"),
    ]
    records, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    assert records[0]["time_windows"] == [
        {"start": "09:00", "end": "12:00"},
        {"start": "13:00", "end": "17:00"},
    ]


def test_build_records_daily_overlap_is_error():
    rows = [
        _rule_row(recurrence_frequency="daily", day="", start="09:00", end="12:00"),
        _rule_row(recurrence_frequency="daily", day="", start="10:00", end="11:00"),
    ]
    _, errors = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert "overlaps another window in the same daily group" in errors[0].errors[0]


def test_build_records_all_day_block():
    row = {"type": "block", "staff_key": "1234567890", "all_day": "true",
           "date": "2026-07-04", "reason": "Holiday"}
    records, errors = build_records(_valid_rows([row]), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    block = records[0]
    assert block["kind"] == "block"
    assert block["start"] == "2026-07-04T00:00:00"
    assert block["end"] == "2026-07-04T23:59:59"
    assert block["all_day"] is True
    assert block["reason"] == "Holiday"


def test_build_records_timed_block():
    row = {"type": "block", "staff_key": "1234567890", "all_day": "false",
           "date": "2026-07-04", "start": "09:00", "end": "10:30"}
    records, _ = build_records(_valid_rows([row]), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    block = records[0]
    assert block["start"] == "2026-07-04T09:00:00"
    assert block["end"] == "2026-07-04T10:30:00"
    assert block["all_day"] is False


def test_build_records_recurring_block():
    row = {"type": "rblock", "staff_key": "1234567890", "day": "monday",
           "start": "12:00", "end": "13:00", "reason": "Lunch", "hold_type": "same_day"}
    records, errors = build_records(_valid_rows([row]), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert errors == []
    rb = records[0]
    assert rb["kind"] == "rblock"
    assert rb["hold_type"] == "same_day"
    assert rb["weekly_schedule"]["monday"] == [{"start": "12:00", "end": "13:00"}]


def test_build_records_recurring_block_default_hold_none():
    row = {"type": "rblock", "staff_key": "1234567890", "day": "monday",
           "start": "12:00", "end": "13:00"}
    records, _ = build_records(_valid_rows([row]), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert records[0]["hold_type"] == "none"


def test_build_records_effective_dates_preserved():
    rows = [_rule_row(effective_start="2026-07-01", effective_end="2026-12-31")]
    records, _ = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert records[0]["effective_start"] == "2026-07-01"
    assert records[0]["effective_end"] == "2026-12-31"


def test_build_records_no_effective_dates_are_none():
    records, _ = build_records(_valid_rows([_rule_row()]), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert records[0]["effective_start"] is None
    assert records[0]["effective_end"] is None


# -- template ----------------------------------------------------------------


def test_records_have_no_underscore_keys():
    # The Canvas RestrictedPython sandbox forbids subscripting dict keys that
    # start with "_". Every record dict must therefore avoid such keys.
    rows = [
        _rule_row(),
        {"type": "block", "staff_key": "1234567890", "all_day": "true", "date": "2026-07-04"},
        {"type": "rblock", "staff_key": "1234567890", "day": "monday", "start": "12:00", "end": "13:00"},
    ]
    records, _ = build_records(_valid_rows(rows), VALID_STAFF, LOCATION_MAP, VISIT_MAP)
    assert records
    for rec in records:
        assert not any(k.startswith("_") for k in rec), rec


def test_generate_template_csv_round_trips():
    template = generate_template_csv()
    result = parse_csv(template)
    assert result.error_rows == []
    assert result.total_rows == 4
    kinds = {r.data["type"] for r in result.valid_rows}
    assert kinds == {"rule", "block", "rblock"}
