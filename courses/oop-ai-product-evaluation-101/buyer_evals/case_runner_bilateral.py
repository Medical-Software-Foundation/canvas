#!/usr/bin/env python3
"""
Buyer-Side Bilateral Conversation Runner

This script creates a dynamic conversation with the intake agent using an LLM
to generate patient responses based on case data. Unlike the unilateral runner,
this doesn't use pre-scripted messages - instead, it uses Anthropic's API to
simulate a real patient responding naturally to the agent's questions.

Usage:
    1. Start the intake agent Flask app manually: python intake_agent/app.py
    2. Run this script: python buyer_evals/case_runner_bilateral.py <case_number>
    3. Find the output in: buyer_evals/cases_bilateral/case_{n}_result.json

Examples:
    python buyer_evals/case_runner_bilateral.py 1
    python buyer_evals/case_runner_bilateral.py 2
"""

import sys
import argparse
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import time
from datetime import datetime

# Add parent directory to path to import llms module
sys.path.insert(0, str(Path(__file__).parent.parent))
from llms.llm_anthropic import LlmAnthropic

# Configuration
BASE_URL = "http://127.0.0.1:5000"
MESSAGE_TIMEOUT = 60000  # 60 seconds max wait for agent response
MAX_TURNS = 30  # Maximum number of conversation turns to prevent infinite loops


