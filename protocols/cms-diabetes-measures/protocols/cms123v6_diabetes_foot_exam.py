"""
CMS123v6 - Diabetes: Foot Exam.

Patients 18-75 with diabetes need an annual comprehensive foot examination consisting of
a visual inspection, a sensory exam, and a pulse exam. Patients are excluded if they have
had a bilateral or two unilateral leg amputations.

https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS123v6.html
"""

from __future__ import annotations

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.questionnaire import Interview
from canvas_sdk.value_set.value_set import ValueSet

from .diabetes_quality_measure import DiabetesQualityMeasure


# Value sets that do not exist in canvas_sdk.value_set.v2022 / v2026.
# Codes are copied verbatim from canvas_workflow_kit.value_set.v2018.


class VisualExamOfFoot(ValueSet):
    """SNOMED code for the visual portion of a comprehensive foot exam."""

    OID = "2.16.840.1.113883.3.464.1003.103.12.1013"
    VALUE_SET_NAME = "Visual Exam of Foot"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"
    SNOMEDCT = {"401191002"}


class SensoryExamOfFoot(ValueSet):
    """SNOMED code for the sensory portion of a comprehensive foot exam."""

    OID = "2.16.840.1.113883.3.464.1003.103.12.1014"
    VALUE_SET_NAME = "Sensory Exam of Foot"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"
    SNOMEDCT = {"134388005"}


class PulseExamOfFoot(ValueSet):
    """SNOMED code for the pulse portion of a comprehensive foot exam."""

    OID = "2.16.840.1.113883.3.464.1003.103.12.1015"
    VALUE_SET_NAME = "Pulse Exam of Foot"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"
    SNOMEDCT = {"91161007"}


class BilateralAmputationOfLegBelowOrAboveKnee(ValueSet):
    """Bilateral leg amputation - any one of these excludes the patient."""

    OID = "2.16.840.1.113883.3.464.1003.113.12.1056"
    VALUE_SET_NAME = "Bilateral amputation of leg below or above knee"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"
    ICD10CM = {"Q7203", "Q7223"}
    ICD9CM = {"8976", "8977"}


class RightUnilateralAmputationAboveOrBelowKnee(ValueSet):
    """Right unilateral leg amputation."""

    OID = "2.16.840.1.113883.3.464.1003.113.12.1057"
    VALUE_SET_NAME = "Right Unilateral Amputation Above or Below Knee"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"
    ICD10CM = {
        "Q7221", "S78011A", "S78011D", "S78111A", "S78111D", "S88011A", "S88011D",
        "S88111A", "S88111D", "S88111S", "S88911S", "Z89511", "Z89521", "Z89611", "Z89621",
    }
    SNOMEDCT = {"308095002", "308097005"}


class LeftUnilateralAmputationAboveOrBelowKnee(ValueSet):
    """Left unilateral leg amputation."""

    OID = "2.16.840.1.113883.3.464.1003.113.12.1058"
    VALUE_SET_NAME = "Left Unilateral Amputation Above or Below Knee"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"
    ICD10CM = {
        "Q7222", "S78012A", "S78012D", "S78112A", "S78112D", "S88012A", "S88012D",
        "S88112A", "S88112D", "S88112S", "S88912S", "Z89512", "Z89522", "Z89612", "Z89622",
    }
    SNOMEDCT = {"308096001", "308098000"}


class UnilateralAmputationBelowOrAboveKneeUnspecifiedLaterality(ValueSet):
    """Unilateral leg amputation, side unspecified."""

    OID = "2.16.840.1.113883.3.464.1003.113.12.1059"
    VALUE_SET_NAME = "Unilateral Amputation Below or Above Knee, Unspecified Laterality"
    EXPANSION_VERSION = "eCQM Update 2017-05-05"
    ICD10CM = {"Q7220"}
    ICD9CM = {"8970", "8971", "8972", "8973", "V4975", "V4976", "V4977"}
    SNOMEDCT = {
        "110470001", "11228000", "12663001", "265735000", "265736004", "298049006",
        "298050006", "38162008", "397163000", "397164006", "397166008", "397167004",
        "397168009", "397169001", "443025009", "6661001", "76017008", "79733001",
        "83574003", "87562003", "88312006",
    }


