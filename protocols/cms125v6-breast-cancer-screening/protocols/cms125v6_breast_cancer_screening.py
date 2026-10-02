"""CMS125v6 Breast Cancer Screening protocol.

Identifies women aged 51-74 who have not had a screening mammogram within
the last 27 months (timeframe + 15-month lookback) and recommends one.

Excluded from the denominator if there is evidence of:
- bilateral mastectomy, OR
- two unilateral mastectomies, OR
- one unilateral mastectomy with a Status-Post-Left/Right Mastectomy diagnosis.
"""

from __future__ import annotations

from typing import Any

import arrow
from django.db.models import Q

from canvas_sdk.commands import InstructCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.imaging import ImagingReport
from canvas_sdk.v1.data.patient import Patient, SexAtBirth
from canvas_sdk.value_set.v2022.condition import (
    StatusPostLeftMastectomy,
    StatusPostRightMastectomy,
)
from canvas_sdk.value_set.v2022.diagnostic_study import Mammography
from canvas_sdk.value_set.v2022.procedure import BilateralMastectomy
from canvas_sdk.value_set.value_set import ValueSet


class UnilateralMastectomy(ValueSet):
    """Procedure codes for a unilateral mastectomy (left, right, or unspecified).

    Ported from ``canvas_workflow_kit.value_set.v2018.UnilateralMastectomy``. The
    SDK ships ``UnilateralMastectomyLeft`` and ``UnilateralMastectomyRight``
    separately; this combined value set preserves the original code list.
    """

    OID = "2.16.840.1.113883.3.464.1003.198.12.1020"
    VALUE_SET_NAME = "Unilateral Mastectomy"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"

    CPT = {
        "19180",
        "19200",
        "19220",
        "19240",
        "19303",
        "19304",
        "19305",
        "19306",
        "19307",
    }

    SNOMEDCT = {
        "172043006",
        "237367009",
        "237368004",
        "274957008",
        "287653007",
        "287654001",
        "318190001",
        "359728003",
        "359731002",
        "359734005",
        "359740003",
        "384723003",
        "395702000",
        "406505007",
        "428564008",
        "428571003",
        "429400009",
        "446109005",
        "446420001",
        "447135002",
        "447421006",
        "66398006",
        "70183006",
    }


class CMS125v6Tomography(ValueSet):
    """LOINC code for breast tomosynthesis (a screening modality for CMS125v6).

    Ported verbatim from ``canvas_workflow_kit.value_set.specials.CMS125v6Tomography``.
    """

    VALUE_SET_NAME = "Tomography"
    EXPANSION_VERSION = "Update 2019-08-01"

    LOINC = {"72142-3"}


