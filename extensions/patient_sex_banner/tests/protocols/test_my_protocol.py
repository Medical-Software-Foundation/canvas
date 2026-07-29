"""Tests for the patient_sex_banner Protocol handler."""
from unittest.mock import patch

from canvas_sdk.v1.data.patient import SexAtBirth

from patient_sex_banner.protocols.my_protocol import Protocol

MODULE = "patient_sex_banner.protocols.my_protocol"


def test_responds_only_to_patient_events():
    """Lifecycle events must stay unsubscribed so install never scans all patients."""
    assert len(Protocol.RESPONDS_TO) == 2


@patch(f"{MODULE}.RemoveBannerAlert")
@patch(f"{MODULE}.AddBannerAlert")
@patch(f"{MODULE}.Patient")
def test_adds_alert_when_sex_not_male_or_female(
    mock_patient_cls, mock_add, mock_remove, protocol, mock_patient
):
    """A non-binary sex-at-birth value adds an alert banner for that one patient."""
    mock_patient.sex_at_birth = "O"
    mock_patient_cls.objects.get.return_value = mock_patient

    result = protocol.compute()

    mock_patient_cls.objects.get.assert_called_once_with(id="patient-uuid-123")
    mock_patient_cls.objects.all.assert_not_called()
    mock_add.assert_called_once()
    mock_remove.assert_not_called()
    kwargs = mock_add.call_args.kwargs
    assert kwargs["key"] == "sex-banner"
    assert kwargs["patient_id"] == "patient-uuid-123"
    assert "WARNING: Patient sex is O" in kwargs["narrative"]
    assert result == [mock_add.return_value.apply.return_value]


@patch(f"{MODULE}.RemoveBannerAlert")
@patch(f"{MODULE}.AddBannerAlert")
@patch(f"{MODULE}.Patient")
def test_removes_banner_when_sex_is_female(
    mock_patient_cls, mock_add, mock_remove, protocol, mock_patient
):
    """A female sex-at-birth value removes any existing banner for that patient."""
    mock_patient.sex_at_birth = SexAtBirth.FEMALE.value
    mock_patient_cls.objects.get.return_value = mock_patient

    result = protocol.compute()

    mock_remove.assert_called_once()
    mock_add.assert_not_called()
    kwargs = mock_remove.call_args.kwargs
    assert kwargs["key"] == "sex-banner"
    assert kwargs["patient_id"] == "patient-uuid-123"
    assert result == [mock_remove.return_value.apply.return_value]


@patch(f"{MODULE}.RemoveBannerAlert")
@patch(f"{MODULE}.AddBannerAlert")
@patch(f"{MODULE}.Patient")
def test_removes_banner_when_sex_is_male(
    mock_patient_cls, mock_add, mock_remove, protocol, mock_patient
):
    """A male sex-at-birth value removes any existing banner for that patient."""
    mock_patient.sex_at_birth = SexAtBirth.MALE.value
    mock_patient_cls.objects.get.return_value = mock_patient

    protocol.compute()

    mock_remove.assert_called_once()
    mock_add.assert_not_called()


@patch(f"{MODULE}.RemoveBannerAlert")
@patch(f"{MODULE}.AddBannerAlert")
@patch(f"{MODULE}.Patient")
def test_missing_patient_returns_no_effects(mock_patient_cls, mock_add, mock_remove, protocol):
    """A stale event for a deleted patient returns [] instead of raising."""

    class DoesNotExist(Exception):
        pass

    mock_patient_cls.DoesNotExist = DoesNotExist
    mock_patient_cls.objects.get.side_effect = DoesNotExist()

    assert protocol.compute() == []
    mock_add.assert_not_called()
    mock_remove.assert_not_called()
