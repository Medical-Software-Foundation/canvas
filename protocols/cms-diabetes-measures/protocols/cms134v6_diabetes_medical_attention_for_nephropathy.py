"""
CMS134v6 - Diabetes: Medical Attention for Nephropathy.

Patients 18-75 with diabetes must have had at least one of the following in the
measurement period:

  * a Dialysis-related referral report
  * an active ACE-inhibitor medication
  * a "dismissing" comorbid condition (hypertensive CKD, kidney failure,
    glomerulonephritis/nephrotic syndrome, diabetic nephropathy, proteinuria)
  * a kidney transplant condition
  * a dialysis-education instruction
  * a urine protein lab

https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS134v6.html
"""

from __future__ import annotations

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.instruction import Instruction
from canvas_sdk.v1.data.lab import LabReport, LabValue
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.referral import ReferralReport
from canvas_sdk.value_set.v2022.condition import (
    DiabeticNephropathy,
    GlomerulonephritisAndNephroticSyndrome,
    HypertensiveChronicKidneyDisease,
    KidneyFailure,
    Proteinuria,
)
from canvas_sdk.value_set.v2022.intervention import DialysisEducation
from canvas_sdk.value_set.v2022.laboratory_test import UrineProteinTests
from canvas_sdk.value_set.v2022.procedure import KidneyTransplant
from canvas_sdk.value_set.value_set import ValueSet

from .diabetes_quality_measure import DiabetesQualityMeasure


class AceInhibitors(ValueSet):
    """FDB-coded ACE inhibitor medications. Codes copied from
    ``canvas_workflow_kit.value_set.medication_class_path2018.AceInhibitors``.
    """

    VALUE_SET_NAME = "ACE Inhibitors"
    EXPANSION_VERSION = "ClassPath Update 18-10-15"
    FDB = {
        "150320", "151988", "152422", "157469", "158667", "163803", "166924",
        "169234", "169840", "170591", "171394", "176891", "179012", "183474",
        "186112", "186234", "189764", "191433", "197641", "202492", "203110",
        "204201", "206201", "206464", "208631", "208761", "208877", "218498",
        "219729", "221638", "227444", "228042", "228880", "230231", "233466",
        "239278", "240070", "241751", "243183", "244736", "244899", "247057",
        "247110", "250819", "253349", "256633", "257247", "264202", "267825",
        "268801", "269739", "272059", "273480", "278853", "279496", "282212",
        "285229", "286924", "288522", "290376", "291544", "291760", "295201",
        "295494", "295862", "298890", "579516", "579530", "591418", "591421",
        "591871", "591977",
    }


class CMS134v6Dialysis(ValueSet):
    """Dialysis-related codes used by CMS134v6 specifically (copied verbatim from
    ``canvas_workflow_kit.value_set.specials.CMS134v6Dialysis``).
    """

    VALUE_SET_NAME = "CMS 134v6 Dialysis"
    EXPANSION_VERSION = "CanvasHCC Update 2018-12-05"
    ICD10CM = {"Z992"}
    SNOMEDCT = {"207RN0300X", "2080P0210X"}


