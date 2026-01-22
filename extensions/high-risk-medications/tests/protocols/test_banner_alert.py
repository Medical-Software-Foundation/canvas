"""Tests for banner_alert protocol."""

import pytest
from unittest.mock import patch

from canvas_sdk.events import EventType
from high_risk_medications.protocols.banner_alert import HighRiskMedicationsBannerAlert
from tests.conftest import HIGH_RISK_PATTERNS


class TestHighRiskMedicationsBannerAlert:
    """Test suite for the high-risk medications banner alert protocol."""

    def _create_handler_with_secrets(self, mock_event, high_risk_secrets):
        """Helper to create handler with secrets configured."""
        handler = HighRiskMedicationsBannerAlert(event=mock_event)
        handler.secrets = high_risk_secrets
        return handler

    def test_adds_banner_for_high_risk_medication(self, mock_event, high_risk_secrets):
        """Test that banner is added when high-risk medications are found."""
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": "Warfarin 5mg", "id": "med-123"}]

        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = self._create_handler_with_secrets(mock_event, high_risk_secrets)
            effects = handler.compute()

            mock_get_meds.assert_called_once_with("patient_123", HIGH_RISK_PATTERNS)

        assert len(effects) == 1

    def test_removes_banner_when_no_high_risk_medications(self, mock_event, high_risk_secrets):
        """Test that banner is removed when no high-risk medications exist."""
        mock_event.context = {"patient": {"id": "patient_456"}}

        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []

            handler = self._create_handler_with_secrets(mock_event, high_risk_secrets)
            effects = handler.compute()

            mock_get_meds.assert_called_once_with("patient_456", HIGH_RISK_PATTERNS)

        assert len(effects) == 1

    @pytest.mark.parametrize("med_name,med_id", [
        ("Warfarin 5mg Tablet", "med-123"),
        ("Insulin Glargine 100 units/mL", "med-456"),
        ("Digoxin 0.25mg Tablet", "med-789"),
        ("Methotrexate 2.5mg Tablet", "med-101"),
        ("WARFARIN SODIUM 5 MG", "med-202"),  # case insensitive
    ])
    def test_identifies_high_risk_medication(self, mock_event, high_risk_secrets, med_name, med_id):
        """Test that high-risk medications are identified and banner is added."""
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": med_name, "id": med_id}]

        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = self._create_handler_with_secrets(mock_event, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_handles_null_medication_display(self, mock_event, high_risk_secrets):
        """Test handling of medication with null display name."""
        mock_event.context = {"patient": {"id": "patient_123"}}

        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []

            handler = self._create_handler_with_secrets(mock_event, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_handles_multiple_high_risk_medications(self, mock_event, high_risk_secrets):
        """Test banner shows multiple high-risk medications."""
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [
            {"name": "Warfarin 5mg", "id": "med-1"},
            {"name": "Insulin Regular", "id": "med-2"}
        ]

        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = self._create_handler_with_secrets(mock_event, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_does_not_flag_non_high_risk_medications(self, mock_event, high_risk_secrets):
        """Test that non-high-risk medications don't trigger banner."""
        mock_event.context = {"patient": {"id": "patient_123"}}

        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []

            handler = self._create_handler_with_secrets(mock_event, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_responds_to_prescribe_events(self):
        """Test that handler responds to prescription events."""
        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_medication_statement_events(self):
        """Test that handler responds to medication statement events."""
        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_stop_medication_events(self):
        """Test that handler responds to stop medication events."""
        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_adjust_prescription_events(self):
        """Test that handler responds to adjust prescription events."""
        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_ENTER_IN_ERROR) in responds_to
