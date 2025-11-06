# Intake Agent

An AI-powered conversational agent for patient intake, registration, and appointment scheduling.

## Setup

1. Configure required secrets in Canvas:
   - `LLM_KEY` - Anthropic API key for Claude
   - `PLUGIN_SECRET_KEY` - Secret key for session signature verification
   - `INTAKE_SCOPE_OF_CARE` - Description of your practice's scope of care
   - `INTAKE_FALLBACK_PHONE_NUMBER` - Fallback phone number for patients to call
   - `POLICIES_URL` - URL to your practice's policies and terms
   - `TWILIO_ACCOUNT_SID` - Twilio account SID for SMS
   - `TWILIO_AUTH_TOKEN` - Twilio auth token
   - `TWILIO_PHONE_NUMBER` - Twilio phone number for sending SMS

2. Configure agent personality in `config.py`:
   - Choose from: warm_professional, efficient_direct, empathetic_supportive, casual_friendly, or formal_courteous
   - Set agent name

3. Install the plugin using the Canvas CLI

4. Access the intake form at: `/plugin-io/api/intake_agent/intake/`

## Functionality

The intake agent guides patients through a structured conversation to collect:

- Health concerns and reason for visit
- Available appointment times and preferred appointment
- Phone number verification via SMS
- Personal information (name, date of birth)
- Policy agreement
- Appointment confirmation via SMS

The agent uses an extensible pattern with prewrite/postread hooks that execute before asking questions and after extracting data. This allows customization of the conversation flow, data validation, and side effects like SMS sending or patient creation.

Session state is managed in Redis cache with HMAC signature-based authentication. Patient records are created automatically when sufficient verified data is collected.

## Testing

Run the full test suite:

```bash
uv run pytest
```

Run tests with coverage:

```bash
uv run pytest --cov=intake_agent --cov-report=term-missing
```

Run specific test files:

```bash
uv run pytest tests/test_agent.py -v
uv run pytest tests/api/test_intake.py -v
```

The test suite includes 234 tests covering:
- Agent conversation logic and personality variations
- Session management and serialization
- API endpoints and authentication
- Twilio SMS integration
- LLM providers (Anthropic, OpenAI, Google)
- Toolkit utilities and patient creation