class ClinicalQualityMeasure125v6(ClinicalQualityMeasure):
    """Breast Cancer Screening (CMS125v6)."""

    class Meta:
        title = "Breast Cancer Screening"
        version = "2002-02-12v1"

        # 27 months, displayed as 2 years, 3 months.
        default_display_interval_in_days = (365 * 2) + (3 * 30)

        description = (
            "Women 50-74 years of age who have not had a mammogram to screen for "
            "breast cancer within the last 27 months."
        )
        information = "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS125v6.html"
        identifiers = ["CMS125v6"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]
        references = [
            "American Cancer Society. 2010. Cancer Facts & Figures 2010. Atlanta: American Cancer Society.",
            'National Cancer Institute. 2010. "Breast Cancer Screening." '
            "http://www.cancer.gov/cancertopics/pdq/screening/breast/healthprofessional",
            "National Business Group on Health. 2011. Pathways to Managing Cancer in the Workplace. "
            "Washington: National Business Group on Health.",
            'U.S. Preventive Services Task Force (USPSTF). 2009. 1) "Screening for breast cancer: '
            'U.S. Preventive Services Task Force recommendation statement." '
            '2) "December 2009 addendum." Ann Intern Med 151(10):716-726.',
            "BreastCancer.org. 2012. U.S. Breast Cancer Statistics. "
            "http://www.breastcancer.org/symptoms/understand_bc/statistics.jsp",
        ]

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.IMAGING_REPORT_CREATED),
        EventType.Name(EventType.IMAGING_REPORT_UPDATED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_CREATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_UPDATED),
    ]

    AGE_RANGE_START = 51
    AGE_RANGE_END = 74
    EXTRA_SCREENING_MONTHS = 15
    PROTOCOL_KEY = "CMS125v6_RECOMMEND_MAMMOGRAPHY"
    RECOMMENDATION_TITLE = "Discuss breast cancer screening and order imaging as appropriate"

    def __init__(
        self,
        *args: Any,
        patient: Patient | None = None,
        timeframe: Timeframe | None = None,
        now: arrow.Arrow | None = None,
        conditions: list[Any] | None = None,
        imaging_reports: list[Any] | None = None,
        event: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if now is not None:
            self.now = now
        self._injected_patient = patient
        self._injected_timeframe = timeframe
        self._injected_conditions = conditions
        self._injected_imaging_reports = imaging_reports
        self._on_date: arrow.Arrow | None = None
        if "patient" in self.event.context:
          self._patient_id: int = self.event.context["patient"]["id"]
        else:
          self._patient_id: int = self.target.id

    @property
    def timeframe(self) -> Timeframe:
        """Return the measurement timeframe (default: last year, or injected)."""
        if self._injected_timeframe is not None:
            return self._injected_timeframe
        return super().timeframe

    @property
    def patient(self) -> Patient:
        """Return the patient (injected in tests; otherwise loaded by ID from the event)."""
        if self._injected_patient is not None:
            return self._injected_patient
        return Patient.find(self.patient_id_from_target())

    # ----- patient demographic helpers -----

    @property
    def is_female(self) -> bool:
        """Whether the patient is recorded as female at birth."""
        return self.patient.sex_at_birth == SexAtBirth.FEMALE

    @property
    def birthday(self) -> arrow.Arrow:
        """Patient's date of birth as an arrow timestamp at UTC midnight."""
        return arrow.get(self.patient.birth_date)

    def age_at(self, when: arrow.Arrow) -> float:
        """Patient's age as a (fractional) number of years at the given moment."""
        return self.patient.age_at(when)

    def age_at_between(self, when: arrow.Arrow, low_inclusive: int, high_exclusive: int) -> bool:
        """Whether the patient's age at ``when`` is in the half-open range ``[low, high)``.

        Mirrors the legacy ``canvas_workflow_kit.patient.Patient.age_at_between``
        semantics: lower bound inclusive, upper bound exclusive. The CMS125v6 spec
        targets women 50-74 with the upper bound treated as exclusive, so
        ``AGE_RANGE_END = 74`` already excludes 74-year-olds.
        """
        age = self.age_at(when)
        return low_inclusive <= age < high_exclusive

    # ----- data access (overridable in tests) -----

    def _conditions_with_coding(self, system: str, codes: set[str]) -> list[Any]:
        """Return committed conditions matching any (system, code) on or before ``timeframe.end``.

        Each returned object exposes ``onset_date`` for the starts-before check.
        """
        if self._injected_conditions is not None:
            return [
                c
                for c in self._injected_conditions
                if any(
                    coding.get("system") == system and coding.get("code") in codes
                    for coding in c.get("codings", [])
                )
                and (c.get("onset_date") is None or c["onset_date"] <= self.timeframe.end.date())
            ]
        end_date = self.timeframe.end.date()
        return list(
            Condition.objects.committed()
            .for_patient(self.patient.id)
            .filter(
                codings__system=system,
                codings__code__in=codes,
                onset_date__lte=end_date,
            )
            .distinct()
        )

    @staticmethod
    def _value_set_codings(value_set: Any) -> list[tuple[str, set[str]]]:
        """Return ``(system_url, codes)`` pairs for every populated system in ``value_set``."""
        return [
            (value_set.CODE_SYSTEM_MAPPING[name], codes)
            for name, codes in value_set.values.items()
            if codes
        ]

    def _has_condition_in_value_set(self, value_set: Any) -> bool:
        """Whether the patient has at least one matching condition on or before timeframe.end."""
        return any(
            self._conditions_with_coding(url, codes)
            for url, codes in self._value_set_codings(value_set)
        )

    def _count_unilateral_mastectomies(self) -> int:
        """Count distinct committed unilateral mastectomy conditions on or before timeframe.end."""
        seen: set[Any] = set()
        for url, codes in self._value_set_codings(UnilateralMastectomy):
            for condition in self._conditions_with_coding(url, codes):
                seen.add(self._condition_key(condition))
        return len(seen)

    @staticmethod
    def _condition_key(condition: Any) -> Any:
        """Return a stable identity for a condition row (DB row dbid, dict id, or object identity)."""
        if isinstance(condition, dict):
            return condition.get("id") or id(condition)
        return getattr(condition, "dbid", None) or getattr(condition, "id", None) or id(condition)

    def _imaging_reports_within(
        self, value_set: Any, start: arrow.Arrow, end: arrow.Arrow
    ) -> list[Any]:
        """Return imaging reports for the patient with codings in ``value_set`` and a date in [start, end]."""
        if self._injected_imaging_reports is not None:
            return [
                r
                for r in self._injected_imaging_reports
                if self._imaging_matches(r, value_set, start, end)
            ]
        q_filter = self._coding_q_filter(value_set)
        if q_filter is None:
            return []
        return list(
            ImagingReport.objects.filter(
                patient__id=self.patient.id,
                original_date__gte=start.date(),
                original_date__lte=end.date(),
            )
            .filter(q_filter)
            .order_by("-original_date")
            .distinct()
        )

    @classmethod
    def _imaging_matches(
        cls, report: dict[str, Any], value_set: Any, start: arrow.Arrow, end: arrow.Arrow
    ) -> bool:
        """Whether an injected (dict-shaped) imaging report matches the value set and date range."""
        original_date = report.get("originalDate")
        if original_date is None:
            return False
        date = arrow.get(original_date)
        if not start <= date <= end:
            return False
        urls = dict(cls._value_set_codings(value_set))
        return any(
            coding.get("code") in urls.get(coding.get("system"), set())
            for coding in report.get("codings", [])
        )

    @classmethod
    def _coding_q_filter(cls, value_set: Any) -> Q | None:
        """Build a Q-object filter joining ``ImagingReportCoding`` to (system, code) pairs."""
        q: Q | None = None
        for url, codes in cls._value_set_codings(value_set):
            clause = Q(codings__system=url, codings__code__in=codes)
            q = clause if q is None else q | clause
        return q

    # ----- protocol logic -----

    def had_mastectomy(self) -> bool:
        """Whether the patient is excluded due to prior mastectomy evidence."""
        if self._has_condition_in_value_set(BilateralMastectomy):
            return True

        unilateral_count = self._count_unilateral_mastectomies()
        if unilateral_count >= 2:
            return True

        if unilateral_count >= 1 and (
            self._has_condition_in_value_set(StatusPostRightMastectomy)
            or self._has_condition_in_value_set(StatusPostLeftMastectomy)
        ):
            return True

        return False

    def first_due_in(self) -> int | None:
        """Days until the patient becomes eligible (turns 51); ``None`` if already eligible or excluded."""
        if (
            self.is_female
            and self.age_at(self.timeframe.end) < self.AGE_RANGE_START
            and not self.had_mastectomy()
        ):
            return (self.birthday.shift(years=self.AGE_RANGE_START) - self.timeframe.end).days
        return None

    def in_initial_population(self) -> bool:
        """Initial population: women 51-74 within the measurement period."""
        return self.is_female and self.age_at_between(
            self.timeframe.end, self.AGE_RANGE_START, self.AGE_RANGE_END
        )

    def in_denominator(self) -> bool:
        """Denominator: initial population, no mastectomy exclusion."""
        return self.in_initial_population() and not self.had_mastectomy()

    def in_numerator(self) -> bool:
        """Numerator: had a screening mammogram within timeframe + 15-month lookback."""
        period = self.timeframe.increased_by(months=-self.EXTRA_SCREENING_MONTHS)
        reports = self._imaging_reports_within(
            Mammography | CMS125v6Tomography, period.start, period.end
        )
        if not reports:
            return False
        most_recent = reports[0]
        original_date = (
            most_recent.original_date
            if hasattr(most_recent, "original_date")
            else most_recent["originalDate"]
        )
        self._on_date = arrow.get(original_date)
        return True

    # ----- effect builders -----

    def screening_interval_context(self) -> str:
        """Human-readable description of the 27-month screening interval (12 + 15 lookback)."""
        total_months = 12 + self.EXTRA_SCREENING_MONTHS
        years, months = divmod(total_months, 12)
        return f"Current screening interval {years} years, {months} months."

    @staticmethod
    def _display_date(date: arrow.Arrow, now: arrow.Arrow) -> str:
        """Format a past date as ``<humanized> on M/D/YY``, matching the legacy protocol output."""
        return f"{date.humanize(now)} on {date.format('M/D/YY')}"

    def _build_due_card(self, patient_id: str) -> ProtocolCard:
        """Build the protocol card returned when the patient is due for a mammogram."""
        card = ProtocolCard(
            patient_id=patient_id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            due_in=-1,
        )
        card.narrative = "No relevant exams found.\n" + self.screening_interval_context()
        card.add_recommendation(
            title=self.RECOMMENDATION_TITLE,
            button="Counsel",
            commands=[InstructCommand()],
        )
        return card

    def _build_satisfied_card(self, patient_id: str, on_date: arrow.Arrow) -> ProtocolCard:
        """Build the protocol card returned when a recent mammogram satisfies the measure."""
        due_in = (
            on_date.shift(days=self.timeframe.duration, months=self.EXTRA_SCREENING_MONTHS)
            - self.now
        ).days
        card = ProtocolCard(
            patient_id=patient_id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            status=ProtocolCard.Status.SATISFIED,
            due_in=due_in,
        )
        card.narrative = (
            f"{self.patient.first_name} had a mammography "
            f"{self._display_date(on_date, self.now)}."
        )
        return card

    def compute(self) -> list[Effect]:
        """Compute the protocol effect(s) in response to an event."""
        patient_id = self.patient.id
        if self.in_denominator():
            if self.in_numerator() and self._on_date:
                card = self._build_satisfied_card(patient_id, self._on_date)
            else:
                card = self._build_due_card(patient_id)
        else:
            card = ProtocolCard(
                patient_id=patient_id,
                key=self.PROTOCOL_KEY,
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
        return [card.apply()]


