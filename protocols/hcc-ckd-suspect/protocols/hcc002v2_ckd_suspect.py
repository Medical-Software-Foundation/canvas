"""HCC002v2 - CKD Suspect.

Surfaces a protocol card for any patient with two or more creatinine lab
values yielding an eGFR below 60 ml/min over the last two years and no active
kidney-related condition on the problem list. The card recommends adding a
diagnosis. Patients who already have an active kidney-failure or
hypertensive-CKD condition receive a satisfied card.
"""

from functools import cached_property

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.lab import LabValue
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.value_set.custom import LabReportCreatinine
from canvas_sdk.value_set.v2022.condition import (
    HypertensiveChronicKidneyDisease,
    KidneyFailure,
)


class Hcc002v2(ClinicalQualityMeasure):
    """CKD Suspect protocol."""

    class Meta:
        title = "CKD suspect"
        version = "2019-02-12v1"
        description = (
            "All patients with evidence of two or more elevated eGFR values "
            "and no active CKD problem on the Conditions List."
        )
        information = (
            "https://canvas-medical.help.usepylon.com/articles/6051758367-ckd-suspect"
        )
        identifiers = ["HCC002v2"]
        types = ["HCC"]
        authors = ["Canvas Medical Team"]
        show_in_chart = False
        references = [
            "Canvas Medical HCC. "
            "https://canvas-medical.help.usepylon.com/articles/6051758367-ckd-suspect"
        ]
        default_permission_flags = {"protocols:actions:HCC002v2:": True}

    RESPONDS_TO = [
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    LOOKBACK_YEARS = 2
    EGFR_THRESHOLD = 60

    @cached_property
    def patient(self) -> Patient:
        """The Patient row for the event target."""
        return Patient.objects.get(id=self.patient_id_from_target())

    @cached_property
    def patient_age(self) -> int:
        """The patient's age (in whole years) at the protocol's reference time."""
        return int(self.patient.age_at(self.now))

    def egfr(self, creatinine: float, units: str) -> float:
        """Compute the 4-variable MDRD eGFR for the protocol's patient.

        Mirrors the legacy formula:
        ``186 * (creatinine / unit_coefficient) ** -1.154 * age ** -0.203 * sex * race``
        where ``unit_coefficient`` is 1 for mg/dL and 88.4 otherwise.
        """
        sex = 0.742 if self.patient.sex_at_birth == "F" else 1
        race = 1.210 if "2054-5" in (self.patient.biological_race_codes or []) else 1
        coefficient = 1 if units == "mg/dL" else 88.4
        return (
            186
            * pow(creatinine / coefficient, -1.154)
            * pow(self.patient_age, -0.203)
            * sex
            * race
        )

    @cached_property
    def lookback_timeframe(self) -> Timeframe:
        """Two years ending at ``self.now``."""
        return Timeframe(start=self.now.shift(years=-self.LOOKBACK_YEARS), end=self.now)

    @cached_property
    def high_creatinine_values(self) -> list[LabValue]:
        """Creatinine lab values in the lookback window whose eGFR is below 60."""
        # eGFR can't be computed for age 0 (ZeroDivisionError in pow(0, -0.203));
        # a pediatric eGFR would be needed instead.
        if self.patient_age == 0:
            return []

        values = (
            LabValue.objects.for_patient(self.patient.id)
            .find(LabReportCreatinine)
            .within(self.lookback_timeframe)
        )

        return [
            value
            for value in values
            if (
                (creatinine := self.relative_float(value.value)) > 0
                and self.egfr(creatinine, value.units) < self.EGFR_THRESHOLD
            )
        ]

    @cached_property
    def has_active_kidney_condition(self) -> bool:
        """True when the patient has an active CKD-related condition."""
        return (
            Condition.objects.for_patient(self.patient.id)
            .find(HypertensiveChronicKidneyDisease | KidneyFailure)
            .active()
            .exists()
        )

    def in_initial_population(self) -> bool:
        """All patients are in the initial population."""
        return True

    def in_denominator(self) -> bool:
        """Patients with two or more eGFR values below 60 in the last two years."""
        return len(self.high_creatinine_values) >= 2

    def in_numerator(self) -> bool:
        """Patients with an active kidney-related condition on the problem list."""
        return self.has_active_kidney_condition

    def compute(self) -> list[Effect]:
        """Emit a ProtocolCard effect when the patient is in the denominator."""
        if not self.in_denominator():
            return []

        card = ProtocolCard(
            patient_id=self.patient.id,
            key="HCC002v2",
            title="CKD suspect",
            due_in=-1,
        )

        if self.in_numerator():
            card.status = ProtocolCard.Status.SATISFIED
        else:
            card.status = ProtocolCard.Status.DUE
            card.narrative = (
                f"{self.patient.first_name} has at least two eGFR measurements "
                "< 60 ml/min over the last two years suggesting renal disease. "
                "There is no associated condition on the Conditions List."
            )
            card.add_recommendation(
                title=(
                    "Consider updating the Conditions List to include kidney "
                    "related problems as clinically appropriate"
                ),
                button="Diagnose",
                command="diagnose",
            )

        return [card.apply()]
