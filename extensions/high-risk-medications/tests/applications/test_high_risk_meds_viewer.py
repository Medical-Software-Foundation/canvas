"""Tests for high_risk_meds_viewer application."""

import pytest
from unittest.mock import MagicMock, patch

from canvas_sdk.effects import EffectType
from high_risk_medications.applications.high_risk_meds_viewer import (
    HighRiskMedsViewer,
    HighRiskMedsActionButton,
)


class TestHighRiskMedsViewer:
    """Test suite for the high-risk medications viewer application."""

    def test_on_open_returns_launch_modal_effect(self, mock_event):
        """Test that on_open returns a LaunchModalEffect."""
        # Setup
        mock_event.context = {"patient": {"id": "patient-123"}}

        # Execute
        viewer = HighRiskMedsViewer(event=mock_event)
        effect = viewer.on_open()

        # Verify
        assert effect is not None
        assert effect.type == EffectType.LAUNCH_MODAL

    def test_on_open_constructs_correct_url(self, mock_event):
        """Test that URL includes patient ID."""
        # Setup
        patient_id = "abc-123-def"
        mock_event.context = {"patient": {"id": patient_id}}

        # Execute
        viewer = HighRiskMedsViewer(event=mock_event)
        effect = viewer.on_open()

        # Verify URL contains patient ID
        assert patient_id in effect.payload

    def test_on_open_handles_missing_patient_context(self, mock_event):
        """Test graceful handling when patient context is missing."""
        # Setup
        mock_event.context = {}

        # Execute
        viewer = HighRiskMedsViewer(event=mock_event)
        effects = viewer.on_open()

        # Verify returns empty list
        assert effects == []

    def test_on_open_handles_missing_patient_id(self, mock_event):
        """Test graceful handling when patient ID is None."""
        # Setup
        mock_event.context = {"patient": {"id": None}}

        # Execute
        viewer = HighRiskMedsViewer(event=mock_event)
        effects = viewer.on_open()

        # Verify returns empty list
        assert effects == []

    def test_on_open_handles_missing_patient_key(self, mock_event):
        """Test graceful handling when patient key is missing from context."""
        # Setup
        mock_event.context = {"user": {"id": "staff-123"}}

        # Execute
        viewer = HighRiskMedsViewer(event=mock_event)
        effects = viewer.on_open()

        # Verify returns empty list
        assert effects == []


class TestHighRiskMedsActionButton:
    """Test suite for the high-risk medications action button."""

    def test_button_title_is_configured(self):
        """Test that button title is set."""
        assert HighRiskMedsActionButton.BUTTON_TITLE == "High Risk Medications"

    def test_button_key_is_configured(self):
        """Test that button key is set."""
        assert HighRiskMedsActionButton.BUTTON_KEY == "high-risk-meds"

    def test_button_location_is_medications_section(self):
        """Test that button appears in medications section."""
        from canvas_sdk.handlers.action_button import ActionButton

        assert (
            HighRiskMedsActionButton.BUTTON_LOCATION
            == ActionButton.ButtonLocation.CHART_SUMMARY_MEDICATIONS_SECTION
        )

    def test_visible_returns_true_for_warfarin(self, mock_event):
        """Test that button is visible when patient has warfarin."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-123"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = "Warfarin 5mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify
        assert is_visible is True
        mock_objects.filter.assert_called_once_with(
            patient__id="patient-123", status="active"
        )

    def test_visible_returns_true_for_insulin(self, mock_event):
        """Test that button is visible when patient has insulin."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-456"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = "Insulin Glargine 100 units/mL"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify
        assert is_visible is True

    def test_visible_returns_true_for_digoxin(self, mock_event):
        """Test that button is visible when patient has digoxin."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-789"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = "Digoxin 0.25mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify
        assert is_visible is True

    def test_visible_returns_true_for_methotrexate(self, mock_event):
        """Test that button is visible when patient has methotrexate."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-101"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = "Methotrexate 2.5mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify
        assert is_visible is True

    def test_visible_returns_false_for_non_high_risk_medication(self, mock_event):
        """Test that button is hidden when patient has no high-risk medications."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-202"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = "Acetaminophen 500mg Tablet"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify
        assert is_visible is False

    def test_visible_returns_false_when_no_medications(self, mock_event):
        """Test that button is hidden when patient has no medications."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-303"
        mock_event.target = mock_target

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = []

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify
        assert is_visible is False

    def test_visible_is_case_insensitive(self, mock_event):
        """Test that pattern matching is case-insensitive."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-404"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = "WARFARIN SODIUM 5 MG"
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify
        assert is_visible is True

    def test_visible_handles_null_medication_display(self, mock_event):
        """Test that button handles medication with null display name."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-505"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = None
        mock_med.codings.first.return_value = mock_coding

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            is_visible = button.visible()

        # Verify - should not crash, should return False
        assert is_visible is False

    def test_handle_returns_launch_modal_effect(self, mock_event):
        """Test that handle returns a LaunchModalEffect."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-606"
        mock_event.target = mock_target

        # Execute
        button = HighRiskMedsActionButton(event=mock_event)
        effects = button.handle()

        # Verify
        assert len(effects) == 1
        assert effects[0].type == EffectType.LAUNCH_MODAL

    def test_handle_constructs_correct_url(self, mock_event):
        """Test that handle URL includes patient ID."""
        # Setup
        patient_id = "patient-707"
        mock_target = MagicMock()
        mock_target.id = patient_id
        mock_event.target = mock_target

        # Execute
        button = HighRiskMedsActionButton(event=mock_event)
        effects = button.handle()

        # Verify URL contains patient ID
        assert patient_id in effects[0].payload

    def test_filters_active_medications_only(self, mock_event):
        """Test that visible() only queries active medications."""
        # Setup
        mock_target = MagicMock()
        mock_target.id = "patient-808"
        mock_event.target = mock_target

        # Execute
        with patch(
            "high_risk_medications.applications.high_risk_meds_viewer.Medication.objects"
        ) as mock_objects:
            mock_objects.filter.return_value = []

            button = HighRiskMedsActionButton(event=mock_event)
            button.visible()

            # Verify status="active" filter was used
            mock_objects.filter.assert_called_once_with(
                patient__id="patient-808", status="active"
            )
