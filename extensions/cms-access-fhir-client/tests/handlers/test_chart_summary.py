"""Tests for AccessChartSummaryConfiguration and AccessChartSummarySection."""
import pytest
from unittest.mock import MagicMock, call, patch


class TestAccessChartSummaryConfiguration:
    def _make_handler(self, secrets=None, patient_id="patient-123"):
        from cms_access_fhir_client.handlers.chart_summary import AccessChartSummaryConfiguration
        mock_event = MagicMock()
        mock_event.target.id = patient_id
        handler = AccessChartSummaryConfiguration(event=mock_event, secrets=secrets or {})
        return handler, mock_event

    def test_returns_empty_when_secret_disabled(self):
        handler, mock_event = self._make_handler(
            secrets={"ACCESS_SHOW_CHART_SUMMARY": "false"}
        )
        effects = handler.compute()
        assert effects == []

    def test_returns_empty_when_secret_absent(self):
        handler, mock_event = self._make_handler(secrets={})
        effects = handler.compute()
        assert effects == []

    def test_returns_configuration_effect_when_enabled(self):
        handler, mock_event = self._make_handler(
            secrets={"ACCESS_SHOW_CHART_SUMMARY": "true"}
        )
        effects = handler.compute()

        assert len(effects) == 1
        from canvas_sdk.effects.base import EffectType
        assert effects[0].type == EffectType.SHOW_PATIENT_CHART_SUMMARY_SECTIONS


class TestAccessChartSummarySection:
    def _make_handler(self, patient_id="patient-123"):
        from cms_access_fhir_client.handlers.chart_summary import AccessChartSummarySection
        mock_event = MagicMock()
        mock_event.target.id = patient_id
        handler = AccessChartSummarySection.__new__(AccessChartSummarySection)
        handler.event = mock_event
        handler.secrets = {}
        return handler, mock_event

    def test_handle_returns_custom_section_with_alignment(self):
        handler, mock_event = self._make_handler()

        mock_alignment = MagicMock()
        mock_alignment.status = "aligned"
        mock_alignment.track = "eCKM"

        mock_qs = MagicMock()
        mock_qs.filter.return_value.order_by.return_value.first.return_value = mock_alignment

        with (
            patch(
                "cms_access_fhir_client.handlers.chart_summary.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.handlers.chart_summary.render_to_string",
                return_value="<div>ACCESS content</div>",
            ) as mock_render,
        ):
            effects = handler.handle()

        assert len(effects) == 1
        from canvas_sdk.effects.base import EffectType
        assert effects[0].type == EffectType.PATIENT_CHART_SUMMARY__CUSTOM_SECTION

        assert mock_qs.mock_calls == [
            call.filter(patient__id="patient-123"),
            call.filter().order_by("-updated_at"),
            call.filter().order_by().first(),
        ]
        assert mock_render.mock_calls == [
            call(
                "templates/access_summary.html",
                {"alignment": mock_alignment, "patient_id": "patient-123"},
            )
        ]

    def test_handle_returns_section_when_no_alignment(self):
        handler, _ = self._make_handler()

        mock_qs = MagicMock()
        mock_qs.filter.return_value.order_by.return_value.first.return_value = None

        with (
            patch(
                "cms_access_fhir_client.handlers.chart_summary.ACCESSAlignment.objects",
                mock_qs,
            ),
            patch(
                "cms_access_fhir_client.handlers.chart_summary.render_to_string",
                return_value="<div>No alignment</div>",
            ) as mock_render,
        ):
            effects = handler.handle()

        assert len(effects) == 1
        assert mock_render.mock_calls == [
            call(
                "templates/access_summary.html",
                {"alignment": None, "patient_id": "patient-123"},
            )
        ]

    def test_section_key_matches_configuration_key(self):
        from cms_access_fhir_client.handlers.chart_summary import (
            AccessChartSummarySection,
            SECTION_KEY,
        )
        assert AccessChartSummarySection.SECTION_KEY == SECTION_KEY
