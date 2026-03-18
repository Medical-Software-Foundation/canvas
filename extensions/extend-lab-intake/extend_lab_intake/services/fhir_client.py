"""FHIR client for creating lab reports via the Canvas API."""

from __future__ import annotations

import base64
from datetime import datetime
from http import HTTPStatus
from typing import Any

import requests
from logger import log


class LabValue:
    """A single lab test value/observation."""

    def __init__(
        self,
        code: str,
        display: str,
        value: str | float | None = None,
        unit: str | None = None,
        reference_range_low: float | None = None,
        reference_range_high: float | None = None,
        reference_range_text: str | None = None,
        is_abnormal: bool = False,
        effective_date: str | None = None,
    ) -> None:
        self.code = code  # LOINC code
        self.display = display  # Human-readable name
        self.value = value
        self.unit = unit
        self.reference_range_low = reference_range_low
        self.reference_range_high = reference_range_high
        self.reference_range_text = reference_range_text
        self.is_abnormal = is_abnormal
        self.effective_date = effective_date  # ISO format


class LabTest:
    """A lab test panel containing multiple values."""

    def __init__(
        self,
        code: str,
        display: str,
        effective_date: str,
        values: list[LabValue] | None = None,
    ) -> None:
        self.code = code  # LOINC code for the panel
        self.display = display  # Human-readable panel name
        self.effective_date = effective_date  # ISO format
        self.values = values if values is not None else []


class LabReport:
    """A complete lab report."""

    def __init__(
        self,
        patient_id: str,
        effective_date: str,
        tests: list[LabTest] | None = None,
        pdf_data: bytes | None = None,
        report_code: str = "laboratory",
        report_display: str = "Laboratory Report",
    ) -> None:
        self.patient_id = patient_id
        self.effective_date = effective_date  # ISO format
        self.tests = tests if tests is not None else []
        self.pdf_data = pdf_data
        self.report_code = report_code
        self.report_display = report_display


