"""HCC003v1 - Diabetes Mellitus With Secondary Complication Suspect.

Surfaces a protocol card for patients who have an active "Diabetes without
complication" diagnosis (E11.9) AND a secondary condition often associated with
diabetes (eye, neurologic, renal, circulatory, or other). For each matched
complication category, a "Diagnose" recommendation is added that suggests
updating the diagnosis to the more specific code.
"""

from functools import cached_property

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.value_set.custom import (
    DiabetesCirculatoryClassConditionSuspect,
    DiabetesEyeClassConditionSuspect,
    DiabetesEyeConditionSuspect,
    DiabetesNeurologicConditionSuspect,
    DiabetesOtherClassConditionSuspect,
    DiabetesRenalConditionSuspect,
    DiabetesWithoutComplication,
)


class Hcc003v1(ClinicalQualityMeasure):
    """Diabetes Mellitus With Secondary Complication Suspect protocol."""

    class Meta:
        title = "Diabetes Mellitus With Secondary Complication Suspect"
        version = "2019-02-12v1"
        description = (
            "All patients with diabetes, uncomplicated AND a "
            "2ndary condition often associated with diabetes."
        )
        information = "https://canvas-medical.help.usepylon.com/articles/2137336140-protocol-diabetes-mellitus-secondary-complication"
        identifiers = ["HCC003v1"]
        types = ["HCC"]
        authors = ["Canvas Medical Team"]
        references = [
            "Canvas Medical HCC, https://canvas-medical.help.usepylon.com/articles/2137336140-protocol-diabetes-mellitus-secondary-complication"
        ]
        default_permission_flags = {"protocols:actions:HCC003v1:": True}

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.CONDITION_RESOLVED),
    ]

    def _has_active_condition(self, value_set: type) -> bool:
        """Return True if the patient has an active condition in ``value_set``."""
        return (
            Condition.objects.for_patient(self.patient_id_from_target())
            .find(value_set)
            .active()
            .exists()
        )

    @cached_property
    def has_diabetes_with_unspecified_condition(self) -> bool:
        """Patient has an active "Diabetes without complication" (E11.9) diagnosis."""
        return self._has_active_condition(DiabetesWithoutComplication)

    @cached_property
    def has_suspect_eye_condition(self) -> bool:
        """Patient has an active suspect eye condition."""
        return self._has_active_condition(
            DiabetesEyeConditionSuspect
        ) or self._has_active_condition(DiabetesEyeClassConditionSuspect)

    @cached_property
    def has_suspect_neurologic_condition(self) -> bool:
        """Patient has an active suspect neurologic condition."""
        return self._has_active_condition(DiabetesNeurologicConditionSuspect)

    @cached_property
    def has_suspect_renal_condition(self) -> bool:
        """Patient has an active suspect renal condition."""
        return self._has_active_condition(DiabetesRenalConditionSuspect)

    @cached_property
    def has_suspect_circulatory_condition(self) -> bool:
        """Patient has an active suspect circulatory condition."""
        return self._has_active_condition(DiabetesCirculatoryClassConditionSuspect)

    @cached_property
    def has_suspect_other_condition(self) -> bool:
        """Patient has another active condition often associated with diabetes."""
        return self._has_active_condition(DiabetesOtherClassConditionSuspect)

    def in_initial_population(self) -> bool:
        """All patients are in the initial population."""
        return True

    def in_denominator(self) -> bool:
        """Patients with an active "Diabetes without complications" diagnosis."""
        return self.has_diabetes_with_unspecified_condition

    def in_numerator(self) -> bool:
        """Patients with at least one active suspect secondary complication."""
        return (
            self.has_suspect_eye_condition
            or self.has_suspect_neurologic_condition
            or self.has_suspect_renal_condition
            or self.has_suspect_circulatory_condition
            or self.has_suspect_other_condition
        )

    def _build_narrative_and_recommendations(
        self, card: ProtocolCard, first_name: str
    ) -> None:
        """Append a narrative line and a "Diagnose" recommendation per matching category."""
        narratives: list[str] = []

        categories = [
            (
                self.has_suspect_eye_condition,
                "an eye condition commonly caused by diabetes on the Conditions list.",
                "Consider updating the Diabetes without complications (E11.9) "
                "to Diabetes with secondary eye disease as clinically appropriate.",
            ),
            (
                self.has_suspect_neurologic_condition,
                "a neurological condition commonly caused by diabetes on the Conditions list.",
                "Consider updating the Diabetes without complications (E11.9) "
                "to Diabetes with secondary neurological sequela as clinically appropriate.",
            ),
            (
                self.has_suspect_renal_condition,
                "a chronic renal condition commonly caused by diabetes on the Conditions list.",
                "Consider updating the Diabetes without complications (E11.9) "
                "to Diabetes with secondary renal disease as clinically appropriate.",
            ),
            (
                self.has_suspect_circulatory_condition,
                "a circulatory condition commonly caused by diabetes on the Conditions list.",
                "Consider updating the Diabetes without complications (E11.9) "
                "to Diabetes with secondary circulatory disorder as clinically appropriate.",
            ),
            (
                self.has_suspect_other_condition,
                "an another condition commonly caused by diabetes on the Conditions list.",
                "Consider updating the Diabetes without complications (E11.9) "
                "to Diabetes with other secondary complication as clinically appropriate.",
            ),
        ]

        for matched, narrative_suffix, recommendation_title in categories:
            if not matched:
                continue
            narratives.append(
                f"{first_name} has Diabetes without complications AND {narrative_suffix}"
            )
            card.add_recommendation(
                title=recommendation_title,
                button="Diagnose",
                command="diagnose",
            )

        card.narrative = "\n".join(narratives)

    def compute(self) -> list[Effect]:
        """Emit a protocol card describing the patient's secondary-complication status."""
        if not self.in_denominator():
            return []

        patient_id = self.patient_id_from_target()
        card = ProtocolCard(
            patient_id=patient_id,
            key="HCC003v1",
            title="Diabetes Mellitus With Secondary Complication Suspect",
        )

        if not self.in_numerator():
            card.status = ProtocolCard.Status.SATISFIED
            card.due_in = -1
            return [card.apply()]

        patient = Patient.objects.get(id=patient_id)
        card.status = ProtocolCard.Status.DUE
        card.due_in = -1
        self._build_narrative_and_recommendations(card, patient.first_name)
        return [card.apply()]