class ClinicalQualityMeasure134v6(DiabetesQualityMeasure):
    """CMS134v6 - Medical attention for nephropathy."""

    class Meta:
        title = "Diabetes: Medical Attention for Nephropathy"
        version = "2019-02-12v1"
        description = (
            "Patients 18-75 years of age with diabetes who have not had a nephropathy "
            "screening test in the last year or evidence of nephropathy."
        )
        information = "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS134v6.html"
        identifiers = ["CMS134v6"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.INSTRUCTION_CREATED),
        EventType.Name(EventType.INSTRUCTION_UPDATED),
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_UPDATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    DISMISSING_CONDITIONS: list[tuple[type[ValueSet], str]] = [
        (HypertensiveChronicKidneyDisease, "Hypertensive Chronic Kidney Disease"),
        (KidneyFailure, "Kidney Failure"),
        (GlomerulonephritisAndNephroticSyndrome, "Glomerulonephritis and Nephrotic Syndrome"),
        (DiabeticNephropathy, "Diabetic Nephropathy"),
        (Proteinuria, "Proteinuria"),
    ]

    message: str | None = None
    _due_in: int = -1

    def in_denominator(self) -> bool:
        """Equals the initial population."""
        return self.in_initial_population()

    def _last_dialysis_report(self) -> ReferralReport | None:
        """Most recent in-period dialysis-related ReferralReport."""
        return (
            ReferralReport.objects.filter(patient__id=self.patient.id)
            .filter(
                original_date__gte=self.timeframe.start.date(),
                original_date__lte=self.timeframe.end.date(),
            )
            .filter(
                codings__system__in=[s for s, _ in self._codings(CMS134v6Dialysis)],
                codings__code__in=[c for _, c in self._codings(CMS134v6Dialysis)],
            )
            .order_by("-original_date")
            .first()
        )

    @staticmethod
    def _codings(value_set: type[ValueSet]) -> list[tuple[str, str]]:
        """Flatten a value set into (system_url, code) pairs."""
        pairs: list[tuple[str, str]] = []
        for system, url in value_set.CODE_SYSTEM_MAPPING.items():
            codes = getattr(value_set, system, None)
            if codes:
                pairs.extend((url, code) for code in codes)
        return pairs

    def _last_dialysis_education(self) -> Instruction | None:
        """Most recent in-period dialysis-education Instruction."""
        return (
            Instruction.objects.for_patient(self.patient.id)
            .committed()
            .find(DialysisEducation)
            .filter(
                note__datetime_of_service__range=(
                    self.timeframe.start.datetime,
                    self.timeframe.end.datetime,
                ),
            )
            .order_by("-note__datetime_of_service")
            .first()
        )

    def _last_urine_protein_lab(self) -> LabReport | None:
        """Most recent in-period urine protein LabReport."""
        value = (
            LabValue.objects.filter(
                report__patient__id=self.patient.id,
                report__original_date__gte=self.timeframe.start.datetime,
                report__original_date__lte=self.timeframe.end.datetime,
            )
            .find(UrineProteinTests)
            .order_by("-report__original_date")
            .first()
        )
        return value.report if value else None

    def in_numerator(self) -> bool:
        """Any of dialysis referral, ACE inhibitor, dismissing condition, kidney transplant,
        or urine protein lab during the period qualifies the patient.
        """
        self.message = None
        self._due_in = -1
        first_name = self.patient.first_name

        dialysis = self._last_dialysis_report()
        if dialysis:
            self.message = (
                f"{first_name} has diabetes and had a Dialysis Related Service "
                f"{self.display_date(arrow.get(dialysis.original_date))}"
            )
            return True

        active_ace = (
            Medication.objects.for_patient(self.patient.id)
            .active()
            .find(AceInhibitors)
            .filter(start_date__lte=self.timeframe.end.datetime)
            .filter(end_date__gte=self.timeframe.start.datetime)
            .exists()
        )
        if active_ace:
            self.message = f"{first_name} has diabetes and is under Ace Inhibitors medication"
            return True

        for condition_vs, label in self.DISMISSING_CONDITIONS:
            has_condition = (
                Condition.objects.for_patient(self.patient.id)
                .active()
                .find(condition_vs)
                .filter(onset_date__lte=self.timeframe.end.date())
                .exists()
            )
            if has_condition:
                self.message = f"{first_name} has diabetes and has been diagnosed {label}"
                return True

        kidney_transplant = (
            Condition.objects.for_patient(self.patient.id)
            .active()
            .find(KidneyTransplant)
            .filter(onset_date__lte=self.timeframe.end.date())
            .exists()
        )
        if kidney_transplant:
            self.message = f"{first_name} has diabetes and had a Kidney Transplant"
            return True

        dialysis_education = self._last_dialysis_education()
        if dialysis_education:
            self.message = (
                f"{first_name} has diabetes and had an ESRD Monthly Outpatient Services "
                f"{self.display_date(arrow.get(dialysis_education.note.datetime_of_service))}"
            )
            return True

        urine_protein = self._last_urine_protein_lab()
        if urine_protein:
            on_date = arrow.get(urine_protein.original_date)
            self._due_in = (on_date.shift(days=self.timeframe.duration) - self.now).days
            self.message = (
                f"{first_name} has diabetes and a urine protein test was done "
                f"{self.display_date(on_date)}"
            )
            return True

        return False

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard for the patient's nephropathy-attention status."""
        if not self.in_denominator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS134v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
            return [card.apply()]

        if self.in_numerator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS134v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.SATISFIED,
                narrative=self.message or "",
                due_in=self._due_in,
            )
            return [card.apply()]

        card = ProtocolCard(
            patient_id=self.patient.id,
            key="CMS134v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            narrative=(
                f"{self.patient.first_name} has diabetes and a urine microalbumin test "
                "is due to screen for nephropathy"
            ),
            due_in=-1,
        )
        card.add_recommendation(title="Order a urine microalbumin test", button="Order")
        return [card.apply()]
