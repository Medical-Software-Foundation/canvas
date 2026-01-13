"""Combined API handler for patient portal content."""

from http import HTTPStatus

import requests

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from portal_content.content_types.education import (
    serve_portal_page as education_serve_portal,
    handle_reports_request as education_handle_reports,
    proxy_pdf as education_proxy_pdf,
)
from portal_content.content_types.imaging import (
    serve_portal_page as imaging_serve_portal,
    handle_reports_request as imaging_handle_reports,
    proxy_pdf as imaging_proxy_pdf,
)
from portal_content.content_types.labs import (
    serve_portal_page as labs_serve_portal,
    handle_reports_request as labs_handle_reports,
    proxy_pdf as labs_proxy_pdf,
)
from portal_content.content_types.visits import (
    serve_portal_page as visits_serve_portal,
    handle_notes_request as visits_handle_notes,
    proxy_pdf as visits_proxy_pdf,
)
from logger import log
from portal_content.shared.config import ConfigurationError, is_component_enabled, validate_configuration
from portal_content.shared.fhir_client import FHIRClient


class PortalContentAPI(PatientSessionAuthMixin, SimpleAPI):
    """API handler for all patient portal content types.

    Uses PatientSessionAuthMixin to ensure only logged-in patients can access endpoints.
    """

    PREFIX = ""

    def _validate_config(self) -> list[Response | Effect] | None:
        """Validate configuration. Returns error response if invalid, None if valid."""
        try:
            validate_configuration(self.secrets)
            return None
        except ConfigurationError as e:
            log.error(f"Configuration error: {e}")
            return [
                JSONResponse(
                    {"status": "error", "message": f"Configuration error: {e}"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    def _get_fhir_token(self, patient_id: str) -> str | None:
        """Retrieve FHIR bearer token via OAuth 2.0 client credentials flow."""
        try:
            client_id = self.secrets.get("CLIENT_ID", "")
            client_secret = self.secrets.get("CLIENT_SECRET", "")

            if not client_id or not client_secret:
                log.error("CLIENT_ID and CLIENT_SECRET secrets not configured")
                return None

            environment = self.environment.get("CUSTOMER_IDENTIFIER", "talkiatry-sandbox")
            token_host = f"https://{environment}.canvasmedical.com"

            log.info(f"Requesting FHIR token from {token_host} for patient {patient_id}")

            response = requests.post(
                f"{token_host}/auth/token/",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "patient": patient_id,
                    "scope": "patient/DiagnosticReport.read patient/DocumentReference.read",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            log.info(f"Token response status: {response.status_code}")

            if response.status_code != 200:
                log.error(f"Token error response: {response.text}")

            response.raise_for_status()
            token_data = response.json()
            token = token_data.get("access_token")

            if token:
                log.info(f"Successfully retrieved FHIR token (length: {len(token)})")
            else:
                log.error(f"No access_token in response: {token_data}")

            return token

        except Exception as e:
            log.error(f"Error retrieving FHIR token: {e}", exc_info=True)
            return None

    def _get_fhir_client(self, patient_id: str) -> FHIRClient | None:
        """Get configured FHIR client with patient-scoped OAuth token."""
        try:
            token = self._get_fhir_token(patient_id)
            if not token:
                log.error("Failed to retrieve FHIR token")
                return None

            environment = self.environment.get("CUSTOMER_IDENTIFIER", "talkiatry-sandbox")
            base_url = f"https://fumage-{environment}.canvasmedical.com"

            log.info(f"Using FHIR base URL: {base_url} with patient-scoped token")
            return FHIRClient(base_url, token)
        except Exception as e:
            log.error(f"Error creating FHIR client: {e}")
            return None

    def _disabled_response(self, component: str) -> list[Response | Effect]:
        """Return response for disabled component."""
        return [
            JSONResponse(
                {"status": "error", "message": f"{component} feature is not enabled"},
                status_code=HTTPStatus.FORBIDDEN,
            )
        ]

    # ==================== EDUCATION ENDPOINTS ====================

    @api.get("/education/portal")
    def serve_education_portal(self) -> list[Response | Effect]:
        """Serve the education portal HTML page."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("education", self.secrets):
            return self._disabled_response("education")
        return education_serve_portal(self)

    @api.post("/education/reports")
    def handle_education_reports(self) -> list[Response | Effect]:
        """Handle education reports API requests."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("education", self.secrets):
            return self._disabled_response("education")
        return education_handle_reports(self)

    @api.get("/education/pdf")
    def proxy_education_pdf(self) -> list[Response | Effect]:
        """Proxy education PDF download."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("education", self.secrets):
            return self._disabled_response("education")
        return education_proxy_pdf(self)

    # ==================== IMAGING ENDPOINTS ====================

    @api.get("/imaging/portal")
    def serve_imaging_portal(self) -> list[Response | Effect]:
        """Serve the imaging portal HTML page."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("imaging", self.secrets):
            return self._disabled_response("imaging")
        return imaging_serve_portal(self)

    @api.post("/imaging/reports")
    def handle_imaging_reports(self) -> list[Response | Effect]:
        """Handle imaging reports API requests."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("imaging", self.secrets):
            return self._disabled_response("imaging")
        return imaging_handle_reports(self)

    @api.get("/imaging/pdf")
    def proxy_imaging_pdf(self) -> list[Response | Effect]:
        """Proxy imaging PDF download."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("imaging", self.secrets):
            return self._disabled_response("imaging")
        return imaging_proxy_pdf(self)

    # ==================== LABS ENDPOINTS ====================

    @api.get("/labs/portal")
    def serve_labs_portal(self) -> list[Response | Effect]:
        """Serve the labs portal HTML page."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("labs", self.secrets):
            return self._disabled_response("labs")
        return labs_serve_portal(self)

    @api.post("/labs/reports")
    def handle_labs_reports(self) -> list[Response | Effect]:
        """Handle labs reports API requests."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("labs", self.secrets):
            return self._disabled_response("labs")
        return labs_handle_reports(self)

    @api.get("/labs/pdf")
    def proxy_labs_pdf(self) -> list[Response | Effect]:
        """Proxy labs PDF download."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("labs", self.secrets):
            return self._disabled_response("labs")
        return labs_proxy_pdf(self)

    # ==================== VISITS ENDPOINTS ====================

    @api.get("/visits/portal")
    def serve_visits_portal(self) -> list[Response | Effect]:
        """Serve the visits portal HTML page."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("visits", self.secrets):
            return self._disabled_response("visits")
        return visits_serve_portal(self)

    @api.post("/visits/notes")
    def handle_visits_notes(self) -> list[Response | Effect]:
        """Handle visits notes API requests."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("visits", self.secrets):
            return self._disabled_response("visits")
        return visits_handle_notes(self)

    @api.get("/visits/pdf")
    def proxy_visits_pdf(self) -> list[Response | Effect]:
        """Proxy visits PDF download."""
        if error := self._validate_config():
            return error
        if not is_component_enabled("visits", self.secrets):
            return self._disabled_response("visits")
        return visits_proxy_pdf(self)
