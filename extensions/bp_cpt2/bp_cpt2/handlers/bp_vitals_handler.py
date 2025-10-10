import re
from typing import Optional
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Command, Observation, Assessment, BillingLineItem, Note
from canvas_sdk.effects.billing_line_item import AddBillingLineItem
from logger import log

from bp_cpt2.utils import get_blood_pressure_readings


class BloodPressureVitalsHandler(BaseHandler):
    """
    Handles blood pressure measurements from vitals commands and returns appropriate
    CPT/HCPCS billing codes based on systolic and diastolic BP values.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.VITALS_COMMAND__POST_COMMIT)
    ]

    def check_for_documented_reason(self, note: Note) -> bool:
        """Check if there's a documented reason for BP not being taken by looking at vitals command data."""
        # Pattern to match documented reasons for no BP
        # Matches variations like "bp not documented reason", "blood pressure not taken because", etc.
        reason_pattern = re.compile(
            r'(bp|blood\s*pressure).{0,20}(not\s+(taken|documented|measured)|unable\s+to\s+(take|obtain)).{0,50}(reason|because|due\s+to|refused)',
            re.IGNORECASE
        )

        # Look for vitals commands on this note
        vitals_commands = Command.objects.filter(
            note=note,
            schema_key="vitals"
        )

        for cmd in vitals_commands:
            if cmd.data and isinstance(cmd.data, dict):
                # Check if there's a 'note' field in the command data
                note_field = cmd.data.get('note')
                if note_field and isinstance(note_field, str):
                    if reason_pattern.search(note_field):
                        log.info(f"Found documented reason for no BP in vitals command note field: {note_field}")
                        return True

        return False


    def determine_bp_codes(self, systolic: Optional[float], diastolic: Optional[float], note: Note) -> list[str]:
        """
        Determine appropriate CPT/HCPCS codes based on BP readings.
        Returns a list of CPT codes to add.
        """
        codes = []

        if systolic is None or diastolic is None:
            log.info(f"Patient {self.patient.id} - Blood pressure not fully documented")
            # Check if there's a documented reason for no BP
            if self.check_for_documented_reason(note):
                codes.append("G8951")  # BP not documented, documented reason
                log.info(f"Patient {self.patient.id} - Using G8951 (documented reason for no BP)")
            else:
                codes.append("G8950")  # BP not documented, reason not given
            return codes

        # Measurement codes - Systolic
        if systolic < 130:
            codes.append("3074F")
        elif systolic < 140:
            codes.append("3075F")
        else:  # systolic >= 140
            codes.append("3077F")

        # Measurement codes - Diastolic
        if diastolic < 80:
            codes.append("3078F")
        elif diastolic < 90:
            codes.append("3079F")
        else:  # diastolic >= 90
            codes.append("3080F")

        # Blood Pressure Control codes
        if systolic < 140 and diastolic < 90:
            codes.append("G8783")  # BP documented and controlled
            codes.append("G8752")  # Most recent BP < 140/90
        else:
            codes.append("G8784")  # BP documented but not controlled

        log.info(f"Patient {self.patient.id} - Determined BP codes: {codes}")
        return codes

    def compute(self) -> list[Effect]:
        """Main compute method called when vitals command is committed."""
        command = Command.objects.get(id=self.event.target.id)
        note = command.note
        self.patient = command.patient

        log.info(f"Processing BP vitals for patient {self.patient.id}, note {note.id}")

        # Get BP readings
        systolic, diastolic = get_blood_pressure_readings(patient=self.patient)

        # Determine appropriate codes
        bp_codes = self.determine_bp_codes(systolic, diastolic, note)

        if not bp_codes:
            # This should never happen - determine_bp_codes always returns at least one code
            raise ValueError(f"No BP codes determined for patient {self.patient.id}")

        # Get assessments for the note
        assessments = [
            str(assessment_id)
            for assessment_id in Assessment.objects.filter(note_id=note.dbid).values_list("id", flat=True)
        ]

        # Get existing billing line items for this note
        existing_codes = set(
            BillingLineItem.objects.filter(
                note_id=note.dbid
            ).values_list("cpt", flat=True)
        )

        # Create billing line items for each code that doesn't already exist
        effects = []
        for code in bp_codes:
            if code in existing_codes:
                log.info(f"Billing code {code} already exists for note {note.id}, skipping")
                continue

            billing_item = AddBillingLineItem(
                note_id=str(note.id),
                cpt=code,
                units=1,
                assessment_ids=assessments,
                modifiers=[]
            )
            effects.append(billing_item.apply())
            log.info(f"Added billing code {code} for patient {self.patient.id}")

        return effects
