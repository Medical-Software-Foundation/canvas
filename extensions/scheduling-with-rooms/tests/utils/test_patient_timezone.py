"""Tests for utils/patient_timezone.py."""

from unittest.mock import patch

import pytest

from scheduling_with_rooms.utils.patient_timezone import get_patient_timezone

MODULE = "scheduling_with_rooms.utils.patient_timezone"


@pytest.fixture
def mock_setting():
    """Patch PatientSetting; no row exists by default."""
    with patch(f"{MODULE}.PatientSetting") as setting:
        setting.objects.filter.return_value.values.return_value.first.return_value = None
        yield setting


def _row(value):
    return {"value": value}


def test_returns_the_preferred_scheduling_timezone(mock_setting):
    mock_setting.objects.filter.return_value.values.return_value.first.return_value = _row(
        "America/New_York"
    )

    assert get_patient_timezone("pt-1") == "America/New_York"


def test_filters_on_the_patient_and_setting_name(mock_setting):
    get_patient_timezone("pt-1")

    kwargs = mock_setting.objects.filter.call_args.kwargs
    assert kwargs["patient__id"] == "pt-1"
    assert kwargs["name"] == "preferredSchedulingTimezone"


def test_no_setting_row_returns_empty_string(mock_setting):
    assert get_patient_timezone("pt-1") == ""


def test_value_is_stripped(mock_setting):
    mock_setting.objects.filter.return_value.values.return_value.first.return_value = _row(
        "  Asia/Saigon  "
    )

    assert get_patient_timezone("pt-1") == "Asia/Saigon"


@pytest.mark.parametrize("value", [None, 42, {"tz": "America/Denver"}, ["America/Denver"]])
def test_non_string_values_are_rejected(mock_setting, value):
    """The column is a JSONField, so it can hold shapes we can't use."""
    mock_setting.objects.filter.return_value.values.return_value.first.return_value = _row(value)

    assert get_patient_timezone("pt-1") == ""


def test_empty_string_value_returns_empty_string(mock_setting):
    mock_setting.objects.filter.return_value.values.return_value.first.return_value = _row("")

    assert get_patient_timezone("pt-1") == ""


def test_makes_no_outbound_http_call(mock_setting):
    """This used to be a FHIR read; it's a plain DB lookup now."""
    mock_setting.objects.filter.return_value.values.return_value.first.return_value = _row(
        "America/New_York"
    )
    with patch("canvas_sdk.utils.http.Http") as mock_http:
        get_patient_timezone("pt-1")

        mock_http.assert_not_called()
