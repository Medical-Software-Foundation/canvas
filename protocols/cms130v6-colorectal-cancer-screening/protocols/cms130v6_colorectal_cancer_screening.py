"""CMS130v6 Colorectal Cancer Screening clinical quality measure.

Surfaces a Protocol Card recommending colorectal cancer screening for adults
50-75 who have not had appropriate screening, and marks the card satisfied
for patients who have had a qualifying exam within the relevant look-back
window.
"""

from functools import cached_property
from typing import Any

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.imaging import ImagingReport
from canvas_sdk.v1.data.lab import LabValue
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.referral import ReferralReport
from canvas_sdk.value_set.v2022.condition import MalignantNeoplasmOfColon
from canvas_sdk.value_set.v2022.diagnostic_study import CtColonography
from canvas_sdk.value_set.v2022.laboratory_test import (
    FecalOccultBloodTestFobt,
    FitDna,
)
from canvas_sdk.value_set.v2022.procedure import (
    Colonoscopy,
    FlexibleSigmoidoscopy,
    TotalColectomy,
)
from canvas_sdk.value_set.value_set import ValueSet


class CMS130v6CtColonography(ValueSet):
    """Supplementary LOINC code for CT Colonography not present in the v2018 value set."""

    VALUE_SET_NAME = "CMS130v6 CT Colonography supplement"
    LOINC = {"79101-2"}


# Look-back windows (in days) per the eCQM specification.
SCREENING_INTERVALS = {
    "FOBT": 365,
    "FIT-DNA": 1096,  # ~3 years
    "Flexible sigmoidoscopy": 1826,  # ~5 years
    "CT Colonography": 1826,  # ~5 years
    "Colonoscopy": 3652,  # ~10 years
}


