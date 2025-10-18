"""
Parser for extracting structured medical intake data from conversations.
"""

import json
import os
import sys
from pathlib import Path

# Add parent directory to path for LLM imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from llm_anthropic import LlmAnthropic

# Import configuration
import config


def _get_verbosity_instruction() -> str:
    """Get verbosity instruction based on config setting."""
    return config.VERBOSITY_MAP.get(config.VERBOSITY, config.VERBOSITY_MAP[3])


def _get_personality_instruction() -> str:
    """Get personality instruction based on config setting."""
    personality = config.PERSONALITIES.get(config.PERSONALITY)
    if personality:
        return personality['traits']
    # Default to friendly if personality not found
    return config.PERSONALITIES['friendly']['traits']


def extract_intake_data(conversation_history: list[dict]) -> dict:
    """
    Extract structured medical intake data from conversation history.

    Args:
        conversation_history: List of message dictionaries with 'participant' and 'content'

    Returns:
        Dictionary with extracted data including:
        - patient_updates: Demographics to update (first_name, last_name, dob, sex, gender, current_health_concerns)
        - conditions: List of conditions with name, status, comment
        - medications: List of medications with name, dose, form, sig, indications
        - allergies: List of allergies with name, comment
        - goals: List of goals with name, comment
    """
    # Format conversation
    conversation_text = ""
    for msg in conversation_history:
        speaker = msg['participant'].upper()
        conversation_text += f"{speaker}: {msg['content']}\n\n"

    system_prompt = """You are a medical data extraction assistant. Extract structured information from patient intake conversations.

Your job is to identify and extract:
- Patient demographics (first_name, last_name, date_of_birth in YYYY-MM-DD format, sex, gender, current_health_concerns)
- Medical conditions (name, status: improving/stable/deteriorating, comment)
- Medications (name, dose, form, sig/instructions, indications/what it's for)
- Allergies (allergen name, reaction details/comment)
- Health goals (goal name, detailed comment)

CRITICAL RULES TO PREVENT DUPLICATES:
- Only extract NEW information from the MOST RECENT patient message
- Do NOT re-extract information that was mentioned earlier in the conversation
- Only extract information that was EXPLICITLY stated in the latest exchange
- Do NOT infer or make up information
- If the patient mentions something vaguely (e.g., "blood pressure medication"), do NOT extract it until they provide the specific name
- For medications: extract name, dose, form (tablet/capsule/liquid), how they take it (sig), and what it's for (indications)
- For conditions: include status if mentioned (improving/stable/deteriorating)
- If no NEW extractable information in the latest message, return empty arrays

Respond with valid JSON only."""

    user_prompt = f"""Extract ONLY NEW medical intake information from the MOST RECENT patient message in this conversation:

{conversation_text}

Respond with this exact JSON schema:
```json
{{
  "patient_updates": {{
    "first_name": "string or null",
    "last_name": "string or null",
    "date_of_birth": "YYYY-MM-DD or null",
    "sex": "string or null",
    "gender": "string or null",
    "current_health_concerns": "string or null"
  }},
  "conditions": [
    {{
      "name": "condition name",
      "status": "improving/stable/deteriorating or null",
      "comment": "additional details or null"
    }}
  ],
  "medications": [
    {{
      "name": "medication name",
      "dose": "dose with unit",
      "form": "tablet/capsule/liquid",
      "sig": "how to take it",
      "indications": "what it's for"
    }}
  ],
  "allergies": [
    {{
      "name": "allergen name",
      "comment": "reaction details"
    }}
  ],
  "goals": [
    {{
      "name": "goal title",
      "comment": "detailed description"
    }}
  ]
}}
```

Only include NEW items that were EXPLICITLY mentioned in the most recent patient message. Use empty arrays if nothing NEW to extract."""

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return {
            "patient_updates": {},
            "conditions": [],
            "medications": [],
            "allergies": [],
            "goals": []
        }

    try:
        llm = LlmAnthropic(api_key=api_key, model=config.MODEL)
        result = llm.chat_with_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_retries=3
        )

        if result['success']:
            data = result['data']

            # Clean up patient_updates - remove nulls
            if 'patient_updates' in data:
                data['patient_updates'] = {k: v for k, v in data['patient_updates'].items() if v is not None}

            return data
        else:
            print(f"Error extracting data: {result['error']}")
            return {
                "patient_updates": {},
                "conditions": [],
                "medications": [],
                "allergies": [],
                "goals": []
            }

    except Exception as e:
        print(f"Exception in extract_intake_data: {e}")
        return {
            "patient_updates": {},
            "conditions": [],
            "medications": [],
            "allergies": [],
            "goals": []
        }


