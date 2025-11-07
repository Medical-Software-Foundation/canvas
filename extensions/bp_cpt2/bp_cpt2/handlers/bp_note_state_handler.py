import json
from typing import Optional

from canvas_sdk.effects import Effect
from canvas_sdk.effects.billing_line_item import AddBillingLineItem
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Command, Medication, Note, Assessment, BillingLineItem
from logger import log

from bp_cpt2.llm_openai import LlmOpenai
from bp_cpt2.utils import get_blood_pressure_readings


class BloodPressureNoteStateHandler(BaseHandler):
    """
    Handles note state changes for treatment plan documentation analysis.

    This handler analyzes clinical notes to determine if blood pressure treatment plans
    are documented and adds appropriate billing codes (G8753-G8755) for uncontrolled BP.

    Treatment codes:
    - G8753: Most recent BP >= 140/90 and treatment plan documented
    - G8754: Most recent BP >= 140/90 and no treatment plan, reason not given
    - G8755: Most recent BP >= 140/90 and no treatment plan, documented reason
    """

    RESPONDS_TO = [
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_UPDATED)
    ]


    def prepare_note_commands_data(self, note: Note) -> str:
        """Extract and format all commands from the note for LLM analysis."""
        commands = Command.objects.filter(note=note)

        commands_data = []
        for cmd in commands:
            cmd_info = {
                "schema_key": cmd.schema_key,
                "data": cmd.data if cmd.data else {}
            }
            commands_data.append(cmd_info)

        if not commands_data:
            return "No commands documented in this note."

        return json.dumps(commands_data, indent=2)

    def prepare_medications_data(self, patient_id: str) -> str:
        """Extract and format active medications for LLM analysis."""
        medications = Medication.objects.for_patient(patient_id).filter(deleted=False)

        medications_data = []
        for med in medications:
            med_info = {
                "name": med.fhir_medication_display if hasattr(med, 'fhir_medication_display') else str(med),
                "status": med.status if hasattr(med, 'status') else "unknown"
            }
            medications_data.append(med_info)

        if not medications_data:
            return "No active medications documented for this patient."

        return json.dumps(medications_data, indent=2)

    def analyze_treatment_plan_with_llm(
        self,
        commands_data: str,
        medications_data: str,
        systolic: float,
        diastolic: float
    ) -> dict:
        """
        Use LLM to analyze if blood pressure treatment plan is documented.

        Returns dict with:
            - has_treatment_plan (bool): Whether a treatment plan is documented
            - has_documented_reason (bool): Whether there's a documented reason for no treatment plan
            - explanation (str): Brief explanation of the analysis
        """
        # Get API key from secrets
        api_key = self.secrets.get('OPENAI_API_KEY')
        if not api_key:
            log.error("OPENAI_API_KEY not found in secrets")
            # Default to no treatment plan documented
            return {
                "has_treatment_plan": False,
                "has_documented_reason": False,
                "explanation": "Unable to analyze: OpenAI API key not configured"
            }

        llm = LlmOpenai(api_key=api_key, model="gpt-4")

        system_prompt = """You are a clinical documentation analyst specializing in hypertension management.
Your task is to analyze clinical note data to determine if a blood pressure treatment plan is documented.

A treatment plan is considered documented if ANY of the following are present:
1. New or adjusted antihypertensive medications prescribed or planned
2. Lifestyle modifications specifically for blood pressure control (e.g., diet changes, exercise, salt restriction)
3. Follow-up plans specifically for blood pressure monitoring or management
4. Referrals to specialists for hypertension management
5. Patient education about blood pressure control

If NO treatment plan is found, check if there's a documented reason why (e.g., "patient declined",
"awaiting specialist consult", "recent medication change, monitoring before adjustment").

You must respond with valid JSON in the following format:
```json
{
    "has_treatment_plan": true/false,
    "has_documented_reason": true/false,
    "explanation": "brief explanation of your analysis"
}
```"""

        user_prompt = f"""Analyze the following clinical data for blood pressure treatment plan documentation.

Patient's Blood Pressure: {systolic}/{diastolic} mmHg (UNCONTROLLED - requires treatment plan)

Clinical Note Commands:
{commands_data}

Active Medications:
{medications_data}

Based on this information, determine:
1. Is there a documented treatment plan for blood pressure management?
2. If no treatment plan, is there a documented reason why?

Provide your analysis in JSON format."""

        # Use chat_with_json to get structured response
        result = llm.chat_with_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_retries=3
        )

        if result["success"]:
            return result["data"]
        else:
            log.error(f"LLM analysis failed: {result['error']}")
            # Default to no treatment plan documented
            return {
                "has_treatment_plan": False,
                "has_documented_reason": False,
                "explanation": f"LLM analysis failed: {result['error']}"
            }

    def determine_treatment_code(self, analysis_result: dict) -> Optional[str]:
        """
        Determine the appropriate treatment billing code based on LLM analysis.

        Returns:
            G8753: Treatment plan documented
            G8754: No treatment plan, reason not given
            G8755: No treatment plan, documented reason
            None: Should not add treatment code
        """
        has_treatment_plan = analysis_result.get("has_treatment_plan", False)
        has_documented_reason = analysis_result.get("has_documented_reason", False)

        if has_treatment_plan:
            return "G8753"
        elif has_documented_reason:
            return "G8755"
        else:
            return "G8754"

    def compute(self) -> list[Effect]:
        """Main compute method called when note state changes."""
        # Check if treatment plan codes are enabled
        include_treatment_codes = self.secrets.get('INCLUDE_TREATMENT_PLAN_CODES', '').lower()
        if include_treatment_codes in ('false', 'f', 'n', 'no', '0', ''):
            log.info("Treatment plan codes disabled via INCLUDE_TREATMENT_PLAN_CODES setting")
            return []

        # Get note state and note_id from event
        new_note_state = self.event.context.get('state')
        note_id = self.event.context.get('note_id')

        log.info(f"Note {note_id} state change to: {new_note_state}")

        # Only process when note is locked or charges are pushed
        if new_note_state not in ['LKD', 'PSH']:
            log.info(f"Skipping BP treatment analysis for note {note_id} - state is {new_note_state}")
            return []

        # Get the note
        try:
            note = Note.objects.get(id=note_id)
        except Note.DoesNotExist:
            log.error(f"Note {note_id} not found")
            return []

        patient = note.patient
        log.info(f"Analyzing BP treatment plan for patient {patient.id}, note {note.id}")

        # Get BP readings for this note
        systolic, diastolic = get_blood_pressure_readings(note)

        # Only add treatment codes if BP is uncontrolled (>= 140/90)
        if systolic is None or diastolic is None:
            log.info(f"No BP readings found for note {note.id}, skipping treatment plan analysis")
            return []

        if systolic < 140 and diastolic < 90:
            log.info(f"BP is controlled ({systolic}/{diastolic}), no treatment plan codes needed")
            return []

        log.info(f"BP is uncontrolled ({systolic}/{diastolic}), analyzing treatment plan")

        # Prepare data for LLM analysis
        commands_data = self.prepare_note_commands_data(note)
        medications_data = self.prepare_medications_data(str(patient.id))

        # Analyze with LLM
        analysis_result = self.analyze_treatment_plan_with_llm(
            commands_data=commands_data,
            medications_data=medications_data,
            systolic=systolic,
            diastolic=diastolic
        )

        log.info(f"Treatment plan analysis result: {analysis_result}")

        # Determine appropriate treatment code
        treatment_code = self.determine_treatment_code(analysis_result)

        if not treatment_code:
            log.info("No treatment code determined")
            return []

        # Check if this code already exists
        existing_codes = set(
            BillingLineItem.objects.filter(
                note_id=note.dbid
            ).values_list("cpt", flat=True)
        )

        if treatment_code in existing_codes:
            log.info(f"Treatment code {treatment_code} already exists for note {note.id}, skipping")
            return []

        # Get assessments for the note
        assessments = [
            str(assessment_id)
            for assessment_id in Assessment.objects.filter(note_id=note.dbid).values_list("id", flat=True)
        ]

        # Create billing line item effect
        billing_item = AddBillingLineItem(
            note_id=str(note.id),
            cpt=treatment_code,
            units=1,
            assessment_ids=assessments,
            modifiers=[]
        )

        log.info(f"Added treatment billing code {treatment_code} for patient {patient.id}: {analysis_result.get('explanation')}")

        return [billing_item.apply()]
