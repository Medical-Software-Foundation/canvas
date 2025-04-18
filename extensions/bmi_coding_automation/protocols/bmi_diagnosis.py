import json
import arrow
import uuid

from dateutil.relativedelta import relativedelta
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.commands import DiagnoseCommand
from canvas_sdk.commands import UpdateDiagnosisCommand
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.condition import ConditionCoding, ClinicalStatus
from logger import log


class BMIDiagnosisProtocol(BaseProtocol):
    """Automate diagnosis of BMI related Z codes after vital command filled out"""

    RESPONDS_TO = [
        EventType.Name(EventType.VITALS_COMMAND__POST_COMMIT)
    ]

    def patient_is_20_or_older(self):
        # function to find the age patient and return true if age is at least 20 years old
        difference = relativedelta(arrow.now().date(), self.patient.birth_date)
        months_old = difference.years * 12 + difference.months

        if months_old < 18:
            return False

        years_old = difference.years
        return years_old >= 20

    def get_current_weight(self):
        # Find current weight in the vital command
        current_weight = Observation.objects.filter(
            **self.filters,
            category='vital-signs',
            name='weight'
        ).exclude(value='').order_by('created').last()

        if not current_weight:
            return None

        log.info(f'Current Weight for patient {self.patient.id}: {current_weight.value} {current_weight.units}')
        
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

        log.info(f'Current Height for patient {self.patient.id}: {current_height.value} {current_height.units}')
        return current_height.value

    def get_patient_z_codes(self):
        # Find the BMI Z codes currently active for this patient
        return ConditionCoding.objects.filter(
            condition__patient=self.patient,
            condition__committer_id__isnull=False,
            condition__entered_in_error_id__isnull=True,
            condition__deleted=False,
            condition__clinical_status=ClinicalStatus.ACTIVE.value,
            code__istartswith='z68',
            system='ICD-10'
        ).order_by('dbid').values_list('code', flat=True)

    def get_new_z_code(self, bmi):
        if bmi <= 19:
            return "Z681"
        elif bmi < 21:
            return "Z6820"
        elif bmi < 22:
            return "Z6821"
        elif bmi < 23:
            return "Z6822"
        elif bmi < 24:
            return "Z6823"
        elif bmi < 25:
            return "Z6824"
        elif bmi < 26:
            return "Z6825"
        elif bmi < 27:
            return "Z6826"
        elif bmi < 28:
            return "Z6827"
        elif bmi < 29:
            return "Z6828"
        elif bmi < 30:
            return "Z6829"
        elif bmi < 31:
            return "Z6830"
        elif bmi < 32:
            return "Z6831"
        elif bmi < 33:
            return "Z6832"
        elif bmi < 34:
            return "Z6833"
        elif bmi < 35:
            return "Z6834"
        elif bmi < 36:
            return "Z6835"
        elif bmi < 37:
            return "Z6836"
        elif bmi < 38:
            return "Z6837"
        elif bmi < 39:
            return "Z6838"
        elif bmi < 40:
            return "Z6839"
        elif bmi < 45:
            return "Z6841"
        elif bmi < 50:
            return "Z6842"
        elif bmi < 60:
            return "Z6843"
        elif bmi < 70:
            return "Z6844"
        else:
            return "Z6845"
        # Return the corresponding Z code for the specific BMI

    def compute(self) -> list[Effect]:
        command = Command.objects.get(id=self.target)
        note = command.note
        self.patient = command.patient

        if not self.patient_is_20_or_older():
            log.info(f"Skipping BMI calculation due to patient {self.patient.id} younger than 20")
            return []


        self.filters =  {
            "patient": self.patient,
            "deleted": False, 
            "entered_in_error_id__isnull": True,
            "committer_id__isnull": False
        }

        # fetch height and weight to calculate BMI
        weight_in_lbs = self.get_current_weight()
        height_in_inches = self.get_current_height()

        if not all([weight_in_lbs,height_in_inches]):
            log.info(f"BMI unable to be calculated for patient {self.patient.id}")
            return []

        bmi = 703 * weight_in_lbs / (int(float(height_in_inches) ** 2))
        log.info(f"BMI calculated for patient {self.patient.id}: {bmi}")

        current_z_codes = self.get_patient_z_codes()
        log.info(f"Found z codes for patient {self.patient.id}: {current_z_codes}")
        new_z_code = self.get_new_z_code(bmi)
        log.info(f"New z code calculated for patient {self.patient.id}: {new_z_code}")

        if new_z_code in current_z_codes:
            log.info(f"Patient {self.patient.id} already is diagnosed for the right z code")
            return []

        if current_z_codes:
            # need a Change/Update Diagnosis command
            update_diagnosis = UpdateDiagnosisCommand(
                command_uuid=str(uuid.uuid4()),
                note_uuid=str(note.id),
                condition_code=current_z_codes.last(),
                new_condition_code=new_z_code,
            )
            log.info(f"Originating a UpdateDiagnosis for patient {self.patient.id}: {update_diagnosis}")
            return [update_diagnosis.originate(), update_diagnosis.commit()]
        else:
            # create a diagnosis command
            diagnose = DiagnoseCommand(
                command_uuid=str(uuid.uuid4()),
                note_uuid=str(note.id),
                icd10_code=new_z_code,
            )
            log.info(f"Originating a Diagnose for patient {self.patient.id}: {diagnose}")
            return [diagnose.originate(), diagnose.commit()]

        return []