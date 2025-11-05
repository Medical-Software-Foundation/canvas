from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from logger import log

from intake_agent.agent import get_initial_greeting, process_patient_message
from intake_agent.api.auth import generate_signature, verify_signature
from intake_agent.api.session import add_message, create_session, get_session


class IntakeAPI(SimpleAPI):
    """
    Patient intake API handler providing an unauthenticated chat interface
    for prospective new patients.
    """

    PREFIX = "/intake"

    # Paths that don't require authentication
    UNAUTHENTICATED_PATHS = {
        "/",           # GET / - Serve HTML
        "/session",    # POST /session - Create session (returns signature)
    }

    def authenticate(self, credentials: Credentials) -> bool:  # noqa: ARG002, pylint: disable=unused-argument
        """
        Centralized authentication using HMAC signature verification.

        Unauthenticated paths (HTML page, session creation) are exempt.
        All other paths require a valid signature in the Authorization header.

        Returns:
            True if request is authenticated or exempt, False otherwise
        """
        path = self.request.path

        # Remove PREFIX from path for comparison
        if path.startswith(self.PREFIX):
            path = path[len(self.PREFIX):]

        # Allow unauthenticated access to exempt paths
        if path in self.UNAUTHENTICATED_PATHS:
            log.info(f"Allowing unauthenticated access to: {path}")
            return True

        # For all other paths, verify signature
        log.info(f"Verifying signature for authenticated path: {path}")

        # Get secret key
        secret_key = self.secrets.get("PLUGIN_SECRET_KEY", "")
        if not secret_key:
            log.error("PLUGIN_SECRET_KEY not configured")
            return False

        # Get signature from Authorization header
        auth_header = self.request.headers.get("Authorization", "")
        if not auth_header.startswith("Signature "):
            log.warning("Missing or invalid Authorization header")
            return False

        provided_signature = auth_header.replace("Signature ", "", 1)

        # Extract session_id from path params
        session_id = self.request.path_params.get("session_id")
        if not session_id:
            log.warning("Could not extract session_id from path params")
            return False

        log.info(f"Authenticating session: {session_id[:8]}...")

        # Verify the signature
        is_valid = verify_signature(session_id, provided_signature, secret_key)

        if not is_valid:
            log.warning(f"Authentication failed for session: {session_id[:8]}...")
        else:
            log.info(f"Authentication successful for session: {session_id[:8]}...")

        return is_valid

    @api.get("/")
    def get_intake_form(self) -> list[HTMLResponse | Effect]:
        """
        Serve the patient intake chat interface.

        Endpoint: GET /plugin-io/api/intake_agent/intake/
        """
        log.info("Serving patient intake chat interface")

        html_content = render_to_string("templates/intake.html", {})

        return [HTMLResponse(html_content)]

    @api.post("/session")
    def create_session(self) -> list[JSONResponse | Effect]:
        """
        Create a new chat session and return the session ID with signature.

        Endpoint: POST /plugin-io/api/intake_agent/intake/session

        Returns:
            JSON response with session_id and signature
        """
        log.info("Creating new chat session")

        session_data = create_session()
        session_id = session_data["session_id"]

        # Generate signature for the session
        secret_key = self.secrets.get("PLUGIN_SECRET_KEY", "")
        if not secret_key:
            log.error("PLUGIN_SECRET_KEY not configured")
            return [
                JSONResponse(
                    {"error": "Server configuration error"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]

        signature = generate_signature(session_id, secret_key)

        return [
            JSONResponse(
                {
                    "session_id": session_id,
                    "signature": signature,
                    "status": "created"
                },
                status_code=HTTPStatus.CREATED
            )
        ]

    @api.get("/session/<session_id>")
    def get_session_data(self) -> list[JSONResponse | Effect]:
        """
        Retrieve session data (requires authentication).

        Endpoint: GET /plugin-io/api/intake_agent/intake/session/<session_id>
        Headers: Authorization: Signature <signature>

        Returns:
            JSON response with session data

        Note: Authentication is handled by the authenticate() method
        """
        session_id = self.request.path_params.get("session_id")
        log.info(f"Retrieving session data for: {session_id}")

        session_data = get_session(session_id)

        if not session_data:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND
                )
            ]

        return [
            JSONResponse(session_data, status_code=HTTPStatus.OK)
        ]

    @api.post("/message/<session_id>")
    def handle_message(self) -> list[JSONResponse | Effect]:
        """
        Handle a user message and broadcast agent response (requires authentication).

        Endpoint: POST /plugin-io/api/intake_agent/intake/message/<session_id>
        Headers: Authorization: Signature <signature>

        Request body:
            {
                "message": str
            }

        Returns:
            JSON response acknowledging receipt

        Note: Authentication is handled by the authenticate() method
        """
        log.info("Processing user message")

        session_id = self.request.path_params.get("session_id")

        body = self.request.json()
        user_message = body.get("message")

        if not user_message:
            return [
                JSONResponse(
                    {"error": "Missing message"},
                    status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        # Validate session exists
        session_data = get_session(session_id)
        if not session_data:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND
                )
            ]

        # Check if this is the initial start message
        effects = []
        if user_message == "__START__":
            # Don't save the start message, just respond with greeting
            agent_response = get_initial_greeting()
        else:
            # Add user message to session
            add_message(session_id, "user", user_message)

            # Get LLM API key
            llm_key = self.secrets.get("LLM_KEY", "")
            if not llm_key:
                log.error("LLM_KEY not configured")
                agent_response = "I apologize, but I'm experiencing a configuration issue. Please try again later."
            else:
                # Get Twilio credentials for phone verification
                twilio_account_sid = self.secrets.get("TWILIO_ACCOUNT_SID", "")
                twilio_auth_token = self.secrets.get("TWILIO_AUTH_TOKEN", "")
                twilio_phone_number = self.secrets.get("TWILIO_PHONE_NUMBER", "")

                # Process message with LLM and generate response
                result = process_patient_message(
                    session_id,
                    user_message,
                    llm_key,
                    twilio_account_sid,
                    twilio_auth_token,
                    twilio_phone_number
                )
                agent_response = result["response"]
                effects = result["effects"]

        # Add agent response to session
        add_message(session_id, "agent", agent_response)

        # Return the agent response and any effects
        return [
            JSONResponse(
                {
                    "status": "success",
                    "session_id": session_id,
                    "agent_response": agent_response
                },
                status_code=HTTPStatus.OK
            )
        ] + effects
