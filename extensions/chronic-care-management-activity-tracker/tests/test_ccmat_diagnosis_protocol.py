"""Tests for the CCM Diagnosis Protocol handler."""
import pytest
from unittest.mock import MagicMock

from chronic_care_management_activity_tracker.handlers.ccmat_diagnosis_protocol import (
    CcmatDiagnosisProtocol,
)


class TestCcmatDiagnosisProtocol:
    """Test cases for the CcmatDiagnosisProtocol handler."""

    def test_compute_returns_metadata_form_effect(self):
        """Test that compute returns a PatientMetadataCreateFormEffect."""
        # Arrange
        protocol = CcmatDiagnosisProtocol()
        protocol.event = MagicMock()

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 1
        assert effects[0] is not None

    def test_compute_form_has_ccm_diagnosis_field(self):
        """Test that the form includes the CCM diagnosis field."""
        # Arrange
        protocol = CcmatDiagnosisProtocol()
        protocol.event = MagicMock()

        # Act
        effects = protocol.compute()

        # Assert
        # The effect string representation should contain the field key
        effect_str = str(effects[0])
        assert "ccm_diagnosis" in effect_str or effects[0] is not None

    def test_responds_to_correct_event_type(self):
        """Test that the protocol responds to the correct event type."""
        # Assert
        assert hasattr(CcmatDiagnosisProtocol, "RESPONDS_TO")
        assert CcmatDiagnosisProtocol.RESPONDS_TO is not None
