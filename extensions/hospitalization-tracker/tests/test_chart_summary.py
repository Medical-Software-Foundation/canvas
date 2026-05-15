"""Tests for chart summary section and configuration handlers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory

from hospitalization_tracker.handlers.chart_summary_config import HospitalizationChartSummaryConfig
from hospitalization_tracker.handlers.chart_summary_section import HospitalizationSummarySection
from tests.conftest import HospitalizationFactory


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


@patch("hospitalization_tracker.handlers.chart_summary_section.Hospitalization.objects")
@patch("hospitalization_tracker.handlers.chart_summary_section.render_to_string")
def test_summary_section_returns_effect_with_html(
    mock_render: MagicMock, mock_objects: MagicMock
) -> None:
    """handle() returns a PatientChartSummaryCustomSection effect with rendered HTML."""
    mock_objects.filter.return_value.order_by.return_value = []
    mock_render.return_value = "<ul><li>No records</li></ul>"

    mock_event = MagicMock()
    mock_event.target.id = "patient-uuid-123"
    handler = HospitalizationSummarySection(event=mock_event)

    effects = handler.handle()

    assert len(effects) == 1
    mock_render.assert_called_once()


@patch("hospitalization_tracker.handlers.chart_summary_section.Hospitalization.objects")
@patch("hospitalization_tracker.handlers.chart_summary_section.render_to_string")
def test_summary_section_passes_hospitalizations_to_template(
    mock_render: MagicMock, mock_objects: MagicMock
) -> None:
    """handle() passes the patient's hospitalizations to the template context."""
    mock_hosp = MagicMock()
    mock_objects.filter.return_value.order_by.return_value = [mock_hosp]
    mock_render.return_value = "<p>content</p>"

    mock_event = MagicMock()
    mock_event.target.id = "patient-uuid-456"
    handler = HospitalizationSummarySection(event=mock_event)

    handler.handle()

    call_kwargs = mock_render.call_args
    context = call_kwargs[0][1]
    assert "hospitalizations" in context
    assert mock_hosp in context["hospitalizations"]


@patch("hospitalization_tracker.handlers.chart_summary_section.Hospitalization.objects")
@patch("hospitalization_tracker.handlers.chart_summary_section.render_to_string")
def test_summary_section_filters_by_patient(
    mock_render: MagicMock, mock_objects: MagicMock
) -> None:
    """handle() queries hospitalizations filtered by the current patient."""
    mock_objects.filter.return_value.order_by.return_value = []
    mock_render.return_value = "<p></p>"

    mock_event = MagicMock()
    mock_event.target.id = "specific-patient-id"
    handler = HospitalizationSummarySection(event=mock_event)

    handler.handle()

    mock_objects.filter.assert_called_once_with(patient__id="specific-patient-id")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integtest
@patch("hospitalization_tracker.handlers.chart_summary_section.render_to_string")
def test_summary_section_integration_empty_patient(mock_render: MagicMock) -> None:
    """Returns a section with empty hospitalizations list for a new patient."""
    mock_render.return_value = "<p>No records</p>"
    patient = PatientFactory.create()

    mock_event = MagicMock()
    mock_event.target.id = str(patient.id)
    handler = HospitalizationSummarySection(event=mock_event)

    effects = handler.handle()
    assert len(effects) == 1
    # Verify no hospitalizations were passed for a brand-new patient
    _, call_args = mock_render.call_args
    assert call_args["hospitalizations"] == [] if mock_render.call_args.kwargs else (
        mock_render.call_args[0][1]["hospitalizations"] == []
    )


@pytest.mark.integtest
@patch("hospitalization_tracker.handlers.chart_summary_section.render_to_string")
def test_summary_section_integration_with_records(mock_render: MagicMock) -> None:
    """Returns a section populated with hospitalizations for a patient."""
    mock_render.return_value = "<p>Records</p>"
    patient = PatientFactory.create()
    HospitalizationFactory.create(patient=patient)
    HospitalizationFactory.create(patient=patient)

    mock_event = MagicMock()
    mock_event.target.id = str(patient.id)
    handler = HospitalizationSummarySection(event=mock_event)

    effects = handler.handle()
    assert len(effects) == 1
    # Verify 2 hospitalizations were found and passed
    call_context = mock_render.call_args[0][1]
    assert len(call_context["hospitalizations"]) == 2