class FHIRClient:
    """Client for Canvas FHIR API operations.

    Handles authentication and the create-lab-report operation.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        instance: str,
    ) -> None:
        """Initialize the FHIR client.

        Args:
            client_id: OAuth client ID
            client_secret: OAuth client secret
            instance: Canvas instance name (e.g., "my-instance")
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.instance = instance
        self._token: str | None = None
        self._token_expires: datetime | None = None

        # Set up URLs based on environment
        if instance == "local":
            self.auth_url = "http://localhost:8000/auth/token/"
            self.fhir_base_url = "http://localhost:8888"
        else:
            self.auth_url = f"https://{instance}.canvasmedical.com/auth/token/"
            self.fhir_base_url = f"https://fumage-{instance}.canvasmedical.com"

    def _get_token(self) -> str | None:
        """Get or refresh OAuth token."""
        # Check if we have a valid cached token
        if self._token and self._token_expires:
            if datetime.now() < self._token_expires:
                return self._token

        try:
            response = requests.post(
                self.auth_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=30,
            )

            if response.status_code != HTTPStatus.OK:
                log.error(f"Failed to get FHIR token: {response.text}")
                return None

            data = response.json()
            self._token = data.get("access_token")

            # Cache token with expiry (subtract 60s for safety margin)
            expires_in = data.get("expires_in", 3600)
            from datetime import timedelta

            self._token_expires = datetime.now() + timedelta(seconds=expires_in - 60)

            return self._token

        except Exception as e:
            log.error(f"Token request failed: {e}")
            return None

    def _get_headers(self) -> dict[str, str]:
        """Get authenticated headers for FHIR requests."""
        token = self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def create_lab_report(self, report: LabReport) -> dict[str, Any]:
        """Create a lab report using the create-lab-report operation.

        Args:
            report: LabReport containing all test data and PDF

        Returns:
            dict with keys: success, diagnostic_report_id, error
        """
        payload = self._build_create_lab_report_payload(report)

        try:
            response = requests.post(
                f"{self.fhir_base_url}/DiagnosticReport/$create-lab-report",
                headers=self._get_headers(),
                json=payload,
                timeout=60,
            )

            correlation_id = response.headers.get("fumage-correlation-id", "unknown")

            if response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED):
                log.info(
                    f"Lab report created successfully. Status: {response.status_code}, Correlation ID: {correlation_id}"
                )

                response_text = response.text

                # Extract DiagnosticReport ID from response
                # FHIR APIs typically return ID in Location header
                location = response.headers.get("Location", "") or response.headers.get("location", "")
                content_location = response.headers.get("Content-Location", "") or response.headers.get("content-location", "")

                report_id = None

                # Try Location header first (preferred)
                if location:
                    # Format: https://fumage-xxx.canvasmedical.com/DiagnosticReport/abc123/_history/1
                    # or: DiagnosticReport/abc123
                    parts = location.split("/")
                    for i, part in enumerate(parts):
                        if part == "DiagnosticReport" and i + 1 < len(parts):
                            report_id = parts[i + 1].split("/_history")[0]
                            break
                    if not report_id:
                        # Fallback: just get the last segment
                        report_id = location.split("/")[-1].split("/_history")[0]

                # Try Content-Location if Location didn't work
                if not report_id and content_location:
                    parts = content_location.split("/")
                    for i, part in enumerate(parts):
                        if part == "DiagnosticReport" and i + 1 < len(parts):
                            report_id = parts[i + 1].split("/_history")[0]
                            break

                # If no header, try to get ID from response body
                if not report_id:
                    try:
                        if response_text:
                            response_data = response.json()

                            # Check if response is DiagnosticReport directly
                            if response_data.get("resourceType") == "DiagnosticReport":
                                report_id = response_data.get("id")

                            # Check if response is Parameters (Canvas $create-lab-report returns this)
                            elif response_data.get("resourceType") == "Parameters":
                                parameters = response_data.get("parameter", [])
                                for param in parameters:
                                    # Look for "return" parameter with valueReference
                                    if param.get("name") == "return":
                                        value_ref = param.get("valueReference", {})
                                        reference = value_ref.get("reference", "")
                                        # Format: "DiagnosticReport/fff1fff7-ad8a-4490-9757-a17e65d7cc59"
                                        if reference.startswith("DiagnosticReport/"):
                                            report_id = reference.split("/")[1]
                                            break

                            # Check if response is OperationOutcome with issue containing reference
                            elif response_data.get("resourceType") == "OperationOutcome":
                                issues = response_data.get("issue", [])
                                for issue in issues:
                                    diagnostics = issue.get("diagnostics", "")
                                    # Some APIs include ID reference in diagnostics
                                    if "DiagnosticReport/" in diagnostics:
                                        parts = diagnostics.split("DiagnosticReport/")
                                        if len(parts) > 1:
                                            report_id = parts[1].split("/")[0].split()[0]
                                            break

                            # Check if response is Bundle
                            elif response_data.get("resourceType") == "Bundle":
                                entries = response_data.get("entry", [])
                                for entry in entries:
                                    resource = entry.get("resource", {})
                                    if resource.get("resourceType") == "DiagnosticReport":
                                        report_id = resource.get("id")
                                        break
                            else:
                                # Try direct ID field as fallback
                                report_id = response_data.get("id")
                    except Exception as e:
                        log.warning(f"Could not parse response body for report ID: {e}")

                return {
                    "success": True,
                    "diagnostic_report_id": report_id,
                    "correlation_id": correlation_id,
                    "error": None,
                }
            else:
                error_msg = f"Failed to create lab report. Status: {response.status_code}, Correlation ID: {correlation_id}, Error: {response.text}"
                log.error(error_msg)
                return {
                    "success": False,
                    "diagnostic_report_id": None,
                    "correlation_id": correlation_id,
                    "error": error_msg,
                }

        except Exception as e:
            error_msg = f"Lab report creation request failed: {e}"
            log.error(error_msg)
            return {
                "success": False,
                "diagnostic_report_id": None,
                "correlation_id": None,
                "error": error_msg,
            }

    def _build_create_lab_report_payload(self, report: LabReport) -> dict[str, Any]:
        """Build the FHIR Parameters payload for create-lab-report."""
        parameters: list[dict[str, Any]] = []

        # Build the main DiagnosticReport resource
        diagnostic_report: dict[str, Any] = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                            "code": "LAB",
                            "display": "Laboratory",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": report.report_code,
                        "display": report.report_display,
                    }
                ]
            },
            "subject": {"reference": f"Patient/{report.patient_id}"},
            "effectiveDateTime": report.effective_date,
        }

        # Add PDF if available
        if report.pdf_data:
            pdf_base64 = base64.b64encode(report.pdf_data).decode("utf-8")
            diagnostic_report["presentedForm"] = [
                {
                    "contentType": "application/pdf",
                    "data": pdf_base64,
                }
            ]

        parameters.append({"name": "labReport", "resource": diagnostic_report})

        # Build lab test collections
        for test in report.tests:
            test_collection = self._build_lab_test_collection(test, report.patient_id)
            parameters.append(test_collection)

        return {"resourceType": "Parameters", "parameter": parameters}

    def _build_lab_test_collection(
        self, test: LabTest, patient_id: str
    ) -> dict[str, Any]:
        """Build a labTestCollection parameter."""
        parts: list[dict[str, Any]] = []

        # Canvas requires coding with exactly 1 item and system must be http://loinc.org
        # Use actual LOINC code if available, otherwise use display as code
        if test.code and test.code != "laboratory" and test.code != "unknown":
            code_element: dict[str, Any] = {
                "text": test.display,
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": test.code,
                        "display": test.display,
                    }
                ]
            }
        else:
            # No LOINC code - Canvas still requires system=http://loinc.org
            # Use display as a placeholder code
            code_element = {
                "text": test.display,
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "laboratory",
                        "display": test.display,
                    }
                ]
            }

        # Lab test (panel) observation
        lab_test_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "status": "final",
            "code": code_element,
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": test.effective_date,
        }
        parts.append({"name": "labTest", "resource": lab_test_obs})

        # Lab values (individual observations)
        for value in test.values:
            lab_value_obs = self._build_lab_value_observation(
                value, patient_id, test.effective_date
            )
            parts.append({"name": "labValue", "resource": lab_value_obs})

        return {"name": "labTestCollection", "part": parts}

    def _build_lab_value_observation(
        self, value: LabValue, patient_id: str, default_date: str
    ) -> dict[str, Any]:
        """Build a lab value observation resource."""
        # Canvas requires coding with exactly 1 item and system must be http://loinc.org
        # Use actual LOINC code if available, otherwise use display as code
        if value.code and value.code != "unknown":
            code_element: dict[str, Any] = {
                "text": value.display,
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": value.code,
                        "display": value.display,
                    }
                ]
            }
        else:
            # No LOINC code - Canvas still requires system=http://loinc.org
            # Use display as a placeholder code
            code_element = {
                "text": value.display,
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "unknown",
                        "display": value.display,
                    }
                ]
            }

        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "status": "final",
            "code": code_element,
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": value.effective_date or default_date,
        }

        # Add value (quantity or string)
        # Canvas expects valueQuantity.value as string per their examples
        if value.value is not None:
            if value.unit:
                obs["valueQuantity"] = {
                    "value": str(value.value),
                    "unit": value.unit,
                    "system": "http://unitsofmeasure.org",
                }
            else:
                obs["valueString"] = str(value.value)

        # Add reference range if available
        # Canvas examples show low/high with just value (as string), no unit
        if (
            value.reference_range_low is not None
            or value.reference_range_high is not None
            or value.reference_range_text
        ):
            ref_range: dict[str, Any] = {}
            if value.reference_range_low is not None:
                ref_range["low"] = {"value": str(value.reference_range_low)}
            if value.reference_range_high is not None:
                ref_range["high"] = {"value": str(value.reference_range_high)}
            if value.reference_range_text:
                ref_range["text"] = value.reference_range_text
            obs["referenceRange"] = [ref_range]

        # Note: Canvas's create-lab-report operation has strict validation on interpretation.
        # For now, skip interpretation to avoid validation errors.
        # The abnormal flag can be viewed from the lab value's reference range comparison.
        # TODO: Investigate Canvas's expected interpretation format

        return obs
