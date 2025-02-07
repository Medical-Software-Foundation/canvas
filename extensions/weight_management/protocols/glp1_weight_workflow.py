import arrow
from dateutil.relativedelta import relativedelta

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.questionnaire import Interview, InterviewQuestionResponse
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.command import Command
from canvas_sdk.commands.commands.history_present_illness import HistoryOfPresentIllnessCommand
from canvas_sdk.commands.commands.diagnose import DiagnoseCommand


from logger import log


class GLP1WeightWorkflow(BaseProtocol):
    """Display the patient’s highest weight before starting a GLP-1 (captured in a questionnaire) 
    and calculate the patient’s BMI at that time.   

    This is essential for continued treatment.    
    dynamically display the amount of weight loss"""

    RESPONDS_TO = [
        EventType.Name(EventType.PLUGIN_CREATED), # for plugin install
        EventType.Name(EventType.PLUGIN_UPDATED),

        EventType.Name(EventType.INTERVIEW_CREATED), # for questionnaire
        EventType.Name(EventType.INTERVIEW_UPDATED),
        EventType.Name(EventType.OBSERVATION_CREATED) # for vitals
    ]

    def get_obsesity_class(self, starting_bmi):
        # based on the starting BMI suggest a obesity condition
        if starting_bmi < 30:
            diagnose_code = 'E66.3'
            obesity_dx = 'Overweight'
        elif starting_bmi >= 30 and starting_bmi < 35:
            diagnose_code = 'E66.811'
            obesity_dx = 'Obesity, Class 1'
        elif starting_bmi >= 35 and starting_bmi < 40:
            diagnose_code = 'E66.812'
            obesity_dx = 'Obesity, Class 2'
        else: # starting_bmi >= 40:
            diagnose_code = 'E66.813'
            obesity_dx = 'Obesity, Class 3'

        return obesity_dx, diagnose_code

    def get_structured_assessment_information(self, patient):
        # Grab the SA with the comorbities question and get the note it is associated with
        structured_assessment = Interview.objects.filter(
            patient=patient,
            deleted=False, 
            entered_in_error_id__isnull=True,
            committer_id__isnull=False,
            questionnaires__code=self.secrets['SA_CODE'] or "GLP1-MedHx-001" # this is the default question in Canvas template
        ).order_by('created').first()

        log.info(f"GLP-1 Medical History SA found: {structured_assessment}")
        if structured_assessment:
            comorbidities = self.get_comorbidities(structured_assessment.dbid)
            note_uuid = Note.objects.get(dbid=structured_assessment.note_id).id
            return structured_assessment.note_id, note_uuid, comorbidities

        return None, None, None

    def get_comorbidities(self, interview_id):
        # Find the comorbidities in a structured assessment question
        answers = InterviewQuestionResponse.objects.filter(
            interview_id=interview_id,
            question__code=self.secrets['COMORBIDITIES_QUESTION_CODE'] or "GLP1-MedHx-002" # this is the default question in Canvas template
        ).exclude(response_option_value='').values_list('response_option_value', flat=True)

        # if no SA filled out, return early
        if not answers:
            return None

        answers = list(answers)
        log.info(f'Found the following comorbidities: {answers}')
        last_index = len(answers) - 1
        answers[last_index] = f'and {answers[last_index]}'
        return ", ".join(answers)

    def get_current_glp1_and_length_of_treatment(self, patient):
        # Find the current glp1 in the intake questionnaire
        answer = InterviewQuestionResponse.objects.filter(
            interview__patient=patient,
            interview__deleted=False, 
            interview__entered_in_error_id__isnull=True,
            interview__committer_id__isnull=False,
            question__code=self.secrets['CURRENT_GLP-1_QUESTION_CODE'] or "VI-005" # this is the default question in Canvas template
        ).exclude(response_option_value='').order_by('created').first()

        # if no questionnaire filled out, return early
        if not answer:
            return None

        log.info(f'Current GLP-1: {answer.response_option_value}')
        if 'none' in answer.response_option_value.lower():
            return ""

        return (f"{answer.response_option_value} and has been on "
                    f"GLP-1 therapy for the last {self.get_len_of_treatment(patient)} months.\n\n")

    def get_len_of_treatment(self, patient):
        # Find the starting weight in the the intake questionnaire
        answer = InterviewQuestionResponse.objects.filter(
            interview__patient=patient,
            interview__deleted=False, 
            interview__entered_in_error_id__isnull=True,
            interview__committer_id__isnull=False,
            question__code=self.secrets['LENGTH_OF_TREATMENT_QUESTION_CODE'] or "VI-017" # this is the default question in Canvas template
        ).exclude(response_option_value='').order_by('created').first()

        # if no questionnaire filled out, return early
        if not answer:
            return None

        log.info(f'Length of GLP-1 Treatment (months): {answer.response_option_value}')
        return answer.response_option_value
    
    def get_starting_weight(self, patient):
        # Find the starting weight in the intake questionnaire
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
            log.info("Questionnaire value could not be converted to a number to calculate weight")
            return None
            
    def get_current_bmi(self, patient, current_weight):
        # Find current weight in the vital command and calculate BMI
        current_height = Observation.objects.filter(
            patient=patient,
            deleted=False, 
            entered_in_error_id__isnull=True,
            committer_id__isnull=False,
            category='vital-signs',
            name='height'
        ).exclude(value='').order_by('created').last()

        if not current_height:
            return None

        current_height = current_height.value
        bmi = round((703 * current_weight) / (float(current_height) ** 2), 1)
        log.info(f'Current height / BMI: {current_height} / {bmi}')
        return bmi

    def get_current_weight(self, patient):
        # Find current weight in the vital command
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

        log.info(f'Current Weight: {current_weight.value} {current_weight.units}')
        if current_weight.units == 'oz':
            return float(current_weight.value) / 16
        return current_weight.value

    def get_starting_height(self, patient):
        # Find current height in the vital command
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

        log.info(f'Current Height: {starting_height.value} {starting_height.units}')
        return starting_height.value

    def compute_banner(self, patient):
        """Compute the Weight Loss banner by finding all the patient's vital values needed"""
        return_early = (None, None, None, None)

        # need to find the starting weight in the intake questionnaire
        starting_weight = self.get_starting_weight(patient)

        # if no questionnaire filled out, return early
        if not starting_weight:
            return return_early

        current_weight = self.get_current_weight(patient)
        # if no vital command with weight filled out, return early
        if not current_weight:
            return return_early

        starting_height = self.get_starting_height(patient)
        # if no vital command with height filled out, return early
        if not starting_height:
            return return_early

        starting_weight = float(starting_weight)
        bmi = round((703 * starting_weight) / (float(starting_height) ** 2), 1)
        weight_loss = round(((float(current_weight) - starting_weight)/starting_weight) * 100, 1)

        return bmi, weight_loss, current_weight, AddBannerAlert(
            patient_id=patient.id,
            key="weight-banner",
            narrative=f"Start lbs: {round(starting_weight, 1)} | Start BMI: {bmi} | Lost: {weight_loss}%",
            placement=[AddBannerAlert.Placement.TIMELINE],
            intent=AddBannerAlert.Intent.INFO
        )

    def calculate_age(self, dob):
        # function to find the age in years/months of the patient
        difference = relativedelta(arrow.now().date(), dob)
        months_old = difference.years * 12 + difference.months

        if months_old < 18:
            return f"{months_old} months"

        return f"{difference.years} years"

    def get_sex(self, patient):
        # Mapping for sex to be user friendly
        sex = patient.sex_at_birth

        _map = {
            "F": "female",
            "M": "male",
            "O": "other",
            "UNK": "unknown"
        }

        return _map.get(sex) or ""

    def compute(self) -> list[Effect]:
        log.info(f'self.event: {self.event.__dict__}')

        # if the plugin is uploaded, we need to compute for all patients
        # careful if running this on an instance with a lot of patients
        if self.event.type in (EventType.PLUGIN_UPDATED, EventType.PLUGIN_CREATED):
            patients = Patient.objects.all()
        else:
            # grab the patient from the target instance that triggered the protocol
            try:
                instance = self.event.target.instance
                patients = [instance.patient]
                log.info(f"instance found: {instance}")
            except:
                return []

        effects = []
        for patient in patients:
            starting_bmi, weight_loss, current_weight, banner = self.compute_banner(patient)
            if not banner:
                log.info(f"No information for banner found, skipping patient {patient.id}")
                continue
            effects.append(banner.apply())

            # grab the SA for GLP-1 Medical History information
            note_dbid, note_uuid, comorbidities = self.get_structured_assessment_information(patient)

            if not note_uuid:
                continue

            # originate a diagnose command depending on starting BMI
            obesity_dx, diagnose_code = self.get_obsesity_class(starting_bmi)
            if diagnose_code:
                diagnoses = Command.objects.filter(note_id=note_dbid, schema_key='diagnose')
                if not any([d.data.get('diagnose', {}).get('value') == diagnose_code.replace('.', '') for d in diagnoses]):
                    log.info(f"No diagnose found so adding: {diagnose_code}")
                    diagnose = DiagnoseCommand(
                        note_uuid=str(note_uuid),
                        icd10_code=diagnose_code,
                    )
                    effects.append(diagnose.originate())
                else:
                    log.info(f"Diagnose already found so skipping: {diagnose_code}")


            # originate or edit HPI command
            fields = {
                'note_uuid': str(note_uuid),
                'narrative': (
                    f"{patient.first_name} is a {self.calculate_age(patient.birth_date)} old "
                    f"{self.get_sex(patient)} with a history of {obesity_dx} establishing for "
                    "weight management and related condition care.\n\n" 
                    f"{self.get_current_glp1_and_length_of_treatment(patient)}"
                    f"Original BMI of {starting_bmi} with a current BMI of "
                    f"{self.get_current_bmi(patient, current_weight)} and has lost {weight_loss}% of their starting body weight.\n\n"
                    f"{patient.first_name} also has reported the following comorbidities: {comorbidities}"
                )
            }
            hpi_found = Command.objects.filter(note_id=note_dbid, schema_key='hpi', state='staged').order_by('created').first()
            if hpi_found:
                fields['command_uuid'] = str(hpi_found.id)
                hpi = HistoryOfPresentIllnessCommand(**fields)
                effects.append(hpi.edit())
                log.info(f"HPI updated on note: {note_dbid} with {fields}")
            else:
                hpi = HistoryOfPresentIllnessCommand(**fields)
                effects.append(hpi.originate(line_number=1))
                log.info(f"HPI created on note: {note_dbid} with {fields}")

        return effects
