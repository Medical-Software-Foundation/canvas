from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import Patient as PatientEffect, PatientContactPoint
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.common import ContactPointSystem, ContactPointUse
from canvas_sdk.v1.data.patient import Patient
from logger import log


class IntakeAPI(SimpleAPI):
    """
    Patient intake API handler providing an unauthenticated public-facing
    intake form for prospective new patients.
    """

    PREFIX = "/intake"

    def authenticate(self, credentials: Credentials) -> bool:
        """
        Allow unauthenticated access to this endpoint.
        Always returns True to allow public access.
        """
        return True

    @api.get("/")
    def get_intake_form(self) -> list[HTMLResponse | Effect]:
        """
        Serve the patient intake form page.

        Endpoint: GET /plugin-io/api/intake_agent/intake/
        """
        log.info("Serving patient intake form")

        # Render the template using Canvas SDK's render_to_string
        # Pass empty context since our template is static HTML
        html_content = render_to_string("templates/intake.html", {})

        return [HTMLResponse(html_content)]

    @api.post("/")
    def submit_intake_form(self) -> list[Response | Effect | HTMLResponse]:
        """
        Handle intake form submission and create a new patient.
        If a patient with matching email or phone exists, show the form again with a banner.

        Endpoint: POST /plugin-io/api/intake_agent/intake
        """
        log.info("Processing intake form submission")

        # Parse form data
        form_data = self.request.form_data()
        first_name = str(form_data.get("firstName", ""))
        last_name = str(form_data.get("lastName", ""))
        email = str(form_data.get("email", ""))
        phone = str(form_data.get("phone", ""))

        # Check for existing patients by email or phone
        existing_patient = None

        if email:
            # Query for patients with this email
            patients_with_email = Patient.objects.filter(
                telecom__system=ContactPointSystem.EMAIL,
                telecom__value=email
            )
            if patients_with_email.exists():
                existing_patient = patients_with_email.first()
                log.info(f"Found existing patient with email {email}: {existing_patient.id}")

        if not existing_patient and phone:
            # Clean phone number for comparison (remove formatting)
            # Use string comprehension to keep only digits
            cleaned_phone = "".join(c for c in phone if c.isdigit())

            # Query for patients with this phone number (last 10 digits)
            if len(cleaned_phone) >= 10:
                phone_query = cleaned_phone[-10:]
                patients_with_phone = Patient.objects.filter(
                    telecom__system=ContactPointSystem.PHONE,
                    telecom__value__contains=phone_query
                )
                if patients_with_phone.exists():
                    existing_patient = patients_with_phone.first()
                    log.info(f"Found existing patient with phone {phone}: {existing_patient.id}")

        # If existing patient found, show form again with banner
        if existing_patient:
            html_content = render_to_string("templates/intake.html", {
                "banner_message": "A patient with this contact information is already on record. Please contact us if you need assistance.",
                "banner_type": "warning"
            })
            return [HTMLResponse(html_content)]

        # No existing patient - create new one
        # Build contact points list
        contact_points = []
        if email:
            contact_points.append(
                PatientContactPoint(
                    system=ContactPointSystem.EMAIL,
                    value=email,
                    use=ContactPointUse.HOME,
                    rank=1,
                    has_consent=True
                )
            )
        if phone:
            contact_points.append(
                PatientContactPoint(
                    system=ContactPointSystem.PHONE,
                    value=phone,
                    use=ContactPointUse.MOBILE,
                    rank=2,
                    has_consent=True
                )
            )

        # Create the patient effect
        patient_effect = PatientEffect(
            first_name=first_name,
            last_name=last_name,
            contact_points=contact_points
        )

        # Create the patient and get the new patient ID from the effect
        create_effect = patient_effect.create()

        log.info(f"Creating new patient: {first_name} {last_name}")

        # Return a 303 See Other redirect to the chat page
        # We'll use a placeholder ID for now - in production this would come from the effect result
        redirect_url = f"/plugin-io/api/intake_agent/chat/NEW_PATIENT"

        return [
            create_effect,
            Response(
                b"",
                status_code=HTTPStatus.SEE_OTHER,
                headers={"Location": redirect_url}
            )
        ]
