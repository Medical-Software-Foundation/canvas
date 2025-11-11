import re
from typing import Optional
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Command, BillingLineItem, Note
from canvas_sdk.effects.billing_line_item import AddBillingLineItem, UpdateBillingLineItem
from logger import log

from bp_cpt2.bp_claim_coder import (
    get_blood_pressure_readings,
    SYSTOLIC_CODES,
    DIASTOLIC_CODES,
    CONTROL_STATUS_CODES,
    NOT_DOCUMENTED_CODES,
    CPT_3074F,
    CPT_3075F,
    CPT_3077F,
    CPT_3078F,
    CPT_3079F,
    CPT_3080F,
    HCPCS_G8783,
    HCPCS_G8784,
    HCPCS_G8752,
    HCPCS_G8950,
    HCPCS_G8951
)


class BloodPressureVitalsHandler(BaseHandler):
    """
    Handles blood pressure measurements from vitals commands and returns appropriate
    CPT/HCPCS billing codes based on systolic and diastolic BP values.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.VITALS_COMMAND__POST_COMMIT)
    ]

    def get_code_category(self, code: str) -> Optional[set[str]]:
        """
        Get the category (set of mutually exclusive codes) that a code belongs to.
        Returns None if the code doesn't belong to any mutually exclusive category.
        """
        if code in SYSTOLIC_CODES:
            return SYSTOLIC_CODES
        elif code in DIASTOLIC_CODES:
            return DIASTOLIC_CODES
        elif code in CONTROL_STATUS_CODES:
            return CONTROL_STATUS_CODES
        elif code in NOT_DOCUMENTED_CODES:
            return NOT_DOCUMENTED_CODES
        return None

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
                codes.append(HCPCS_G8951)  # BP not documented, documented reason
                log.info(f"Patient {self.patient.id} - Using {HCPCS_G8951} (documented reason for no BP)")
            else:
                codes.append(HCPCS_G8950)  # BP not documented, reason not given
            return codes

        # Measurement codes - Systolic
        if systolic < 130:
            codes.append(CPT_3074F)
        elif systolic < 140:
            codes.append(CPT_3075F)
        else:  # systolic >= 140
            codes.append(CPT_3077F)

        # Measurement codes - Diastolic
        if diastolic < 80:
            codes.append(CPT_3078F)
        elif diastolic < 90:
            codes.append(CPT_3079F)
        else:  # diastolic >= 90
            codes.append(CPT_3080F)

        # Blood Pressure Control codes
        if systolic < 140 and diastolic < 90:
            codes.append(HCPCS_G8783)  # BP documented and controlled
            codes.append(HCPCS_G8752)  # Most recent BP < 140/90
        else:
            codes.append(HCPCS_G8784)  # BP documented but not controlled

        log.info(f"Patient {self.patient.id} - Determined BP codes: {codes}")
        return codes

    def compute(self) -> list[Effect]:
        """Main compute method called when vitals command is committed."""
        command = Command.objects.get(id=self.event.target.id)
        note = command.note
        self.patient = command.patient

        log.info(f"Processing BP vitals for patient {self.patient.id}, note {note.id}")

        # Get BP readings
        systolic, diastolic = get_blood_pressure_readings(note)

        # Determine appropriate codes
        bp_codes = self.determine_bp_codes(systolic, diastolic, note)

        if not bp_codes:
            # This should never happen - determine_bp_codes always returns at least one code
            raise ValueError(f"No BP codes determined for patient {self.patient.id}")

        # Note: Assessment linking is now handled by the note state handler when the note is locked
        # This ensures assessments added after vitals are properly linked

        # Get existing billing line items for this note
        existing_billing_items = list(BillingLineItem.objects.filter(note_id=note.dbid))
        existing_codes_map = {item.cpt: item for item in existing_billing_items}

        # Process each code that should be present
        effects = []
        for code in bp_codes:
            # Check if this exact code already exists
            if code in existing_codes_map:
                log.info(f"Billing code {code} already exists for note {note.id}, no update needed")
                continue

            # Check if a different code from the same category exists (needs update)
            code_category = self.get_code_category(code)
            conflicting_item = None

            if code_category:
                # Look for any existing code from the same category
                for existing_code, billing_item in existing_codes_map.items():
                    if existing_code != code and existing_code in code_category:
                        conflicting_item = billing_item
                        break

            if conflicting_item:
                # Update the existing billing line item to the new code
                update_effect = UpdateBillingLineItem(
                    billing_line_item_id=str(conflicting_item.id),
                    cpt=code,
                    units=1,
                    assessment_ids=[],
                    modifiers=[]
                )
                effects.append(update_effect.apply())
                log.info(f"Updated billing code {conflicting_item.cpt} -> {code} for patient {self.patient.id}, note {note.id}")

                # Update our map to reflect the change
                del existing_codes_map[conflicting_item.cpt]
                existing_codes_map[code] = conflicting_item
            else:
                # Add new billing line item
                add_effect = AddBillingLineItem(
                    note_id=str(note.id),
                    cpt=code,
                    units=1,
                    assessment_ids=[],
                    modifiers=[]
                )
                effects.append(add_effect.apply())
                log.info(f"Added billing code {code} for patient {self.patient.id}, note {note.id}")

        return effects
