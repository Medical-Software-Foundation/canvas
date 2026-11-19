"""Tests for the patient_sex_banner Protocol event handler."""
from unittest.mock import patch

from patient_sex_banner.protocols.my_protocol import Protocol

MODULE = "patient_sex_banner.protocols.my_protocol"


def test_responds_only_to_patient_events():
    """Lifecycle events must stay unsubscribed so install never scans all patients."""
    assert len(Protocol.RESPONDS_TO) == 2


@patch(f"{MODULE}.banner_effect_for_patient")
@patch(f"{MODULE}.Patient")
def test_reconciles_only_the_event_patient(mock_patient_cls, mock_reconcile, protocol, mock_patient):
    """compute() fetches the single event patient and never scans the whole panel."""
    mock_patient_cls.objects.get.return_value = mock_patient

    result = protocol.compute()

    mock_patient_cls.objects.get.assert_called_once_with(id="patient-uuid-123")
    mock_patient_cls.objects.all.assert_not_called()
    mock_reconcile.assert_called_once_with(mock_patient)
    assert result == [mock_reconcile.return_value]


@patch(f"{MODULE}.banner_effect_for_patient")
@patch(f"{MODULE}.Patient")
def test_missing_patient_returns_no_effects(mock_patient_cls, mock_reconcile, protocol):
    """A stale event for a deleted patient returns [] instead of raising."""

    class DoesNotExist(Exception):
        pass

    mock_patient_cls.DoesNotExist = DoesNotExist
    mock_patient_cls.objects.get.side_effect = DoesNotExist()

    assert protocol.compute() == []
    mock_reconcile.assert_not_called()
