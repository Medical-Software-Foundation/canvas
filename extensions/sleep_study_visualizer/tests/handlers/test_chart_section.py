"""Tests for the chart section + Epworth trend helpers."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sleep_study_visualizer.handlers.chart_section import (
    SleepStudyChartSection,
    SleepStudyChartSectionConfiguration,
    _build_study_context,
    _collect_epworth_history,
    _decimal_or_dash,
    _sum_epworth_responses,
)


def _make_section_handler(patient_id: str = "patient-abc"):
    event = MagicMock()
    event.target.id = patient_id
    event.context = {"section": "sleep_studies"}
    handler = SleepStudyChartSection(event)
    return handler, event


class TestDecimalFormatting:
    def test_decimal_or_dash_returns_dash_for_none(self):
        assert _decimal_or_dash(None) == "—"

    def test_decimal_or_dash_strips_trailing_zeros(self):
        assert _decimal_or_dash(Decimal("14.0")) == "14"

    def test_decimal_or_dash_preserves_significant_decimals(self):
        assert _decimal_or_dash(Decimal("14.5")) == "14.5"

    def test_decimal_or_dash_trims_multiple_trailing_zeros(self):
        assert _decimal_or_dash(Decimal("14.50")) == "14.5"

    def test_decimal_or_dash_integer_decimal(self):
        assert _decimal_or_dash(Decimal("14")) == "14"

    def test_decimal_or_dash_no_scientific_notation_for_round_values(self):
        # Regression: normalize()+format() was used here; format() is not a
        # sandbox builtin, and normalize() alone emits "1E+2" for 100.
        assert _decimal_or_dash(Decimal("100")) == "100"


class TestStudyContext:
    def test_builds_complete_context_for_full_study(self):
        result = MagicMock()
        result.dbid = 42
        result.study_date = date(2026, 4, 12)
        result.ahi = Decimal("18.4")
        result.rdi = Decimal("22.1")
        result.odi = Decimal("14.0")
        result.severity = "Moderate"
        result.epworth_score = 12

        ctx = _build_study_context(result)

        assert ctx["id"] == "42"
        assert ctx["study_date"] == date(2026, 4, 12)
        assert ctx["ahi"] == "18.4"
        assert ctx["rdi"] == "22.1"
        assert ctx["odi"] == "14"
        assert ctx["severity"] == "Moderate"
        assert ctx["severity_class"] == "moderate"
        assert ctx["epworth_score"] == 12

    def test_blank_severity_yields_unknown_class(self):
        result = MagicMock()
        result.dbid = 1
        result.study_date = date(2026, 4, 12)
        result.ahi = None
        result.rdi = None
        result.odi = None
        result.severity = ""
        result.epworth_score = None

        ctx = _build_study_context(result)

        assert ctx["severity"] == ""
        assert ctx["severity_class"] == "unknown"
        assert ctx["epworth_score"] == "—"
        assert ctx["ahi"] == "—"


def _interview_with_responses(*values):
    """Build an Interview mock whose prefetched .all() yields response mocks.

    Each value becomes a response_option.value; None means a missing option.
    """
    interview = MagicMock()
    responses = []
    for v in values:
        r = MagicMock()
        if v is None:
            r.response_option = None
        else:
            r.response_option.value = v
        responses.append(r)
    interview.interview_responses.all.return_value = responses
    return interview


class TestEpworthSum:
    def test_sums_scored_response_options(self):
        interview = _interview_with_responses("2", "3", "1")
        assert _sum_epworth_responses(interview) == 6

    def test_returns_none_when_no_scored_responses(self):
        interview = _interview_with_responses(None)
        assert _sum_epworth_responses(interview) is None

    def test_ignores_unparseable_values(self):
        interview = _interview_with_responses("2", "not a number")
        assert _sum_epworth_responses(interview) == 2

    def test_skips_blank_option_values(self):
        interview = _interview_with_responses("4", "")
        assert _sum_epworth_responses(interview) == 4


class TestCollectEpworthHistory:
    def _patch_sources(self, sleep_studies, interviews):
        """Patch SleepStudyResult and Interview query chains used by the collector."""
        ssr = patch(
            "sleep_study_visualizer.handlers.chart_section.SleepStudyResult.objects"
        )
        iv = patch(
            "sleep_study_visualizer.handlers.chart_section.Interview.objects"
        )
        mock_ssr = ssr.start()
        mock_iv = iv.start()
        mock_ssr.filter.return_value.order_by.return_value = sleep_studies
        (
            mock_iv.filter.return_value.order_by.return_value.distinct.return_value.prefetch_related.return_value
        ) = interviews
        return [ssr, iv]

    def test_merges_and_sorts_both_sources_oldest_first(self):
        study = MagicMock()
        study.study_date = date(2026, 5, 1)
        study.epworth_score = 11

        interview = MagicMock()
        interview.created = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)

        patches = self._patch_sources([study], [interview])
        try:
            with patch(
                "sleep_study_visualizer.handlers.chart_section._sum_epworth_responses",
                return_value=8,
            ):
                points = _collect_epworth_history(99)
        finally:
            for p in patches:
                p.stop()

        # Oldest first: the Jan interview precedes the May sleep study.
        assert [p["date"] for p in points] == ["2026-01-15", "2026-05-01"]
        assert points[0] == {
            "date": "2026-01-15",
            "score": 8,
            "source": "Epworth questionnaire",
        }
        assert points[1] == {
            "date": "2026-05-01",
            "score": 11,
            "source": "Sleep study",
        }

    def test_skips_interviews_with_no_scorable_responses(self):
        interview = MagicMock()
        interview.created = datetime(2026, 2, 1, tzinfo=timezone.utc)

        patches = self._patch_sources([], [interview])
        try:
            with patch(
                "sleep_study_visualizer.handlers.chart_section._sum_epworth_responses",
                return_value=None,
            ):
                points = _collect_epworth_history(99)
        finally:
            for p in patches:
                p.stop()

        assert points == []

    def test_returns_empty_when_no_data(self):
        patches = self._patch_sources([], [])
        try:
            points = _collect_epworth_history(99)
        finally:
            for p in patches:
                p.stop()

        assert points == []


class TestSleepStudyChartSection:
    def test_returns_empty_state_when_patient_not_found(self):
        handler, _ = _make_section_handler()

        with patch(
            "sleep_study_visualizer.handlers.chart_section.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.chart_section.render_to_string"
        ) as mock_render:
            mock_cp.filter.return_value.first.return_value = None
            mock_render.return_value = "<empty>No sleep studies on file</empty>"
            effects = handler.handle()

        assert len(effects) == 1
        # The empty-state HTML carries the empty-title copy
        payload = json.loads(effects[0].payload)
        assert "No sleep studies on file" in payload["data"]["content"]
        # Confirm we rendered with empty studies list
        ctx = mock_render.call_args.args[1]
        assert ctx["studies"] == []
        assert ctx["epworth_history"] == []

    def test_renders_studies_and_collects_epworth_when_patient_found(self):
        handler, _ = _make_section_handler()
        custom_patient = MagicMock()
        custom_patient.dbid = 99

        study = MagicMock()
        study.dbid = 5
        study.study_date = date(2026, 4, 12)
        study.ahi = Decimal("18.0")
        study.rdi = Decimal("22.0")
        study.odi = Decimal("14.0")
        study.severity = "Moderate"
        study.epworth_score = 12

        with patch(
            "sleep_study_visualizer.handlers.chart_section.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.chart_section.SleepStudyResult.objects"
        ) as mock_ssr, patch(
            "sleep_study_visualizer.handlers.chart_section._collect_epworth_history"
        ) as mock_history, patch(
            "sleep_study_visualizer.handlers.chart_section.render_to_string"
        ) as mock_render:
            mock_cp.filter.return_value.first.return_value = custom_patient
            mock_ssr.filter.return_value.order_by.return_value = [study]
            mock_history.return_value = [
                {"date": "2026-04-12", "score": 12, "source": "Sleep study"},
            ]
            mock_render.return_value = "<rendered/>"

            effects = handler.handle()

        assert len(effects) == 1
        # Template was given the right context — that's the behavior under test.
        ctx = mock_render.call_args.args[1]
        assert len(ctx["studies"]) == 1
        assert ctx["studies"][0]["severity"] == "Moderate"
        assert ctx["studies"][0]["epworth_score"] == 12
        assert ctx["epworth_history"][0]["score"] == 12
        mock_history.assert_called_once_with(99)


class TestSectionConfiguration:
    def test_sleep_studies_section_listed_first(self):
        event = MagicMock()
        config = SleepStudyChartSectionConfiguration(event)
        effects = config.compute()

        assert len(effects) == 1
        payload = json.loads(effects[0].payload)
        sections = payload["data"]["sections"]
        # First section is the custom one
        assert sections[0]["key"] == "sleep_studies"
        assert sections[0]["custom"] is True
