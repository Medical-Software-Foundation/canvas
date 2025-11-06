"""
Intake agent that uses LLM to extract structured patient information.

The agent manages the conversation flow, extracting required patient information
and storing it in the session cache. Once all information is collected, the agent
concludes the conversation and ignores further messages.
"""

import random
from datetime import datetime

from logger import log

from intake_agent.api.session import complete_session, get_session, update_session
from intake_agent.config import AGENT_NAME, AGENT_PERSONALITIES, AGENT_PERSONALITY
from intake_agent.llms.llm_anthropic import LlmAnthropic
from intake_agent.twilio_client import TwilioClient

# Patient record status codes
PATIENT_RECORD_STATUS_NOT_STARTED = 1
PATIENT_RECORD_STATUS_PENDING = 2
PATIENT_RECORD_STATUS_COMPLETE = 3


# Required fields for patient intake
REQUIRED_FIELDS = ["reason_for_visit", "phone", "first_name", "last_name", "date_of_birth"]


def check_reason_in_scope(reason: str, scope_description: str, llm_api_key: str) -> dict:
    """
    Use LLM to determine if the reason for visit is in scope.

    Args:
        reason: Patient's reason for visit
        scope_description: Description of what's in scope (from INTAKE_SCOPE_OF_CARE secret)
        llm_api_key: Anthropic API key for LLM

    Returns:
        Dictionary with:
            - in_scope: bool
            - explanation: str
            - error: str (if failed)
    """
    try:
        llm = LlmAnthropic(api_key=llm_api_key)

        system_prompt = """You are a medical triage assistant. Your job is to determine if a patient's reason for seeking care falls within the scope of services that can be handled by this intake system.

You will be given:
1. The patient's reason for seeking care
2. A description of what is in scope for this system

Respond with a JSON object:
{
    "in_scope": true or false,
    "explanation": "Brief explanation of why it is or isn't in scope"
}

Be conservative - if you're unsure, mark as out of scope."""

        user_prompt = f"""SCOPE OF CARE:
{scope_description}

PATIENT'S REASON FOR VISIT:
{reason}

Is this reason within scope? Respond with JSON."""

        result = llm.chat_with_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_retries=2
        )

        if result["success"]:
            data = result["data"]
            return {
                "in_scope": data.get("in_scope", False),
                "explanation": data.get("explanation", ""),
                "error": None
            }
        else:
            return {
                "in_scope": False,
                "explanation": "",
                "error": result["error"]
            }

    except Exception as e:
        log.error(f"Error checking reason in scope: {str(e)}")
        return {
            "in_scope": False,
            "explanation": "",
            "error": str(e)
        }










# ===== INTAKE AGENT CLASS =====


