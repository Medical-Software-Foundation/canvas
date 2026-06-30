import json
from unittest.mock import Mock

from canvas_sdk.effects.panel_configuration import PanelConfiguration
from canvas_sdk.effects.patient_chart_summary_configuration import (
    PatientChartSummaryConfiguration,
)
from canvas_sdk.events import EventType

from panel_and_summary_layouts.handlers.event_handlers import (
    HIDDEN_GLOBAL_SECTIONS,
    HIDDEN_PATIENT_SECTIONS,
    PATIENT_SUMMARY_SECTION_ORDER,
    VISIBLE_GLOBAL_SECTIONS,
    VISIBLE_PATIENT_SECTIONS,
    PanelLayout,
    PatientSummaryLayout,
)


def _make_event(target_id: str | None) -> Mock:
    event = Mock()
    event.type = EventType.PANEL_SECTIONS_CONFIGURATION
    event.target.id = target_id
    return event


def test_handler_responds_to_panel_sections_configuration() -> None:
    assert (
        PanelLayout.RESPONDS_TO
        == EventType.Name(EventType.PANEL_SECTIONS_CONFIGURATION)
    )


def test_hidden_and_visible_partition_global_sections() -> None:
    all_sections = set(PanelConfiguration.PanelGlobalSection)
    assert set(VISIBLE_GLOBAL_SECTIONS).isdisjoint(HIDDEN_GLOBAL_SECTIONS)
    assert set(VISIBLE_GLOBAL_SECTIONS) | set(HIDDEN_GLOBAL_SECTIONS) == all_sections


def test_visible_global_sections_have_expected_order() -> None:
    assert VISIBLE_GLOBAL_SECTIONS == [
        PanelConfiguration.PanelGlobalSection.APPOINTMENT,
        PanelConfiguration.PanelGlobalSection.TASK,
        PanelConfiguration.PanelGlobalSection.REFILL_REQUEST,
        PanelConfiguration.PanelGlobalSection.CHANGE_REQUEST,
        PanelConfiguration.PanelGlobalSection.LAB_REPORT,
        PanelConfiguration.PanelGlobalSection.IMAGING_REPORT,
        PanelConfiguration.PanelGlobalSection.REFERRAL_REPORT,
        PanelConfiguration.PanelGlobalSection.UNCATEGORIZED_DOCUMENT,
        PanelConfiguration.PanelGlobalSection.PRESCRIPTION_ALERT,
    ]


def test_hidden_and_visible_partition_patient_sections() -> None:
    all_sections = set(PanelConfiguration.PanelPatientSection)
    assert set(VISIBLE_PATIENT_SECTIONS).isdisjoint(HIDDEN_PATIENT_SECTIONS)
    assert set(VISIBLE_PATIENT_SECTIONS) | set(HIDDEN_PATIENT_SECTIONS) == all_sections


def test_visible_patient_sections_have_expected_order() -> None:
    assert VISIBLE_PATIENT_SECTIONS == [
        PanelConfiguration.PanelPatientSection.COMMAND,
        PanelConfiguration.PanelPatientSection.TASK,
        PanelConfiguration.PanelPatientSection.REFILL_REQUEST,
        PanelConfiguration.PanelPatientSection.CHANGE_REQUEST,
        PanelConfiguration.PanelPatientSection.LAB_REPORT,
        PanelConfiguration.PanelPatientSection.IMAGING_REPORT,
        PanelConfiguration.PanelPatientSection.REFERRAL_REPORT,
        PanelConfiguration.PanelPatientSection.UNCATEGORIZED_DOCUMENT,
        PanelConfiguration.PanelPatientSection.PRESCRIPTION_ALERT,
    ]


def test_hidden_global_set_contents() -> None:
    assert HIDDEN_GLOBAL_SECTIONS == frozenset(
        {
            PanelConfiguration.PanelGlobalSection.RECALL_APPOINTMENT,
            PanelConfiguration.PanelGlobalSection.OUTSTANDING_REFERRAL,
            PanelConfiguration.PanelGlobalSection.INPATIENT_STAY,
            PanelConfiguration.PanelGlobalSection.MESSAGE,
        }
    )


def test_hidden_patient_set_contents() -> None:
    assert HIDDEN_PATIENT_SECTIONS == frozenset(
        {PanelConfiguration.PanelPatientSection.INPATIENT_STAY}
    )


def test_compute_returns_global_config_when_no_target_id() -> None:
    handler = PanelLayout(event=_make_event(target_id=""))

    effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert payload["data"]["sections"] == [s.value for s in VISIBLE_GLOBAL_SECTIONS]
    for hidden in HIDDEN_GLOBAL_SECTIONS:
        assert hidden.value not in payload["data"]["sections"]


def test_compute_returns_patient_config_when_target_id_present() -> None:
    handler = PanelLayout(event=_make_event(target_id="patient-uuid-123"))

    effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert payload["data"]["sections"] == [s.value for s in VISIBLE_PATIENT_SECTIONS]
    assert (
        PanelConfiguration.PanelPatientSection.INPATIENT_STAY.value
        not in payload["data"]["sections"]
    )


def test_patient_summary_handler_responds_to_correct_event() -> None:
    assert PatientSummaryLayout.RESPONDS_TO == EventType.Name(
        EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION
    )


def test_patient_summary_order_excludes_coding_gaps() -> None:
    assert (
        PatientChartSummaryConfiguration.Section.CODING_GAPS
        not in PATIENT_SUMMARY_SECTION_ORDER
    )


def test_patient_summary_order_has_no_duplicates() -> None:
    assert len(PATIENT_SUMMARY_SECTION_ORDER) == len(
        set(PATIENT_SUMMARY_SECTION_ORDER)
    )


def test_patient_summary_order_covers_every_section_except_coding_gaps() -> None:
    expected = set(PatientChartSummaryConfiguration.Section) - {
        PatientChartSummaryConfiguration.Section.CODING_GAPS
    }
    assert set(PATIENT_SUMMARY_SECTION_ORDER) == expected


def test_patient_summary_order_starts_with_goals_then_care_teams() -> None:
    assert PATIENT_SUMMARY_SECTION_ORDER[:2] == [
        PatientChartSummaryConfiguration.Section.GOALS,
        PatientChartSummaryConfiguration.Section.CARE_TEAMS,
    ]


def test_patient_summary_compute_returns_configured_order() -> None:
    handler = PatientSummaryLayout(event=Mock())

    effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    section_keys = [section["key"] for section in payload["data"]["sections"]]
    assert section_keys == [s.value for s in PATIENT_SUMMARY_SECTION_ORDER]
