"""
Intake agent that uses LLM to extract structured patient information.

The agent manages the conversation flow, extracting required patient information
and storing it in the session cache. Once all information is collected, the agent
concludes the conversation and ignores further messages.
"""

import random
from datetime import datetime

from canvas_sdk.effects.patient import Patient, PatientContactPoint, PatientMetadata
from canvas_sdk.v1.data.common import ContactPointSystem, ContactPointUse
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
REQUIRED_FIELDS = ["first_name", "last_name", "email", "phone", "date_of_birth", "reason_for_visit"]


def generate_verification_code() -> str:
    """
    Generate a random 6-digit verification code.

    Returns:
        6-digit string code
    """
    return f"{random.randint(0, 999999):06d}"


def send_verification_code(phone: str, code: str, twilio_account_sid: str, twilio_auth_token: str, twilio_phone_number: str) -> dict:
    """
    Send a verification code via SMS to the patient's phone number.

    Args:
        phone: Patient's phone number
        code: 6-digit verification code
        twilio_account_sid: Twilio Account SID
        twilio_auth_token: Twilio Auth Token
        twilio_phone_number: Twilio phone number to send from

    Returns:
        Dictionary with:
            - success: bool
            - error: str (if failed)
    """
    try:
        client = TwilioClient(account_sid=twilio_account_sid, auth_token=twilio_auth_token)

        message_body = f"Your verification code is: {code}\n\nPlease share this code with {AGENT_NAME} to verify your phone number."

        result = client.send_sms(
            to=phone,
            from_=twilio_phone_number,
            body=message_body
        )

        if result["success"]:
            log.info(f"Verification code sent to {phone}: {result['message_sid']}")
            return {"success": True, "error": None}
        else:
            log.error(f"Failed to send verification code to {phone}: {result['error']}")
            return {"success": False, "error": result["error"]}

    except Exception as e:
        error_msg = f"Error sending verification code: {str(e)}"
        log.error(error_msg)
        return {"success": False, "error": error_msg}


def get_system_prompt() -> str:
    """
    Generate the system prompt for the intake agent based on configuration.

    Returns:
        System prompt string with agent name and personality
    """
    # Get personality configuration
    personality_config = AGENT_PERSONALITIES.get(AGENT_PERSONALITY, AGENT_PERSONALITIES["warm_professional"])
    personality_description = personality_config["description"]
    personality_traits = "\n".join([f"- {trait}" for trait in personality_config["traits"]])

    return f"""You are {AGENT_NAME}, a medical intake assistant. Your goal is to collect the following required information from a prospective patient:

1. First name
2. Last name
3. Email address
4. Phone number
5. Date of birth (format: YYYY-MM-DD)
6. Reason for visit (brief description of why they're seeking care)

YOUR PERSONALITY:
{personality_description}

Key traits to embody:
{personality_traits}

You should:
- Introduce yourself by name when greeting new patients
- Ask for missing information naturally in conversation, consistent with your personality
- Only ask for one or two pieces of information at a time to avoid overwhelming the patient
- Validate that email addresses look reasonable (contain @)
- Validate that phone numbers are provided (any format is acceptable)
- Validate that dates of birth are in YYYY-MM-DD format
- Extract information from the patient's messages when they provide it
- Once all information is collected, thank them and let them know someone will be in touch soon

PHONE VERIFICATION PROCESS:
- When you first extract a phone number, you MUST prioritize verifying it before asking for other information
- Set "send_verification_code" to true to trigger sending a verification code via SMS
- Ask the patient to share the 6-digit code they receive via text
- Compare the code they provide against the verification code
- Set "verification_code_match" to true if the codes match, false if they don't match
- If verification fails, politely let them know and they can request another code
- If they request another code (or didn't receive it), set "send_verification_code" to true again
- Once the phone is verified, continue collecting remaining information
- Do NOT create a patient record until the phone number is verified

CRITICAL SECURITY RULE - VERIFICATION CODES:
- NEVER reveal or mention the actual verification code in your messages to the patient
- NEVER say things like "The code is 123456" or "I sent you 123456"
- You will NOT see the actual verification code in the collected data - this is intentional for security
- Only tell the patient "I've sent a verification code to your phone" or similar
- If the code doesn't match, say "That code doesn't match. Please try again or I can send you a new code"
- The system handles code generation and comparison automatically - you just set the flags

After each patient message, you must respond with a JSON object in this exact format:

```json
{{
    "extracted_data": {{
        "first_name": "value or null",
        "last_name": "value or null",
        "email": "value or null",
        "phone": "value or null",
        "date_of_birth": "value or null",
        "reason_for_visit": "value or null"
    }},
    "send_verification_code": true or false,
    "verification_code_match": true or false or null,
    "all_information_collected": true or false,
    "response_to_patient": "Your message to the patient (in character with your personality)"
}}
```

Important guidelines:
- Only include data in extracted_data if you found it in the patient's message or conversation history
- Set fields to null if the information hasn't been provided yet
- Set all_information_collected to true ONLY when ALL required fields have non-null values
- The response_to_patient should be natural, conversational, and consistent with your personality
- If information was already collected in a previous message, include it in extracted_data
- Don't ask for information that was already provided
"""


