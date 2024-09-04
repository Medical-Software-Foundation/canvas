# type: ignore
import arrow

from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import InstructionRecommendation
from canvas_workflow_kit.value_set.specials import Hcc005v1AnnualWellnessVisit


class Hcc005v1(ClinicalQualityMeasure):

    class Meta:
        title = 'Annual Wellness Visit'
        version = '2019-11-04v1'
        description = 'Patient 65 or older due  for Annual Wellness Visit.'
        information = 'https://canvas-medical.zendesk.com/hc/en-us/articles/360059083973-Annual-Wellness-Visit-HCC005v1'  # noqa: E501

        identifiers = ['HCC005v1']

        types = ['HCC']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        authors = [
            'Canvas Medical Team',
        ]

        references = [
            'Canvas Medical HCC, https://canvas-medical.zendesk.com/hc/en-us/articles/360059083973-Annual-Wellness-Visit-HCC005v1'  # noqa: E501
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_BILLING_LINE_ITEM,
            ClinicalQualityMeasure.CHANGE_PATIENT,
        ]

    MINIMUM_AGE = 65

    _last_visit = None

    def in_initial_population(self) -> bool:
        """
        Initial population: Patients 65+ years of age
        """
        return bool(self.patient.age_at(self.timeframe.end) > self.MINIMUM_AGE)

    def in_denominator(self) -> bool:
        """
        Patients in the initial population
        """
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        """
        Patients without visit including cpt G0438 or G0439 in >1 year
        """
        self._last_visit = (
            self.patient.billing_line_items.find(Hcc005v1AnnualWellnessVisit).within(
                self.timeframe).last())
        return not bool(self._last_visit)

    def recent_visit_context(self) -> str:
        record = self.patient.billing_line_items.find(Hcc005v1AnnualWellnessVisit).last()
        if record:
            last_date = arrow.get(record['created'])
            return f'Last Annual Wellness Visit was {self.display_date(last_date)}.'
        else:
            return 'There are no Annual Wellness Visits on record.'

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(
                    f'{self.patient.first_name} is due for a Annual Wellness Visit.')
                result.add_narrative(self.recent_visit_context())
                result.add_recommendation(
                    InstructionRecommendation(
                        key='HCC005v1_RECOMMEND_WELLNESS_VISIT',
                        rank=1,
                        button='Plan',
                        patient=self.patient,
                        instruction=Hcc005v1AnnualWellnessVisit,
                        title='Schedule for Annual Wellness Visit'))
            else:
                visit_date = arrow.get(self._last_visit['created'])
                result.due_in = (visit_date.shift(days=self.timeframe.duration) - self.now).days
                result.status = STATUS_SATISFIED
                result.add_narrative('{patient} had a visit {date}.'.format(
                    patient=self.patient.first_name, date=self.display_date(visit_date)))
        else:
            result.due_in = (
                self.patient.birthday.shift(years=self.MINIMUM_AGE) - self.timeframe.end).days

        return result