class ClinicalQualityMeasure123v6(DiabetesQualityMeasure):
    """CMS123v6 - Diabetes foot exam."""

    class Meta:
        title = "Diabetes: Foot Exam"
        version = "2023-07-06v1"
        description = (
            "Patients 18-75 years of age with diabetes who have not received a foot exam "
            "in the last year."
        )
        information = "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS123v6.html"
        identifiers = ["CMS123v6"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    _on_dates: list[arrow.Arrow] | None = None

    @property
    def period(self) -> str:
        """Render the date range of the patient's three foot-exam findings."""
        if not self._on_dates:
            return "N/A"
        from_date = min(self._on_dates)
        to_date = max(self._on_dates)
        if from_date == to_date:
            return self.display_date(from_date)
        return f"between {from_date.format('M/D/YY')} and {to_date.format('M/D/YY')}"

    def in_denominator(self) -> bool:
        """Initial population, minus the amputation exclusion."""
        if not self.in_initial_population():
            return False

        prior_conditions = Condition.objects.for_patient(self.patient.id).filter(
            onset_date__lte=self.timeframe.end.date()
        )

        if prior_conditions.find(BilateralAmputationOfLegBelowOrAboveKnee).exists():
            return False

        amputations = prior_conditions.find(
            LeftUnilateralAmputationAboveOrBelowKnee
            | RightUnilateralAmputationAboveOrBelowKnee
            | UnilateralAmputationBelowOrAboveKneeUnspecifiedLaterality
        )
        if amputations.count() >= 2:
            return False

        return True

    def _exam_dates(self, value_set: type[ValueSet]) -> list[arrow.Arrow]:
        """Dates of committed interviews with a response coded in ``value_set``.

        Mirrors the legacy ``patient.interviews.find_question_response(VS)``
        semantics: an interview qualifies when any of its
        ``InterviewQuestionResponse`` rows points at a ``ResponseOption`` whose
        ``code`` is in the value set. (Codes in eCQM measure value sets are
        SNOMED CT, so collisions with other code systems are not a concern.)
        """
        codes = {code for code_set in value_set.values.values() for code in code_set}
        interviews = (
            Interview.objects.for_patient(self.patient.id)
            .committed()
            .filter(
                deleted=False,
                interview_responses__response_option__code__in=codes,
                created__gte=self.timeframe.start.datetime,
                created__lte=self.timeframe.end.datetime,
            )
            .distinct()
        )
        return [arrow.get(i.created) for i in interviews]

    def in_numerator(self) -> bool:
        """All three exam findings (visual, sensory, pulse) must have happened in the period."""
        all_dates: list[arrow.Arrow] = []
        for exam_class in (VisualExamOfFoot, SensoryExamOfFoot, PulseExamOfFoot):
            dates = self._exam_dates(exam_class)
            if not dates:
                self._on_dates = []
                return False
            all_dates.append(max(dates))
        self._on_dates = all_dates
        return True

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard summarizing the patient's foot-exam status."""
        if not self.in_denominator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS123v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
            return [card.apply()]

        first_name = self.patient.first_name
        if self.in_numerator():
            assert self._on_dates is not None
            due_in = (min(self._on_dates).shift(days=self.timeframe.duration) - self.now).days
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS123v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.SATISFIED,
                narrative=(
                    f"{first_name} has diabetes and his comprehensive foot exam "
                    f"was done {self.period}."
                ),
                due_in=due_in,
            )
            return [card.apply()]

        card = ProtocolCard(
            patient_id=self.patient.id,
            key="CMS123v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            narrative=f"{first_name} has diabetes and is due for foot exam.",
            due_in=-1,
        )
        card.add_recommendation(
            title=(
                "Conduct comprehensive foot examination including assessment of protective "
                "sensation, pulses and visual inspection."
            ),
        )
        return [card.apply()]
