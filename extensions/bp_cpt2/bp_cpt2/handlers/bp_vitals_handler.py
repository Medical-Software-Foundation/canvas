import re
from typing import Optional
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Command, Observation, BillingLineItem, Note
from canvas_sdk.v1.data.assessment import Assessment
from canvas_sdk.effects.billing_line_item import AddBillingLineItem, UpdateBillingLineItem
from logger import log

from bp_cpt2.utils import get_blood_pressure_readings
from bp_cpt2.llm_openai import LlmOpenai


class BloodPressureVitalsHandler(BaseHandler):
    """
    Handles blood pressure measurements from vitals commands and returns appropriate
    CPT/HCPCS billing codes based on systolic and diastolic BP values.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.VITALS_COMMAND__POST_COMMIT)
    ]

    # Code categories - codes within the same category are mutually exclusive
    SYSTOLIC_CODES = {"3074F", "3075F", "3077F"}
    DIASTOLIC_CODES = {"3078F", "3079F", "3080F"}
    CONTROL_STATUS_CODES = {"G8783", "G8784"}  # G8752 can coexist with these
    NOT_DOCUMENTED_CODES = {"G8950", "G8951"}  # These are also mutually exclusive

    def get_code_category(self, code: str) -> Optional[set[str]]:
        """
        Get the category (set of mutually exclusive codes) that a code belongs to.
        Returns None if the code doesn't belong to any mutually exclusive category.
        """
        if code in self.SYSTOLIC_CODES:
            return self.SYSTOLIC_CODES
        elif code in self.DIASTOLIC_CODES:
            return self.DIASTOLIC_CODES
        elif code in self.CONTROL_STATUS_CODES:
            return self.CONTROL_STATUS_CODES
        elif code in self.NOT_DOCUMENTED_CODES:
            return self.NOT_DOCUMENTED_CODES
        return None

    def get_hypertension_related_assessments(self, note: Note) -> list[str]:
        """
        Get assessment IDs that are related to hypertension using LLM analysis.

        Args:
            note: Note object to get assessments from

        Returns:
            List of assessment IDs (as strings) that are hypertension-related
        """
        # Get all assessments for this note
        assessments = list(Assessment.objects.filter(note_id=note.dbid, deleted=False))
        if not assessments:
            return []

        # Build assessment data for LLM analysis
        assessment_data = []
        for assessment in assessments:
            if not assessment.condition:
                continue

            # Get condition codings
            codings = []
            try:
                condition_codings = assessment.condition.codings.filter(system='ICD-10')
                for coding in condition_codings:
                    coding_info = {
                        "system": coding.system if hasattr(coding, 'system') else '',
                        "code": coding.code if hasattr(coding, 'code') else '',
                        "display": coding.display if hasattr(coding, 'display') else ''
                    }
                    codings.append(coding_info)
            except (AttributeError, Exception):
                pass

            if codings:
                assessment_entry = {
                    "assessment_id": str(assessment.id),
                    "codings": codings
                }
                assessment_data.append(assessment_entry)

        if not assessment_data:
            return []

        # Use LLM to identify hypertension-related assessments
        try:
            openai_api_key = self.secrets.get('OPENAI_API_KEY')
            if not openai_api_key:
                log.warning(f"Note {note.id} - OPENAI_API_KEY not configured, cannot filter hypertension-related assessments")
                return []

            client = LlmOpenai(api_key=openai_api_key)

            system_prompt = "You are a medical coding assistant that helps identify hypertension-related diagnoses."
            user_prompt = f"""Analyze the following assessments and determine which ones are clearly related to hypertension (high blood pressure).

Assessments to analyze:
{assessment_data}

Return a JSON object with a single key "hypertension_related_assessment_ids" containing an array of assessment_id strings that are related to hypertension.

Examples of hypertension-related conditions:
- Essential hypertension
- Hypertensive heart disease
- Hypertensive chronic kidney disease
- Secondary hypertension
- Hypertensive crisis
- Renovascular hypertension
- And other conditions that are directly caused by or related to high blood pressure

Do NOT include conditions that are merely risk factors for hypertension (like diabetes, obesity) or complications that can occur with many conditions.

If none of the assessments are hypertension-related, return an empty array."""

            response = client.chat_with_json(system_prompt=system_prompt, user_prompt=user_prompt, max_retries=2)

            if response and isinstance(response, dict) and response.get('success'):
                response_data = response.get('data', {})
                related_ids = response_data.get('hypertension_related_assessment_ids', [])

                if isinstance(related_ids, list):
                    log.info(f"Note {note.id} - Found {len(related_ids)} hypertension-related assessments")
                    return related_ids
                else:
                    log.warning(f"Note {note.id} - LLM returned invalid format for hypertension_related_assessment_ids")
                    return []
            else:
                error_msg = response.get('error', 'Unknown error') if isinstance(response, dict) else 'Invalid response format'
                log.warning(f"Note {note.id} - LLM request failed: {error_msg}")
                return []

        except Exception as e:
            log.error(f"Note {note.id} - Error identifying hypertension-related assessments: {e}")
            return []

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
        systolic, diastolic = get_blood_pressure_readings(note)

        # Determine appropriate codes
        bp_codes = self.determine_bp_codes(systolic, diastolic, note)

        if not bp_codes:
            # This should never happen - determine_bp_codes always returns at least one code
            raise ValueError(f"No BP codes determined for patient {self.patient.id}")

        # Get hypertension-related assessments for the note using LLM analysis
        assessments = self.get_hypertension_related_assessments(note)

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
                    assessment_ids=assessments,
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
                    assessment_ids=assessments,
                    modifiers=[]
                )
                effects.append(add_effect.apply())
                log.info(f"Added billing code {code} for patient {self.patient.id}, note {note.id}")

        return effects
