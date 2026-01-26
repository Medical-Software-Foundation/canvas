"""Tests for high_risk_medication_annotations protocol."""

import json
import pytest
from unittest.mock import MagicMock, patch, call

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from high_risk_medications.protocols.high_risk_medication_annotations import Protocol


class TestHighRiskMedicationAnnotations:
    """Test suite for high-risk medication annotation protocol."""

    def test_warfarin_is_annotated(self, mock_event):
        """Test that medication containing 'warfarin' is annotated as High Risk."""
        # Setup
        results = [
            {
                "text": "warfarin sodium 5 mg tablet",
                "disabled": False,
                "description": False,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_insulin_is_annotated(self, mock_event):
        """Test that medication containing 'insulin' is annotated as High Risk."""
        # Setup
        results = [
            {
                "text": "insulin lispro 100 unit/mL injection",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_digoxin_is_annotated(self, mock_event):
        """Test that medication containing 'digoxin' is annotated as High Risk."""
        # Setup
        results = [
            {
                "text": "digoxin 0.125 mg tablet",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_methotrexate_is_annotated(self, mock_event):
        """Test that medication containing 'methotrexate' is annotated as High Risk."""
        # Setup
        results = [
            {
                "text": "methotrexate sodium 2.5 mg tablet",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_non_high_risk_medication_unchanged(self, mock_event):
        """Test that non-high-risk medications have no annotation."""
        # Setup
        results = [
            {
                "text": "acetaminophen 500 mg tablet",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] is None

    def test_case_insensitive_matching_uppercase(self, mock_event):
        """Test that pattern matching is case-insensitive (uppercase)."""
        # Setup
        results = [
            {
                "text": "INSULIN LISPRO 100 UNIT/ML",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_case_insensitive_matching_mixed(self, mock_event):
        """Test that pattern matching is case-insensitive (mixed case)."""
        # Setup
        results = [
            {
                "text": "Warfarin Sodium 5 Mg Tablet",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_partial_pattern_matching(self, mock_event):
        """Test that patterns match anywhere in medication name."""
        # Setup
        results = [
            {
                "text": "some insulin glargine product",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_multiple_medications_mixed(self, mock_event):
        """Test mix of high-risk and non-high-risk medications."""
        # Setup
        results = [
            {
                "text": "acetaminophen 500 mg tablet",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            },
            {
                "text": "warfarin sodium 5 mg tablet",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            },
            {
                "text": "ibuprofen 200 mg tablet",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            },
            {
                "text": "insulin lispro injection",
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify results
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)

        # First medication (acetaminophen) - not annotated
        assert payload[0]["annotations"] is None

        # Second medication (warfarin) - annotated
        assert payload[1]["annotations"] == ["High Risk"]

        # Third medication (ibuprofen) - not annotated
        assert payload[2]["annotations"] is None

        # Fourth medication (insulin) - annotated
        assert payload[3]["annotations"] == ["High Risk"]

    def test_empty_results_list(self, mock_event):
        """Test graceful handling of empty results list."""
        # Setup
        mock_event.context = {"results": []}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload == []

    def test_missing_results_key(self, mock_event):
        """Test graceful handling when results key is missing."""
        # Setup
        mock_event.context = {}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result - should return None payload indicating no modifications
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload is None

    def test_medication_with_missing_text_field(self, mock_event):
        """Test handling of medication result missing text field."""
        # Setup
        results = [
            {
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify result - should not crash, text defaults to empty string
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] is None

    def test_all_high_risk_patterns(self, mock_event):
        """Test that all four high-risk patterns are detected."""
        # Setup
        results = [
            {"text": "warfarin 5 mg", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "insulin regular", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "digoxin 0.25 mg", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "methotrexate 10 mg", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
        ]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify all are annotated
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS

        # Parse JSON payload
        payload = json.loads(effects[0].payload)
        assert all(result["annotations"] == ["High Risk"] for result in payload)

    def test_prescribe_event_type(self, mock_event):
        """Test protocol responds to PRESCRIBE__PRESCRIBE__POST_SEARCH event."""
        # Verify event type is in RESPONDS_TO
        assert EventType.Name(EventType.PRESCRIBE__PRESCRIBE__POST_SEARCH) in Protocol.RESPONDS_TO

    def test_refill_event_type(self, mock_event):
        """Test protocol responds to REFILL__PRESCRIBE__POST_SEARCH event."""
        # Verify event type is in RESPONDS_TO
        assert EventType.Name(EventType.REFILL__PRESCRIBE__POST_SEARCH) in Protocol.RESPONDS_TO

    def test_medication_statement_event_type(self, mock_event):
        """Test protocol responds to MEDICATION_STATEMENT__MEDICATION__POST_SEARCH event."""
        # Verify event type is in RESPONDS_TO
        assert EventType.Name(EventType.MEDICATION_STATEMENT__MEDICATION__POST_SEARCH) in Protocol.RESPONDS_TO

    def test_returns_autocomplete_search_results_effect(self, mock_event):
        """Test that protocol returns correct effect type."""
        # Setup
        results = [{"text": "test", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}}]
        mock_event.context = {"results": results}

        # Execute
        handler = Protocol(event=mock_event)
        effects = handler.compute()

        # Verify mock
        assert mock_event.mock_calls == []

        # Verify effect type
        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