def get_conversation_history(session_data: dict) -> str:
    """
    Format conversation history for the LLM context.

    Args:
        session_data: Session data containing messages

    Returns:
        Formatted conversation history string
    """
    messages = session_data.get("messages", [])
    if not messages:
        return "No previous messages."

    history_parts = []
    for msg in messages:
        role = "Patient" if msg["role"] == "user" else "Agent"
        history_parts.append(f"{role}: {msg['content']}")

    return "\n".join(history_parts)


def get_collected_data_summary(session_data: dict) -> str:
    """
    Format collected data for the LLM context.

    SECURITY NOTE: This function MUST NOT reveal the verification code to the LLM,
    as the LLM might accidentally include it in responses to the patient.

    Args:
        session_data: Session data containing collected_data

    Returns:
        Formatted collected data summary
    """
    collected = session_data.get("collected_data", {})
    phone_verified = session_data.get("phone_verified", False)
    verification_code = session_data.get("phone_verification_code")

    parts = []
    for field in REQUIRED_FIELDS:
        value = collected.get(field)
        status = f"'{value}'" if value else "NOT COLLECTED"

        # Add verification status for phone field
        # SECURITY: Never reveal the actual verification code to the LLM
        if field == "phone" and value:
            if phone_verified:
                status += " (VERIFIED)"
            elif verification_code:
                status += " (VERIFICATION CODE SENT, AWAITING PATIENT CONFIRMATION)"
            else:
                status += " (NOT VERIFIED YET)"

        parts.append(f"- {field}: {status}")

    return "\n".join(parts)


def create_patient(collected_data: dict, session_id: str) -> dict:
    """
    Create a new patient record via Canvas SDK effects.

    This method returns effects that will be processed asynchronously by Canvas.
    The patient record will be created in the background, and we store the
    session_id in patient metadata for later tracking.

    Args:
        collected_data: Patient data collected during intake
        session_id: The intake session ID to store in patient metadata

    Returns:
        Dictionary with:
            - success: bool (always True, as effects are queued)
            - effects: list of Effect objects to be returned
            - error: str (None for success)

    Raises:
        ValueError: If required data is missing or invalid
    """
    # Validate required fields
    required = ["first_name", "last_name", "email", "phone", "date_of_birth"]
    for field in required:
        if not collected_data.get(field):
            raise ValueError(f"Missing required field for patient creation: {field}")

    log.info(
        f"Creating patient for {collected_data['first_name']} {collected_data['last_name']}"
    )

    # Parse date_of_birth string (YYYY-MM-DD) to date object
    try:
        birthdate = datetime.strptime(collected_data["date_of_birth"], "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(
            f"Invalid date_of_birth format: {collected_data['date_of_birth']} (expected YYYY-MM-DD)"
        ) from e

    # Create patient effect
    patient_effect = Patient(
        first_name=collected_data["first_name"],
        last_name=collected_data["last_name"],
        birthdate=birthdate,
        # Contact information
        contact_points=[
            PatientContactPoint(
                system=ContactPointSystem.PHONE,
                value=collected_data["phone"],
                use=ContactPointUse.MOBILE,
                rank=1,
                has_consent=True,
            ),
            PatientContactPoint(
                system=ContactPointSystem.EMAIL,
                value=collected_data["email"],
                use=ContactPointUse.WORK,
                rank=2,
                has_consent=True,
            ),
        ],
        # Store intake session ID in metadata
        metadata=[PatientMetadata(key="intake_session_id", value=session_id)],
    )

    log.info(f"Queued patient creation effect for session {session_id}")

    return {
        "success": True,
        "effects": [patient_effect.create()],
        "error": None,
    }


