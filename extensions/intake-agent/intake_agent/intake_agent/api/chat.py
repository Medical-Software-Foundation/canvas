from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.patient import Patient
from logger import log


class ChatAPI(SimpleAPI):
    """
    Chat interface for newly registered patients.
    """

    PREFIX = "/chat"

    def authenticate(self, credentials: Credentials) -> bool:
        """
        Allow unauthenticated access to this endpoint.
        Always returns True to allow public access.
        """
        return True

    @api.get("/<patient_id>")
    def get_chat(self) -> list[HTMLResponse | Effect]:
        """
        Serve the chat page for a specific patient.

        Endpoint: GET /plugin-io/api/intake_agent/chat/<patient_id>
        """
        # Get the patient_id from path parameters
        patient_id = self.request.path_params.get("patient_id")

        log.info(f"Loading chat page for patient: {patient_id}")

        try:
            # Fetch the patient data using Patient.objects.get
            patient = Patient.objects.get(id=patient_id)

            # Render the template with patient context
            html_content = render_to_string("templates/chat.html", {
                "patient": patient
            })

            return [HTMLResponse(html_content)]

        except Exception as e:
            log.error(f"Error loading patient {patient_id}: {e}")

            # Return a simple error page
            error_html = f"""
            <!DOCTYPE html>
            <html>
            <head><title>Error</title></head>
            <body>
                <h1>Patient Not Found</h1>
                <p>Unable to load patient with ID: {patient_id}</p>
                <p>Error: {e}</p>
            </body>
            </html>
            """
            return [HTMLResponse(error_html)]
