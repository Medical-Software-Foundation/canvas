"""Tests for the QuickCopyPatientInfoSectionConfig handler."""

import json
from unittest.mock import Mock

from canvas_sdk.effects.patient_chart_summary_configuration import (
    PatientChartSummaryConfiguration,
)
from canvas_sdk.events import EventType

from quick_copy_patient_info.handlers.section_config import (
    SECTION_KEY,
    QuickCopyPatientInfoSectionConfig,
)


def test_section_key_value() -> None:
    """The section key is the slug we use everywhere else; locking it
    here prevents an accidental rename from silently breaking routing."""
    assert SECTION_KEY == "quick_copy_patient_info"


def test_responds_to_section_configuration_event() -> None:
    assert QuickCopyPatientInfoSectionConfig.RESPONDS_TO == EventType.Name(
        EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION
    )


def test_compute_emits_a_single_effect() -> None:
    handler = QuickCopyPatientInfoSectionConfig(event=Mock())
    effects = handler.compute()
    assert len(effects) == 1


def test_custom_section_is_pinned_to_top() -> None:
    """The 'quick_copy_patient_info' custom section must be the first
    entry so it surfaces above the standard chart sections."""
    handler = QuickCopyPatientInfoSectionConfig(event=Mock())
    [effect] = handler.compute()

    sections = json.loads(effect.payload)["data"]["sections"]
    assert sections[0] == {"custom": True, "key": SECTION_KEY}


def test_all_default_sections_are_preserved() -> None:
    """Emitting PatientChartSummaryConfiguration overrides the default
    order, so we must include every standard section to avoid hiding
    them."""
    handler = QuickCopyPatientInfoSectionConfig(event=Mock())
    [effect] = handler.compute()

    sections = json.loads(effect.payload)["data"]["sections"]
    standard_keys = {s["key"] for s in sections if not s["custom"]}
    expected = {member.value for member in PatientChartSummaryConfiguration.Section}
    assert standard_keys == expected


def test_no_duplicate_section_keys() -> None:
    handler = QuickCopyPatientInfoSectionConfig(event=Mock())
    [effect] = handler.compute()

    sections = json.loads(effect.payload)["data"]["sections"]
    keys = [s["key"] for s in sections]
    assert len(keys) == len(set(keys))


def test_only_one_custom_section() -> None:
    """Sanity: we only register our own section, not a duplicate."""
    handler = QuickCopyPatientInfoSectionConfig(event=Mock())
    [effect] = handler.compute()

    sections = json.loads(effect.payload)["data"]["sections"]
    custom_sections = [s for s in sections if s["custom"]]
    assert len(custom_sections) == 1
    assert custom_sections[0]["key"] == SECTION_KEY
