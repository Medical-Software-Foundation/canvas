from labcorp_draw_guidance.domain.command_parsing import (
    extract_lab_partner_name,
    extract_test_identifiers,
)


def test_extract_lab_partner_name_from_plain_string() -> None:
    """Test that a plain string lab_partner value is returned as-is."""
    tested = extract_lab_partner_name({"lab_partner": "Labcorp"})

    assert tested == "Labcorp"


def test_extract_lab_partner_name_from_dict_text_key() -> None:
    """Test that a dict lab_partner value resolves via its 'text' key."""
    tested = extract_lab_partner_name({"lab_partner": {"value": "abc-123", "text": "Labcorp"}})

    assert tested == "Labcorp"


def test_extract_lab_partner_name_from_dict_falls_back_to_name_key() -> None:
    """Test that a dict lab_partner value falls back to 'name' when 'text' is absent."""
    tested = extract_lab_partner_name({"lab_partner": {"value": "abc-123", "name": "Labcorp"}})

    assert tested == "Labcorp"


def test_extract_lab_partner_name_returns_none_when_missing() -> None:
    """Test that a missing lab_partner field returns None."""
    tested = extract_lab_partner_name({})

    assert tested is None


def test_extract_lab_partner_name_returns_none_for_empty_string() -> None:
    """Test that an empty string lab_partner value returns None."""
    tested = extract_lab_partner_name({"lab_partner": ""})

    assert tested is None


def test_extract_lab_partner_name_returns_none_for_dict_with_no_usable_keys() -> None:
    """Test that a dict lab_partner value with no recognized keys returns None."""
    tested = extract_lab_partner_name({"lab_partner": {"unexpected_key": "Labcorp"}})

    assert tested is None


def test_extract_test_identifiers_from_plain_strings() -> None:
    """Test that a list of plain string test entries is returned unchanged (minus duplicates)."""
    tested = extract_test_identifiers({"tests": ["001453", "322000", "001453"]})

    assert tested == ["001453", "322000"]


def test_extract_test_identifiers_from_dicts() -> None:
    """Test that dict test entries resolve via the 'value' key first."""
    tested = extract_test_identifiers(
        {"tests": [{"value": "001453", "text": "CBC W/Diff"}, {"code": "322000"}]}
    )

    assert tested == ["001453", "322000"]


def test_extract_test_identifiers_falls_back_through_key_priority() -> None:
    """Test that a dict entry without 'value' or 'code' falls back to 'id' then 'text'."""
    tested = extract_test_identifiers({"tests": [{"id": "abc-123"}, {"text": "TSH"}]})

    assert tested == ["abc-123", "TSH"]


def test_extract_test_identifiers_skips_unresolvable_entries() -> None:
    """Test that entries with no usable identifier are skipped rather than raising."""
    tested = extract_test_identifiers({"tests": [{"unexpected_key": "x"}, "001453", 42]})

    assert tested == ["001453"]


def test_extract_test_identifiers_returns_empty_list_when_tests_missing() -> None:
    """Test that a missing 'tests' field returns an empty list."""
    tested = extract_test_identifiers({})

    assert tested == []


def test_extract_test_identifiers_returns_empty_list_when_tests_not_a_list() -> None:
    """Test that a non-list 'tests' field returns an empty list rather than raising."""
    tested = extract_test_identifiers({"tests": "not-a-list"})

    assert tested == []
