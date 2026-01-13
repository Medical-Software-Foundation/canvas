"""FHIR client for Canvas API interactions."""

import requests

from logger import log


class FHIRClient:
    """Client for interacting with Canvas FHIR API."""

    def __init__(self, base_url: str, token: str):
        """Initialize FHIR client."""
        self.base_url = base_url.rstrip("/")
        self.token = token

    def search_diagnostic_reports(
        self,
        patient_id: str,
        status: str | None = None,
        category: str | None = None,
        date: str | None = None,
    ) -> dict:
        """Search for DiagnosticReport resources."""
        params = {"patient": patient_id}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if date:
            params["date"] = date

        url = f"{self.base_url}/DiagnosticReport"

        log.info(f"FHIR search DiagnosticReport: {url} with params: {params}")

        try:
            response = requests.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            )

            log.info(f"FHIR API response status: {response.status_code}")

            if response.status_code != 200:
                log.error(f"FHIR API error response: {response.text}")

            response.raise_for_status()
            data = response.json()
            log.info(f"Found {len(data.get('entry', []))} DiagnosticReports")
            return data

        except Exception as e:
            log.error(f"Error searching DiagnosticReports: {e}", exc_info=True)
            return {"resourceType": "Bundle", "entry": []}

    def search_document_references(
        self,
        patient_id: str,
        status: str | None = None,
        category: str | None = None,
        type: str | None = None,
        encounter: str | None = None,
        date: str | None = None,
    ) -> dict:
        """Search for DocumentReference resources."""
        params = {"patient": patient_id}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if type:
            params["type"] = type
        if encounter:
            params["encounter"] = encounter
        if date:
            params["date"] = date

        url = f"{self.base_url}/DocumentReference"

        log.info(f"FHIR search DocumentReference: {url} with params: {params}")

        try:
            response = requests.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            )

            log.info(f"FHIR API response status: {response.status_code}")

            if response.status_code != 200:
                log.error(f"FHIR API error response: {response.text}")

            response.raise_for_status()
            data = response.json()
            log.info(f"Found {len(data.get('entry', []))} DocumentReferences")
            return data

        except Exception as e:
            log.error(f"Error searching DocumentReferences: {e}", exc_info=True)
            return {"resourceType": "Bundle", "entry": []}

    def get_document_content_url(self, document_reference: dict) -> str | None:
        """Extract the document content URL from a DocumentReference."""
        try:
            content = document_reference.get("content", [])
            if content and len(content) > 0:
                attachment = content[0].get("attachment", {})
                url = attachment.get("url")
                return url
        except Exception as e:
            log.error(f"Error extracting document URL: {e}")

        return None
