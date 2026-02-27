"""Tests for high_risk_medication_annotations protocol."""

import json
import pytest
from unittest.mock import MagicMock

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from high_risk_medications.protocols.high_risk_medication_annotations import Protocol


class TestHighRiskMedicationAnnotations:
    """Test suite for high-risk medication annotation protocol."""

    def _create_handler(self, context, high_risk_secrets):
        """Helper to create handler with event context and secrets."""
        event = MagicMock()
        event.context = context
        handler = Protocol(event=event)
        handler.secrets = high_risk_secrets
        return handler

    def test_warfarin_is_annotated(self, high_risk_secrets):
        """Test that medication containing 'warfarin' is annotated as High Risk."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_insulin_is_annotated(self, high_risk_secrets):
        """Test that medication containing 'insulin' is annotated as High Risk."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_digoxin_is_annotated(self, high_risk_secrets):
        """Test that medication containing 'digoxin' is annotated as High Risk."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_methotrexate_is_annotated(self, high_risk_secrets):
        """Test that medication containing 'methotrexate' is annotated as High Risk."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_non_high_risk_medication_unchanged(self, high_risk_secrets):
        """Test that non-high-risk medications have no annotation."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] is None

    def test_case_insensitive_matching_uppercase(self, high_risk_secrets):
        """Test that pattern matching is case-insensitive (uppercase)."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_case_insensitive_matching_mixed(self, high_risk_secrets):
        """Test that pattern matching is case-insensitive (mixed case)."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_partial_pattern_matching(self, high_risk_secrets):
        """Test that patterns match anywhere in medication name."""
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

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] == ["High Risk"]

    def test_multiple_medications_mixed(self, high_risk_secrets):
        """Test mix of high-risk and non-high-risk medications."""
        results = [
            {"text": "acetaminophen 500 mg tablet", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "warfarin sodium 5 mg tablet", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "ibuprofen 200 mg tablet", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "insulin lispro injection", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
        ]

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] is None
        assert payload[1]["annotations"] == ["High Risk"]
        assert payload[2]["annotations"] is None
        assert payload[3]["annotations"] == ["High Risk"]

    def test_empty_results_list(self, high_risk_secrets):
        """Test graceful handling of empty results list."""
        handler = self._create_handler({"results": []}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload == []

    def test_missing_results_key(self, high_risk_secrets):
        """Test graceful handling when results key is missing."""
        handler = self._create_handler({}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload is None

    def test_medication_with_missing_text_field(self, high_risk_secrets):
        """Test handling of medication result missing text field."""
        results = [
            {
                "disabled": False,
                "description": None,
                "annotations": None,
                "extra": {},
                "value": {}
            }
        ]

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert payload[0]["annotations"] is None

    def test_all_high_risk_patterns(self, high_risk_secrets):
        """Test that all four high-risk patterns are detected."""
        results = [
            {"text": "warfarin 5 mg", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "insulin regular", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "digoxin 0.25 mg", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
            {"text": "methotrexate 10 mg", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}},
        ]

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
        payload = json.loads(effects[0].payload)
        assert all(result["annotations"] == ["High Risk"] for result in payload)

    def test_prescribe_event_type(self):
        """Test protocol responds to PRESCRIBE__PRESCRIBE__POST_SEARCH event."""
        assert EventType.Name(EventType.PRESCRIBE__PRESCRIBE__POST_SEARCH) in Protocol.RESPONDS_TO

    def test_refill_event_type(self):
        """Test protocol responds to REFILL__PRESCRIBE__POST_SEARCH event."""
        assert EventType.Name(EventType.REFILL__PRESCRIBE__POST_SEARCH) in Protocol.RESPONDS_TO

    def test_medication_statement_event_type(self):
        """Test protocol responds to MEDICATION_STATEMENT__MEDICATION__POST_SEARCH event."""
        assert EventType.Name(EventType.MEDICATION_STATEMENT__MEDICATION__POST_SEARCH) in Protocol.RESPONDS_TO

    def test_returns_autocomplete_search_results_effect(self, high_risk_secrets):
        """Test that protocol returns correct effect type."""
        results = [{"text": "test", "disabled": False, "description": None, "annotations": None, "extra": {}, "value": {}}]

        handler = self._create_handler({"results": results}, high_risk_secrets)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.AUTOCOMPLETE_SEARCH_RESULTS
