from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.questionnaire import Interview, InterviewQuestionResponse
from canvas_sdk.v1.data.observation import Observation

from logger import log


class GLP1WeightCalculationBanner(BaseProtocol):
    """Display the patient’s highest weight before starting a GLP-1 (captured in a questionnaire) 
    and calculate the patient’s BMI at that time.   

    This is essential for continued treatment.    
    dynamically display the amount of weight loss"""

    RESPONDS_TO = [
        EventType.Name(EventType.INTERVIEW_CREATED),
        EventType.Name(EventType.INTERVIEW_UPDATED),
        EventType.Name(EventType.OBSERVATION_CREATED) # for vitals
    ]

    def get_starting_weight(self, patient):
        # need to find the starting weight in the the vineyard intake questionnaire
        answer = InterviewQuestionResponse.objects.filter(
            interview__patient=patient,
            interview__deleted=False, 
            interview__entered_in_error_id__isnull=True,
            interview__committer_id__isnull=False,
            question__code=self.secrets['STARTING_WEIGHT_QUESTION_CODE'] or "VI-015" # this is the default question in Canvas template
        ).exclude(response_option_value='').order_by('created').first()

        # if no questionnaire filled out, return early
        if not answer:
            return None

        log.info(f'Highest weight when started GLP-1: {answer.response_option_value} lbs')
        try:
            return float(answer.response_option_value)
        except:
            raise Exception("Questionnaire value could not be converted to a number to calculate weight")

    def get_current_weight(self, patient):
        # need to find current weight in the vital command
        current_weight = Observation.objects.filter(
            patient=patient,
            deleted=False, 
            entered_in_error_id__isnull=True,
            committer_id__isnull=False,
            category='vital-signs',
            name='weight'
        ).exclude(value='').order_by('created').last()

        if not current_weight:
            return None

        log.info(f'Current Weight {current_weight.value} {current_weight.units}')
        if current_weight.units == 'oz':
            return float(current_weight.value) / 16
        return current_weight.value

    def get_starting_height(self, patient):
        # need to find current height in the vital command
        starting_height = Observation.objects.filter(
            patient=patient,
            deleted=False, 
            entered_in_error_id__isnull=True,
            committer_id__isnull=False,
            category='vital-signs',
            name='height'
        ).exclude(value='').order_by('created').first()

        if not starting_height:
            return None

        log.info(f'Current Height {starting_height.value} {starting_height.units}')
        return starting_height.value

    def compute(self) -> list[Effect]:
        log.info(f'self.event {self.event}')

        if self.event.type == EventType.OBSERVATION_CREATED:
            observation = Observation.objects.get(id=self.target)
            patient = observation.patient
        elif self.event.type in (EventType.INTERVIEW_UPDATED, EventType.INTERVIEW_CREATED):
            interview = Interview.objects.get(id=self.target)
            patient = interview.patient
        else:
            return []

        # need to find the starting weight in the the vineyard intake questionnaire
        starting_weight = self.get_starting_weight(patient)

        # if no questionnaire filled out, return early
        if not starting_weight:
            return []

        current_weight = self.get_current_weight(patient)
        # if no vital command with weight filled out, return early
        if not current_weight:
            return []

        starting_height = self.get_starting_height(patient)
        # if no vital command with height filled out, return early
        if not starting_height:
            return []

        starting_weight = float(starting_weight)
        bmi = round((703 * starting_weight) / (float(starting_height) ** 2), 1)
        weight_loss = round(((float(current_weight) - starting_weight)/starting_weight) * 100, 1)

        banner = AddBannerAlert(
            patient_id=patient.id,
            key="weight-banner",
            narrative=f"Start lbs: {round(starting_weight, 1)} | Start BMI: {bmi} | Lost: {weight_loss}%",
            placement=[AddBannerAlert.Placement.TIMELINE],
            intent=AddBannerAlert.Intent.INFO
        )

        return [banner.apply()]