class IntakeAgent:
    """
    Class-based intake agent that manages the conversation flow and patient data collection.

    This agent handles the complete 13-step intake workflow, managing session state and
    delegating to appropriate step methods based on the current workflow state.
    """

    def __init__(
        self,
        session_id: str,
        session_data: dict,
        llm_api_key: str,
        scope_of_care: str,
        fallback_phone_number: str,
        policies_url: str,
        twilio_account_sid: str = None,
        twilio_auth_token: str = None,
        twilio_phone_number: str = None
    ):
        """
        Initialize the IntakeAgent with session and configuration data.

        Args:
            session_id: The session identifier
            session_data: Session data dictionary containing state and collected data
            llm_api_key: Anthropic API key for LLM
            scope_of_care: Description of services in scope for intake
            fallback_phone_number: Phone number to provide when out of scope
            policies_url: URL to clinic policies
            twilio_account_sid: Twilio Account SID (optional, required for SMS)
            twilio_auth_token: Twilio Auth Token (optional, required for SMS)
            twilio_phone_number: Twilio phone number (optional, required for SMS)
        """
        self.session_id = session_id
        self.session_data = session_data
        self.llm_api_key = llm_api_key
        self.scope_of_care = scope_of_care
        self.fallback_phone_number = fallback_phone_number
        self.policies_url = policies_url
        self.twilio_account_sid = twilio_account_sid
        self.twilio_auth_token = twilio_auth_token
        self.twilio_phone_number = twilio_phone_number
        self.conversation_history = get_conversation_history(session_data)
        self.collected_data_summary = get_collected_data_summary(session_data)
        self.collected_data = session_data.get("collected_data", {})

    def update_session(self):
        """Update the session in the cache with current session data."""
        update_session(self.session_id, self.session_data)

    def step_1_collect_reason(self, user_message: str) -> dict:
        """Step 1: Collect reason for visit with empathy and light follow-ups."""
        user_prompt = f"""CONVERSATION HISTORY:
{self.conversation_history}

CURRENTLY COLLECTED DATA:
{self.collected_data_summary}

NEW PATIENT MESSAGE:
{user_message}

===== YOUR TASK =====

You are in STEP 1: Collecting the patient's reason for visit.

INSTRUCTIONS:
- If they've provided a reason in their new message and you haven't already asked a question or two, show empathy and ask 1-2 light follow-up questions
  (Examples: "How long has this been bothering you?" or "Is this affecting your daily activities?")
- Extract any reason_for_visit information they provide
- Be supportive and caring

NEXT STEP LOGIC:
- If patient has provided a clear reason for visit → next_step: "check_scope"
- If still gathering details → next_step: "collect_reason"

Extract all information and respond to the patient."""

        llm = LlmAnthropic(api_key=self.llm_api_key)
        result = llm.chat_with_json(
            system_prompt=get_system_prompt(),
            user_prompt=user_prompt,
            max_retries=3
        )

        return result

    def step_2_check_scope(self, user_message: str) -> dict:
        """Step 2: Checks if reason for visit is in scope of online intake."""
        reason = self.session_data.get("collected_data", {}).get("reason_for_visit")

        if not reason:
            # Need to go back to collect_reason
            return {
                "success": True,
                "data": {
                    "next_step": "collect_reason",
                    "extracted_data": {},
                    "selected_appointment_index": None,
                    "verification_code_match": None,
                    "policy_agreement_accepted": None,
                    "response_to_patient": "Could you tell me what brings you in today?"
                }
            }

        # Check scope
        scope_result = check_reason_in_scope(reason, self.scope_of_care, self.llm_api_key)

        if scope_result["error"]:
            # Error checking scope, continue anyway
            in_scope = True
        else:
            in_scope = scope_result["in_scope"]

        # Update session
        self.session_data["collected_data"]["reason_in_scope"] = in_scope

        # TODO: Fix this
        in_scope = True

        if in_scope:
            return self.step_4_request_appointments()
        
        return self.step_3_out_of_scope()

    def step_3_out_of_scope(self) -> dict:
        """Step 3: Handle out-of-scope situations."""
        return {
            "success": True,
            "data": {
                "next_step": "complete",
                "extracted_data": {},
                "selected_appointment_index": None,
                "verification_code_match": None,
                "policy_agreement_accepted": None,
                "response_to_patient": f"Please call us at {self.fallback_phone_number} to discuss your needs. We're here to help!"
            }
        }

    def step_4_request_appointments(self) -> dict:
        """Step 4: Request available appointment slots."""
        # System provides slots
        # TODO: Handle the back-and-forth cycle of finding available slots, needs LLM here and conversation history. etc
        # TODO: Implement real slots
        appointment_slots = get_placeholder_appointment_slots()
        self.session_data["collected_data"]["proposed_appointment_times"] = appointment_slots

        # Format appointment times for presentation
        apt_descriptions = []
        for i, apt in enumerate(appointment_slots):
            apt_dt = datetime.fromisoformat(apt["start_datetime"])
            formatted = apt_dt.strftime("%A, %B %d at %I:%M %p")
            apt_descriptions.append(f"{i+1}. {formatted} with {apt['provider']}")

        apt_text = "\n".join(apt_descriptions)

        return {
            "success": True,
            "data": {
                "next_step": "select_appointment",
                "extracted_data": {},
                "selected_appointment_index": None,
                "verification_code_match": None,
                "policy_agreement_accepted": None,
                "response_to_patient": f"I have these appointment times available:\n\n{apt_text}\n\nWhich time works best for you?"
            }
        }

    def step_5_select_appointment(self, user_message: str) -> dict:
        """Step 5: Patient selects an appointment time."""
        user_prompt = f"""CONVERSATION HISTORY:
{self.conversation_history}

CURRENTLY COLLECTED DATA:
{self.collected_data_summary}

NEW PATIENT MESSAGE:
{user_message}

===== YOUR TASK =====

You are in STEP 5: Patient is selecting a preferred appointment time (not confirmed yet)

INSTRUCTIONS:
- If the patient indicates a choice of preferred time, extract the index (0-based) into selected_appointment_index

NEXT STEP LOGIC:
- If patient selected an appointment → next_step: "collect_phone"
- If they want different times → next_step: "request_appointments"
- If still deciding or wants alternatives → next_step: "select_appointment"

Extract the appointment choice if provided."""

        llm = LlmAnthropic(api_key=self.llm_api_key)
        result = llm.chat_with_json(
            system_prompt=get_system_prompt(),
            user_prompt=user_prompt,
            max_retries=3
        )

        # Process the result: extract selected_appointment_index and store in session_data
        if result.get("success"):
            step_data = result["data"]
            selected_apt_index = step_data.get("selected_appointment_index")

            if selected_apt_index is not None:
                proposed_times = self.session_data.get("collected_data", {}).get("proposed_appointment_times", [])
                if 0 <= selected_apt_index < len(proposed_times):
                    selected_apt = proposed_times[selected_apt_index]
                    self.session_data["collected_data"]["selected_appointment_time"] = selected_apt["start_datetime"]
                    self.session_data["collected_data"]["selected_appointment_index"] = selected_apt_index
                    log.info(f"Selected appointment {selected_apt_index} for session {self.session_id}")
                else:
                    log.warning(f"Invalid appointment index {selected_apt_index} for session {self.session_id}")

        return result

    def step_6_collect_phone(self, user_message: str) -> dict:
        """Step 6: Collect phone number."""
        user_prompt = f"""CONVERSATION HISTORY:
{self.conversation_history}

CURRENTLY COLLECTED DATA:
{self.collected_data_summary}

NEW PATIENT MESSAGE:
{user_message}

===== YOUR TASK =====

You are in STEP 6: Collecting the patient's mobile phone number.

INSTRUCTIONS:
- Ask for their mobile phone number for appointment confirmation
- Extract the phone number when provided (any format is fine)
- Explain we'll send a verification code

NEXT STEP LOGIC:
- If phone number provided → next_step: "send_verification"
- If still waiting for phone → next_step: "collect_phone"

Extract the phone number if provided."""

        llm = LlmAnthropic(api_key=self.llm_api_key)
        result = llm.chat_with_json(
            system_prompt=get_system_prompt(),
            user_prompt=user_prompt,
            max_retries=3
        )

        if result['data'].get('next_step') == 'send_verification':
            return self.step_7_send_verification()

        return result

    def step_7_send_verification(self) -> dict:
        """Step 7: Send verification code (system action)."""
        phone = self.session_data.get("collected_data", {}).get("phone")
        response_to_patient = "I've sent a 6-digit verification code to your phone. Please share that code with me when you receive it."

        # Send verification code via SMS
        if phone and all([self.twilio_account_sid, self.twilio_auth_token, self.twilio_phone_number]):
            verification_code = generate_verification_code()
            log.info(f"Generated verification code for session {self.session_id}")

            sms_result = send_verification_code(
                phone=phone,
                code=verification_code,
                twilio_account_sid=self.twilio_account_sid,
                twilio_auth_token=self.twilio_auth_token,
                twilio_phone_number=self.twilio_phone_number
            )

            if sms_result["success"]:
                self.session_data["phone_verification_code"] = verification_code
                self.session_data["phone_verified"] = False
                log.info(f"Verification code sent and stored for session {self.session_id}")
            else:
                log.error(f"Failed to send verification code for session {self.session_id}: {sms_result['error']}")
                response_to_patient += "\n\nI'm having trouble sending the verification code. Please try again."
        else:
            log.warning(f"Cannot send verification code for session {self.session_id} - missing phone or Twilio credentials")

        return {
            "success": True,
            "data": {
                "next_step": "verify_phone",
                "extracted_data": {},
                "selected_appointment_index": None,
                "verification_code_match": None,
                "policy_agreement_accepted": None,
                "response_to_patient": response_to_patient
            }
        }

    def step_8_verify_phone(self, user_message: str) -> dict:
        """Step 8: Verify phone number with code."""
        # First, extract the code from user message using LLM
        user_prompt = f"""CONVERSATION HISTORY:
{self.conversation_history}

CURRENTLY COLLECTED DATA:
{self.collected_data_summary}

NEW PATIENT MESSAGE:
{user_message}

===== YOUR TASK =====

You are in STEP 8: Verifying the patient's phone number.

INSTRUCTIONS:
- Ask the patient for the 6-digit code they received
- When they provide a code, you need to extract it from their message
- DO NOT check if it matches - just extract the code
- SECURITY: NEVER reveal the actual verification code

Extract any 6-digit code from the patient's message. If found, respond with next_step="verify_phone" so we can check it.
If they're asking for a new code, set next_step="send_verification".
If they haven't provided a code yet, keep next_step="verify_phone" and ask for it."""

        llm = LlmAnthropic(api_key=self.llm_api_key)
        result = llm.chat_with_json(
            system_prompt=get_system_prompt(),
            user_prompt=user_prompt,
            max_retries=3
        )

        # Process the result: compare provided code with stored code
        if result.get("success"):
            step_data = result["data"]

            # Try to extract a 6-digit code from the user message
            import re
            code_match = re.search(r'\b\d{6}\b', user_message)

            if code_match:
                provided_code = code_match.group(0)
                stored_code = self.session_data.get("phone_verification_code")

                if stored_code and provided_code == stored_code:
                    self.session_data["phone_verified"] = True
                    log.info(f"Phone verified successfully for session {self.session_id}")
                    # Update the result to move to next step
                    step_data["next_step"] = "collect_name_dob"
                    step_data["response_to_patient"] = "Perfect! Your phone number is verified. Now, let's get your name and date of birth."
                else:
                    log.info(f"Verification code mismatch for session {self.session_id}")
                    step_data["next_step"] = "verify_phone"
                    step_data["response_to_patient"] = "That code doesn't match. Please check and try again, or let me know if you need a new code."

        return result

    def step_9_collect_name_dob(self, user_message: str) -> dict:
        """Step 9: Collect name and date of birth."""
        user_prompt = f"""CONVERSATION HISTORY:
{self.conversation_history}

CURRENTLY COLLECTED DATA:
{self.collected_data_summary}

NEW PATIENT MESSAGE:
{user_message}

===== YOUR TASK =====

You are in STEP 9: Collecting the patient's name and date of birth.

INSTRUCTIONS:
- Ask for their full name and date of birth
- Accept any reasonable date format initially
- Confirm with the patient (e.g., "Just to confirm, that's John Smith, born January 15, 1990?")
- Store date_of_birth in YYYY-MM-DD format after confirmation

NEXT STEP LOGIC:
- If have first_name AND last_name AND date_of_birth → next_step: "create_patient"
- If still collecting → next_step: "collect_name_dob"

Extract name and DOB information."""

        llm = LlmAnthropic(api_key=self.llm_api_key)
        result = llm.chat_with_json(
            system_prompt=get_system_prompt(),
            user_prompt=user_prompt,
            max_retries=3
        )

        return result

    def step_10_create_patient_present_policies(self, user_message: str) -> dict:
        """Step 10: Create patient record (system action)."""
        effects = []

        # Create patient record
        collected_data = self.session_data.get("collected_data", {})
        phone_verified = self.session_data.get("phone_verified", False)
        required_for_patient = ["first_name", "last_name", "phone", "date_of_birth"]
        all_required_present = all(collected_data.get(field) for field in required_for_patient)
        log.info(f"all_required_present: {all_required_present}")

        if all_required_present and phone_verified:
            patient_status = self.session_data.get("patient_record_status", PATIENT_RECORD_STATUS_NOT_STARTED)
            if patient_status == PATIENT_RECORD_STATUS_NOT_STARTED:
                log.info(f"Creating patient record for session {self.session_id}")
                try:
                    create_result = create_patient(collected_data, self.session_id)
                    if create_result["success"]:
                        effects = create_result["effects"]
                        self.session_data["patient_record_status"] = PATIENT_RECORD_STATUS_PENDING
                        log.info(f"Patient creation queued for session {self.session_id}")
                    else:
                        log.error(f"Failed to create patient for session {self.session_id}: {create_result.get('error')}")
                        response_to_patient = "I'm having trouble creating your patient record. Let me try again."
                except Exception as e:
                    log.error(f"Exception creating patient for session {self.session_id}: {str(e)}")
                    response_to_patient = "I'm having trouble creating your patient record. Let me try again."
        else:
            log.warning(f"Cannot create patient for session {self.session_id} - missing data or unverified phone")

        result = self.step_11_present_policies(user_message)
        response_to_patient = result['data']['response_to_patient']
        result['data']['response_to_patient'] = "Great, I've started creating your medical record. " + response_to_patient
        result["effects"] = effects

        return result

    def step_11_present_policies(self, user_message: str) -> dict:
        """Step 11: Present policies and get agreement."""
        user_prompt = f"""CONVERSATION HISTORY:
{self.conversation_history}

CURRENTLY COLLECTED DATA:
{self.collected_data_summary}

NEW PATIENT MESSAGE:
{user_message}

===== YOUR TASK =====

You are in STEP 11: Presenting clinic policies.

INSTRUCTIONS:
- Show the policies URL as a markdown link: "Please review our [clinic policies]({self.policies_url})"
- Ask if they've read and agree to the policies
- Set policy_agreement_accepted to true when they agree

NEXT STEP LOGIC:
- If policy_agreement_accepted=true → next_step: "send_confirmation"
- If they disagree or have concerns → next_step: "complete" (end session)
- If still waiting → next_step: "present_policies"

Determine if patient agrees to policies."""

        llm = LlmAnthropic(api_key=self.llm_api_key)
        result = llm.chat_with_json(
            system_prompt=get_system_prompt(),
            user_prompt=user_prompt,
            max_retries=3
        )

        # Process the result: extract policy_agreement_accepted and store in session_data
        if result.get("success"):
            step_data = result["data"]
            policy_accepted = step_data.get("policy_agreement_accepted")

            if policy_accepted is not None:
                self.session_data["collected_data"]["policy_agreement_accepted"] = policy_accepted
                log.info(f"Policy agreement status: {policy_accepted}")

        return result

    def step_12_send_confirmation(self) -> dict:
        """Step 12: Send appointment confirmation with MRN (system action)."""
        response_to_patient = "Perfect! I've sent a confirmation text to your phone with your appointment details and Medical Record Number (MRN). Please save your MRN for future visits. If anything changes, please contact the clinic. Thank you!"

        # Send appointment confirmation with MRN
        collected_data = self.session_data.get("collected_data", {})
        phone = collected_data.get("phone")
        apt_time = collected_data.get("selected_appointment_time")
        reason = collected_data.get("reason_for_visit")
        mrn = collected_data.get("patient_mrn")

        # Try to retrieve MRN if not stored
        if not mrn:
            log.info(f"Attempting to retrieve MRN for session {self.session_id}")
            mrn = get_patient_mrn_by_session(self.session_id)
            if mrn:
                self.session_data["collected_data"]["patient_mrn"] = mrn
                log.info(f"Retrieved and stored MRN {mrn} for session {self.session_id}")

        # Send SMS if we have all required info
        if all([phone, apt_time, reason, mrn, self.twilio_account_sid, self.twilio_auth_token, self.twilio_phone_number]):
            log.info(f"Sending appointment confirmation SMS for session {self.session_id}")
            sms_result = send_appointment_confirmation_sms(
                phone=phone,
                appointment_time=apt_time,
                reason=reason,
                mrn=mrn,
                twilio_account_sid=self.twilio_account_sid,
                twilio_auth_token=self.twilio_auth_token,
                twilio_phone_number=self.twilio_phone_number
            )

            if sms_result["success"]:
                log.info(f"Appointment confirmation sent for session {self.session_id}")
                complete_session(self.session_id)
            else:
                log.error(f"Failed to send appointment confirmation for session {self.session_id}: {sms_result['error']}")
                response_to_patient = "I'm having trouble sending the confirmation. Let me try again."
        else:
            log.warning(f"Cannot send confirmation for session {self.session_id} - missing required data")
            if not mrn:
                response_to_patient = "I'm still waiting for your patient record to be created. Let me check on that..."

        return {
            "success": True,
            "data": {
                "next_step": "complete",
                "extracted_data": {},
                "selected_appointment_index": None,
                "verification_code_match": None,
                "policy_agreement_accepted": None,
                "response_to_patient": response_to_patient
            }
        }

    def step_13_complete(self) -> dict:
        """Step 13: Session complete."""
        return {
            "success": True,
            "data": {
                "next_step": "complete",
                "extracted_data": {},
                "selected_appointment_index": None,
                "verification_code_match": None,
                "policy_agreement_accepted": None,
                "response_to_patient": "You're all set! Check your phone for the confirmation. Looking forward to seeing you!"
            }
        }

    def process(self, user_message: str) -> dict:
        """
        Process a patient message and generate an agent response.

        This method handles the complete 13-step intake workflow using the class-based
        architecture. Each step method contains its own prompting logic, and this method
        delegates to the appropriate step and handles side effects.

        Args:
            user_message: The patient's message

        Returns:
            Dictionary with:
                - response: str - Agent response message to send to patient
                - effects: list - List of Effect objects to return to Canvas
        """
        # Check if intake already completed
        if self.session_data.get("status") == "completed":
            log.info(f"Ignoring message for completed session: {self.session_id}")
            return {
                "response": "Thank you! Your intake is complete. Someone from our team will be in touch with you soon.",
                "effects": []
            }

        # Get current next_step from session
        next_step = self.session_data.get("next_step", "collect_reason")
        log.info(f"Session {self.session_id}: current step={next_step}")

        # Call the appropriate step method based on next_step
        if next_step == "collect_reason":
            result = self.step_1_collect_reason(user_message)
        elif next_step == "check_scope":
            result = self.step_2_check_scope(user_message)
        elif next_step == "out_of_scope":
            result = self.step_3_out_of_scope()
        elif next_step == "request_appointments":
            result = self.step_4_request_appointments()
        elif next_step == "select_appointment":
            result = self.step_5_select_appointment(user_message)
        elif next_step == "collect_phone":
            result = self.step_6_collect_phone(user_message)
        elif next_step == "send_verification":
            result = self.step_7_send_verification()
        elif next_step == "verify_phone":
            result = self.step_8_verify_phone(user_message)
        elif next_step == "collect_name_dob":
            result = self.step_9_collect_name_dob(user_message)
        elif next_step == "create_patient":
            result = self.step_10_create_patient_present_policies(user_message)
        elif next_step == "present_policies":
            result = self.step_11_present_policies(user_message)
        elif next_step == "send_confirmation":
            result = self.step_12_send_confirmation()
        elif next_step == "complete":
            result = self.step_13_complete()
        else:
            log.error(f"Unknown step: {next_step}")
            return {
                "response": "I apologize, but I encountered an error. Please try again.",
                "effects": []
            }

        # Check if step method call was successful
        if not result.get("success"):
            log.error(f"Step method error for session {self.session_id}: {result.get('error')}")
            return {
                "response": "I apologize, but I'm having trouble processing your message. Could you please try again?",
                "effects": []
            }

        # Extract data from step method result
        step_data = result["data"]
        new_next_step = step_data.get("next_step", "collect_reason")
        extracted_data = step_data.get("extracted_data", {})
        response_to_patient = step_data.get("response_to_patient", "")

        log.info(f"Session {self.session_id}: new_next_step={new_next_step}")
        log.info(f"Session {self.session_id}: extracted_data={extracted_data}")

        if not response_to_patient:
            log.warning(f"Empty response_to_patient for session {self.session_id}")
            response_to_patient = "Thank you for that information. How can I help you further?"

        # Update collected data in session with extracted_data
        if extracted_data:
            collected_data = self.session_data.get("collected_data", {})
            for field in REQUIRED_FIELDS:
                value = extracted_data.get(field)
                if value is not None:
                    collected_data[field] = value
                    log.info(f"Updated {field} for session {self.session_id}")
            self.session_data["collected_data"] = collected_data

        # Get effects from result (for steps that create effects, like create_patient)
        effects = []
        if "effects" in result:
            effects = result["effects"]
            log.info(f"EFFECTS ARE PRESENT: {effects}")

        # Handle session completion
        if new_next_step == "complete":
            log.info(f"Session {self.session_id} completed")
            complete_session(self.session_id)

        # Store the NEW next_step in session_data and update session
        self.session_data["next_step"] = new_next_step
        self.update_session()

        return {
            "response": response_to_patient,
            "effects": effects
        }


