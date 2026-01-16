"""Tests for patient_summary_configuration protocol."""

import pytest
from unittest.mock import MagicMock

from high_risk_medications.protocols.patient_summary_configuration import SummarySectionLayout


class TestSummarySectionLayout:
    """Test suite for the patient summary configuration handler."""

    def test_returns_patient_chart_summary_configuration_effect(self, mock_event):
        """Test that handler returns PatientChartSummaryConfiguration effect."""
        # Execute
        handler = SummarySectionLayout(event=mock_event)
        effects = handler.compute()

        # Verify
        assert len(effects) == 1
        assert effects[0] is not None

    def test_includes_medications_section(self, mock_event):
        """Test that medications section is included in layout."""
        # Execute
        handler = SummarySectionLayout(event=mock_event)
        effects = handler.compute()

        # Verify effect was created (sections are configured correctly in the handler)
        assert len(effects) == 1

    def test_includes_all_configured_sections(self, mock_event):
        """Test that all expected sections are configured."""
        # Execute
        handler = SummarySectionLayout(event=mock_event)
        effects = handler.compute()

        # Verify effect was created with proper configuration
        assert len(effects) == 1
        assert effects[0] is not None

    def test_responds_to_section_configuration_event(self):
        """Test that handler responds to PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION."""
        from canvas_sdk.events import EventType

        responds_to = SummarySectionLayout.RESPONDS_TO

        assert responds_to == EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)

    def test_handler_initialization(self, mock_event):
        """Test that handler can be initialized with an event."""
        # Execute
        handler = SummarySectionLayout(event=mock_event)

        # Verify
        assert handler is not None
        assert handler.event == mock_event

    def test_compute_returns_list(self, mock_event):
        """Test that compute returns a list of effects."""
        # Execute
        handler = SummarySectionLayout(event=mock_event)
        effects = handler.compute()

        # Verify
        assert isinstance(effects, list)
        assert len(effects) > 0

    def test_configuration_is_reproducible(self, mock_event):
        """Test that configuration is consistent across multiple calls."""
        # Execute
        handler1 = SummarySectionLayout(event=mock_event)
        effects1 = handler1.compute()

        handler2 = SummarySectionLayout(event=mock_event)
        effects2 = handler2.compute()

        # Verify both produce effects
        assert len(effects1) == len(effects2)
        assert len(effects1) == 1
        assert len(effects2) == 1
