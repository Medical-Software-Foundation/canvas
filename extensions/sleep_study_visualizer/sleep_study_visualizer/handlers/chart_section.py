"""Sleep Studies chart summary section handlers.

Two handlers are required:
1. SleepStudyChartSection — PatientChartSummaryCustomSectionHandler that renders the HTML.
2. SleepStudyChartSectionConfiguration — BaseHandler that adds the section to the layout.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_chart_summary_configuration import PatientChartSummaryConfiguration
from canvas_sdk.effects.patient_chart_summary_custom_section import PatientChartSummaryCustomSection
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Interview, InterviewQuestionResponse
from django.db.models import Prefetch

from sleep_study_visualizer.constants import (
    EPWORTH_QUESTIONNAIRE_CODE,
    EPWORTH_QUESTIONNAIRE_CODE_SYSTEM,
)
from sleep_study_visualizer.models.sleep_study_result import CustomPatient, SleepStudyResult

# Cache-bust token regenerated at import time so the browser fetches fresh CSS.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

_SECTION_KEY = "sleep_studies"


def _decimal_or_dash(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    # Strip trailing zeros using string ops only. The RestrictedPython runner
    # does not provide the format() builtin, and Decimal.normalize() can emit
    # scientific notation. str() avoids both. 14.0 -> "14", 14.50 -> "14.5".
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _build_study_context(result: SleepStudyResult) -> dict:
    """Pre-format a single SleepStudyResult for the template."""
    return {
        "id": str(result.dbid),
        "study_date": result.study_date,
        "ahi": _decimal_or_dash(result.ahi),
        "rdi": _decimal_or_dash(result.rdi),
        "odi": _decimal_or_dash(result.odi),
        "severity": (result.severity or "").strip(),
        "severity_class": (result.severity or "unknown").strip().lower() or "unknown",
        "epworth_score": result.epworth_score if result.epworth_score is not None else "—",
    }


def _collect_epworth_history(patient_dbid: int) -> list[dict]:
    """Build the time series for the Epworth trend modal.

    Sources merged:
    - SleepStudyResult.epworth_score — captured alongside the sleep study Q.
    - Interview rows for the standalone Epworth questionnaire (LOINC 69732-3).

    Each entry is {"date": ISO date, "score": int, "source": str}. Sorted oldest first.
    """
    points: list[dict] = []

    sleep_studies = SleepStudyResult.objects.filter(
        patient_id=patient_dbid,
        epworth_score__isnull=False,
    ).order_by("study_date")
    for s in sleep_studies:
        points.append(
            {
                "date": s.study_date.isoformat(),
                "score": int(s.epworth_score),
                "source": "Sleep study",
            }
        )

    # Standalone Epworth questionnaire - pull each Interview's scoring response.
    # Prefetch the responses (and their response_option) so summing scores below
    # does not fire one query per interview (N+1).
    interviews = (
        Interview.objects.filter(
            patient_id=patient_dbid,
            questionnaires__code_system=EPWORTH_QUESTIONNAIRE_CODE_SYSTEM,
            questionnaires__code=EPWORTH_QUESTIONNAIRE_CODE,
            entered_in_error__isnull=True,
        )
        .order_by("created")
        .distinct()
        .prefetch_related(
            Prefetch(
                "interview_responses",
                queryset=InterviewQuestionResponse.objects.select_related(
                    "response_option"
                ),
            )
        )
    )
    for interview in interviews:
        score = _sum_epworth_responses(interview)
        if score is None:
            continue
        points.append(
            {
                "date": interview.created.date().isoformat(),
                "score": score,
                "source": "Epworth questionnaire",
            }
        )

    points.sort(key=lambda p: p["date"])
    return points


def _sum_epworth_responses(interview: Interview) -> Optional[int]:
    """Sum scored response_option values for the 8-question Epworth scale.

    The Canvas Epworth questionnaire stores each answer's numeric value on the
    ResponseOption.value field. Returns the total, or None if no scored responses.
    """
    total = 0
    counted = 0
    # Use the prefetched .all() (response_option already select_related on the
    # parent queryset) so this does not issue a fresh query per interview.
    responses: list[InterviewQuestionResponse] = list(
        interview.interview_responses.all()
    )
    for r in responses:
        if r.response_option is None:
            continue
        raw = (r.response_option.value or "").strip()
        if not raw:
            continue
        try:
            total += int(raw)
            counted += 1
        except ValueError:
            continue
    return total if counted else None


class SleepStudyChartSection(PatientChartSummaryCustomSectionHandler):
    """Renders the Sleep Studies custom section."""

    SECTION_KEY = _SECTION_KEY

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id

        custom_patient = CustomPatient.objects.filter(id=patient_id).first()
        if custom_patient is None:
            return [self._render([], [])]

        results = SleepStudyResult.objects.filter(patient=custom_patient).order_by(
            "-study_date"
        )
        studies = [_build_study_context(r) for r in results]
        epworth_history = _collect_epworth_history(custom_patient.dbid)

        return [self._render(studies, epworth_history)]

    @staticmethod
    def _render(studies: list[dict], epworth_history: list[dict]) -> Effect:
        return PatientChartSummaryCustomSection(
            content=render_to_string(
                "templates/sleep_studies_section.html",
                {
                    "studies": studies,
                    "epworth_history": epworth_history,
                    "cache_bust": _CACHE_BUST,
                },
            ),
            icon="💤",
        ).apply()


class SleepStudyChartSectionConfiguration(BaseHandler):
    """Registers the Sleep Studies section first in the patient chart summary layout."""

    RESPONDS_TO = [EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)]

    def compute(self) -> list[Effect]:
        return [
            PatientChartSummaryConfiguration(
                sections=[
                    PatientChartSummaryConfiguration.CustomSection(name=_SECTION_KEY),
                    PatientChartSummaryConfiguration.Section.MEDICATIONS,
                    PatientChartSummaryConfiguration.Section.CONDITIONS,
                    PatientChartSummaryConfiguration.Section.CARE_TEAMS,
                    PatientChartSummaryConfiguration.Section.VITALS,
                    PatientChartSummaryConfiguration.Section.ALLERGIES,
                    PatientChartSummaryConfiguration.Section.GOALS,
                    PatientChartSummaryConfiguration.Section.IMMUNIZATIONS,
                ]
            ).apply()
        ]
