import json
import arrow
from dateutil.relativedelta import relativedelta

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.questionnaire import InterviewQuestionResponse
from canvas_sdk.v1.data.observation import Observation

from logger import log


class Protocol(BaseProtocol):
    """
        Listen to vitals and questionnaire commands being committed. 
        Try to calculate the TDEE once the patient sex, age, height,
        weight, and current activity level is known. 
        Add a banner alert with the calculated TDEE
    """

    RESPONDS_TO = [
        EventType.Name(EventType.VITALS_COMMAND__POST_COMMIT),
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_ENTER_IN_ERROR),
    ]

    banner_key = 'TDEE'

    def calculate_age(self, birth_date):
        # function to find the age in years/months of the patient
        difference = relativedelta(arrow.now().date(), birth_date)
        months_old = difference.years * 12 + difference.months

        if months_old < 18:
            return None

        years_old = difference.years
        if years_old < 18:
            return None

        return years_old

    def get_current_weight(self):
        # Find current weight in the vital command
        current_weight = Observation.objects.filter(
            **self.filters,
            category='vital-signs',
            name='weight'
        ).exclude(value='').order_by('created').last()

        if not current_weight:
            return None

        log.info(f'Current Weight: {current_weight.value} {current_weight.units}')
        
        # convert to lbs
        if current_weight.units == 'oz':
            return float(current_weight.value) / 16
        return current_weight.value

    def get_current_height(self):
        # Find current height in the vital command
        current_height = Observation.objects.filter(
            **self.filters,
            category='vital-signs',
            name='height'
        ).exclude(value='').order_by('created').last()

        if not current_height:
            return None

        log.info(f'Current Height: {current_height.value} {current_height.units}')
        return current_height.value

    def get_current_activity_level(self):
        # Get answer to questionnaire for current activity level
        answer = InterviewQuestionResponse.objects.filter(
            **{f"interview__{k}": v for k, v in self.filters.items()},
            question__code=self.secrets['CURRENT_ACTIVITY_LEVEL_QUESTION_CODE'] or "activity-002" # this is the default question in Canvas template
        ).exclude(response_option_value='').order_by('created').last()

        # if no questionnaire filled out, return early
        if not answer:
            return None

        log.info(f'Current Activity Level: {answer.response_option_value}')
        return answer.response_option_value

    def compute(self) -> list[Effect]:
        command = Command.objects.get(id=self.target)
        patient = command.patient
        age = self.calculate_age(patient.birth_date)

        if not age: 
            log.info(f"Patient {patient.id} is under 18, skipping energy protein needs calculation")
            return []

        log.info(f"Attempting to calculation patient {patient.id} ({patient.sex_at_birth} - {age} year old) energy protein needs")

        self.filters =  {
            "patient": patient,
            "deleted": False, 
            "entered_in_error_id__isnull": True,
            "committer_id__isnull": False
        }

        current_weight_in_lbs = self.get_current_weight()
        current_height_inches = self.get_current_height()
        current_activity_level = self.get_current_activity_level()

        missing_fields = []
        if not current_weight_in_lbs: 
            missing_fields.append('weight')
        if not current_height_inches:
            missing_fields.append('height')
        if not current_activity_level:
            missing_fields.append('current activity level')
            
        if missing_fields:
            log.info(f"Unable to calculate due to {', '.join(missing_fields)} missing")
            banner = RemoveBannerAlert(
                key=self.banner_key,
                patient_id=patient.id,
            )
        else:
            # calculate TDEE and recommend a plan narrative
            sex = patient.sex_at_birth
            weight_in_kg = float(current_weight_in_lbs) * 0.453592
            height_in_cm = float(current_height_inches) * 2.54

            log.info(f'Patient has weight of {current_weight_in_lbs} lbs / {weight_in_kg} kg and '
                f'height of {current_height_inches} in / {height_in_cm} cm')

            if sex == 'F':
                # female calculation
                BMR = (10*weight_in_kg) + (6.25*height_in_cm) - (5*age) - 161
            else:
                # male calculation (defaults all unknown sex to male)
                BMR = (10*weight_in_kg) + (6.25*height_in_cm) - (5*age) + 5

            log.info(f"BMR = {BMR}")

            TDEE = None
            if 'Sedentary' in current_activity_level:
                TDEE = BMR*1.2
            elif "Lightly active" in current_activity_level: 
                TDEE = BMR*1.375
            elif "Moderately active" in current_activity_level: 
                TDEE = BMR*1.55
            elif "Very active" in current_activity_level: 
                TDEE = BMR*1.725
            elif "Extremely active" in current_activity_level: 
                TDEE = BMR*1.9
            
            banner = AddBannerAlert(
                patient_id=patient.id,
                key=self.banner_key,
                narrative=f"{patient.first_name}'s estimated energy needs are {TDEE:.1f} kcal/day",
                placement=[AddBannerAlert.Placement.CHART],
                intent=AddBannerAlert.Intent.INFO,
            )
            log.info(banner.narrative)
            
        return [banner.apply()]


