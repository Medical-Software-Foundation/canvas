import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import ImmunizationRecommendation, AllergyRecommendation
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.immunization import InfluenzaVaccine
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesIndividualCounseling

class COVIDVaccineValueSet(ValueSet):
    pass

class AcuteIllnessValueSet(ValueSet):
    pass

class SevereAllergyValueSet(ValueSet):
    pass

class ModerateIllnessValueSet(ValueSet):
    pass

class GBSHistoryValueSet(ValueSet):
    pass

class ImmunizationProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(self.patient.age_at(arrow.now()) >= 0.5)

    def in_denominator(self) -> bool:
        flu_vaccine = self.patient.immunizations.find(InfluenzaVaccine).after(arrow.now().shift(months=-6))
        covid_vaccine = self.patient.immunizations.find(COVIDVaccineValueSet).after(arrow.now().shift(months=-6))
        acute_illness = self.patient.conditions.find(AcuteIllnessValueSet)
        return len(flu_vaccine) == 0 and len(covid_vaccine) == 0 and len(acute_illness) == 0

    def in_numerator(self) -> bool:
        severe_allergy = self.patient.allergy_intolerances.find(SevereAllergyValueSet)
        moderate_illness = self.patient.conditions.find(ModerateIllnessValueSet)
        gbs_history = self.patient.conditions.find(GBSHistoryValueSet)
        recent_vaccine = self.patient.immunizations.after(arrow.now().shift(days=-14))
        return (len(severe_allergy) == 0 and len(moderate_illness) == 0 and len(gbs_history) == 0 and
                self.patient.age_at(arrow.now()) >= 0.5 and len(recent_vaccine) == 0)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE

        if not self.in_numerator():
            allergy_recommendation = AllergyRecommendation(
                key='severe_allergy',
                title='Check for Severe Allergy',
                narrative='Recommend checking for any severe allergic reactions to flu or COVID-19 vaccines.',
                allergy=SevereAllergyValueSet
            )
            immunization_recommendation = ImmunizationRecommendation(
                key='flu_covid_vaccine',
                title='Administer Flu and COVID-19 Vaccines',
                narrative='Recommend administering the current season’s flu vaccine and the latest COVID-19 vaccine.',
                immunization=InfluenzaVaccine | COVIDVaccineValueSet
            )
            result.add_recommendation(allergy_recommendation)
            result.add_recommendation(immunization_recommendation)

        return result