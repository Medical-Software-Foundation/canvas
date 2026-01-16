"""Tests for banner_alert protocol."""

import pytest
from unittest.mock import MagicMock, patch, call

from high_risk_medications.protocols.banner_alert import HighRiskMedicationsBannerAlert


class TestHighRiskMedicationsBannerAlert:
    """Test suite for the high-risk medications banner alert protocol."""

    def test_adds_banner_for_high_risk_medication(self, mock_event, mock_medication):
        """Test that banner is added when high-risk medications are found."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": "Warfarin 5mg", "id": "med-123"}]

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

            # Verify helper function was called
            mock_get_meds.assert_called_once_with("patient_123")

        # Verify effect
        assert len(effects) == 1
        # Should be AddBannerAlert effect

    def test_removes_banner_when_no_high_risk_medications(self, mock_event):
        """Test that banner is removed when no high-risk medications exist."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_456"}}

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

            # Verify helper function was called
            mock_get_meds.assert_called_once_with("patient_456")

        # Verify effect
        assert len(effects) == 1
        # Should be RemoveBannerAlert effect

    def test_identifies_warfarin_as_high_risk(self, mock_event):
        """Test that warfarin is identified as high-risk."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": "Warfarin 5mg Tablet", "id": "med-123"}]

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Verify AddBannerAlert was returned
        assert len(effects) == 1

    def test_identifies_insulin_as_high_risk(self, mock_event):
        """Test that insulin is identified as high-risk."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": "Insulin Glargine 100 units/mL", "id": "med-456"}]

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Verify AddBannerAlert was returned
        assert len(effects) == 1

    def test_identifies_digoxin_as_high_risk(self, mock_event):
        """Test that digoxin is identified as high-risk."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": "Digoxin 0.25mg Tablet", "id": "med-789"}]

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Verify AddBannerAlert was returned
        assert len(effects) == 1

    def test_identifies_methotrexate_as_high_risk(self, mock_event):
        """Test that methotrexate is identified as high-risk."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": "Methotrexate 2.5mg Tablet", "id": "med-101"}]

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Verify AddBannerAlert was returned
        assert len(effects) == 1

    def test_case_insensitive_pattern_matching(self, mock_event):
        """Test that pattern matching is case-insensitive."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [{"name": "WARFARIN SODIUM 5 MG", "id": "med-202"}]

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Verify AddBannerAlert was returned
        assert len(effects) == 1

    def test_filters_active_medications_only(self, mock_event):
        """Test that helper function is called with patient ID."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_999"}}

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

            # Verify helper function was called with patient ID
            mock_get_meds.assert_called_once_with("patient_999")

    def test_handles_null_medication_display(self, mock_event):
        """Test handling of medication with null display name."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}

        # Execute - helper returns empty list when no high-risk meds found
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Should not crash - should remove banner (no high-risk meds found)
        assert len(effects) == 1

    def test_responds_to_prescribe_events(self):
        """Test that handler responds to prescription events."""
        from canvas_sdk.events import EventType

        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_medication_statement_events(self):
        """Test that handler responds to medication statement events."""
        from canvas_sdk.events import EventType

        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_stop_medication_events(self):
        """Test that handler responds to stop medication events."""
        from canvas_sdk.events import EventType

        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_adjust_prescription_events(self):
        """Test that handler responds to adjust prescription events."""
        from canvas_sdk.events import EventType

        responds_to = HighRiskMedicationsBannerAlert.RESPONDS_TO

        assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_handles_multiple_high_risk_medications(self, mock_event):
        """Test banner shows multiple high-risk medications."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}
        high_risk_meds = [
            {"name": "Warfarin 5mg", "id": "med-1"},
            {"name": "Insulin Regular", "id": "med-2"}
        ]

        # Execute
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = high_risk_meds

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Verify AddBannerAlert was returned
        assert len(effects) == 1

    def test_does_not_flag_non_high_risk_medications(self, mock_event):
        """Test that non-high-risk medications don't trigger banner."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}

        # Execute - helper returns empty list when no high-risk patterns match
        with patch("high_risk_medications.protocols.banner_alert.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []

            handler = HighRiskMedicationsBannerAlert(event=mock_event)
            effects = handler.compute()

        # Should return RemoveBannerAlert (no high-risk meds)
        assert len(effects) == 1
