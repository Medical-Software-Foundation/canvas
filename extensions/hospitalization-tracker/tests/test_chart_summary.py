"""Tests for chart summary section and configuration handlers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory

from hospitalization_tracker.handlers.chart_summary_config import HospitalizationChartSummaryConfig
from hospitalization_tracker.handlers.chart_summary_section import HospitalizationSummarySection
from tests.conftest import HospitalizationFactory  # noqa: F401 (used by integtest factories)


# ---------------------------------------------------------------------------
# HospitalizationChartSummaryConfig
# ---------------------------------------------------------------------------


def test_chart_summary_config_returns_configuration_effect() -> None:
    """compute() returns a single PatientChartSummaryConfiguration effect."""
    from canvas_sdk.effects.patient_chart_summary_configuration import PatientChartSummaryConfiguration
    from canvas_sdk.events import EventType

    mock_event = MagicMock()
    mock_event.type = EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION

    handler = HospitalizationChartSummaryConfig(event=mock_event)
    effects = handler.compute()

    assert len(effects) == 1


def test_chart_summary_config_responds_to_correct_event() -> None:
    """RESPONDS_TO is set to PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION."""
    from canvas_sdk.events import EventType

    assert EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION) in (
        HospitalizationChartSummaryConfig.RESPONDS_TO
    )


def test_chart_summary_config_includes_custom_section() -> None:
    """The configuration includes the 'hospitalization_history' custom section."""
    from canvas_sdk.effects.patient_chart_summary_configuration import PatientChartSummaryConfiguration
    from canvas_sdk.events import EventType

    mock_event = MagicMock()
    mock_event.type = EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION

    with patch.object(PatientChartSummaryConfiguration, "apply") as mock_apply:
        mock_apply.return_value = MagicMock()
        HospitalizationChartSummaryConfig(event=mock_event).compute()

    mock_apply.assert_called_once()


# ---------------------------------------------------------------------------
# HospitalizationSummarySection
# ---------------------------------------------------------------------------


def test_summary_section_section_key() -> None:
    """SECTION_KEY is set to 'hospitalization_history'."""
    assert HospitalizationSummarySection.SECTION_KEY == "hospitalization_history"


def test_summary_section_returns_one_effect() -> None:
    """handle() returns exactly one PatientChartSummaryCustomSection effect."""
    mock_event = MagicMock()
    mock_event.target.id = "patient-uuid-123"
    handler = HospitalizationSummarySection(event=mock_event)

    effects = handler.handle()

    assert len(effects) == 1


def test_summary_section_effect_contains_patient_url() -> None:
    """handle() returns a URL-based effect pointing to the section API with the patient ID."""
    patient_id = "patient-uuid-456"
    mock_event = MagicMock()
    mock_event.target.id = patient_id
    handler = HospitalizationSummarySection(event=mock_event)

    effects = handler.handle()

    # Effect payload contains the section URL with the patient_id
    payload = effects[0].payload
    assert patient_id in payload
    assert "hospitalization_tracker/section" in payload


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integtest
def test_summary_section_integration_url_contains_patient_id() -> None:
    """Integration: handle() URL encodes the correct patient ID from the event target."""
    patient = PatientFactory.create()
    patient_id = str(patient.id)

    mock_event = MagicMock()
    mock_event.target.id = patient_id
    handler = HospitalizationSummarySection(event=mock_event)

    effects = handler.handle()
    assert len(effects) == 1
    assert patient_id in effects[0].payload


@pytest.mark.integtest
def test_summary_section_integration_different_patients_get_different_urls() -> None:
    """Integration: two different patients produce different section URLs."""
    patient_a = PatientFactory.create()
    patient_b = PatientFactory.create()

    mock_event_a = MagicMock()
    mock_event_a.target.id = str(patient_a.id)
    mock_event_b = MagicMock()
    mock_event_b.target.id = str(patient_b.id)

    url_a = HospitalizationSummarySection(event=mock_event_a).handle()[0].payload
    url_b = HospitalizationSummarySection(event=mock_event_b).handle()[0].payload

    assert url_a != url_b
