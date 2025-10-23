import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data import Command
from canvas_sdk.v1.data.questionnaire import Questionnaire
from canvas_sdk.commands import (
    HistoryOfPresentIllnessCommand,
    PhysicalExamCommand,
    ReviewOfSystemsCommand,
    InstructCommand,
    QuestionnaireCommand,
)
from canvas_sdk.commands.constants import CodeSystems, Coding

from datetime import datetime
from dateutil.relativedelta import relativedelta
from logger import log


class TelehealthNoteTemplate(BaseProtocol):
    """
    Protocol that automatically populates telehealth visit notes with a detailed HPI
    and standard commands when a reason for visit is originated.

    Triggers on: REASON_FOR_VISIT_COMMAND__POST_ORIGINATE

    Inserts:
    - History of Present Illness with patient name, age, DOB, sex, and reason for visit
    - Review of Systems (blank)
    - PHQ-9 Questionnaire
    - Physical Exam (blank)
    - Instruct (blank)
    """

    RESPONDS_TO = EventType.Name(EventType.REASON_FOR_VISIT_COMMAND__POST_ORIGINATE)

    # Note types that should trigger this template
    TELEHEALTH_NOTE_TYPES = (
        'Telehealth visit',
        'Telemedicine visit',
    )

    def calculate_age(self, patient):
        """Calculate the age in years/months of the patient"""
        dob = patient.birth_date
        difference = relativedelta(arrow.now().date(), dob)
        months_old = difference.years * 12 + difference.months

        if months_old < 18:
            return f"{months_old} month"

        return f"{difference.years} year"

    def get_sex(self, patient):
        """Map the sex coding value to user friendly string"""
        sex = patient.sex_at_birth

        _map = {
            "F": "female",
            "M": "male",
            "O": "other",
            "UNK": "unknown"
        }

        return _map.get(sex, "unknown")

    def format_date(self, date_obj):
        """Format date as MM/DD/YYYY"""
        if date_obj:
            return date_obj.strftime("%m/%d/%Y")
        return "Unknown"

    def get_rfv_display(self):
        """
        Extract the reason for visit display text and coding from the event context.
        Returns a formatted string with the RFV information.
        """
        try:
            # Get coding data from the context
            coding_data = self.context.get("fields", {}).get("coding", {})
            comment = self.context.get("fields", {}).get("comment", "")

            # Extract display text and code
            display_text = coding_data.get("text", "") or coding_data.get("display", "")
            code = coding_data.get("value", "") or coding_data.get("code", "")
            system = coding_data.get("system", "")

            # Build the RFV string
            if display_text:
                if code and system:
                    # Extract just the system name (e.g., "SNOMED" from full URL)
                    system_name = system.split('/')[-1] if '/' in system else system
                    return f"{display_text} ({system_name}: {code})"
                else:
                    return display_text
            elif comment:
                return comment
            else:
                return "[Reason for visit - please specify]"
        except Exception as e:
            log.error(f"Error extracting RFV display: {str(e)}")
            return "[Reason for visit - please specify]"

    def note_has_hpi(self, note):
        """
        Check if the note already has an HPI command to avoid duplicates
        """
        hpi_commands = note.commands.filter(schema_key="historyOfPresentIllness")
        return hpi_commands.exists()

    def is_telehealth_note(self, note):
        """
        Check if the note type is a telehealth visit
        """
        note_type_name = note.note_type_version.name
        return note_type_name in self.TELEHEALTH_NOTE_TYPES

    def compute(self) -> list[Effect]:
        """
        This method gets called when a REASON_FOR_VISIT_COMMAND__POST_ORIGINATE event fires.

        It will:
        1. Verify this is a telehealth visit note
        2. Check if HPI already exists (avoid duplicates)
        3. Get patient demographics and calculate age
        4. Extract reason for visit information
        5. Insert detailed HPI with patient info and RFV
        6. Insert blank ROS, PHQ-9, Physical Exam, and Instruct commands
        """

        # Get the note from the context
        note_uuid = self.context.get("note", {}).get("uuid")
        note_id = self.context.get("note", {}).get("id")

        if not note_uuid or not note_id:
            log.error("No note UUID or ID found in context")
            return []

        log.info(f"Reason for Visit originated in note {note_id}")

        # Get the full note object
        note = Note.objects.get(id=note_uuid)

        # Check if this is a telehealth visit note
        if not self.is_telehealth_note(note):
            log.info(f"Note type '{note.note_type_version.name}' is not a telehealth visit. Skipping template.")
            return []

        # Check if HPI already exists
        if self.note_has_hpi(note):
            log.info(f"HPI already exists in note {note_id}. Skipping template insertion.")
            return []

        log.info(f"Inserting telehealth note template for note {note_id}")

        # Get patient information
        patient = note.patient
        patient_name = f"{patient.first_name} {patient.last_name}"
        age = self.calculate_age(patient)
        sex = self.get_sex(patient)
        dob = self.format_date(patient.birth_date)

        # Get reason for visit display
        rfv_display = self.get_rfv_display()

        # Build the HPI narrative
        hpi_narrative = (
            f"{patient_name} is a {age} year old {sex} "
            f"(DOB: {dob}) who presents today for: {rfv_display}"
        )

        log.info(f"Creating HPI: {hpi_narrative}")

        # Create History of Present Illness with detailed narrative
        hpi = HistoryOfPresentIllnessCommand(
            note_uuid=note_uuid,
            narrative=hpi_narrative
        )

        # Create Review of Systems (blank)
        ros = ReviewOfSystemsCommand(note_uuid=note_uuid)

        # Create PHQ-9 Questionnaire
        effects = []
        try:
            phq9_questionnaire = Questionnaire.objects.get(
                code="44249-1",  # PHQ-9 LOINC code
                code_system="LOINC",
                can_originate_in_charting=True
            )
            phq9 = QuestionnaireCommand(
                note_uuid=note_uuid,
                questionnaire_id=str(phq9_questionnaire.id)
            )
            phq9_effect = phq9.originate()
            log.info("PHQ-9 questionnaire command created")
        except Exception as e:
            log.error(f"Error creating PHQ-9 questionnaire: {str(e)}")
            phq9_effect = None

        # Create Physical Exam (blank)
        exam = PhysicalExamCommand(note_uuid=note_uuid)

        # Create Instruct command (blank/unstructured)
        instruct = InstructCommand(
            note_uuid=note_uuid,
            coding=Coding(
                system=CodeSystems.UNSTRUCTURED,
                code=""
            )
        )

        # Build effects list
        effects = [
            hpi.originate(),
            ros.originate(),
        ]

        if phq9_effect:
            effects.append(phq9_effect)

        effects.extend([
            exam.originate(),
            instruct.originate()
        ])

        log.info(f"Inserted {len(effects)} commands into note {note_id}")

        return effects
