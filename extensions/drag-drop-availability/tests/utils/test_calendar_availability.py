"""Tests for calendar_availability.py (availability manager: title parsing only)."""

from drag_drop_availability.utils.calendar_availability import parse_calendar_title


# parse_calendar_title -------------------------------------------------

def test_parse_calendar_title_three_parts():
    name, ctype, loc = parse_calendar_title("Christopher Taylor: Clinic: Florida")
    assert name == "Christopher Taylor"
    assert ctype == "Clinic"
    assert loc == "Florida"


def test_parse_calendar_title_two_parts():
    name, ctype, loc = parse_calendar_title("Richard Wilson: Clinic")
    assert name == "Richard Wilson"
    assert ctype == "Clinic"
    assert loc is None


def test_parse_calendar_title_one_part():
    name, ctype, loc = parse_calendar_title("Just A Name")
    assert name == "Just A Name"
    assert ctype == ""
    assert loc is None


def test_parse_calendar_title_location_with_colon():
    name, ctype, loc = parse_calendar_title("Dr. X: Clinic: Loc:Sub")
    assert loc == "Loc:Sub"
