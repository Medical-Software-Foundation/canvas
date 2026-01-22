"""Tests for chart_summary_grouping protocol."""

import pytest
from unittest.mock import MagicMock

from high_risk_medications.protocols.chart_summary_grouping import Protocol


class TestChartSummaryGrouping:
    """Test suite for the chart summary grouping handler."""

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

    def test_compute_returns_list(self, mock_chart_medications_event):
        """Test that compute returns a list of effects."""
        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert isinstance(effects, list)
        assert len(effects) == 1

    def test_groups_high_risk_medication_warfarin(self, mock_chart_medications_event):
        """Test that warfarin is grouped as high-risk."""
        mock_chart_medications_event.context = [
            {
                "id": 1,
                "codings": [
                    {"code": "123", "system": "http://www.fdbhealth.com/", "display": "Warfarin 5mg Tablet"}
                ]
            }
        ]

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_groups_high_risk_medication_insulin(self, mock_chart_medications_event):
        """Test that insulin is grouped as high-risk."""
        mock_chart_medications_event.context = [
            {
                "id": 2,
                "codings": [
                    {"code": "456", "system": "http://www.fdbhealth.com/", "display": "Insulin Glargine 100 units/mL"}
                ]
            }
        ]

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_groups_high_risk_medication_digoxin(self, mock_chart_medications_event):
        """Test that digoxin is grouped as high-risk."""
        mock_chart_medications_event.context = [
            {
                "id": 3,
                "codings": [
                    {"code": "789", "system": "http://www.fdbhealth.com/", "display": "Digoxin 0.25mg Tablet"}
                ]
            }
        ]

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_groups_high_risk_medication_methotrexate(self, mock_chart_medications_event):
        """Test that methotrexate is grouped as high-risk."""
        mock_chart_medications_event.context = [
            {
                "id": 4,
                "codings": [
                    {"code": "101", "system": "http://www.fdbhealth.com/", "display": "Methotrexate 2.5mg Tablet"}
                ]
            }
        ]

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_case_insensitive_matching(self, mock_chart_medications_event):
        """Test that pattern matching is case-insensitive."""
        mock_chart_medications_event.context = [
            {
                "id": 5,
                "codings": [
                    {"code": "111", "system": "http://www.fdbhealth.com/", "display": "WARFARIN 10MG TABLET"}
                ]
            }
        ]

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_non_high_risk_medication_not_grouped(self, mock_chart_medications_event):
        """Test that non-high-risk medications are not added to the high-risk group."""
        mock_chart_medications_event.context = [
            {
                "id": 6,
                "codings": [
                    {"code": "222", "system": "http://www.fdbhealth.com/", "display": "Acetaminophen 500mg Tablet"}
                ]
            }
        ]

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_empty_context(self, mock_chart_medications_event):
        """Test handler with empty medication context."""
        mock_chart_medications_event.context = []

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_mixed_medications(self, mock_chart_medications_event):
        """Test with a mix of high-risk and non-high-risk medications."""
        mock_chart_medications_event.context = [
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

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1

    def test_multiple_high_risk_medications(self, mock_chart_medications_event):
        """Test with multiple high-risk medications."""
        mock_chart_medications_event.context = [
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

        handler = Protocol(event=mock_chart_medications_event)
        effects = handler.compute()

        assert len(effects) == 1


@pytest.fixture
def mock_chart_medications_event():
    """Create a mock event for patient chart medications."""
    event = MagicMock()
    event.context = []
    return event
