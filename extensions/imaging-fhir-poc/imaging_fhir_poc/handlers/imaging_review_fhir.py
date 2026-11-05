import json
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.v1.data.imaging import ImagingReport
from logger import log


class ImagingReviewFhirHandler(BaseProtocol):
    """Handler that makes FHIR API requests when imaging reviews are committed."""

    RESPONDS_TO = [EventType.Name(EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT)]

    def compute(self) -> list[Effect]:
        """Handle the imaging review commit event."""
        context = self.event.context
        patient_id = context.get("patient", {}).get("id")
        if not patient_id:
            log.warning("No patient ID in imaging review event context")
            return []

        log.info(f"Imaging review committed for patient {patient_id}")
        log.info(f"Event context: {json.dumps(context, indent=2)}")

        message_to_patient = context.get("fields", {}).get("message_to_patient", "")
        log.info(f"Message to patient: {message_to_patient}")

        report_dbid = self._extract_report_dbid(context)
        report_timestamp = self._get_report_timestamp(report_dbid) if report_dbid else None

        self._fetch_document_references(patient_id, report_timestamp)

        return []

    def _extract_report_dbid(self, context: dict[str, Any]) -> int | None:
        """Extract the report dbid from the event context.

        The context structure is:
        {
            "fields": {
                "report": [
                    {"value": "304", "text": "...", ...}
                ]
            }
        }
        """
        reports = context.get("fields", {}).get("report", [])
        if not reports or not isinstance(reports, list):
            return None
        first_report = reports[0]
        if not isinstance(first_report, dict):
            return None
        value = first_report.get("value")
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            log.warning(f"Invalid report value: {value}")
            return None

    def _get_report_timestamp(self, report_dbid: int) -> datetime | None:
        """Get the created timestamp from an imaging report."""
        try:
            report = ImagingReport.objects.get(dbid=report_dbid)
            if report.created:
                return cast(datetime, report.created)
        except ImagingReport.DoesNotExist:
            log.warning(f"ImagingReport not found with dbid: {report_dbid}")
        return None

    def _fetch_document_references(
        self, patient_id: str, report_timestamp: datetime | None
    ) -> None:
        """Fetch DocumentReference resources from FHIR API."""
        fhir_base_url = self.secrets.get("FHIR_BASE_URL", "").rstrip("/")
        client_id = self.secrets.get("CLIENT_ID", "")
        client_secret = self.secrets.get("CLIENT_SECRET", "")

        if not all([fhir_base_url, client_id, client_secret]):
            log.error("Missing required secrets: FHIR_BASE_URL, CLIENT_ID, or CLIENT_SECRET")
            return

        token = self._get_oauth_token(fhir_base_url, client_id, client_secret)
        if not token:
            return

        self._search_document_references(fhir_base_url, token, patient_id, report_timestamp)

    def _get_oauth_token(
        self, fhir_base_url: str, client_id: str, client_secret: str
    ) -> str | None:
        """Get OAuth2 access token using client credentials flow.

        FHIR base URL format: https://fumage-<subdomain>.canvasmedical.com
        Token URL format: https://<subdomain>.canvasmedical.com/auth/token/
        """
        # Extract hostname from URL (e.g., "fumage-example.canvasmedical.com")
        hostname = fhir_base_url.replace("https://", "").replace("http://", "").split("/")[0]
        # Remove 'fumage-' prefix to get the Canvas instance hostname
        canvas_hostname = hostname.replace("fumage-", "", 1)
        token_url = f"https://{canvas_hostname}/auth/token/"

        http = Http()
        response = http.post(
            token_url,
            data=urlencode({
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if not response.ok:
            log.error(f"OAuth token request failed: {response.status_code}")
            return None

        token_data: dict[str, Any] = response.json()
        access_token = token_data.get("access_token")
        if isinstance(access_token, str):
            log.info("Successfully obtained OAuth token")
            return access_token

        log.error("OAuth response missing access_token")
        return None

    def _search_document_references(
        self, fhir_base_url: str, token: str, patient_id: str, report_timestamp: datetime | None
    ) -> None:
        """Search for DocumentReference resources via FHIR API."""
        params: list[tuple[str, str]] = [
            ("patient", f"Patient/{patient_id}"),
            ("category", "http://schemas.canvasmedical.com/fhir/document-reference-category|imagingreport"),
            ("status", "current"),
        ]

        if report_timestamp:
            time_start = report_timestamp - timedelta(minutes=1)
            time_end = report_timestamp + timedelta(minutes=1)
            params.append(("date", f"ge{time_start.isoformat()}"))
            params.append(("date", f"le{time_end.isoformat()}"))

        search_url = f"{fhir_base_url}/DocumentReference?{urlencode(params)}"

        http = Http()
        response = http.get(
            search_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/fhir+json",
            },
        )

        if not response.ok:
            log.error(f"FHIR API request failed: {response.status_code}")
            return

        bundle: dict[str, Any] = response.json()
        total = bundle.get("total", 0)
        log.info(f"FHIR DocumentReference search returned {total} results")
        log.info(f"FHIR response: {json.dumps(bundle, indent=2)}")
