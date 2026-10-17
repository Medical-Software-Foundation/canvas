"""Tests for the shared banner-effect helpers."""
from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.patient import SexAtBirth

from patient_sex_banner import banner

MODULE = "patient_sex_banner.banner"


def _patient(sex, pid="patient-1"):
    p = MagicMock()
    p.id = pid
    p.sex_at_birth = sex
    return p


def test_sex_needs_banner_true_for_non_binary():
    assert banner.sex_needs_banner("O") is True


def test_sex_needs_banner_false_for_female_and_male():
    assert banner.sex_needs_banner(SexAtBirth.FEMALE.value) is False
    assert banner.sex_needs_banner(SexAtBirth.MALE.value) is False


@patch(f"{MODULE}.AddBannerAlert")
def test_add_banner_effect_builds_alert(mock_add):
    result = banner.add_banner_effect(_patient("O"))

    mock_add.assert_called_once()
    kwargs = mock_add.call_args.kwargs
    assert kwargs["key"] == "sex-banner"
    assert kwargs["patient_id"] == "patient-1"
    assert "WARNING: Patient sex is O" in kwargs["narrative"]
    assert result == mock_add.return_value.apply.return_value


@patch(f"{MODULE}.RemoveBannerAlert")
def test_remove_banner_effect_builds_remove(mock_remove):
    result = banner.remove_banner_effect(_patient(SexAtBirth.FEMALE.value))

    mock_remove.assert_called_once()
    kwargs = mock_remove.call_args.kwargs
    assert kwargs["key"] == "sex-banner"
    assert kwargs["patient_id"] == "patient-1"
    assert result == mock_remove.return_value.apply.return_value


@patch(f"{MODULE}.AddBannerAlert")
@patch(f"{MODULE}.RemoveBannerAlert")
def test_reconcile_adds_when_not_binary(mock_remove, mock_add):
    result = banner.banner_effect_for_patient(_patient("UNK"))

    mock_add.assert_called_once()
    mock_remove.assert_not_called()
    assert result == mock_add.return_value.apply.return_value


@patch(f"{MODULE}.AddBannerAlert")
@patch(f"{MODULE}.RemoveBannerAlert")
def test_reconcile_removes_when_male(mock_remove, mock_add):
    result = banner.banner_effect_for_patient(_patient(SexAtBirth.MALE.value))

    mock_remove.assert_called_once()
    mock_add.assert_not_called()
    assert result == mock_remove.return_value.apply.return_value
