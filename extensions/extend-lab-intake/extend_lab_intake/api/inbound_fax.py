"""SimpleAPI endpoint for receiving inbound lab report faxes."""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from hmac import compare_digest
from typing import Any
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPI, api
from canvas_sdk.v1.data.team import Team
from logger import log

from extend_lab_intake.services.extend_client import (
    ExtendClient,
    ExtendRunStatus,
    ExtendError,
    ProcessorTree,
)
from extend_lab_intake.services.fhir_client import FHIRClient, LabReport, LabTest, LabValue
from extend_lab_intake.services.llm_client import LLMClient
from extend_lab_intake.services.patient_matcher import PatientMatcher, ExtractedDemographics
from extend_lab_intake.services.summarizer import LabResultSummarizer
from extend_lab_intake.utils.constants import Secrets, Labels, S3Config
from extend_lab_intake.utils.hmac_auth import verify_session_token
from extend_lab_intake.utils.s3_client import S3Client


class InboundFaxAPI(SimpleAPI):
    """API endpoint for receiving lab report PDFs from external systems.

    Endpoints:
    - POST /lab-intake/inbound-fax - Receive PDF and classify (no extraction)
    - POST /lab-intake/extract - Manually trigger extraction for a document
    - POST /lab-intake/discard - Discard a document from the queue
    - GET /lab-intake/health - Health check
    """

    PREFIX = "/lab-intake"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        """Authenticate using API key or session token.

        Supports two authentication methods:
        1. Direct API key - for external callers (e.g., external webhook)
        2. Session token - for frontend modal (time-limited, more secure)

        Session tokens are in format: {timestamp}.{hmac_signature}
        They expire after 5 minutes.
        """
        provided_key = credentials.key
        expected_key = self.secrets.get(Secrets.INBOUND_FAX_TOKEN, "")

        if not expected_key:
            log.warning("INBOUND_FAX_TOKEN secret not configured")
            return False

        # Check if this looks like a session token (contains a dot)
        if "." in provided_key:
            return self._verify_session_token(provided_key)

        # Direct API key authentication
        return compare_digest(provided_key.encode(), expected_key.encode())

    def _verify_session_token(self, token: str) -> bool:
        """Verify a session token for frontend requests.

        Args:
            token: Session token in format "timestamp.signature"

        Returns:
            True if token is valid and not expired, False otherwise
        """
        secret_key = self.secrets.get(Secrets.INBOUND_FAX_TOKEN, "")

        if not secret_key:
            log.warning("INBOUND_FAX_TOKEN secret not configured")
            return False

        is_valid, error = verify_session_token(
            secret_key=secret_key,
            token=token,
        )

        if not is_valid:
            log.warning(f"Session token verification failed: {error}")

        return is_valid

    @api.post("/inbound-fax")
    def receive_fax(self) -> list[Response | Effect]:
        """Handle incoming lab report PDF - classify only, no extraction.

        Expected request:
        - Content-Type: multipart/form-data
        - Body: PDF file in 'file' field

        Returns:
        - 202 Accepted with intake_id and classification
        - 400 Bad Request if no PDF provided
        - 500 Internal Server Error on processing failure
        """
        # Extract PDF from multipart form data
        form_data = self.request.form_data()
        file_part = form_data.get("file")

        if not file_part or not file_part.content:
            return [
                JSONResponse(
                    {"error": "No PDF file provided in 'file' field"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        pdf_data = file_part.content
        file_name = file_part.filename or f"lab_report_{uuid4().hex[:8]}.pdf"

        log.info(f"Received lab report: {file_name}, size: {len(pdf_data)} bytes")

        # Generate unique identifiers for this intake
        intake_id = uuid4().hex[:12]
        s3_key = f"intake/{intake_id}/{file_name}"

        # Process: upload and classify only
        result = self._classify_document(
            pdf_data=pdf_data,
            file_name=file_name,
            s3_key=s3_key,
            intake_id=intake_id,
        )

        if result["success"]:
            return [
                JSONResponse(
                    {
                        "status": "success",
                        "intake_id": intake_id,
                        "classification": result.get("classification"),
                        "classification_confidence": result.get("classification_confidence"),
                    },
                    status_code=HTTPStatus.ACCEPTED,
                )
            ]
        else:
            return [
                JSONResponse(
                    {
                        "status": "error",
                        "intake_id": intake_id,
                        "error": result.get("error"),
                    },
                    status_code=HTTPStatus.ACCEPTED,
                )
            ]

    def _classify_document(
        self,
        pdf_data: bytes,
        file_name: str,
        s3_key: str,
        intake_id: str,
    ) -> dict[str, Any]:
        """Upload PDF and run classification only (no extraction).

        Stores classification result as metadata JSON in S3.
        """
        s3_client = self._get_s3_client()
        extend_client = self._get_extend_client()

        # Step 1: Upload PDF to S3
        log.info(f"Uploading PDF to S3: {s3_key}")
        upload_response = s3_client.upload_pdf(s3_key, pdf_data)

        if upload_response.status_code not in (200, 201):
            return {
                "success": False,
                "error": f"S3 upload failed: {upload_response.status_code}",
            }

        # Generate presigned URL for Extend AI
        presigned_url = s3_client.generate_presigned_url(s3_key, expires_in=3600)

        # Step 2: Parse processor tree
        processor_tree_json = self.secrets.get(Secrets.EXTEND_AI_PROCESSOR_TREE, "")

        if not processor_tree_json:
            return {
                "success": False,
                "error": "EXTEND_AI_PROCESSOR_TREE secret not configured",
            }

        processor_tree = ProcessorTree.from_json(processor_tree_json)

        # Step 3: Run classification only
        classifier = processor_tree.get_first_classifier()
        if not classifier:
            return {
                "success": False,
                "error": "No classifier configured in processor tree",
            }

        log.info(f"Running classification for intake {intake_id}")
        classify_result = extend_client.run_processor(
            processor_id=classifier.processor_id,
            file_name=file_name,
            file_url=presigned_url,
        )

        if isinstance(classify_result, ExtendError):
            return {
                "success": False,
                "error": f"Classification failed: {classify_result.message}",
            }

        # Wait for classification to complete
        classify_result = extend_client.wait_for_completion(classify_result.run_id)

        if isinstance(classify_result, ExtendError):
            return {
                "success": False,
                "error": f"Classification failed: {classify_result.message}",
            }

        if classify_result.status == ExtendRunStatus.FAILED:
            return {
                "success": False,
                "error": f"Classification failed: {classify_result.error}",
            }

        # Parse classification result
        classification_output = classify_result.output or {}
        classification_id = classification_output.get("id", "")
        classification_type = classification_output.get("type", "")
        classification_confidence = classification_output.get("confidence")

        log.info(f"Classification complete: {classification_type} (confidence: {classification_confidence})")

        # Step 4: Store metadata in S3
        received_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "intake_id": intake_id,
            "file_name": file_name,
            "received_at": received_at,
            "status": "classified",
            "classification": {
                "id": classification_id,
                "type": classification_type,
                "confidence": classification_confidence,
                "raw_output": classification_output,
            },
            "extraction": None,  # Will be populated on manual processing
        }

        metadata_key = f"intake/{intake_id}/metadata.json"
        metadata_response = s3_client.upload_json(metadata_key, metadata)

        if metadata_response.status_code not in (200, 201):
            log.warning(f"Failed to upload metadata: {metadata_response.status_code}")

        # Step 5: Add to index for fast queue loading
        s3_client.add_to_index(
            intake_id=intake_id,
            filename=file_name,
            status="classified",
            classification_type=classification_type,
            received_at=received_at,
            size_bytes=len(pdf_data),
        )

        return {
            "success": True,
            "classification": classification_type,
            "classification_confidence": classification_confidence,
        }

    @api.post("/extract")
    def extract_document(self) -> list[Response | Effect]:
        """Manually trigger extraction for a classified document.

        Expected request body (JSON):
        - intake_id: The intake ID to extract

        Returns extracted data and creates FHIR resources if patient matched.
        """
        body = self.request.json()
        intake_id = body.get("intake_id")

        if not intake_id:
            return [
                JSONResponse(
                    {"error": "intake_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(f"Manual extraction triggered for intake {intake_id}")

        result = self._extract_and_process(intake_id)

        # Build response effects
        effects: list[Effect] = []

        if result["success"]:
            # Create task - link to patient if matched with sufficient confidence
            patient_id = result.get("patient_id")
            confidence = result.get("confidence", "none")
            classification = result.get("classification", "unknown")

            fallback_team_id = self._get_fallback_team_id()

            task_title = f"Lab Intake ({classification}): {result.get('file_name', intake_id)}"

            task_effect = AddTask(
                title=task_title,
                team_id=fallback_team_id,
                labels=[Labels.LAB_INTAKE],
                status=TaskStatus.COMPLETED if patient_id and confidence in ("high", "medium") else TaskStatus.OPEN,
                patient_id=patient_id if patient_id and confidence in ("high", "medium") else None,
            )
            effects.append(task_effect.apply())

            return effects + [
                JSONResponse(
                    {
                        "status": "success",
                        "intake_id": intake_id,
                        "patient_id": patient_id,
                        "diagnostic_report_id": result.get("diagnostic_report_id"),
                        "confidence": confidence,
                        "classification": classification,
                        "summary": result.get("summary"),
                        "output": result.get("output"),  # Include full extraction output
                    },
                    status_code=HTTPStatus.OK,
                )
            ]
        else:
            return [
                JSONResponse(
                    {
                        "status": "error",
                        "intake_id": intake_id,
                        "error": result.get("error"),
                    },
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    def _extract_and_process(self, intake_id: str) -> dict[str, Any]:
        """Run extraction and full processing for a document."""
        log.info(f"[EXTRACT] Starting extraction for intake {intake_id}")

        s3_client = self._get_s3_client()
        extend_client = self._get_extend_client()
        llm_client = self._get_llm_client()

        # Step 1: Load metadata from S3
        log.info(f"[EXTRACT] Step 1: Loading metadata from S3")
        metadata_key = f"intake/{intake_id}/metadata.json"
        metadata = s3_client.get_json(metadata_key)

        if not metadata:
            log.error(f"[EXTRACT] Metadata not found for intake {intake_id}")
            return {
                "success": False,
                "error": f"Metadata not found for intake {intake_id}",
            }

        file_name = metadata.get("file_name", "")
        classification_data = metadata.get("classification", {})
        classification_id = classification_data.get("id", "")
        classification_type = classification_data.get("type", "")

        log.info(f"[EXTRACT] File: {file_name}, Classification: {classification_type} ({classification_id})")

        # Check if already processed
        if metadata.get("extraction"):
            log.warning(f"[EXTRACT] Document already processed: {intake_id}")
            return {
                "success": False,
                "error": "Document has already been processed",
            }

        # Step 2: Get processor tree and find extractor
        log.info(f"[EXTRACT] Step 2: Getting processor tree")
        processor_tree_json = self.secrets.get(Secrets.EXTEND_AI_PROCESSOR_TREE, "")
        if not processor_tree_json:
            log.error(f"[EXTRACT] EXTEND_AI_PROCESSOR_TREE secret not configured")
            return {
                "success": False,
                "error": "EXTEND_AI_PROCESSOR_TREE secret not configured",
            }

        processor_tree = ProcessorTree.from_json(processor_tree_json)

        classifier = processor_tree.get_first_classifier()
        if not classifier:
            log.error(f"[EXTRACT] No classifier configured in processor tree")
            return {
                "success": False,
                "error": "No classifier configured",
            }

        log.info(f"[EXTRACT] Looking for extractor for classification_id: {classification_id}")
        extractor = processor_tree.get_extractor_for_classification(
            classifier.processor_id, classification_id
        )

        if not extractor:
            log.warning(f"[EXTRACT] No extractor found for classification: {classification_id}")
            # Update metadata to mark as no extractor
            metadata["status"] = "no_extractor"
            metadata["extraction"] = {"skipped": True, "reason": f"No extractor for classification: {classification_id}"}
            s3_client.upload_json(metadata_key, metadata)

            # Update index status
            s3_client.update_index_status(intake_id, "no_extractor")

            return {
                "success": True,
                "patient_id": None,
                "diagnostic_report_id": None,
                "confidence": "none",
                "summary": f"No extractor configured for document type: {classification_type}",
                "classification": classification_type,
                "file_name": file_name,
            }

        log.info(f"[EXTRACT] Found extractor: {extractor.processor_id}")

        # Step 3: Generate presigned URL and run extraction
        log.info(f"[EXTRACT] Step 3: Running Extend AI extraction")
        pdf_key = f"intake/{intake_id}/{file_name}"
        presigned_url = s3_client.generate_presigned_url(pdf_key, expires_in=3600)

        log.info(f"[EXTRACT] Running extraction for intake {intake_id} with processor {extractor.processor_id}")
        extract_result = extend_client.run_processor(
            processor_id=extractor.processor_id,
            file_name=file_name,
            file_url=presigned_url,
        )

        if isinstance(extract_result, ExtendError):
            log.error(f"[EXTRACT] Extend AI run_processor failed: {extract_result.status_code} - {extract_result.message}")
            return {
                "success": False,
                "error": f"Extraction failed: {extract_result.message}",
                "classification": classification_type,
            }

        log.info(f"[EXTRACT] Waiting for extraction completion, run_id: {extract_result.run_id}")
        extract_result = extend_client.wait_for_completion(extract_result.run_id)

        if isinstance(extract_result, ExtendError):
            log.error(f"[EXTRACT] Extend AI wait_for_completion failed: {extract_result.status_code} - {extract_result.message}")
            return {
                "success": False,
                "error": f"Extraction failed: {extract_result.message}",
                "classification": classification_type,
            }

        if extract_result.status == ExtendRunStatus.FAILED:
            log.error(f"[EXTRACT] Extend AI extraction failed: {extract_result.error}")
            return {
                "success": False,
                "error": f"Extraction failed: {extract_result.error}",
                "classification": classification_type,
            }

        extraction_output = extract_result.output or {}
        log.info(f"[EXTRACT] Extraction complete for intake {intake_id}, output keys: {list(extraction_output.keys())}")

        # Step 4: Match patient
        log.info(f"[EXTRACT] Step 4: Matching patient")
        patient_matcher = PatientMatcher(llm_client)
        demographics = ExtractedDemographics.from_extend_output(extraction_output)
        log.info(f"[EXTRACT] Demographics: {demographics}")
        match_result = patient_matcher.match_patient(demographics)

        patient_id = match_result.patient_id
        confidence = match_result.confidence
        match_details = match_result.match_details
        patient_name = match_result.patient_name
        log.info(f"[EXTRACT] Patient match result: {patient_id} ({patient_name}) (confidence: {confidence})")

        # Step 5: Generate summary
        log.info(f"[EXTRACT] Step 5: Generating summary")
        summarizer = LabResultSummarizer(llm_client)
        summary = summarizer.summarize_from_extend_output(extraction_output)
        log.info(f"[EXTRACT] Summary generated: {summary[:100] if summary else 'None'}...")

        # Step 6: Note - FHIR DiagnosticReport is created manually via /save-report endpoint
        diagnostic_report_id = None

        # Step 7: Update metadata with extraction results
        log.info(f"[EXTRACT] Step 7: Saving metadata to S3")
        metadata["status"] = "processed"
        metadata["extraction"] = {
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "output": extraction_output,
            "patient_match": {
                "patient_id": patient_id,
                "patient_name": patient_name,
                "confidence": confidence,
                "details": match_details,
            },
            "summary": summary,
            "diagnostic_report_id": diagnostic_report_id,
        }
        s3_client.upload_json(metadata_key, metadata)

        # Update index status
        s3_client.update_index_status(intake_id, "processed")

        log.info(f"[EXTRACT] Extraction complete for intake {intake_id}")
        return {
            "success": True,
            "patient_id": patient_id,
            "diagnostic_report_id": diagnostic_report_id,
            "confidence": confidence,
            "summary": summary,
            "classification": classification_type,
            "file_name": file_name,
            "output": extraction_output,  # Include full extraction output
        }

    @api.post("/save-report")
    def save_report(self) -> list[Response | Effect]:
        """Save extracted lab data as a Canvas DiagnosticReport.

        Expected request body (JSON):
        - intake_id: The intake ID to save

        Returns the created DiagnosticReport ID.
        """
        body = self.request.json()
        intake_id = body.get("intake_id")

        if not intake_id:
            return [
                JSONResponse(
                    {"error": "intake_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        s3_client = self._get_s3_client()
        fhir_client = self._get_fhir_client()

        # Load metadata from S3
        metadata_key = f"intake/{intake_id}/metadata.json"
        metadata = s3_client.get_json(metadata_key)

        if not metadata:
            return [
                JSONResponse(
                    {"error": f"Metadata not found for intake {intake_id}"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        extraction = metadata.get("extraction")
        if not extraction or extraction.get("skipped"):
            return [
                JSONResponse(
                    {"error": "Document has not been extracted yet"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Check if already saved
        if extraction.get("diagnostic_report_id"):
            return [
                JSONResponse(
                    {
                        "status": "already_saved",
                        "diagnostic_report_id": extraction["diagnostic_report_id"],
                    },
                    status_code=HTTPStatus.OK,
                )
            ]

        # Get patient match info
        patient_match = extraction.get("patient_match", {})
        patient_id = patient_match.get("patient_id")
        confidence = patient_match.get("confidence", "none")

        if not patient_id:
            return [
                JSONResponse(
                    {"error": "No patient matched - cannot save report"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Get PDF data
        file_name = metadata.get("file_name", "")
        pdf_key = f"intake/{intake_id}/{file_name}"
        pdf_data = s3_client.get_object(pdf_key)

        if not pdf_data:
            return [
                JSONResponse(
                    {"error": "PDF file not found in S3"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        # Build and create FHIR lab report
        extraction_output = extraction.get("output", {})
        log.info(f"Creating FHIR DiagnosticReport for patient {patient_id}")

        lab_report = self._build_lab_report(
            patient_id=patient_id,
            extraction_output=extraction_output,
            pdf_data=pdf_data,
        )

        fhir_result = fhir_client.create_lab_report(lab_report)

        if fhir_result["success"]:
            diagnostic_report_id = fhir_result["diagnostic_report_id"]
            log.info(f"DiagnosticReport created: {diagnostic_report_id}")

            if not diagnostic_report_id:
                log.warning(f"FHIR returned success but no diagnostic_report_id. Full result: {fhir_result}")

            # Update metadata with report ID
            metadata["extraction"]["diagnostic_report_id"] = diagnostic_report_id
            metadata["status"] = "saved"
            log.info(f"Saving metadata with diagnostic_report_id={diagnostic_report_id}, status=saved")
            s3_client.upload_json(metadata_key, metadata)
            log.info(f"Metadata saved to {metadata_key}")

            # Update index status
            s3_client.update_index_status(intake_id, "saved")

            # Create task if not already done
            effects: list[Effect] = []
            fallback_team_id = self._get_fallback_team_id()
            classification_type = metadata.get("classification", {}).get("type", "unknown")

            task_title = f"Lab Intake ({classification_type}): {file_name}"

            task_effect = AddTask(
                title=task_title,
                team_id=fallback_team_id,
                labels=[Labels.LAB_INTAKE],
                status=TaskStatus.COMPLETED if confidence in ("high", "medium") else TaskStatus.OPEN,
                patient_id=patient_id,
            )
            effects.append(task_effect.apply())

            return effects + [
                JSONResponse(
                    {
                        "status": "success",
                        "diagnostic_report_id": diagnostic_report_id,
                        "patient_id": patient_id,
                    },
                    status_code=HTTPStatus.OK,
                )
            ]
        else:
            return [
                JSONResponse(
                    {"error": f"FHIR creation failed: {fhir_result['error']}"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    @api.get("/document")
    def get_document(self) -> list[Response | Effect]:
        """Get full document details for expanded row view.

        Query parameters:
        - intake_id: The intake ID to retrieve

        Returns the document metadata including:
        - presigned_url: URL for viewing the PDF
        - classification: Full classification data with raw_output
        - extraction: Full extraction data if processed
        """
        intake_id = self.request.query_params.get("intake_id")

        if not intake_id:
            return [
                JSONResponse(
                    {"error": "intake_id query parameter is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        s3_client = self._get_s3_client()

        metadata_key = f"intake/{intake_id}/metadata.json"
        metadata = s3_client.get_json(metadata_key)

        if not metadata:
            return [
                JSONResponse(
                    {"error": f"Document not found: {intake_id}"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        # Generate presigned URL for PDF viewing
        file_name = metadata.get("file_name", "")
        pdf_key = f"intake/{intake_id}/{file_name}"
        presigned_url = s3_client.generate_presigned_url(pdf_key, expires_in=3600)

        # Add presigned URL to response
        response_data = {
            **metadata,
            "presigned_url": presigned_url,
        }

        return [
            JSONResponse(response_data, status_code=HTTPStatus.OK)
        ]

    @api.post("/discard")
    def discard_document(self) -> list[Response | Effect]:
        """Discard a document from the queue.

        Expected request body (JSON):
        - intake_id: The intake ID to discard
        """
        body = self.request.json()
        intake_id = body.get("intake_id")

        if not intake_id:
            return [
                JSONResponse(
                    {"error": "intake_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        s3_client = self._get_s3_client()

        # Load metadata to get file name
        metadata_key = f"intake/{intake_id}/metadata.json"
        metadata = s3_client.get_json(metadata_key)

        if metadata:
            file_name = metadata.get("file_name", "")
            pdf_key = f"intake/{intake_id}/{file_name}"

            # Delete PDF
            s3_client.delete_object(pdf_key)

        # Delete metadata
        s3_client.delete_object(metadata_key)

        # Remove from index
        s3_client.remove_from_index(intake_id)

        log.info(f"Discarded document: intake {intake_id}")

        return [
            JSONResponse(
                {"status": "success", "intake_id": intake_id},
                status_code=HTTPStatus.OK,
            )
        ]

    def _get_fallback_team_id(self) -> str | None:
        """Get the fallback team ID for task assignment."""
        teams = Team.objects.filter(name__icontains="lab").all()
        if teams:
            return str(teams[0].id)

        teams = Team.objects.all()[:1]
        if teams:
            return str(teams[0].id)

        return None

    def _build_lab_report(
        self,
        patient_id: str,
        extraction_output: dict[str, Any],
        pdf_data: bytes,
    ) -> LabReport:
        """Build a LabReport from extraction output.

        Extend AI wraps extraction in { "value": {...}, "metadata": {...} }
        so we need to unwrap the value first.
        """
        # Unwrap Extend AI value wrapper
        values = extraction_output.get("value", extraction_output)

        effective_date = values.get("collection_date") or values.get(
            "report_date"
        )
        effective_date = self._normalize_datetime(effective_date)

        tests = self._parse_lab_tests(values)

        log.info(f"Building lab report for patient {patient_id}: {len(tests)} tests, date={effective_date}")

        return LabReport(
            patient_id=patient_id,
            effective_date=effective_date,
            tests=tests,
            pdf_data=pdf_data,
        )

    def _parse_lab_tests(self, extraction_values: dict[str, Any]) -> list[LabTest]:
        """Parse lab tests from Extend AI extraction output.

        The extraction_values should be the unwrapped 'value' from Extend AI output.
        Expected schema fields: test_results array with test_name, result_value, unit,
        reference_range, abnormal_flag.
        Panel-level fields: lab_test_name, lab_test_loinc, lab_test_loinc_source.
        """
        tests: list[LabTest] = []

        # Look for test results - schema uses 'test_results'
        raw_results = (
            extraction_values.get("test_results")
            or extraction_values.get("tests")
            or extraction_values.get("results")
            or extraction_values.get("panels")
            or []
        )

        effective_date = extraction_values.get("collection_date") or extraction_values.get(
            "report_date"
        )
        effective_date = self._normalize_datetime(effective_date)

        # For lipid panels and similar, all results are typically in one panel
        # Create a single LabTest to hold all values
        if raw_results:
            # Get panel-level name and LOINC from extraction
            panel_name = (
                extraction_values.get("lab_test_name")
                or extraction_values.get("panel_name")
                or "Laboratory Panel"
            )
            panel_loinc = (
                extraction_values.get("lab_test_loinc")
                or extraction_values.get("panel_loinc")
            )

            test = LabTest(
                code=panel_loinc if panel_loinc else "laboratory",
                display=panel_name,
                effective_date=effective_date,
            )

            for raw_result in raw_results:
                if not isinstance(raw_result, dict):
                    continue

                # Map schema field names to LabValue
                # Schema: test_name, result_value, unit, reference_range, abnormal_flag
                test_name = (
                    raw_result.get("test_name")
                    or raw_result.get("name")
                    or "Unknown Test"
                )

                result_value = raw_result.get("result_value") or raw_result.get("value")

                unit = raw_result.get("unit") or raw_result.get("units")

                reference_range = (
                    raw_result.get("reference_range")
                    or raw_result.get("ref_range")
                )

                # Check for abnormal flag - can be string like "H", "L", "A" or boolean
                abnormal_flag = raw_result.get("abnormal_flag") or raw_result.get("abnormal")
                is_abnormal = bool(abnormal_flag) if abnormal_flag else False

                # Get LOINC code if available from extraction
                loinc_code = raw_result.get("loinc") or raw_result.get("loinc_code")

                value = LabValue(
                    code=loinc_code if loinc_code else "unknown",
                    display=test_name,
                    value=result_value,
                    unit=unit,
                    reference_range_text=reference_range,
                    is_abnormal=is_abnormal,
                )
                test.values.append(value)

            if test.values:
                tests.append(test)

        return tests

    def _get_s3_client(self) -> S3Client:
        """Create S3 client from secrets."""
        return S3Client(
            aws_key=self.secrets.get(Secrets.AWS_ACCESS_KEY_ID, ""),
            aws_secret=self.secrets.get(Secrets.AWS_SECRET_ACCESS_KEY, ""),
            bucket=S3Config.BUCKET,
            region=S3Config.REGION,
            instance=self.environment.get("CUSTOMER_IDENTIFIER", "unknown"),
        )

    def _get_extend_client(self) -> ExtendClient:
        """Create Extend AI client from secrets."""
        return ExtendClient(
            api_key=self.secrets.get(Secrets.EXTEND_AI_KEY, ""),
        )

    def _get_llm_client(self) -> LLMClient:
        """Create LLM client from secrets."""
        return LLMClient(
            api_key=self.secrets.get(Secrets.ANTHROPIC_API_KEY, ""),
        )

    def _normalize_datetime(self, date_str: str | None) -> str:
        """Normalize a date string to full ISO 8601 datetime format.

        FHIR requires full datetime format (e.g., 2024-01-15T00:00:00Z).
        Extend AI extraction may return just a date (e.g., 2024-01-15).

        Args:
            date_str: Date string in various formats, or None

        Returns:
            Full ISO 8601 datetime string
        """
        if not date_str:
            return datetime.now(timezone.utc).isoformat()

        # If it already has time component, return as-is
        if "T" in date_str:
            # Ensure it has timezone
            if not date_str.endswith("Z") and "+" not in date_str and "-" not in date_str[-6:]:
                return f"{date_str}Z"
            return date_str

        # Date only - add midnight UTC time
        # Handle various date formats
        try:
            # Try ISO format (YYYY-MM-DD)
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
            return parsed.strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            pass

        try:
            # Try US format (MM/DD/YYYY)
            parsed = datetime.strptime(date_str, "%m/%d/%Y")
            return parsed.strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            pass

        try:
            # Try US format with 2-digit year (MM/DD/YY)
            parsed = datetime.strptime(date_str, "%m/%d/%y")
            return parsed.strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            pass

        # Fallback to current time if parsing fails
        log.warning(f"Could not parse date '{date_str}', using current time")
        return datetime.now(timezone.utc).isoformat()

    def _get_fhir_client(self) -> FHIRClient:
        """Create FHIR client from secrets."""
        return FHIRClient(
            client_id=self.secrets.get(Secrets.FHIR_CLIENT_ID, ""),
            client_secret=self.secrets.get(Secrets.FHIR_CLIENT_SECRET, ""),
            instance=self.environment.get("CUSTOMER_IDENTIFIER", "unknown"),
        )

    @api.get("/health")
    def health_check(self) -> list[Response | Effect]:
        """Health check endpoint (unauthenticated)."""
        return [
            JSONResponse(
                {"status": "healthy", "service": "lab-intake"},
                status_code=HTTPStatus.OK,
            )
        ]
