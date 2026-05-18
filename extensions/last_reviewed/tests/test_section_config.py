"""Tests for the LastReviewedSectionConfig handler."""

import json
from unittest.mock import Mock

from canvas_sdk.effects.patient_chart_summary_configuration import (
    PatientChartSummaryConfiguration,
)
from canvas_sdk.events import EventType

from last_reviewed.handlers.section_config import (
    SECTION_KEY,
    LastReviewedSectionConfig,
)


def test_responds_to_section_configuration_event() -> None:
    assert LastReviewedSectionConfig.RESPONDS_TO == EventType.Name(
        EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION
    )


def test_compute_emits_a_single_effect() -> None:
    handler = LastReviewedSectionConfig(event=Mock())
    effects = handler.compute()
    assert len(effects) == 1


def test_custom_section_is_pinned_to_top() -> None:
    """The 'last_reviewed_summary' custom section must be the first entry so it
    surfaces above the standard chart sections."""
    handler = LastReviewedSectionConfig(event=Mock())
    [effect] = handler.compute()

    sections = json.loads(effect.payload)["data"]["sections"]
    assert sections[0] == {"custom": True, "key": SECTION_KEY}


def test_all_default_sections_are_preserved() -> None:
    """Emitting PatientChartSummaryConfiguration overrides the default order, so
    we must include every standard section to avoid hiding them."""
    handler = LastReviewedSectionConfig(event=Mock())
    [effect] = handler.compute()

    sections = json.loads(effect.payload)["data"]["sections"]
    standard_keys = {s["key"] for s in sections if not s["custom"]}
    expected = {member.value for member in PatientChartSummaryConfiguration.Section}
    assert standard_keys == expected


def test_no_duplicate_section_keys() -> None:
    handler = LastReviewedSectionConfig(event=Mock())
    [effect] = handler.compute()

    sections = json.loads(effect.payload)["data"]["sections"]
    keys = [s["key"] for s in sections]
    assert len(keys) == len(set(keys))
