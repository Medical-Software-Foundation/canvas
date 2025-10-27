"""
Patient simulator using Playwright to interact with the intake agent UI.

This simulates a real patient using the web interface, completely decoupled
from the internal implementation.
"""

import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# Add parent directory to path for LLM imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from llms.llm_anthropic import LlmAnthropic


class PatientSimulator:
    """
    Simulates a patient interacting with the intake agent through the browser UI.
    Uses Playwright to interact with the actual web interface like a human would.
    """

    def __init__(self, persona: dict, api_key: str, headless: bool = False):
        """
        Initialize patient simulator.

        Args:
            persona: Dictionary with patient information (ground truth)
            api_key: Anthropic API key for generating responses
            headless: Whether to run browser in headless mode
        """
        self.persona = persona
        self.llm = LlmAnthropic(api_key=api_key, model='claude-sonnet-4-5-20250929')
        self.headless = headless
        self.disclosed_info = set()  # Track what info has been revealed
        self.conversation_history = []

    def _get_patient_context(self) -> str:
        """Build context string about the patient for LLM."""
        context_parts = [
            f"You are simulating a patient named {self.persona.get('first_name', 'Unknown')} {self.persona.get('last_name', '')}.",
            f"Date of birth: {self.persona.get('date_of_birth', 'Unknown')}",
            f"Sex: {self.persona.get('sex', 'Unknown')}",
            f"Gender: {self.persona.get('gender', 'Unknown')}",
        ]

        if self.persona.get('current_health_concerns'):
            context_parts.append(f"Current health concerns: {self.persona['current_health_concerns']}")

        if self.persona.get('conditions'):
            context_parts.append(f"Medical conditions: {', '.join([c['name'] for c in self.persona['conditions']])}")

        if self.persona.get('medications'):
            meds = []
            for med in self.persona['medications']:
                med_str = med['name']
                if med.get('dose'):
                    med_str += f" {med['dose']}"
                if med.get('sig'):
                    med_str += f", {med['sig']}"
                meds.append(med_str)
            context_parts.append(f"Current medications: {', '.join(meds)}")

        if self.persona.get('allergies'):
            context_parts.append(f"Allergies: {', '.join([a['name'] for a in self.persona['allergies']])}")

        if self.persona.get('goals'):
            context_parts.append(f"Health goals: {', '.join([g['name'] for g in self.persona['goals']])}")

        return "\n".join(context_parts)

    def _generate_response(self, agent_message: str) -> str:
        """
        Generate patient response to agent's question using LLM.

        Args:
            agent_message: The message from the intake agent

        Returns:
            Patient's response
        """
        system_prompt = f"""You are roleplaying as a patient in a medical intake conversation.

{self._get_patient_context()}

IMPORTANT INSTRUCTIONS:
- Respond naturally and conversationally as this patient would
- Answer the agent's questions truthfully based on the patient information above
- Don't volunteer all information at once - answer what's asked
- Be realistic - patients sometimes forget details or need prompting
- Keep responses concise and natural
- If asked about something not in your patient info, say you don't have that condition/medication/etc.
"""

        # Build conversation history
        conversation_text = ""
        for msg in self.conversation_history:
            conversation_text += f"{msg['role'].upper()}: {msg['content']}\n\n"
        conversation_text += f"AGENT: {agent_message}\n\n"

        user_prompt = f"""Here is the conversation so far:

{conversation_text}

Respond as the patient. Keep it natural and conversational."""

        result = self.llm.chat(system_prompt=system_prompt, user_prompt=user_prompt)

        if result['success']:
            response = result['content']
            # Track conversation
            self.conversation_history.append({'role': 'agent', 'content': agent_message})
            self.conversation_history.append({'role': 'patient', 'content': response})
            return response
        else:
            return "I'm not sure what you mean."

    def _wait_for_agent_response(self, page: Page, previous_count: int, timeout: int = 30000) -> str:
        """
        Wait for agent to respond and return the NEW message.

        Args:
            page: Playwright page object
            previous_count: Number of agent messages before sending
            timeout: Timeout in milliseconds

        Returns:
            Agent's message text
        """
        # Wait for a new agent message to appear (count should increase)
        start_time = time.time()
        while time.time() - start_time < timeout / 1000:
            agent_messages = page.query_selector_all('.message-agent .message-bubble')
            if len(agent_messages) > previous_count:
                # New message appeared, return it
                return agent_messages[-1].text_content()
            time.sleep(0.1)

        # Timeout - return last message anyway
        agent_messages = page.query_selector_all('.message-agent .message-bubble')
        if agent_messages:
            return agent_messages[-1].text_content()
        return ""

    def run_conversation(self, base_url: str = "http://localhost:5000", max_turns: int = 20):
        """
        Run a simulated patient conversation.

        Args:
            base_url: Base URL of the application
            max_turns: Maximum number of conversation turns
        """
        with sync_playwright() as p:
            # Launch browser
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()

            try:
                # Navigate to home page
                print(f"Opening {base_url}")
                page.goto(base_url)

                # Click "Intake New Patient" button
                print("Creating new patient...")
                page.click('text=Intake New Patient')

                # Wait for patient page to load
                page.wait_for_selector('#message-input')
                print("Patient page loaded")

                # Wait for initial greeting from agent
                print("Waiting for agent greeting...")
                time.sleep(2)  # Give it time to generate greeting

                # Count messages before waiting
                agent_message_count = 0
                agent_greeting = self._wait_for_agent_response(page, previous_count=agent_message_count, timeout=30000)
                agent_message_count += 1
                print(f"\nAGENT: {agent_greeting}")

                # Conversation loop
                for turn in range(max_turns):
                    # Generate patient response
                    patient_response = self._generate_response(agent_greeting)
                    print(f"PATIENT: {patient_response}")

                    # Type response in input field
                    page.fill('#message-input', patient_response)

                    # Click send button
                    page.click('text=Send')

                    # Small delay to let message appear
                    time.sleep(0.5)

                    # Wait for agent response (track count to detect new messages)
                    print("Waiting for agent response...")
                    agent_greeting = self._wait_for_agent_response(page, previous_count=agent_message_count, timeout=30000)
                    agent_message_count += 1
                    print(f"\nAGENT: {agent_greeting}")

                    # Check if conversation seems complete (look for closing phrases)
                    lower_message = agent_greeting.lower()
                    completion_phrases = [
                        'thank you for',
                        'all set',
                        'that completes',
                        'we have everything',
                        'intake is complete',
                        'gathered all the information',
                        'have all the information we need'
                    ]
                    if any(phrase in lower_message for phrase in completion_phrases):
                        print("\nConversation appears complete!")
                        break

                print(f"\nConversation ended after {turn + 1} turns")

                # Keep browser open for inspection
                if not self.headless:
                    print("\nBrowser window will stay open for 10 seconds for inspection...")
                    time.sleep(10)

            finally:
                browser.close()


if __name__ == "__main__":
    import os

    # Example persona
    persona = {
        "first_name": "John",
        "last_name": "Smith",
        "date_of_birth": "1985-06-15",
        "sex": "male",
        "gender": "male",
        "current_health_concerns": "High blood pressure and occasional chest pain",
        "conditions": [
            {"name": "Hypertension", "status": "stable", "comment": "Diagnosed 2 years ago"},
            {"name": "Type 2 Diabetes", "status": "improving", "comment": "Managing with diet and medication"}
        ],
        "medications": [
            {"name": "Lisinopril", "dose": "10mg", "form": "tablet", "sig": "once daily", "indications": "blood pressure"},
            {"name": "Metformin", "dose": "500mg", "form": "tablet", "sig": "twice daily with meals", "indications": "diabetes"}
        ],
        "allergies": [
            {"name": "Penicillin", "comment": "causes rash"}
        ],
        "goals": [
            {"name": "Lose weight", "comment": "Want to lose 20 pounds in 6 months"},
            {"name": "Reduce blood pressure medication", "comment": "Hope to manage through lifestyle changes"}
        ]
    }

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    simulator = PatientSimulator(persona=persona, api_key=api_key, headless=False)
    simulator.run_conversation()
