"""Tests for the Expired ICD-10 annotation protocol."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from expired_icd10_alert.helpers import (
    _load_bundled_codes,
    get_expired_codes,
    normalize_icd10_code,
)
from expired_icd10_alert.protocols.expired_icd10_annotation import (
    EXPIRED_TAG,
    ExpiredICD10Annotation,
)


def make_protocol(
    conditions: list[dict[str, Any]],
    override: str | None = None,
) -> ExpiredICD10Annotation:
    """Build a protocol instance with the given conditions in context.

    `override` is wired into `self.secrets` exactly as Canvas would surface it.
    """
    event = MagicMock()
    event.context = conditions
    protocol = ExpiredICD10Annotation(event=event)
    protocol.secrets = (
        {"EXPIRED_ICD10_CODES_OVERRIDE": override} if override is not None else {}
    )
    return protocol


def annotated_ids(effects: list[Any]) -> dict[str, list[str]]:
    """Pull the single annotation payload out of the returned effects."""
    assert len(effects) == 1
    assert effects[0].type == EffectType.ANNOTATE_PATIENT_CHART_CONDITION_RESULTS
    return json.loads(effects[0].payload)


class TestEventBinding:
    def test_responds_to_patient_chart_conditions(self) -> None:
        assert ExpiredICD10Annotation.RESPONDS_TO == EventType.Name(
            EventType.PATIENT_CHART__CONDITIONS
        )


class TestAnnotationBehavior:
    def test_expired_code_with_period_is_tagged(self) -> None:
        condition = {
            "id": "c1",
            "codings": [{"system": "ICD-10", "code": "E78.01"}],
        }
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {"c1": [EXPIRED_TAG]}

    def test_expired_code_without_period_is_tagged(self) -> None:
        condition = {
            "id": "c2",
            "codings": [{"system": "ICD-10", "code": "G35"}],
        }
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {"c2": [EXPIRED_TAG]}

    def test_valid_code_is_not_tagged(self) -> None:
        condition = {
            "id": "c3",
            "codings": [{"system": "ICD-10", "code": "Z00.00"}],
        }
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {}

    def test_fhir_system_uri_is_recognized(self) -> None:
        condition = {
            "id": "c4",
            "codings": [
                {"system": "http://hl7.org/fhir/sid/icd-10", "code": "G35"}
            ],
        }
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {"c4": [EXPIRED_TAG]}

    def test_non_icd10_coding_is_ignored(self) -> None:
        condition = {
            "id": "c5",
            "codings": [{"system": "SNOMED", "code": "73211009"}],
        }
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {}

    def test_condition_with_mixed_codings_uses_icd10(self) -> None:
        condition = {
            "id": "c6",
            "codings": [
                {"system": "SNOMED", "code": "73211009"},
                {"system": "ICD-10", "code": "B88.0"},
            ],
        }
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {"c6": [EXPIRED_TAG]}

    def test_condition_without_codings_is_skipped(self) -> None:
        condition = {"id": "c7", "codings": []}
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {}

    def test_condition_missing_codings_key_is_skipped(self) -> None:
        condition = {"id": "c8"}
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {}

    def test_entered_in_error_is_skipped(self) -> None:
        condition = {
            "id": "c9",
            "entered_in_error": True,
            "codings": [{"system": "ICD-10", "code": "G35"}],
        }
        effects = make_protocol([condition]).compute()
        assert annotated_ids(effects) == {}

    def test_empty_context_returns_empty_payload(self) -> None:
        effects = make_protocol([]).compute()
        assert annotated_ids(effects) == {}

    def test_mixed_conditions_tag_only_expired(self) -> None:
        conditions = [
            {"id": "a", "codings": [{"system": "ICD-10", "code": "G35"}]},
            {"id": "b", "codings": [{"system": "ICD-10", "code": "Z00.00"}]},
            {"id": "c", "codings": [{"system": "ICD-10", "code": "R10.2"}]},
        ]
        effects = make_protocol(conditions).compute()
        assert annotated_ids(effects) == {
            "a": [EXPIRED_TAG],
            "c": [EXPIRED_TAG],
        }


class TestOverrideSecret:
    def test_override_replaces_bundled_list(self) -> None:
        # I10 is not in the bundled list — confirm baseline first.
        condition = {
            "id": "x",
            "codings": [{"system": "ICD-10", "code": "I10"}],
        }
        assert annotated_ids(make_protocol([condition]).compute()) == {}

        # With the override, I10 is the only expired code.
        effects = make_protocol([condition], override="I10").compute()
        assert annotated_ids(effects) == {"x": [EXPIRED_TAG]}

    def test_override_excludes_bundled_codes(self) -> None:
        # G35 is in the bundled list but not in the override — should not tag.
        condition = {
            "id": "y",
            "codings": [{"system": "ICD-10", "code": "G35"}],
        }
        effects = make_protocol([condition], override="I10").compute()
        assert annotated_ids(effects) == {}

    def test_empty_override_falls_back_to_bundled(self) -> None:
        condition = {
            "id": "z",
            "codings": [{"system": "ICD-10", "code": "G35"}],
        }
        effects = make_protocol([condition], override="").compute()
        assert annotated_ids(effects) == {"z": [EXPIRED_TAG]}

    def test_whitespace_override_falls_back_to_bundled(self) -> None:
        condition = {
            "id": "z2",
            "codings": [{"system": "ICD-10", "code": "G35"}],
        }
        effects = make_protocol([condition], override="   ").compute()
        assert annotated_ids(effects) == {"z2": [EXPIRED_TAG]}

    def test_override_handles_periods_and_whitespace(self) -> None:
        condition = {
            "id": "p",
            "codings": [{"system": "ICD-10", "code": "I10"}],
        }
        effects = make_protocol([condition], override=" I.10 , ").compute()
        assert annotated_ids(effects) == {"p": [EXPIRED_TAG]}


class TestHelpers:
    def test_normalize_strips_periods_and_uppercases(self) -> None:
        assert normalize_icd10_code("e78.01") == "E7801"
        assert normalize_icd10_code("B88.0") == "B880"
        assert normalize_icd10_code("G35") == "G35"

    @pytest.mark.parametrize("value", ["", None])
    def test_normalize_handles_empty(self, value: str | None) -> None:
        assert normalize_icd10_code(value) == ""

    def test_bundled_codes_match_data_file(self) -> None:
        # Sanity check that the bundled data loads and is non-empty.
        codes = _load_bundled_codes()
        assert "G35" in codes
        assert "E7801" in codes  # E78.01 normalized
        assert len(codes) >= 20

    def test_get_expired_codes_returns_bundled_when_no_override(self) -> None:
        assert get_expired_codes(None) == _load_bundled_codes()
        assert get_expired_codes("") == _load_bundled_codes()
