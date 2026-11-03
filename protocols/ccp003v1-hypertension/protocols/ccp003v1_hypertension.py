"""CCP003v1 — Diagnosis Of Hypertension.

Surfaces a protocol card for every patient who has an active hypertension
condition on file, recommending that the patient be contacted. Patients without
an active hypertension condition receive a satisfied card.
"""

import arrow

from canvas_sdk.commands import FollowUpCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.value_set.v2022.condition import DiagnosisOfHypertension


class Ccp003v1(ClinicalQualityMeasure):
    """Diagnosis Of Hypertension protocol."""

    class Meta:
        title = "Diagnosis Of Hypertension"
        version = "2020-04-02v1"
        description = "All patients with Diagnosis Of Hypertension."
        information = "https://canvas-medical.help.usepylon.com/"
        identifiers = ["CCP003v1"]
        types = ["CCP"]
        authors = ["Canvas Medical Team"]
        show_in_chart = False
        references = ["Canvas Medical CCP. https://canvas-medical.help.usepylon.com/"]
        default_permission_flags = {"protocols:actions:CCP003v1:": True}

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.CONDITION_RESOLVED),
    ]

    @property
    def active_hypertension_conditions(self) -> list[Condition]:
        """Active hypertension conditions for the patient, oldest first by onset."""
        return list(
            Condition.objects.for_patient(self.patient_id_from_target())
            .find(DiagnosisOfHypertension)
            .active()
            .order_by("onset_date")
        )

    @property
    def date_of_diagnosis(self) -> str:
        """The earliest onset date among the patient's active hypertension conditions, or ''."""
        for condition in self.active_hypertension_conditions:
            if condition.onset_date:
                return condition.onset_date.isoformat()
        return ""

    def in_initial_population(self) -> bool:
        """All patients are in the initial population."""
        return True

    def in_denominator(self) -> bool:
        """Patients in the initial population."""
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        """Patients that have been diagnosed with hypertension."""
        return bool(self.date_of_diagnosis)

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard effect describing the patient's hypertension status."""
        if not self.in_denominator():
            return []

        patient_id = self.patient_id_from_target()
        patient = Patient.objects.get(id=patient_id)

        card = ProtocolCard(
            patient_id=patient_id,
            key="CCP003v1",
            title="Diagnosis Of Hypertension",
        )

        if self.in_numerator():
            formatted_date = arrow.get(self.date_of_diagnosis).format(
                "ddd, MMM Do YYYY"
            )
            card.narrative = f"{patient.first_name} has been diagnosed of hypertension on {formatted_date}."
            card.status = ProtocolCard.Status.DUE
            card.due_in = 0
            card.add_recommendation(
                title="Contact the patient",
                button="Schedule",
                commands=[FollowUpCommand()],
            )
        else:
            card.narrative = (
                f"{patient.first_name} has not been diagnosed of hypertension."
            )
            card.status = ProtocolCard.Status.SATISFIED
            card.due_in = -1

        return [card.apply()]