def process_patient_message(
    session_id: str,
    user_message: str,
    llm_api_key: str,
    twilio_account_sid: str = None,
    twilio_auth_token: str = None,
    twilio_phone_number: str = None
) -> dict:
    """
    Process a patient message and generate an agent response.

    This function:
    1. Checks if intake is already completed
    2. Loads conversation history and collected data
    3. Uses LLM to extract information and generate response
    4. Handles phone verification (sending codes, verifying codes)
    5. Updates session with newly extracted data
    6. Creates patient record via SDK if all data collected and phone verified
    7. Marks session as completed if all data collected

    Args:
        session_id: The session identifier
        user_message: The patient's message
        llm_api_key: Anthropic API key for LLM
        twilio_account_sid: Twilio Account SID (optional, required for phone verification)
        twilio_auth_token: Twilio Auth Token (optional, required for phone verification)
        twilio_phone_number: Twilio phone number (optional, required for phone verification)

    Returns:
        Dictionary with:
            - response: str - Agent response message to send to patient
            - effects: list - List of Effect objects to return to Canvas
    """
    session_data = get_session(session_id)

    if not session_data:
        log.error(f"Session not found: {session_id}")
        return {
            "response": "I apologize, but I couldn't find your session. Please refresh and try again.",
            "effects": []
        }

    # Check if intake already completed
    if session_data.get("status") == "completed":
        log.info(f"Ignoring message for completed session: {session_id}")
        return {
            "response": "Thank you! Your intake is complete. Someone from our team will be in touch with you soon.",
            "effects": []
        }

    # Get conversation history and current collected data
    conversation_history = get_conversation_history(session_data)
    collected_data_summary = get_collected_data_summary(session_data)

    # Build user prompt with context
    user_prompt = f"""CONVERSATION HISTORY:
{conversation_history}

CURRENTLY COLLECTED DATA:
{collected_data_summary}

NEW PATIENT MESSAGE:
{user_message}

Please analyze this message, extract any new information, and respond to the patient. Remember to output a JSON object with extracted_data, all_information_collected, and response_to_patient fields."""

    # Call LLM with JSON response
    llm = LlmAnthropic(api_key=llm_api_key)

    try:
        result = llm.chat_with_json(
            system_prompt=get_system_prompt(),
            user_prompt=user_prompt,
            max_retries=3
        )

        if not result["success"]:
            log.error(f"LLM error for session {session_id}: {result['error']}")
            return {
                "response": "I apologize, but I'm having trouble processing your message. Could you please try again?",
                "effects": []
            }

        llm_response = result["data"]

        # Validate response structure
        if not isinstance(llm_response, dict):
            log.error(f"Invalid LLM response type for session {session_id}: {type(llm_response)}")
            return {
                "response": "I apologize, but I encountered an error. Please try again.",
                "effects": []
            }

        extracted_data = llm_response.get("extracted_data", {})
        all_info_collected = llm_response.get("all_information_collected", False)
        response_to_patient = llm_response.get("response_to_patient", "")
        should_send_verification_code = llm_response.get("send_verification_code", False)
        verification_code_match = llm_response.get("verification_code_match", None)

        if not response_to_patient:
            log.warning(f"Empty response_to_patient for session {session_id}")
            response_to_patient = "Thank you for that information. How can I help you further?"

        # Update collected data in session
        if extracted_data:
            collected_data = session_data.get("collected_data", {})

            for field in REQUIRED_FIELDS:
                value = extracted_data.get(field)
                if value is not None:
                    collected_data[field] = value
                    log.info(f"Updated {field} for session {session_id}")

            session_data["collected_data"] = collected_data
            update_session(session_id, session_data)

        # Handle phone verification code sending
        if should_send_verification_code:
            phone = session_data.get("collected_data", {}).get("phone")

            if phone and all([twilio_account_sid, twilio_auth_token, twilio_phone_number]):
                # Generate and send verification code
                verification_code = generate_verification_code()
                log.info(f"Generated verification code for session {session_id}: {verification_code}")

                # Send SMS
                sms_result = send_verification_code(
                    phone=phone,
                    code=verification_code,
                    twilio_account_sid=twilio_account_sid,
                    twilio_auth_token=twilio_auth_token,
                    twilio_phone_number=twilio_phone_number
                )

                if sms_result["success"]:
                    # Store verification code in session
                    session_data["phone_verification_code"] = verification_code
                    session_data["phone_verified"] = False
                    update_session(session_id, session_data)
                    log.info(f"Verification code sent and stored for session {session_id}")
                else:
                    log.error(f"Failed to send verification code for session {session_id}: {sms_result['error']}")
                    response_to_patient += "\n\nI'm having trouble sending the verification code. Please try again in a moment."
            else:
                if not phone:
                    log.warning(f"Cannot send verification code - no phone number for session {session_id}")
                else:
                    log.warning(f"Cannot send verification code - missing Twilio credentials for session {session_id}")

        # Handle phone verification code matching
        if verification_code_match is not None:
            stored_code = session_data.get("phone_verification_code")

            if verification_code_match is True and stored_code:
                # Mark phone as verified
                session_data["phone_verified"] = True
                update_session(session_id, session_data)
                log.info(f"Phone verified successfully for session {session_id}")
            elif verification_code_match is False:
                log.info(f"Verification code mismatch for session {session_id}")

        # Check if all information collected
        effects = []
        if all_info_collected:
            collected_data = session_data.get("collected_data", {})
            all_fields_present = all(
                collected_data.get(field) is not None
                for field in REQUIRED_FIELDS
            )
            phone_verified = session_data.get("phone_verified", False)

            if all_fields_present and phone_verified:
                log.info(f"All information collected and phone verified for session {session_id}")

                # Get current patient record status (default to not_started)
                patient_status = session_data.get("patient_record_status", PATIENT_RECORD_STATUS_NOT_STARTED)

                # Create patient record
                if patient_status == PATIENT_RECORD_STATUS_NOT_STARTED:
                    log.info(f"Creating patient record for session {session_id}")
                    result = create_patient(collected_data, session_id)

                    if result["success"]:
                        effects = result["effects"]

                        # Mark status as pending
                        session_data["patient_record_status"] = PATIENT_RECORD_STATUS_PENDING
                        update_session(session_id, session_data)

                        response_to_patient += "\n\nYour patient record is being created. Someone from our team will be in touch with you soon."
                        log.info(f"Patient creation queued for session {session_id}")
                    else:
                        log.error(f"Failed to create patient: {result.get('error')}")
                        response_to_patient += "\n\nWe've received all your information and will process it shortly."
                elif patient_status == PATIENT_RECORD_STATUS_PENDING:
                    log.info(f"Patient creation pending for session {session_id}")
                    response_to_patient += "\n\nYour patient record is being created. Someone from our team will be in touch with you soon."
                elif patient_status == PATIENT_RECORD_STATUS_COMPLETE:
                    log.info(f"Patient record already complete for session {session_id}")
                    # Future: Include MRN or patient info if available

                # Mark session as completed
                complete_session(session_id)
            elif all_fields_present and not phone_verified:
                log.warning(
                    f"LLM indicated all_information_collected=true but phone not verified for session {session_id}"
                )
            else:
                log.warning(
                    f"LLM indicated all_information_collected=true but missing fields for session {session_id}"
                )

        return {
            "response": response_to_patient,
            "effects": effects
        }

    except Exception as e:
        log.error(f"Exception processing message for session {session_id}: {str(e)}")
        return {
            "response": "I apologize, but I encountered an error. Please try again.",
            "effects": []
        }


