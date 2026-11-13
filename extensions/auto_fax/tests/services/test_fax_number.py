import pytest

from auto_fax.services.fax_number import e164, for_fax_effect, masked, ten_digits


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(555) 234-0100", "5552340100"),
        ("+1 555.234.0100", "5552340100"),
        ("15552340100", "5552340100"),
        ("555-234-0100 ext 22", "5552340100"),
        ("555 234 0100 x7", "5552340100"),
        (None, None),
        ("", None),
        ("234-0100", None),
        ("055-234-0100", None),
        ("155-234-0100", None),
        ("+44 20 7946 0958", None),
    ],
)
def test_ten_digits(raw, expected):
    assert ten_digits(raw) == expected


def test_formats():
    assert for_fax_effect("5552340100") == "15552340100"
    assert e164("5552340100") == "+15552340100"
    assert masked("5552340100") == "***-***-0100"
