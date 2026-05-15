"""Tests for parse_schedulable_roles."""

from provider_availability_manager.utils.staff_lookup import parse_schedulable_roles


def test_empty_string_returns_empty_list():
    assert parse_schedulable_roles("") == []


def test_none_returns_empty_list():
    assert parse_schedulable_roles(None) == []


def test_json_array_parsed():
    assert parse_schedulable_roles('["MD","NP"]') == ["MD", "NP"]


def test_comma_separated_parsed():
    assert parse_schedulable_roles("MD,NP,PA") == ["MD", "NP", "PA"]


def test_comma_separated_strips_whitespace():
    assert parse_schedulable_roles("MD, NP, PA") == ["MD", "NP", "PA"]


def test_malformed_json_falls_back_to_comma_split():
    assert parse_schedulable_roles('"MD","NP"') == ["MD", "NP"]
