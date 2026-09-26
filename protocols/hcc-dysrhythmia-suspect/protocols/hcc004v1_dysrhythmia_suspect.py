"""HCC004v1 - Dysrhythmia Suspect.

Surfaces a protocol card for patients who have an active medication in the
Antiarrhythmics drug class but no active condition in the Dysrhythmia class
on their Conditions List. The card recommends adding a dysrhythmia-related
diagnosis as clinically appropriate.
"""

from functools import cached_property

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.value_set.custom import Antiarrhythmics, DysrhythmiaClassConditionSuspect


class Hcc004v1(ClinicalQualityMeasure):
    """Dysrhythmia Suspect protocol."""

    class Meta:
        title = "Dysrhythmia Suspects"
        version = "2019-02-12v1"
        description = (
            "All patients with potential dysrhythmia based on an "
            "active medication without associated active problem."
        )
        information = "https://canvas-medical.help.usepylon.com/articles/7052809697-protocol-dysrhythmia-suspects-hcc004v1"
        identifiers = ["HCC004v1"]
        types = ["HCC"]
        authors = ["Canvas Medical Team"]
        references = [
            "Canvas Medical HCC, https://canvas-medical.help.usepylon.com/articles/7052809697-protocol-dysrhythmia-suspects-hcc004v1"
        ]
        default_permission_flags = {"protocols:actions:HCC004v1:": True}

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_UPDATED),
    ]

    def _has_active(self, model: type, value_set: type) -> bool:
        """Return True if the patient has an active ``model`` row matching ``value_set``."""
        return (
            model.objects.for_patient(self.patient_id_from_target())
            .active()
            .find(value_set)
            .exists()
        )

    @cached_property
    def has_active_antiarrhythmic_medication(self) -> bool:
        """Patient has an active medication in the Antiarrhythmics drug class."""
        return self._has_active(Medication, Antiarrhythmics)

    @cached_property
    def has_active_dysrhythmia_condition(self) -> bool:
        """Patient has an active condition in the Dysrhythmia class."""
        return self._has_active(Condition, DysrhythmiaClassConditionSuspect)

    def in_initial_population(self) -> bool:
        """All patients are in the initial population."""
        return True

    def in_denominator(self) -> bool:
        """Patients with any active medication in the Antiarrhythmics drug class."""
        return self.has_active_antiarrhythmic_medication

    def in_numerator(self) -> bool:
        """Patients without an active condition in the Dysrhythmia class."""
        return not self.has_active_dysrhythmia_condition

    def compute(self) -> list[Effect]:
        """Emit a ProtocolCard describing the patient's dysrhythmia-suspect status."""
        if not self.in_denominator():
            return []

        patient_id = self.patient_id_from_target()
        card = ProtocolCard(
            patient_id=patient_id,
            key="HCC004v1",
            title="Dysrhythmia Suspects",
        )

        if not self.in_numerator():
            card.status = ProtocolCard.Status.SATISFIED
            return [card.apply()]

        patient = Patient.objects.get(id=patient_id)
        card.status = ProtocolCard.Status.DUE
        card.narrative = (
            f"{patient.first_name} has an active medication on the Medication List "
            "commonly used for Dysrhythmia. There is no associated condition on "
            "the Conditions List."
        )
        card.add_recommendation(
            title=(
                "Consider updating the Conditions List to include Dysrhythmia "
                "related problem as clinically appropriate."
            ),
            button="Diagnose",
            command="diagnose",
        )
        return [card.apply()]
