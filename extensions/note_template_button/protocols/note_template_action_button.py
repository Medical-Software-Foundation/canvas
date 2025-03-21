import arrow 

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import Questionnaire
from canvas_sdk.commands import (
    HistoryOfPresentIllnessCommand,
    DiagnoseCommand,
    PhysicalExamCommand,
    PlanCommand,
    ReasonForVisitCommand,
    ReviewOfSystemsCommand,
)

from canvas_sdk.value_set.v2022.condition import (
    DiagnosisOfHypertension,
    EssentialHypertension
)

from datetime import datetime
from dateutil.relativedelta import relativedelta
from logger import log


class NoteTemplateActionButton(ActionButton):
    """
        Protocol will add a button to the Note Header that when clicked
        will insert specific blank commands.
    """


    BUTTON_TITLE = "Insert Standard Template"
    BUTTON_KEY = "INSERT_STANDARD_TEMPLATE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    VISIBLE_NOTE_TYPE_NAMES = (
        'Office visit',
    )

    def note_body_is_empty(self, note):
        """
            Loop through the Note Body to see if the note is completely empty of commands
        """
        return all([b == {'type': 'text', 'value': ''} for b in note.body])

    def visible(self) -> bool:
        """
            Only show button if we are in a specific note type 
            and no commands are already in the note

            there is code but it is commented out for only showing
            if the patient has a specific active diagnosis
        """
        note_id = self.event.context['note_id']
        note = Note.objects.get(dbid=note_id)

        log.info(f"{note.note_type_version.name} Note Loaded")
        if (
            note.note_type_version.name in self.VISIBLE_NOTE_TYPE_NAMES
            and self.note_body_is_empty(note)
        ):
            # Look at patient diagnoses only show button if patient diagnosed with 
            # EssentialHypertension or DiagnosisOfHypertension
            # patient = note.patient
            # condition_filter = {
            #     "committer_id__isnull": False,
            #     "entered_in_error_id__isnull": True,
            #     "clinical_status": 'active'
            # }
            # diagnose_of_hypertension = patient.conditions.find(DiagnosisOfHypertension).filter(**condition_filter)
            # essential_hypertension = patient.conditions.find(EssentialHypertension).filter(**condition_filter)
            # if not (diagnose_of_hypertension or essential_hypertension):
            #     return False

            return True

        return False

    def calculate_age(self, patient):
        """ function to find the age in years/months of the patient """
        dob = patient.birth_date
        difference = relativedelta(arrow.now().date(), dob)
        months_old = difference.years * 12 + difference.months

        if months_old < 18:
            return f"{months_old} month"

        return f"{difference.years} year"

    def get_sex(self, patient):
        """ Function to map the sex coding value to user friendly string """
        sex = patient.sex_at_birth

        _map = {
            "F": "female",
            "M": "male",
            "O": "other",
            "UNK": "unknown"
        }

        return _map[sex]


    def handle(self) -> list[Effect]:
        """
            Function is kicked of when the button in the note is clicked. 

            It will insert empty commands of:
                Reason For Visit
                History of Present Illness
                Review of Systems
                Physical Exam
                Diagnose
                Plan
        """

        note_id = self.event.context['note_id']
        log.info(f"Note Template Action Button has been clicked in note {note_id}")

        note = Note.objects.get(dbid=note_id)
        note_uuid = str(note.id)
        patient = note.patient

        rfv = ReasonForVisitCommand(note_uuid=note_uuid)

        hpi = HistoryOfPresentIllnessCommand(
            note_uuid=note_uuid,
            narrative=f'{patient.first_name} {patient.last_name} is a {self.calculate_age(patient)} old {self.get_sex(patient)} who presents today for'
        )

        # brief_ros = Questionnaire.objects.get(
        #     name="Brief ROS",
        #     can_originate_in_charting=True
        # )
        ros = ReviewOfSystemsCommand(
            note_uuid=note_uuid,
            # questionnaire_id=str(brief_ros.id)
        )

        # brief_exam = Questionnaire.objects.get(
        #     name="Brief Exam",
        #     can_originate_in_charting=True
        # )
        exam = PhysicalExamCommand(
            note_uuid=note_uuid,
            # questionnaire_id=str(brief_exam.id)
        )

        diagnose = DiagnoseCommand(note_uuid=note_uuid)

        plan = PlanCommand(note_uuid=note_uuid)


        return [
            rfv.originate(),
            hpi.originate(),
            ros.originate(),
            exam.originate(),
            diagnose.originate(),
            plan.originate()
        ]
