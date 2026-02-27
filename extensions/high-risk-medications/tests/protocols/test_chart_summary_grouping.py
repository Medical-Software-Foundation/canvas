"""Tests for chart_summary_grouping protocol."""

import pytest
from unittest.mock import MagicMock, patch

from high_risk_medications.protocols.chart_summary_grouping import Protocol
from tests.conftest import HIGH_RISK_PATTERNS


class TestChartSummaryGrouping:
    """Test suite for the chart summary grouping handler."""

    def _create_handler(self, context, high_risk_secrets):
        """Helper to create handler with event target and secrets."""
        event = MagicMock()
        event.target.id = "patient-123"
        event.context = context
        handler = Protocol(event=event)
        handler.secrets = high_risk_secrets
        return handler

    def test_responds_to_patient_chart_medications_event(self):
        """Test that handler responds to PATIENT_CHART__MEDICATIONS."""
        from canvas_sdk.events import EventType

        responds_to = Protocol.RESPONDS_TO

        assert responds_to == EventType.Name(EventType.PATIENT_CHART__MEDICATIONS)

    def test_handler_initialization(self, mock_event):
        """Test that handler can be initialized with an event."""
        handler = Protocol(event=mock_event)

        assert handler is not None
        assert handler.event == mock_event

    def test_compute_returns_list(self, high_risk_secrets):
        """Test that compute returns a list of effects."""
        handler = self._create_handler([], high_risk_secrets)

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []
            effects = handler.compute()

        assert isinstance(effects, list)
        assert len(effects) == 1

    def test_groups_high_risk_medication_warfarin(self, high_risk_secrets):
        """Test that warfarin is grouped as high-risk."""
        context = [
            {
                "id": 1,
                "codings": [
                    {"code": "123", "system": "http://www.fdbhealth.com/", "display": "Warfarin 5mg Tablet"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = [{"name": "Warfarin 5mg Tablet", "id": "med-1"}]
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()
            mock_get_meds.assert_called_once_with("patient-123", HIGH_RISK_PATTERNS)

        assert len(effects) == 1

    def test_groups_high_risk_medication_insulin(self, high_risk_secrets):
        """Test that insulin is grouped as high-risk."""
        context = [
            {
                "id": 2,
                "codings": [
                    {"code": "456", "system": "http://www.fdbhealth.com/", "display": "Insulin Glargine 100 units/mL"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = [{"name": "Insulin Glargine 100 units/mL", "id": "med-2"}]
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_groups_high_risk_medication_digoxin(self, high_risk_secrets):
        """Test that digoxin is grouped as high-risk."""
        context = [
            {
                "id": 3,
                "codings": [
                    {"code": "789", "system": "http://www.fdbhealth.com/", "display": "Digoxin 0.25mg Tablet"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = [{"name": "Digoxin 0.25mg Tablet", "id": "med-3"}]
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_groups_high_risk_medication_methotrexate(self, high_risk_secrets):
        """Test that methotrexate is grouped as high-risk."""
        context = [
            {
                "id": 4,
                "codings": [
                    {"code": "101", "system": "http://www.fdbhealth.com/", "display": "Methotrexate 2.5mg Tablet"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = [{"name": "Methotrexate 2.5mg Tablet", "id": "med-4"}]
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_case_insensitive_matching(self, high_risk_secrets):
        """Test that pattern matching is case-insensitive."""
        context = [
            {
                "id": 5,
                "codings": [
                    {"code": "111", "system": "http://www.fdbhealth.com/", "display": "WARFARIN 10MG TABLET"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = [{"name": "WARFARIN 10MG TABLET", "id": "med-5"}]
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_non_high_risk_medication_not_grouped(self, high_risk_secrets):
        """Test that non-high-risk medications are not added to the high-risk group."""
        context = [
            {
                "id": 6,
                "codings": [
                    {"code": "222", "system": "http://www.fdbhealth.com/", "display": "Acetaminophen 500mg Tablet"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_empty_context(self, high_risk_secrets):
        """Test handler with empty medication context."""
        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = []
            handler = self._create_handler([], high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_mixed_medications(self, high_risk_secrets):
        """Test with a mix of high-risk and non-high-risk medications."""
        context = [
            {
                "id": 1,
                "codings": [
                    {"code": "123", "system": "http://www.fdbhealth.com/", "display": "Warfarin 5mg Tablet"}
                ]
            },
            {
                "id": 2,
                "codings": [
                    {"code": "222", "system": "http://www.fdbhealth.com/", "display": "Acetaminophen 500mg Tablet"}
                ]
            },
            {
                "id": 3,
                "codings": [
                    {"code": "456", "system": "http://www.fdbhealth.com/", "display": "Insulin Lispro 100 units/mL"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = [
                {"name": "Warfarin 5mg Tablet", "id": "med-1"},
                {"name": "Insulin Lispro 100 units/mL", "id": "med-3"},
            ]
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1

    def test_multiple_high_risk_medications(self, high_risk_secrets):
        """Test with multiple high-risk medications."""
        context = [
            {
                "id": 1,
                "codings": [
                    {"code": "123", "system": "http://www.fdbhealth.com/", "display": "Warfarin 5mg Tablet"}
                ]
            },
            {
                "id": 2,
                "codings": [
                    {"code": "456", "system": "http://www.fdbhealth.com/", "display": "Insulin Glargine 100 units/mL"}
                ]
            },
            {
                "id": 3,
                "codings": [
                    {"code": "789", "system": "http://www.fdbhealth.com/", "display": "Digoxin 0.125mg Tablet"}
                ]
            },
            {
                "id": 4,
                "codings": [
                    {"code": "101", "system": "http://www.fdbhealth.com/", "display": "Methotrexate 10mg Injection"}
                ]
            }
        ]

        with patch("high_risk_medications.protocols.chart_summary_grouping.get_high_risk_meds") as mock_get_meds:
            mock_get_meds.return_value = [
                {"name": "Warfarin 5mg Tablet", "id": "med-1"},
                {"name": "Insulin Glargine 100 units/mL", "id": "med-2"},
                {"name": "Digoxin 0.125mg Tablet", "id": "med-3"},
                {"name": "Methotrexate 10mg Injection", "id": "med-4"},
            ]
            handler = self._create_handler(context, high_risk_secrets)
            effects = handler.compute()

        assert len(effects) == 1