def load_case(case_path: Path) -> dict:
    """
    Load case file (JSON format) with patient characteristics.

    Returns:
        dict with keys: case_number, case_timestamp, patient_name, patient_dob,
        patient_sex, patient_gender_identity, conditions, medications, allergies,
        goals, concerns, personality
    """
    with open(case_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Validate required fields
    required_fields = [
        'case_number', 'case_timestamp', 'patient_name', 'patient_dob',
        'patient_sex', 'patient_gender_identity', 'conditions', 'medications',
        'allergies', 'goals', 'concerns', 'personality'
    ]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Case file missing required field: {field}")

    return data


def create_patient_prompt(case_data: dict) -> str:
    """
    Create a system prompt for the LLM to roleplay as the patient.
    """
    return f"""You are roleplaying as a patient seeking medical care. You are chatting with an intake agent who is gathering your medical information.

Your character:
- Name: {case_data['patient_name']}
- Date of Birth: {case_data['patient_dob']}
- Sex: {case_data['patient_sex']}
- Gender Identity: {case_data['patient_gender_identity']}
- Conditions: {case_data['conditions']}
- Medications: {case_data['medications']}
- Allergies: {case_data['allergies']}
- Goals: {case_data['goals']}
- Concerns: {case_data['concerns']}
- Personality: {case_data['personality']}

Important instructions:
1. Respond naturally as this patient would, based on their personality
2. Answer the intake agent's questions based on the information above
3. Stay in character and be conversational
4. Don't volunteer all information at once - let the agent guide the conversation
5. If asked about something not covered in your character details, you can improvise minor details or say you don't know
6. Keep responses relatively brief and natural (1-3 sentences typically)
7. Show the personality traits described above in your responses
8. CRITICAL: Do NOT include any narrator commentary, stage directions, or actions in asterisks like "*pauses*", "*sounds uncertain*", "*looks down*", etc. Only provide the actual spoken words the patient would say.
9. If the agent seems to be wrapping up or saying they have everything they need, respond appropriately (e.g., "Okay, thank you" or "Sounds good") to help close the conversation.

Remember: You are seeking care and the agent is trying to help you. Be cooperative but authentic to your character. Only speak actual words - never narrate or describe your actions."""


def generate_patient_response(
    llm: LlmAnthropic,
    case_data: dict,
    last_agent_message: str
) -> str:
    """
    Use LLM to generate a patient response based on the conversation
    history and the last agent message.

    Args:
        llm: Initialized LlmAnthropic instance with conversation history
        case_data: The case data with patient characteristics
        last_agent_message: The most recent message from the agent

    Returns:
        The generated patient response
    """
    # Add the latest agent message to the conversation
    user_prompt = f"The intake agent says: {last_agent_message}\n\nHow do you respond?"

    # Call LLM
    response = llm.chat(user_prompt=user_prompt)

    if not response["success"]:
        raise Exception(f"LLM request failed: {response['error']}")

    return response["content"]


def get_agent_messages(page) -> list[str]:
    """Extract all agent messages from the page."""
    agent_messages = page.locator('.message-agent .message-bubble').all_text_contents()
    return agent_messages


def get_patient_messages(page) -> list[str]:
    """Extract all patient messages from the page."""
    patient_messages = page.locator('.message-patient .message-bubble').all_text_contents()
    return patient_messages


def wait_for_agent_response(page, previous_message_count: int, timeout: int = MESSAGE_TIMEOUT) -> bool:
    """
    Wait for the agent to send a new response message.
    Returns True if response received, False if timeout.
    """
    try:
        # Wait for the message count to increase
        start_time = time.time()
        while time.time() - start_time < timeout / 1000:
            current_messages = get_agent_messages(page)
            if len(current_messages) > previous_message_count:
                # Also wait for typing indicator to disappear
                try:
                    page.wait_for_selector('#typing-indicator', state='hidden', timeout=5000)
                except:
                    pass  # Typing indicator might not appear
                return True
            time.sleep(0.5)

        return False
    except PlaywrightTimeout:
        print("  ⚠️  Warning: Timeout waiting for agent response")
        return False


def send_message(page, message: str) -> bool:
    """
    Send a patient message through the browser interface.
    Returns True if sent successfully.
    """
    try:
        # Find the textarea input
        input_field = page.locator('#message-input')

        # Type the message
        input_field.fill(message)

        # Click the send button
        send_button = page.locator('#send-button')
        send_button.click()

        # Small delay to ensure message is sent
        time.sleep(0.5)

        return True
    except Exception as e:
        print(f"  ❌ Error sending message: {e}")
        return False


def check_conversation_complete(last_agent_message: str, patient_response: str = None) -> bool:
    """
    Check if the conversation appears to be complete based on the agent's message
    and optionally the patient's response.
    """
    message_lower = last_agent_message.lower()

    # Agent completion phrases
    agent_completion_phrases = [
        "thank you for providing",
        "i have everything i need",
        "all set",
        "we're all done",
        "we are all done",
        "completed your intake",
        "finish up here",
        "that's all the information",
        "that completes",
        "we have everything",
        "all the information i need",
        "have a great day",
        "take care",
        "we'll be in touch",
        "someone will contact you",
        "you're all set",
        "thanks for your time",
        "appreciate your time",
    ]

    # Check if agent is signaling completion
    if any(phrase in message_lower for phrase in agent_completion_phrases):
        return True

    # Check if the agent's message doesn't contain a question mark
    # AND doesn't seem to be requesting information
    has_question = '?' in last_agent_message
    requesting_info = any(word in message_lower for word in [
        'what', 'when', 'where', 'who', 'how', 'which', 'can you',
        'could you', 'would you', 'tell me', 'let me know', 'do you'
    ])

    # If no question and not requesting info, might be wrapping up
    if not has_question and not requesting_info and len(last_agent_message.split()) > 10:
        # Likely a closing statement
        return True

    # Check patient response if provided
    if patient_response:
        response_lower = patient_response.lower()
        patient_closing_phrases = [
            "okay, thank you",
            "sounds good",
            "thanks",
            "got it",
            "perfect",
            "great, thanks",
        ]

        # If patient gives a very short closing response
        if any(phrase in response_lower for phrase in patient_closing_phrases):
            if len(patient_response.split()) <= 5:
                return True

    return False


def extract_conversation(page) -> list[dict]:
    """
    Extract the full conversation from the page.

    Returns:
        List of message dictionaries with 'role' and 'content' keys
    """
    conversation = []

    # Get all messages in order (both agent and patient)
    all_messages = page.locator('.message').all()

    for message_elem in all_messages:
        # Determine role based on class
        classes = message_elem.get_attribute('class')
        if 'message-agent' in classes:
            role = 'agent'
        elif 'message-patient' in classes:
            role = 'patient'
        else:
            continue

        # Get message content
        bubble = message_elem.locator('.message-bubble')
        content = bubble.text_content().strip()

        conversation.append({
            'role': role,
            'content': content
        })

    return conversation


def extract_structured_data(page) -> dict:
    """
    Extract the structured medical data that the intake agent populated.

    Returns:
        Dictionary with patient demographics and medical information
    """
    from bs4 import BeautifulSoup
    import re

    # Get the page HTML
    html_content = page.content()
    soup = BeautifulSoup(html_content, 'html.parser')

    data = {
        'patient': {},
        'conditions': [],
        'medications': [],
        'allergies': [],
        'goals': []
    }

    # Extract patient header info
    header = soup.find('div', class_='record-header')
    if header:
        h2 = header.find('h2')
        if h2:
            data['patient']['name'] = h2.get_text(strip=True)

        header_info = header.find('div', class_='record-header-info')
        if header_info:
            info_text = header_info.get_text()
            # Extract DOB, Age, Sex/Gender with more specific patterns
            # DOB should be in format YYYY-MM-DD
            dob_match = re.search(r'DOB:\s*(\d{4}-\d{2}-\d{2})', info_text)
            # Age should be number followed by 'y'
            age_match = re.search(r'Age:\s*(\d+y)', info_text)
            # Sex/Gender should be word|word at the end (avoiding age numbers)
            sex_gender_match = re.search(r'([A-Za-z]+)\|([A-Za-z]+)', info_text)

            if dob_match:
                data['patient']['dob'] = dob_match.group(1)
            if age_match:
                data['patient']['age'] = age_match.group(1)
            if sex_gender_match:
                data['patient']['sex'] = sex_gender_match.group(1)
                data['patient']['gender'] = sex_gender_match.group(2)

    # Extract conditions, medications, allergies, goals
    sections = soup.find_all('div', class_='record-section')
    for section in sections:
        title = section.find('div', class_='section-title')
        if not title:
            continue

        title_text = title.get_text(strip=True)

        if 'Conditions' in title_text:
            for item in section.find_all('div', class_='record-item'):
                condition = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    # Extract name without status badge
                    badge = name_div.find('span', class_='status-badge')
                    if badge:
                        condition['status'] = badge.get_text(strip=True)
                        badge.extract()
                    condition['name'] = name_div.get_text(strip=True)

                # Extract comment/details
                details = item.find_all('div', class_='item-detail')
                if details:
                    condition['details'] = [d.get_text(strip=True) for d in details]

                data['conditions'].append(condition)

        elif 'Medications' in title_text:
            for item in section.find_all('div', class_='record-item'):
                medication = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    medication['name'] = name_div.get_text(strip=True)

                # Extract all details (dose/form, sig, indication)
                details = item.find_all('div', class_='item-detail')
                medication['details'] = []
                for detail in details:
                    text = detail.get_text(strip=True)
                    medication['details'].append(text)

                    # Try to parse specific fields
                    if 'For:' in text:
                        medication['indication'] = text.replace('For:', '').strip()
                    elif re.search(r'\d+\s*mg', text, re.IGNORECASE):
                        medication['dose_form'] = text
                    elif any(word in text.lower() for word in ['daily', 'twice', 'once', 'morning', 'evening']):
                        medication['sig'] = text

                data['medications'].append(medication)

        elif 'Allergies' in title_text:
            for item in section.find_all('div', class_='record-item'):
                allergy = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    allergy['name'] = name_div.get_text(strip=True)

                details = item.find_all('div', class_='item-detail')
                if details:
                    allergy['details'] = [d.get_text(strip=True) for d in details]

                data['allergies'].append(allergy)

        elif 'Goals' in title_text:
            for item in section.find_all('div', class_='record-item'):
                goal = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    goal['name'] = name_div.get_text(strip=True)

                details = item.find_all('div', class_='item-detail')
                if details:
                    goal['details'] = [d.get_text(strip=True) for d in details]

                data['goals'].append(goal)

    return data


def run_bilateral_conversation(
    base_url: str,
    case_data: dict,
    llm: LlmAnthropic,
    max_turns: int = MAX_TURNS
) -> dict:
    """
    Run a bilateral conversation where the LLM generates patient responses.

    Returns:
        dict with 'conversation' (list of messages) and 'metadata'
    """
    print("🎬 Starting bilateral conversation...\n")

    # Initialize LLM with system prompt
    system_prompt = create_patient_prompt(case_data)
    llm.reset_messages()
    llm.add_system_message(system_prompt)

    with sync_playwright() as p:
        # Launch browser (headless=False to see what's happening)
        print("🌐 Launching browser...")
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            # Navigate to new patient intake
            print(f"📍 Navigating to {base_url}/patient/new")
            page.goto(f"{base_url}/patient/new")

            # Wait for the page to load and the greeting to appear
            print("⏳ Waiting for agent greeting...")
            page.wait_for_selector('.message-agent', timeout=30000)
            print("✅ Agent greeting received\n")

            # Conversation loop
            turn = 0
            while turn < max_turns:
                turn += 1

                # Get all current agent messages
                agent_messages = get_agent_messages(page)
                agent_message_count = len(agent_messages)

                if not agent_messages:
                    print("⚠️  No agent messages found")
                    break

                last_agent_message = agent_messages[-1]
                print(f"🤖 [{turn}] Agent: {last_agent_message[:80]}...")

                # Check if conversation seems complete before responding
                if turn > 3 and check_conversation_complete(last_agent_message):
                    print("\n✅ Conversation appears complete (agent indicated completion)")
                    break

                # Generate patient response using LLM
                print("  🧠 Generating patient response...")
                try:
                    patient_response = generate_patient_response(
                        llm,
                        case_data,
                        last_agent_message
                    )

                    # Add assistant response to LLM conversation history
                    llm.add_assistant_message(patient_response)

                    print(f"👤 [{turn}] Patient: {patient_response[:80]}...")

                    # Check if patient+agent exchange indicates completion
                    if turn > 3 and check_conversation_complete(last_agent_message, patient_response):
                        print("\n✅ Conversation complete (closing exchange detected)")
                        # Send the final patient message
                        send_message(page, patient_response)
                        time.sleep(2)  # Wait for it to display
                        break

                    # Send the message
                    if not send_message(page, patient_response):
                        print("  ❌ Failed to send message")
                        break

                    # Wait for agent response
                    print("  ⏳ Waiting for agent response...")
                    if not wait_for_agent_response(page, agent_message_count):
                        print("  ⚠️  No response received, ending conversation")
                        break

                    print()  # Blank line for readability

                    # Brief pause between turns
                    time.sleep(1)

                except Exception as e:
                    print(f"  ❌ Error generating response: {e}")
                    break

            if turn >= max_turns:
                print(f"⚠️  Reached maximum turns ({max_turns}), ending conversation\n")

            print("✅ Conversation complete!")
            print("⏳ Waiting 2 seconds for final updates...\n")
            time.sleep(2)

            # Extract the full conversation
            print("💾 Extracting conversation...")
            conversation = extract_conversation(page)
            print(f"✅ Extracted {len(conversation)} messages")

            # Extract structured data
            print("💾 Extracting structured data...")
            structured_data = extract_structured_data(page)
            print(f"✅ Extracted structured data:")
            print(f"   - Patient: {structured_data['patient'].get('name', 'N/A')}")
            print(f"   - Conditions: {len(structured_data['conditions'])}")
            print(f"   - Medications: {len(structured_data['medications'])}")
            print(f"   - Allergies: {len(structured_data['allergies'])}")
            print(f"   - Goals: {len(structured_data['goals'])}\n")

            # Create result using schema
            metadata = {
                'case_number': case_data['case_number'],
                'case_timestamp': case_data['case_timestamp'],
                'run_timestamp': datetime.now().isoformat(),
                'total_turns': turn,
                'patient_name': case_data['patient_name']
            }

            return create_result_from_schema(conversation, structured_data, metadata)

        except Exception as e:
            print(f"\n❌ Error during conversation: {e}")
            raise
        finally:
            browser.close()


def create_result_from_schema(conversation: list, structured_data: dict, metadata: dict) -> dict:
    """
    Create a result dictionary following the schema defined in _case_result_template.json.

    Args:
        conversation: List of conversation messages with 'role' and 'content'
        structured_data: Dictionary with patient, conditions, medications, allergies, goals
        metadata: Dictionary with case metadata

    Returns:
        Result dictionary following the schema
    """
    # Load the schema template to ensure we follow it
    script_dir = Path(__file__).parent
    template_path = script_dir / "cases_bilateral" / "_case_result_template.json"

    with open(template_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    # Construct result following the schema structure
    result = {
        'conversation': conversation,
        'structured_data_detected': {
            'patient': structured_data.get('patient', {}),
            'conditions': structured_data.get('conditions', []),
            'medications': structured_data.get('medications', []),
            'allergies': structured_data.get('allergies', []),
            'goals': structured_data.get('goals', [])
        },
        'metadata': {
            'case_number': metadata.get('case_number', ''),
            'case_timestamp': metadata.get('case_timestamp', ''),
            'run_timestamp': metadata.get('run_timestamp', ''),
            'total_turns': metadata.get('total_turns', 0),
            'patient_name': metadata.get('patient_name', '')
        }
    }

    return result


def save_result(result: dict, output_path: Path):
    """Save the conversation result to a JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"💾 Result saved to: {output_path}")


def main():
    """Main execution function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Run a bilateral conversation with the intake agent using LLM-generated responses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python evals/buy_side/case_runner_bilateral.py 1    # Run case 1
  python evals/buy_side/case_runner_bilateral.py 2    # Run case 2
        """
    )
    parser.add_argument(
        'case_number',
        type=str,
        help='Case number to run (e.g., 1 for case_001.json, or 001)'
    )
    args = parser.parse_args()

    # Normalize case number to 3 digits
    case_num = args.case_number.zfill(3)

    print("=" * 70)
    print(f"  Buyer-Side Bilateral Conversation - Case {case_num}")
    print("=" * 70)
    print()

    # Construct file paths
    script_dir = Path(__file__).parent
    cases_dir = script_dir / "cases_bilateral"
    case_file = cases_dir / f"case_{case_num}.json"

    # Check that case file exists
    if not case_file.exists():
        print(f"❌ Error: Case file not found: {case_file}")
        print(f"   Please create: cases_bilateral/case_{case_num}.json")
        print()
        print("Available cases:")
        for case_path in sorted(cases_dir.glob("case_*.json")):
            if not case_path.name.startswith("_"):
                print(f"  - {case_path.stem}")
        sys.exit(1)

    # Load case data
    print(f"📄 Loading case: {case_file.name}")
    case_data = load_case(case_file)

    print(f"✅ Patient: {case_data['patient_name']}")
    print(f"   Personality: {case_data['personality']}")
    print(f"   Primary concerns: {case_data['concerns'][:100]}...\n")

    # Initialize LLM
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ Error: ANTHROPIC_API_KEY environment variable not set")
        print("   Please set it with: export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    llm = LlmAnthropic(api_key=api_key, model='claude-sonnet-4-5-20250929')
    llm.max_tokens = 500  # Keep responses concise
    print("✅ LLM initialized\n")

    # Check that the app is running
    print(f"🔍 Checking if intake app is running at {BASE_URL}...")
    try:
        import requests
        response = requests.get(BASE_URL, timeout=5)
        print(f"✅ App is running (status: {response.status_code})\n")
    except Exception as e:
        print(f"❌ Error: Cannot connect to {BASE_URL}")
        print("   Please start the intake app first:")
        print("   > python intake_agent/app.py")
        sys.exit(1)

    # Run the bilateral conversation
    try:
        result = run_bilateral_conversation(BASE_URL, case_data, llm)

        # Save the result
        output_file = cases_dir / f"case_{case_num}_result.json"
        save_result(result, output_file)

        print("\n" + "=" * 70)
        print("✅ SUCCESS!")
        print("=" * 70)
        print(f"\nConversation summary:")
        print(f"  • Patient: {result['metadata']['patient_name']}")
        print(f"  • Total messages: {len(result['conversation'])}")
        print(f"  • Total turns: {result['metadata']['total_turns']}")
        print(f"  • Output file: {output_file.relative_to(script_dir.parent.parent)}")
        print(f"  • Schema: _case_result_template.json")

        print("\nYou can now:")
        print(f"  1. Review the conversation in: {output_file.name}")
        print(f"  2. Analyze the results for quality and completeness")
        print(f"  3. Compare with other runs or cases")
        print(f"  4. Reference the schema in: _case_result_template.json")

    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ FAILED")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