def get_initial_greeting() -> str:
    """
    Get the initial greeting message for a new patient.
    Personalized based on agent name and personality.

    Returns:
        Initial greeting message
    """
    # Generate greeting based on personality
    if AGENT_PERSONALITY == "warm_professional":
        return f"Hello! Welcome to our healthcare intake service. My name is {AGENT_NAME}, and I'm here to help you get started with scheduling your visit. To begin, may I have your name?"
    elif AGENT_PERSONALITY == "efficient_direct":
        return f"Hello. I'm {AGENT_NAME}, your intake assistant. I'll need to collect some information to get you scheduled. Let's start with your name."
    elif AGENT_PERSONALITY == "empathetic_supportive":
        return f"Hello and welcome! I'm {AGENT_NAME}, and I'm here to support you through the intake process. I know visiting a new healthcare provider can feel overwhelming, so I'll guide you through this step by step. To start, could you please share your name with me?"
    elif AGENT_PERSONALITY == "casual_friendly":
        return f"Hey there! I'm {AGENT_NAME}. Thanks for reaching out! I'm here to help get you all set up for your visit. Let's start easy - what's your name?"
    elif AGENT_PERSONALITY == "formal_courteous":
        return f"Good day. I am {AGENT_NAME}, your medical intake coordinator. I will be assisting you with your registration today. May I please have your full name?"
    else:
        # Default fallback
        return f"Hello! I'm {AGENT_NAME}, and I'm here to help you with your healthcare intake. To begin, may I have your name?"