# ===== MAIN PROCESSING FUNCTION =====


def process_patient_message(
    session_id: str,
    user_message: str,
    llm_api_key: str,
    scope_of_care: str,
    fallback_phone_number: str,
    policies_url: str,
    twilio_account_sid: str = None,
    twilio_auth_token: str = None,
    twilio_phone_number: str = None
) -> dict:
    """
    Process a patient message and generate an agent response.

    This is the public API function that creates an IntakeAgent instance and
    processes the patient's message through the 13-step intake workflow.

    Args:
        session_id: The session identifier
        user_message: The patient's message
        llm_api_key: Anthropic API key for LLM
        scope_of_care: Description of services in scope for intake
        fallback_phone_number: Phone number to provide when out of scope
        policies_url: URL to clinic policies
        twilio_account_sid: Twilio Account SID (optional, required for SMS)
        twilio_auth_token: Twilio Auth Token (optional, required for SMS)
        twilio_phone_number: Twilio phone number (optional, required for SMS)

    Returns:
        Dictionary with:
            - response: str - Agent response message to send to patient
            - effects: list - List of Effect objects to return to Canvas
    """
    # Get session data
    session_data = get_session(session_id)

    if not session_data:
        log.error(f"Session not found: {session_id}")
        return {
            "response": "I apologize, but I couldn't find your session. Please refresh and try again.",
            "effects": []
        }

    # Create IntakeAgent instance
    agent = IntakeAgent(
        session_id=session_id,
        session_data=session_data,
        llm_api_key=llm_api_key,
        scope_of_care=scope_of_care,
        fallback_phone_number=fallback_phone_number,
        policies_url=policies_url,
        twilio_account_sid=twilio_account_sid,
        twilio_auth_token=twilio_auth_token,
        twilio_phone_number=twilio_phone_number
    )

    # Process the message and return the result
    return agent.process(user_message)

