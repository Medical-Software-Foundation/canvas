"""AWV workflow section modules."""

from guided_awv.modules.advance_care_planning import AdvanceCarePlanningModule
from guided_awv.modules.alcohol_screening import AlcoholScreeningModule
from guided_awv.modules.assessment_plan import AssessmentPlanModule
from guided_awv.modules.base import AWVType, BaseModule
from guided_awv.modules.cognitive_assessment import CognitiveAssessmentModule
from guided_awv.modules.current_providers import CurrentProvidersModule
from guided_awv.modules.depression_screening import DepressionScreeningModule
from guided_awv.modules.fall_risk import FallRiskModule
from guided_awv.modules.family_history import FamilyHistoryModule
from guided_awv.modules.followup_scheduling import FollowUpSchedulingModule
from guided_awv.modules.functional_ability import FunctionalAbilityModule
from guided_awv.modules.hearing_vision import HearingVisionModule
from guided_awv.modules.hra import HRAModule
from guided_awv.modules.medical_history import MedicalHistoryModule
from guided_awv.modules.medication_reconciliation import MedicationReconciliationModule
from guided_awv.modules.preventive_services import PreventiveServicesModule
from guided_awv.modules.sdoh_screening import SDOHScreeningModule
from guided_awv.modules.vitals import VitalsModule

__all__ = [
    "AWVType",
    "BaseModule",
    "HRAModule",
    "MedicalHistoryModule",
    "MedicationReconciliationModule",
    "FamilyHistoryModule",
    "CurrentProvidersModule",
    "VitalsModule",
    "HearingVisionModule",
    "DepressionScreeningModule",
    "AlcoholScreeningModule",
    "CognitiveAssessmentModule",
    "SDOHScreeningModule",
    "FunctionalAbilityModule",
    "FallRiskModule",
    "PreventiveServicesModule",
    "AdvanceCarePlanningModule",
    "AssessmentPlanModule",
    "FollowUpSchedulingModule",
]

# Ordered list of all module classes, sorted by each module's ORDER attribute
ALL_MODULES = sorted(
    [
        HRAModule,
        MedicalHistoryModule,
        MedicationReconciliationModule,
        FamilyHistoryModule,
        CurrentProvidersModule,
        VitalsModule,
        HearingVisionModule,
        DepressionScreeningModule,
        AlcoholScreeningModule,
        CognitiveAssessmentModule,
        SDOHScreeningModule,
        FunctionalAbilityModule,
        FallRiskModule,
        PreventiveServicesModule,
        AdvanceCarePlanningModule,
        AssessmentPlanModule,
        FollowUpSchedulingModule,
    ],
    key=lambda m: m.ORDER,
)
