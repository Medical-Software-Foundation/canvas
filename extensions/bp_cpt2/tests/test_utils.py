# To run the tests, use the command `pytest` in the terminal or uv run pytest.

from bp_cpt2.utils import to_bool


def test_to_bool_returns_true_for_truthy_strings() -> None:
    """Test that to_bool returns True for various truthy string values."""
    truthy_values = [
        'true',
        'True',
        'TRUE',
        'yes',
        'Yes',
        'YES',
        'y',
        'Y',
        '1',
        't',
        'T',
        'on',
        'ON',
        'enabled',
        'ENABLED',
        'anything',  # Any non-falsy string is truthy
    ]

    for value in truthy_values:
        assert to_bool(value) is True, f"Expected '{value}' to be truthy"


def test_to_bool_returns_false_for_falsy_strings() -> None:
    """Test that to_bool returns False for various falsy string values."""
    falsy_values = [
        'false',
        'False',
        'FALSE',
        'f',
        'F',
        'n',
        'N',
        'no',
        'No',
        'NO',
        '0',
    ]

    for value in falsy_values:
        assert to_bool(value) is False, f"Expected '{value}' to be falsy"


def test_to_bool_returns_false_for_empty_string() -> None:
    """Test that to_bool returns False for empty string."""
    assert to_bool('') is False


def test_to_bool_returns_false_for_none() -> None:
    """Test that to_bool returns False for None (empty value)."""
    # In Python, None will be falsy in the initial if check
    assert to_bool(None) is False


def test_to_bool_handles_whitespace() -> None:
    """Test that to_bool strips whitespace from values."""
    # Whitespace around truthy values
    assert to_bool('  true  ') is True
    assert to_bool('\ttrue\t') is True
    assert to_bool('  yes  ') is True

    # Whitespace around falsy values
    assert to_bool('  false  ') is False
    assert to_bool('\tno\t') is False
    assert to_bool('  0  ') is False


def test_to_bool_handles_mixed_case() -> None:
    """Test that to_bool is case-insensitive."""
    # Mixed case truthy
    assert to_bool('TrUe') is True
    assert to_bool('yEs') is True

    # Mixed case falsy
    assert to_bool('FaLsE') is False
    assert to_bool('nO') is False


def test_to_bool_whitespace_only_returns_false() -> None:
    """Test that to_bool returns False for whitespace-only strings."""
    whitespace_values = [
        '   ',
        '\t',
        '\n',
        '\r',
        '  \t\n  ',
    ]

    for value in whitespace_values:
        # Whitespace-only strings become empty after strip(), which is in the falsy list
        assert to_bool(value) is False, f"Expected whitespace-only '{repr(value)}' to be falsy"


def test_to_bool_returns_true_for_numeric_strings() -> None:
    """Test that to_bool returns True for non-zero numeric strings."""
    numeric_truthy = [
        '1',
        '2',
        '100',
        '-1',
        '0.5',
    ]

    for value in numeric_truthy:
        if value != '0':  # 0 is explicitly falsy
            assert to_bool(value) is True, f"Expected numeric '{value}' to be truthy"


def test_to_bool_real_world_usage() -> None:
    """Test to_bool with real-world secret values as used in the handlers."""
    # These simulate actual secret values from Canvas
    assert to_bool('true') is True  # INCLUDE_TREATMENT_PLAN_CODES = 'true'
    assert to_bool('false') is False  # INCLUDE_TREATMENT_PLAN_CODES = 'false'
    assert to_bool('yes') is True  # SHOW_BUTTON_FOR_MANUAL_TRIGGER = 'yes'
    assert to_bool('no') is False  # SHOW_BUTTON_FOR_MANUAL_TRIGGER = 'no'
    assert to_bool('') is False  # Secret not set or empty