class ClinicalQualityMeasure130v6(ClinicalQualityMeasure):
    """
    Colorectal Cancer Screening (CMS130v6).

    Percentage of adults 50-75 years of age who had appropriate screening for
    colorectal cancer.

    See: https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS130v6.html
    """

    class Meta:
        title = "Colorectal Cancer Screening"
        version = "2020-02-24v1"
        description = (
            "Adults 50-75 years of age who have not had appropriate "
            "screening for colorectal cancer."
        )
        information = "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS130v6.html"
        identifiers = ["CMS130v6"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]
        references = [
            "American Cancer Society. 2015. Cancer Prevention & Early Detection Facts & Figures 2015-2016. Atlanta: American Cancer Society.",
            "National Cancer Institute. 2015. SEER Stat Fact Sheets: Colon and Rectum Cancer. Bethesda, MD, http://seer.cancer.gov/statfacts/html/colorect.html",
            "U.S. Preventive Services Task Force (USPSTF). 2008. Screening for colorectal cancer: U.S. Preventive Services Task Force recommendation statement. Ann Intern Med 149(9):627-37.",
        ]

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.IMAGING_REPORT_CREATED),
        EventType.Name(EventType.IMAGING_REPORT_UPDATED),
        EventType.Name(EventType.REFERRAL_REPORT_CREATED),
        EventType.Name(EventType.REFERRAL_REPORT_UPDATED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_CREATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_UPDATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_DELETED),
    ]

    PROTOCOL_KEY = "CMS130v6"
    AGE_RANGE_START = 50
    AGE_RANGE_END = 75

    CT_COLONOGRAPHY_VALUE_SET = CtColonography | CMS130v6CtColonography
    COLON_EXCLUSION_VALUE_SET = TotalColectomy | MalignantNeoplasmOfColon

    @cached_property
    def patient(self) -> Patient:
        """Return the Patient this protocol is being computed for."""
        return Patient.objects.get(id=self.patient_id_from_target())

    def in_age_range(self) -> bool:
        """Return True if the patient is between AGE_RANGE_START and AGE_RANGE_END (inclusive)."""
        age = self.patient.age_at(self.now)
        return self.AGE_RANGE_START <= age <= self.AGE_RANGE_END

    def had_colon_exclusion(self) -> bool:
        """Return True if the patient has an active colon exclusion (colectomy or colon cancer)."""
        return (
            Condition.objects.find(self.COLON_EXCLUSION_VALUE_SET)
            .for_patient(self.patient.id)
            .active()
            .exists()
        )

    def first_due_in(self) -> int | None:
        """Return days until the patient first becomes eligible, or None if not applicable."""
        if self.patient.age_at(self.now) >= self.AGE_RANGE_START:
            return None
        if self.had_colon_exclusion():
            return None
        birthday = arrow.get(self.patient.birth_date)
        return (birthday.shift(years=self.AGE_RANGE_START) - self.now).days

    def _latest_lab(self, value_set: type[ValueSet] | Any, days: int) -> Any:
        """Return the most recent LabValue within the look-back window, or None."""
        window_start = self.now.shift(days=-days)
        return (
            LabValue.objects.find(value_set)
            .filter(
                report__patient__id=self.patient.id,
                report__original_date__gte=window_start.date(),
                report__original_date__lte=self.now.date(),
            )
            .order_by("-report__original_date")
            .first()
        )

    def _latest_report_date(self, value_set: type[ValueSet] | Any, days: int) -> Any:
        """Return the most recent referral or imaging report date in the window matching ``value_set``.

        ReferralReport/ImagingReport do not mix in ``ValueSetLookupQuerySetMixin``,
        so the value set is flattened and applied as a ``codings`` filter
        (``codings__system`` + ``codings__code``).
        """
        window_start = self.now.shift(days=-days)
        values = value_set.values
        urls = [value_set.CODE_SYSTEM_MAPPING[name] for name in values]
        codes = {code for code_set in values.values() for code in code_set}
        kwargs = {
            "patient__id": self.patient.id,
            "original_date__gte": window_start.date(),
            "original_date__lte": self.now.date(),
            "codings__system__in": urls,
            "codings__code__in": codes,
        }
        candidates = [
            ReferralReport.objects.filter(**kwargs)
            .order_by("-original_date")
            .values_list("original_date", flat=True)
            .first(),
            ImagingReport.objects.filter(**kwargs)
            .order_by("-original_date")
            .values_list("original_date", flat=True)
            .first(),
        ]
        present = [d for d in candidates if d is not None]
        return max(present) if present else None

    @cached_property
    def _last_exam(self) -> dict | None:
        """Return a dict describing the most recent qualifying screening exam, or None.

        The dict contains:
            date: ISO-format date of the exam
            what: human-readable exam name
            days: look-back window length (days) used to evaluate this exam
        """
        fobt = self._latest_lab(FecalOccultBloodTestFobt, SCREENING_INTERVALS["FOBT"])
        if fobt is not None:
            return {
                "date": fobt.report.original_date.isoformat(),
                "what": "FOBT",
                "days": SCREENING_INTERVALS["FOBT"],
            }

        fitdna = self._latest_lab(FitDna, SCREENING_INTERVALS["FIT-DNA"])
        if fitdna is not None:
            return {
                "date": fitdna.report.original_date.isoformat(),
                "what": "FIT-DNA",
                "days": SCREENING_INTERVALS["FIT-DNA"],
            }

        report_exams = {
            "Flexible sigmoidoscopy": FlexibleSigmoidoscopy,
            "CT Colonography": self.CT_COLONOGRAPHY_VALUE_SET,
            "Colonoscopy": Colonoscopy,
        }
        for what, value_set in report_exams.items():
            record = self._latest_report_date(value_set, SCREENING_INTERVALS[what])
            if record is not None:
                return {
                    "date": record.isoformat(),
                    "what": what,
                    "days": SCREENING_INTERVALS[what],
                }

        return None

    def in_numerator(self) -> bool:
        """True if the patient has any qualifying screening within the look-back window."""
        return self._last_exam is not None

    def in_denominator(self) -> bool:
        """True if the patient is in the measure denominator."""
        if not self.in_age_range():
            return False
        if self.had_colon_exclusion():
            return False
        return True

    def _recommendation_context(self) -> dict:
        """Return the shared context (encounter diagnosis) for every recommendation."""
        return {
            "conditions": [
                [
                    {
                        "code": "Z1211",
                        "system": "ICD-10",
                        "display": "Encounter for screening for malignant neoplasm of colon",
                    }
                ]
            ]
        }

    def _satisfied_card(self, exam: dict) -> ProtocolCard:
        """Build the protocol card for a patient who is up-to-date."""
        last_date = arrow.get(exam["date"])
        due_in = (last_date.shift(days=exam["days"]) - self.now).days
        narrative = (
            f"{self.patient.first_name} had a {exam['what']} on "
            f"{last_date.format('M/D/YY')}."
        )
        return ProtocolCard(
            patient_id=self.patient.id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=narrative,
            status=ProtocolCard.Status.SATISFIED,
            due_in=due_in,
        )

    def _due_card(self) -> ProtocolCard:
        """Build the protocol card for a patient due for screening, with recommendations."""
        card = ProtocolCard(
            patient_id=self.patient.id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=f"{self.patient.first_name} is due for a Colorectal Cancer Screening.",
            status=ProtocolCard.Status.DUE,
            due_in=-1,
        )
        context = self._recommendation_context()

        card.add_recommendation(
            title="Order a FOBT",
            button="Order",
            command="labOrder",
            context={**context, "lab": list(FecalOccultBloodTestFobt.values.get("LOINC", set()))},
        )
        card.add_recommendation(
            title="Order a FIT-DNA",
            button="Order",
            command="labOrder",
            context={**context, "lab": list(FitDna.values.get("LOINC", set()))},
        )
        card.add_recommendation(
            title="Order a Flexible sigmoidoscopy",
            button="Order",
            command="refer",
            context={**context, "specialties": ["Gastroenterology"]},
        )
        card.add_recommendation(
            title="Order a CT Colonography",
            button="Order",
            command="imagingOrder",
            context={**context, "specialties": ["Radiology"]},
        )
        card.add_recommendation(
            title="Order a Colonoscopy",
            button="Order",
            command="refer",
            context={**context, "specialties": ["Gastroenterology"]},
        )

        return card

    def _not_applicable_card(self) -> ProtocolCard:
        """Build a protocol card for a patient outside the age range or with an exclusion."""
        due_in = self.first_due_in()
        return ProtocolCard(
            patient_id=self.patient.id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=(
                f"{self.patient.first_name} is not currently in the CMS130v6 measure population."
            ),
            status=ProtocolCard.Status.NOT_APPLICABLE,
            due_in=due_in if due_in is not None else -1,
        )

    def compute(self) -> list[Effect]:
        """Compute the protocol's effect list for the current event."""
        if not self.in_denominator():
            return [self._not_applicable_card().apply()]

        exam = self._last_exam
        if exam is not None:
            return [self._satisfied_card(exam).apply()]

        return [self._due_card().apply()]


__exports__ = ("CMS130v6CtColonography", "ClinicalQualityMeasure130v6")
