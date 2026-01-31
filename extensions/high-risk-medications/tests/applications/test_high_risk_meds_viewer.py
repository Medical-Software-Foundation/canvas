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
        mock_event.context = {"patient": {"id": "patient-123"}}

        viewer = HighRiskMedsViewer(event=mock_event)
        effect = viewer.on_open()

        assert effect is not None
        assert effect.type == EffectType.LAUNCH_MODAL

    def test_on_open_constructs_correct_url(self, mock_event):
        """Test that URL includes patient ID."""
        patient_id = "abc-123-def"
        mock_event.context = {"patient": {"id": patient_id}}

        viewer = HighRiskMedsViewer(event=mock_event)
        effect = viewer.on_open()

        assert patient_id in effect.payload

    @pytest.mark.parametrize("context", [
        {},
        {"patient": {"id": None}},
        {"user": {"id": "staff-123"}},
    ])
    def test_on_open_handles_missing_patient(self, mock_event, context):
        """Test graceful handling when patient context is missing or invalid."""
        mock_event.context = context

        viewer = HighRiskMedsViewer(event=mock_event)
        effects = viewer.on_open()

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

    @pytest.mark.parametrize("med_name,should_be_visible", [
        ("Warfarin 5mg Tablet", True),
        ("Insulin Glargine 100 units/mL", True),
        ("Digoxin 0.25mg Tablet", True),
        ("Methotrexate 2.5mg Tablet", True),
        ("WARFARIN SODIUM 5 MG", True),  # case insensitive
        ("Acetaminophen 500mg Tablet", False),
    ])
    def test_visible_for_medication(self, mock_event, high_risk_secrets, med_name, should_be_visible):
        """Test button visibility based on medication type."""
        mock_target = MagicMock()
        mock_target.id = "patient-123"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = med_name
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            button.secrets = high_risk_secrets
            is_visible = button.visible()

        assert bool(is_visible) == should_be_visible

    def test_visible_returns_false_when_no_medications(self, mock_event, high_risk_secrets):
        """Test that button is hidden when patient has no medications."""
        mock_target = MagicMock()
        mock_target.id = "patient-303"
        mock_event.target = mock_target

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = []

            button = HighRiskMedsActionButton(event=mock_event)
            button.secrets = high_risk_secrets
            is_visible = button.visible()

        assert not is_visible

    def test_visible_handles_null_medication_display(self, mock_event, high_risk_secrets):
        """Test that button handles medication with null display name."""
        mock_target = MagicMock()
        mock_target.id = "patient-505"
        mock_event.target = mock_target

        mock_med = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = None
        mock_med.codings.first.return_value = mock_coding

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = [mock_med]

            button = HighRiskMedsActionButton(event=mock_event)
            button.secrets = high_risk_secrets
            is_visible = button.visible()

        assert not is_visible

    def test_handle_returns_launch_modal_effect(self, mock_event):
        """Test that handle returns a LaunchModalEffect."""
        mock_target = MagicMock()
        mock_target.id = "patient-606"
        mock_event.target = mock_target

        button = HighRiskMedsActionButton(event=mock_event)
        effects = button.handle()

        assert len(effects) == 1
        assert effects[0].type == EffectType.LAUNCH_MODAL

    def test_handle_constructs_correct_url(self, mock_event):
        """Test that handle URL includes patient ID."""
        patient_id = "patient-707"
        mock_target = MagicMock()
        mock_target.id = patient_id
        mock_event.target = mock_target

        button = HighRiskMedsActionButton(event=mock_event)
        effects = button.handle()

        assert patient_id in effects[0].payload

    def test_filters_active_medications_only(self, mock_event, high_risk_secrets):
        """Test that visible() only queries active medications."""
        mock_target = MagicMock()
        mock_target.id = "patient-808"
        mock_event.target = mock_target

        with patch("high_risk_medications.helper.Medication.objects") as mock_objects:
            mock_objects.filter.return_value = []

            button = HighRiskMedsActionButton(event=mock_event)
            button.secrets = high_risk_secrets
            button.visible()

            mock_objects.filter.assert_called_once_with(
                patient__id="patient-808", status="active"
            )
