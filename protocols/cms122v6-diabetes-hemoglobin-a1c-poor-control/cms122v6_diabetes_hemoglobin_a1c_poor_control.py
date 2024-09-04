# type: ignore
from typing import Any, Dict, List, Optional

import arrow

from cached_property import cached_property

from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ExternallyAwareClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import InstructionRecommendation, LabRecommendation
# flake8: noqa
from canvas_workflow_kit.value_set.v2018 import (
    Diabetes,
    DietaryRecommendations,
    Hba1CLaboratoryTest
)
from canvas_workflow_kit.builtin_cqms.diabetes_quality_measure import DiabetesQualityMeasure


class ClinicalQualityMeasure122v6(ExternallyAwareClinicalQualityMeasure, DiabetesQualityMeasure):
    """
    Diabetes: Hemoglobin A1c (HbA1c) Poor Control (> 9%)

    Description: Percentage of patients 18-75 years of age with diabetes who had hemoglobin A1c >
    9.0% during the measurement period

    Definition: None

    Rationale: As the seventh leading cause of death in the U.S., diabetes kills approximately
    75,000 people a year (CDC FastStats 2015). Diabetes is a group of diseases marked by high blood
    glucose levels, resulting from the body's inability to produce or use insulin (CDC Statistics
    2014, ADA Basics 2013). People with diabetes are at increased risk of serious health
    complications including vision loss, heart disease, stroke, kidney failure, amputation of toes,
    feet or legs, and premature death. (CDC Fact Sheet 2014).

    In 2012, diabetes cost the U.S. an estimated $245 billion: $176 billion in direct medical costs
    and $69 billion in reduced productivity. This is a 41 percent increase from the estimated $174
    billion spent on diabetes in 2007 (ADA Economic 2013).

    Reducing A1c blood level results by 1 percentage point (eg, from 8.0 percent to 7.0 percent)
    helps reduce the risk of microvascular complications (eye, kidney and nerve diseases) by as
    much as 40 percent (CDC Estimates 2011).

    Guidance: Patient is numerator compliant if most recent HbA1c level >9%, the most recent HbA1c
    result is missing, or if there are no HbA1c tests performed and results documented during the
    measurement period. If the HbA1c test result is in the medical record, the test can be used to
    determine numerator compliance.

    Only patients with a diagnosis of Type 1 or Type 2 diabetes should be included in the
    denominator of this measure; patients with a diagnosis of secondary diabetes due to another
    condition should not be included.

    More information: https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS122v6.html
    """

    class Meta:
        title = 'Diabetes: Hemoglobin HbA1c Poor Control (> 9%)'

        version = '2019-02-12v1'

        description = (
            'Patients 18-75 years of age with diabetes who have either a hemoglobin A1c > 9.0% '
            'or no hemoglobin A1c within the last year.')
        information = 'https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS122v6.html'

        identifiers = ['CMS122v6']

        types = ['CQM']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]

        authors = [
            'National Committee for Quality Assurance',
        ]
        references = [
            'American Diabetes Association. Glycemic targets. Sec. 6. In Standards of Medical Care in Diabetes-2017. Diabetes Care 2017;40(Suppl. 1):S48-S56',
            'American Diabetes Association. 2013. Diabetes Basics. www.diabetes.org/diabetes-basics/?loc=GlobalNavDB',
            'American Diabetes Association (ADA). April 2013. Economic Costs of Diabetes in the U.S. in 2012. Diabetes Care. Vol. 36 no. 41033-46. http://care.diabetesjournals.org/content/36/4/1033.full',
            'Centers for Disease Control and Prevention (CDC). 2014. National Diabetes Statistics Report. http://www.cdc.gov/diabetes/pdfs/data/2014-report-estimates-of-diabetes-and-its-burden-in-the-united-states.pdf',
            'Centers for Disease Control and Prevention (CDC). 2015. FastStats: Deaths and Mortality. www.cdc.gov/nchs/fastats/deaths.htm.',
            'Centers for Disease Control and Prevention. 2011. National diabetes fact sheet: national estimates and general information on diabetes and prediabetes in the United States, 2011. Atlanta, GA: U.S. Department of Health and Human Services, Centers for Disease Control and Prevention. www.cdc.gov/diabetes/pubs/pdf/ndfs_2011.pdf',
            'Centers for Disease Control and Prevention. 2014. CDC Features. Diabetes Latest. www.cdc.gov/features/diabetesfactsheet/.', ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_CONDITION,
            ClinicalQualityMeasure.CHANGE_LAB_REPORT,
            ClinicalQualityMeasure.CHANGE_PATIENT,
        ]

    @classmethod
    def enabled(cls) -> bool:
        return True

    MINIMUM_HBA1C = 9.0

    @cached_property
    def last_hba1c_record(self) -> Dict[str, Any]:
        return (self.patient.lab_reports
                .find(Hba1CLaboratoryTest)
                .within(self.timeframe)
                .last())  # yapf: disable

    @property
    def last_hba1c_value(self) -> float:
        # TODO based on solution adopted through https://github.com/canvas-medical/canvas/issues/4799
        if self.last_hba1c_record:
            if isinstance(self.last_hba1c_record['value'], str):
                return self.relative_float(self.last_hba1c_record['value'])
            else:
                return float(self.last_hba1c_record['value'])

    @property
    def last_hba1c_arrow(self) -> Optional[arrow.Arrow]:
        if self.last_hba1c_record:
            return arrow.get(self.last_hba1c_record['originalDate'])

    @property
    def last_hba1c_date(self) -> str:
        if self.last_hba1c_record:
            return self.display_date(arrow.get(self.last_hba1c_record['originalDate']))

    def in_denominator(self) -> bool:
        """
        Denominator: Equals Initial Population

        Exclusions: Exclude patients who were in hospice care during the measurement year

        Exceptions: None
        """
        if not self.in_initial_population():
            return False

        if self.patient.hospice_within(self.timeframe):
            return False

        return True

    def in_numerator(self) -> bool:
        """
        Numerator:
         + patients without test performed in the measurement period
         + patients with a performed test in the period but without result
         + patients whose most recent HbA1c level (performed during the measurement period) is >9.0%

        Exclusions: Not Applicable
        """
        if not self.last_hba1c_record:
            return True

        return self.last_hba1c_value > self.MINIMUM_HBA1C

    def craft_unsatisfied_result(self):
        result = ProtocolResult()

        result.due_in = (self.last_hba1c_arrow.shift(days=self.timeframe.duration) - self.now).days
        result.status = STATUS_SATISFIED

        result.add_narrative(
            f"{self.patient.first_name}'s last HbA1c done {self.last_hba1c_date} was "
            f'{self.last_hba1c_value:.1f}%.')

        return result

    def craft_satisfied_result(self):
        """
        Clinical recommendation: American Diabetes Association (2017):

        - A reasonable A1C goal for many nonpregnant adults is <7%. (Level of evidence: A)

        - Providers might reasonably suggest more stringent A1C goals (such as <6.5%) for selected
        individual patients if this can be achieved without significant hypoglycemia or other
        adverse effects of treatment. Appropriate patients might include those with short duration
        of diabetes, type 2 diabetes treated with lifestyle or metformin only, long life
        expectancy, or no significant cardiovascular disease (CVD). (Level of evidence: C)

        - Less stringent A1C goals (such as <8%) may be appropriate for patients
        with a history of severe hypoglycemia, limited life expectancy, advanced microvascular or
        macrovascular complications, extensive comorbid
        conditions, or long-standing diabetes in whom the general goal is difficult to attain
        despite diabetes self-management education, appropriate glucose monitoring, and effective
        doses of multiple glucose-lowering agents including insulin. (Level of evidence: B)
        """
        result = ProtocolResult()

        context = {
            'conditions': [[{
                'code': 'Z131',
                'system': 'ICD-10',
                'display': 'Encounter for screening for diabetes mellitus',
            }]]
        }

        first_name = self.patient.first_name

        result.due_in = -1
        result.status = STATUS_DUE

        if self.last_hba1c_value is None:
            result.add_narrative("{0}'s last HbA1c test was over {1}.".format(
                first_name,
                self.now.shift(days=-1 * self.timeframe.duration, months=-1).humanize(
                    other=self.now, granularity='month', only_distance=True)).replace(' ago', ''))

            result.add_recommendation(
                LabRecommendation(
                    key='CMS122v6_RECOMMEND_HBA1C',
                    rank=1,
                    button='Order',
                    patient=self.patient,
                    context=context,
                    lab=Hba1CLaboratoryTest,
                    condition=Diabetes,
                    title='Order HbA1c'))
        else:
            result.add_narrative(f"{first_name}'s last HbA1c done {self.last_hba1c_date} was "
                                 f'{self.last_hba1c_value:.1f}%.')

            title = ('Discuss lifestyle modification and medication adherence. '
                     'Consider diabetes education and medication intensification as appropriate.')

            result.add_recommendation(
                InstructionRecommendation(
                    key='CMS122v6_RECOMMEND_DISCUSS_LIFESTYLE',
                    rank=1,
                    button='Instruct',
                    patient=self.patient,
                    instruction=DietaryRecommendations,
                    title=title))

        return result