def generate_greeting() -> str:
    """
    Generate an initial greeting message for a new patient.

    Returns:
        Greeting message string
    """
    verbosity_instruction = _get_verbosity_instruction()
    personality_instruction = _get_personality_instruction()

    system_prompt = f"""You are {config.AGENT_NAME}, an AI intake agent for EZGrow, a longevity medical practice. Your goal is to gather complete medical intake information from the patient through natural conversation.

You need to collect:
- Demographics: full name, date of birth, sex, gender
- Current health concerns
- Medical conditions (with status: improving/stable/deteriorating if applicable)
- Current medications (name, dose, form, instructions, what it's for)
- Allergies (allergen name and reaction details)
- Health goals

This is your first message to the patient.

PERSONALITY: {personality_instruction}

COMMUNICATION STYLE: {verbosity_instruction}"""

    user_prompt = """Generate a warm, professional greeting to start the patient intake conversation. Introduce yourself and explain what information you'll be collecting during this intake."""

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return f"Hello! I'm {config.AGENT_NAME}. I'll be helping you complete your medical intake today. Let's start with your name - what should I call you?"

    try:
        llm = LlmAnthropic(api_key=api_key, model=config.MODEL)
        result = llm.chat(system_prompt=system_prompt, user_prompt=user_prompt)

        if result['success']:
            return result['content']
        else:
            return f"Hello! I'm {config.AGENT_NAME}. I'll be helping you complete your medical intake today. Let's start with your name - what should I call you?"

    except Exception as e:
        print(f"Error generating greeting: {e}")
        return f"Hello! I'm {config.AGENT_NAME}. I'll be helping you complete your medical intake today. Let's start with your name - what should I call you?"


def generate_response(conversation_history: list[dict]) -> str:
    """
    Generate conversational response from agent.

    Args:
        conversation_history: List of message dictionaries

    Returns:
        Agent's response string
    """
    # Format conversation
    conversation_text = ""
    for msg in conversation_history:
        speaker = msg['participant'].upper()
        conversation_text += f"{speaker}: {msg['content']}\n\n"

    verbosity_instruction = _get_verbosity_instruction()
    personality_instruction = _get_personality_instruction()

    system_prompt = f"""You are {config.AGENT_NAME}, an AI intake agent for EZGrow, a longevity medical practice. Your goal is to gather complete medical intake information from the patient through natural conversation.

You need to collect:
- Demographics: full name, date of birth, sex, gender
- Current health concerns
- Medical conditions (with status: improving/stable/deteriorating if applicable)
- Current medications (name, dose, form, instructions, what it's for)
- Allergies (allergen name and reaction details)
- Health goals

Ask follow-up questions to get complete information. When the patient provides partial information (like "blood pressure medication"), ask for specifics (the actual medication name, dose, etc.).

When you have gathered information, confirm it with the patient before considering it complete.

PERSONALITY: {personality_instruction}

COMMUNICATION STYLE: {verbosity_instruction}"""

    user_prompt = f"""Here is the conversation so far:

{conversation_text}

Respond as the agent. Keep your response conversational and focused on gathering the necessary intake information."""

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return "I apologize, but I'm having technical difficulties. Please try again later."

    try:
        llm = LlmAnthropic(api_key=api_key, model=config.MODEL)
        result = llm.chat(system_prompt=system_prompt, user_prompt=user_prompt)

        if result['success']:
            return result['content']
        else:
            return "I apologize, but I'm having trouble processing your message. Could you please rephrase?"

    except Exception as e:
        print(f"Error generating response: {e}")
        return "I apologize, but I encountered an error. Please try again."
