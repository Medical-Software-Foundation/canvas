from datetime import datetime, timedelta
from logger import log
import random

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import Patient, PatientContactPoint, PatientMetadata
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.common import ContactPointSystem, ContactPointUse

from intake_agent.api.session import IntakeSession, ProposedAppointment
from intake_agent.twilio_client import TwilioClient


class Toolkit:

    @classmethod
    def generate_verification_code(cls) -> str:
        """
        Generate a random 6-digit verification code.

        Returns:
            6-digit string code
        """
        return f"{random.randint(0, 999999):06d}"

    @classmethod
    def send_verification_code(cls, phone: str, code: str, twilio_account_sid: str, twilio_auth_token: str, twilio_phone_number: str) -> dict:
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
        client = TwilioClient(account_sid=twilio_account_sid, auth_token=twilio_auth_token)

        message_body = f"Your verification code is: {code}"

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

    @classmethod
    def send_appointment_confirmation_sms(
        cls,
        phone: str,
        appointment_time: str,
        reason: str,
        mrn: str,
        twilio_account_sid: str,
        twilio_auth_token: str,
        twilio_phone_number: str
    ) -> dict:
        """
        Send appointment confirmation via SMS with appointment details and MRN.

        Args:
            phone: Patient's phone number
            appointment_time: ISO datetime string for appointment
            reason: Reason for visit
            mrn: Medical record number
            twilio_account_sid: Twilio Account SID
            twilio_auth_token: Twilio Auth Token
            twilio_phone_number: Twilio phone number to send from

        Returns:
            Dictionary with:
                - success: bool
                - error: str (if failed)
        """
        # Parse and format appointment time
        apt_dt = datetime.fromisoformat(appointment_time)
        formatted_time = apt_dt.strftime("%A, %B %d at %I:%M %p")

        client = TwilioClient(account_sid=twilio_account_sid, auth_token=twilio_auth_token)

        message_body = f"""Your appointment is confirmed!

Date & Time: {formatted_time}
Reason: {reason}
Medical Record Number (MRN): {mrn}

Someone from our team will reach out soon. Thank you!"""

        result = client.send_sms(
            to=phone,
            from_=twilio_phone_number,
            body=message_body
        )

        if result["success"]:
            log.info(f"Appointment confirmation sent to {phone}")
            return {"success": True, "error": None}
        else:
            log.error(f"Failed to send appointment confirmation: {result['error']}")
            return {"success": False, "error": result["error"]}

    @classmethod
    def get_next_available_appointments(cls) -> list[ProposedAppointment]:
        """
        Generate placeholder appointment slots for tomorrow morning and afternoon.

        This is a placeholder function. Real implementation will query available slots.

        Returns:
            List of ProposedAppointment objects
        """
        # TODO: Implement call to FHIR Slot API endpoint
        tomorrow = datetime.now() + timedelta(days=1)

        # Morning slot: 9:00 AM
        morning = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 9, 0, 0)

        # Afternoon slot: 2:00 PM
        afternoon = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 14, 0, 0)

        return [
            ProposedAppointment(
                provider_id="provider-1",
                provider_name="Veronica Hernandez, MD",
                location_id="location-1",
                location_name="Main Clinic",
                start_datetime=morning,
                duration=20
            ),
            ProposedAppointment(
                provider_id="provider-2",
                provider_name="Evan Stern, NP",
                location_id="location-2",
                location_name="Virtual (Zoom)",
                start_datetime=afternoon,
                duration=30
            )
        ]


    @classmethod
    def get_patient_mrn_by_session(cls, session_id: str) -> str | None:
        """
        Query the created patient record by session ID metadata to get MRN.

        Args:
            session_id: The intake session ID stored in patient metadata

        Returns:
            Patient MRN (ID) or None if not found
        """
        # Query patient by metadata
        patient = Patient.objects.filter(
            metadata__key="intake_session_id",
            metadata__value=session_id
        ).first()

        if patient:
            # Patient ID is the MRN in Canvas
            return str(patient.id)
        else:
            log.warning(f"No patient found for session {session_id}")
            return None

    @classmethod
    def create_patient(session: IntakeSession) -> Effect:
        # Create patient effect with phone contact
        has_phone_consent = session.phone_verified_timestamp != ""
        patient_effect = Patient(
            first_name=session.first_name,
            last_name=session.last_name,
            birthdate=session.date_of_birth.date(),
            contact_points=[
                PatientContactPoint(
                    system=ContactPointSystem.PHONE,
                    value=session.phone_number,
                    use=ContactPointUse.MOBILE,
                    rank=1,
                    has_consent=has_phone_consent
                ),
            ],
            # Store intake session ID in metadata
            metadata=[PatientMetadata(key="intake_session_id", value=session.session_id)],
        )

        log.info(f"Queued patient creation effect for session {session.session_id}")

        return patient_effect.create()
