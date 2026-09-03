"""
CMS131v6 - Diabetes: Eye Exam.

Patients 18-75 with diabetes need a retinal or dilated eye exam by an eye care professional
during the measurement period - or a *negative* (no diabetic retinopathy) exam in the
12 months preceding it - to be numerator-compliant.

https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS131v6.html
"""

from __future__ import annotations

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.referral import ReferralReport
from canvas_sdk.value_set.v2022.physical_exam import RetinalOrDilatedEyeExam
from canvas_sdk.value_set.value_set import ValueSet

from .diabetes_quality_measure import DiabetesQualityMeasure


# CPT 92250 (fundus photography) is the recommended in-house procedure when the patient
# cannot be referred to an eye care professional. Not present in canvas_sdk.value_set.v2022,
# so reproduced verbatim.
class FundusPhotography(ValueSet):
    """CPT code for fundus (retinal) photography."""

    VALUE_SET_NAME = "Fundus Photography"
    CPT = {"92250"}


# SNOMED code 721103006 marks an explicitly *negative* retinal exam.
NEGATIVE_RETINAL_FINDING_CODE = "721103006"


class ClinicalQualityMeasure131v6(DiabetesQualityMeasure):
    """CMS131v6 - Diabetic eye exam."""

    class Meta:
        title = "Diabetes: Eye Exam"
        version = "2019-08-02v1"
        description = (
            "Patients 18-75 years of age with diabetes who have not had a retinal or "
            "dilated eye exam by an eye care professional."
        )
        information = "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS131v6.html"
        identifiers = ["CMS131v6"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    _on_date: arrow.Arrow | None = None
    _in_period: bool | None = None
    _finding: str = ""

    def in_denominator(self) -> bool:
        """Equals the initial population."""
        return self.in_initial_population()

    def _retinal_reports_in(self, start: arrow.Arrow, end: arrow.Arrow):
        """Committed ``RetinalOrDilatedEyeExam`` referral reports in ``[start, end]``.

        ReferralReport doesn't ship with a ``ValueSetLookupQuerySetMixin``, so we
        flatten the value set ourselves and filter on the report's codings.
        """
        # CODE_SYSTEM_MAPPING is {name: url}; codings store the url.
        values = RetinalOrDilatedEyeExam.values  # {system_name: set[code]}
        urls = [RetinalOrDilatedEyeExam.CODE_SYSTEM_MAPPING[name] for name in values]
        codes = {code for code_set in values.values() for code in code_set}
        return (
            ReferralReport.objects.filter(patient__id=self.patient.id)
            .filter(original_date__gte=start.date(), original_date__lte=end.date())
            .filter(codings__system__in=urls, codings__code__in=codes)
            .order_by("original_date")
            .distinct()
        )

    def in_numerator(self) -> bool:
        """Eye exam during the period OR a negative exam in the prior period."""
        in_period_reports = list(
            self._retinal_reports_in(self.timeframe.start, self.timeframe.end)
        )

        if in_period_reports:
            self._in_period = True
            last = in_period_reports[-1]
        else:
            self._in_period = False
            prior_start = self.timeframe.start.shift(days=-self.timeframe.duration)
            prior_reports = list(self._retinal_reports_in(prior_start, self.timeframe.start))
            if not prior_reports:
                return False
            last = prior_reports[-1]

        # Look at the codings on the last referral report to pull the finding text and
        # decide whether a negative-result code is present.
        negative_finding = False
        codings = getattr(last, "codings", None)
        if codings is not None:
            for coding in codings.all():
                if getattr(coding, "name", "") == "Findings":
                    self._finding = getattr(coding, "display", "") or getattr(
                        coding, "value", ""
                    )
                if getattr(coding, "code", "") == NEGATIVE_RETINAL_FINDING_CODE:
                    negative_finding = True

        self._on_date = arrow.get(last.original_date)

        return self._in_period or negative_finding

    def _satisfied_card(self) -> ProtocolCard:
        """Build a SATISFIED card based on in-period vs. prior-period negative finding."""
        assert self._on_date is not None
        due_in = (self._on_date.shift(days=self.timeframe.duration) - self.now).days
        exam_date = self.display_date(self._on_date)
        first_name = self.patient.first_name
        if self._in_period:
            narrative = (
                f"{first_name} has diabetes and a retinal examination was done "
                f"{exam_date}, demonstrating {self._finding}."
            )
        else:
            next_date = self._on_date.shift(days=self.timeframe.duration).format("M/D/YY")
            narrative = (
                f"{first_name} has diabetes and a retinal examination was done "
                f"{exam_date} demonstrating no diabetic eye disease. "
                f"Next examination is due {next_date}."
            )
        return ProtocolCard(
            patient_id=self.patient.id,
            key="CMS131v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.SATISFIED,
            narrative=narrative,
            due_in=due_in,
        )

    def _due_card(self) -> ProtocolCard:
        """Build a DUE card with perform/refer recommendations."""
        first_name = self.patient.first_name
        if self._on_date:
            exam_date = self.display_date(self._on_date)
            narrative = (
                f"{first_name} has diabetes and a prior abnormal retinal examination "
                f"{exam_date} showing {self._finding}. "
                f"{first_name} is due for retinal examination."
            )
        else:
            humanized = (
                self.now.shift(months=-1, days=-self.timeframe.duration)
                .humanize(other=self.now, granularity="month", only_distance=True)
                .replace(" ago", "")
            )
            narrative = (
                f"{first_name} has diabetes and no documentation of retinal "
                f"examination in the past {humanized}."
            )

        card = ProtocolCard(
            patient_id=self.patient.id,
            key="CMS131v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            narrative=narrative,
            due_in=-1,
        )
        card.add_recommendation(title="Perform retinal examination", button="Perform")
        card.add_recommendation(title="Refer for retinal examination", button="Refer")
        return card

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard for the patient's eye-exam status."""
        if not self.in_denominator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS131v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
            return [card.apply()]

        if self.in_numerator():
            return [self._satisfied_card().apply()]
        return [self._due_card().apply()]


# Keep RetinalOrDilatedEyeExam importable from this module for downstream readability.
__all__ = (
    "ClinicalQualityMeasure131v6",
    "FundusPhotography",
    "RetinalOrDilatedEyeExam",
)
