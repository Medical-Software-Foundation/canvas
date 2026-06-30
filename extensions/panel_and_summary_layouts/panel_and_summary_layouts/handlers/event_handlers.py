"""Example handlers that demonstrate the layout-related Canvas SDK effects.

`PanelLayout` configures which sections appear (and in what order) in the
two side panels using `PanelConfiguration`. `PatientSummaryLayout` reorders
the patient chart summary sections using `PatientChartSummaryConfiguration`.

To customize for your instance, edit the four module-level constants below.
Any section not listed in the visible list is hidden; ordering follows the
list order. Sections that overflow available panel space collapse into the
panel's "..." menu.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.panel_configuration import PanelConfiguration
from canvas_sdk.effects.patient_chart_summary_configuration import (
    PatientChartSummaryConfiguration,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

HIDDEN_GLOBAL_SECTIONS: frozenset[PanelConfiguration.PanelGlobalSection] = frozenset(
    {
        PanelConfiguration.PanelGlobalSection.RECALL_APPOINTMENT,
        PanelConfiguration.PanelGlobalSection.OUTSTANDING_REFERRAL,
        PanelConfiguration.PanelGlobalSection.INPATIENT_STAY,
        PanelConfiguration.PanelGlobalSection.MESSAGE,
    }
)

VISIBLE_GLOBAL_SECTIONS: list[PanelConfiguration.PanelGlobalSection] = [
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

HIDDEN_PATIENT_SECTIONS: frozenset[PanelConfiguration.PanelPatientSection] = frozenset(
    {PanelConfiguration.PanelPatientSection.INPATIENT_STAY}
)

VISIBLE_PATIENT_SECTIONS: list[PanelConfiguration.PanelPatientSection] = [
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


class PanelLayout(BaseHandler):
    """Configures the global and patient side-panel sections."""

    RESPONDS_TO = EventType.Name(EventType.PANEL_SECTIONS_CONFIGURATION)

    def compute(self) -> list[Effect]:
        # `event.target.id` is the patient id on patient-panel events and
        # empty on global-panel events. Branch on that to scope the config.
        if self.event.target.id:
            return [
                PanelConfiguration(
                    sections=VISIBLE_PATIENT_SECTIONS,
                    page=PanelConfiguration.Page.PATIENT,
                ).apply()
            ]

        return [
            PanelConfiguration(
                sections=VISIBLE_GLOBAL_SECTIONS,
                page=PanelConfiguration.Page.GLOBAL,
            ).apply()
        ]


PATIENT_SUMMARY_SECTION_ORDER: list[PatientChartSummaryConfiguration.Section] = [
    PatientChartSummaryConfiguration.Section.GOALS,
    PatientChartSummaryConfiguration.Section.CARE_TEAMS,
    PatientChartSummaryConfiguration.Section.MEDICATIONS,
    PatientChartSummaryConfiguration.Section.ALLERGIES,
    PatientChartSummaryConfiguration.Section.VITALS,
    PatientChartSummaryConfiguration.Section.CONDITIONS,
    PatientChartSummaryConfiguration.Section.SOCIAL_DETERMINANTS,
    PatientChartSummaryConfiguration.Section.IMMUNIZATIONS,
    PatientChartSummaryConfiguration.Section.FAMILY_HISTORY,
    PatientChartSummaryConfiguration.Section.SURGICAL_HISTORY,
]


class PatientSummaryLayout(BaseHandler):
    """Reorders the patient chart summary sections."""

    RESPONDS_TO = EventType.Name(
        EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION
    )

    def compute(self) -> list[Effect]:
        return [
            PatientChartSummaryConfiguration(
                sections=PATIENT_SUMMARY_SECTION_ORDER
            ).apply()
        ]
