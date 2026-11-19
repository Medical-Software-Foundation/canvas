"""Extend AI HTTP client for document extraction."""

import re
import time
from typing import Any

import requests
from pydantic import ValidationError

from logger import log

from doc_intake_ai.constants import API_URL, API_VERSION, MAX_RETRIES
from doc_intake_ai.models import CategorizationResult, DocumentExtraction


def start_categorization(
    content_url: str,
    available_types: list[dict[str, Any]],
    api_key: str,
    processor_id: str,
) -> str | None:
    """Phase 1: Start async categorization and return run ID.

    Builds the extraction schema from available_types and POSTs to Extend AI
    with sync=False. Returns the run ID on success, None on failure.
    """
    if not content_url:
        log.error("[EXTEND] Missing content URL for categorization")
        return None

    slug_map = _build_slug_map(available_types)
    schema = _build_extraction_schema(list(slug_map.keys()))

    return start_extraction(api_key, processor_id, content_url, schema)


def start_template_extraction(
    content_url: str,
    fields_schema: dict[str, Any],
    api_key: str,
    processor_id: str,
) -> str | None:
    """Phase 2: Start async template field extraction and return run ID."""
    if not content_url:
        log.error("[EXTEND] Missing content URL for template extraction")
        return None

    return start_extraction(api_key, processor_id, content_url, fields_schema)


def start_extraction(
    api_key: str,
    processor_id: str,
    file_url: str,
    config: dict[str, Any],
) -> str | None:
    """POST to /processor_runs with async mode. Returns run ID or None."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-extend-api-version": API_VERSION,
    }
    payload = {
        "processorId": processor_id,
        "file": {"fileUrl": file_url},
        "config": config,
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
            if response.status_code < 400:
                data = response.json()
                run_id: str | None = data.get("processorRun", {}).get("id")
                if run_id:
                    log.info("[EXTEND] Started run %s", run_id)
                    return run_id
                log.error("[EXTEND] No run ID in response")
                return None

            if response.status_code < 500:
                log.error("[EXTEND] Client error %d: %s", response.status_code, _format_error(response))
                return None

            if attempt < MAX_RETRIES:
                log.warning("[EXTEND] Retry %d after status %d", attempt + 1, response.status_code)
                time.sleep(attempt + 1)

        except requests.RequestException as e:
            log.warning("[EXTEND] Request error: %s", e)
            if attempt >= MAX_RETRIES:
                return None
            time.sleep(attempt + 1)

    return None


def parse_categorization_result(
    processor_run: dict[str, Any],
    available_types: list[dict[str, Any]],
) -> CategorizationResult:
    """Parse a webhook processorRun payload into a CategorizationResult."""
    output = processor_run.get("output", {})
    extraction_raw = output.get("value", {})
    metadata = output.get("metadata")

    slug_map = _build_slug_map(available_types)
    extraction = _parse_extraction(extraction_raw)
    doc_slug = extraction.document_type or extraction_raw.get("document_type")
    matched_type = slug_map.get(doc_slug) if doc_slug else None

    confidence = _parse_min_confidence(metadata)

    log.info(
        "[EXTRACT] type=%s confidence=%s",
        matched_type.get("name") if matched_type else None,
        round(confidence, 2) if confidence else None,
    )

    return CategorizationResult(
        document_type=matched_type,
        extraction=extraction,
        metadata=metadata,
        confidence=confidence,
    )


def parse_template_result(
    processor_run: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Parse a webhook processorRun payload into template extraction data."""
    output = processor_run.get("output", {})
    return output.get("value", {}), output.get("metadata")


def _build_slug_map(available_types: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build mapping from slugified names to document types."""
    result: dict[str, dict[str, Any]] = {}
    for doc_type in available_types:
        name = doc_type.get("name")
        if name:
            slug = _slugify(name)
            if slug and slug not in result:
                result[slug] = doc_type
    return result


def _slugify(value: str) -> str:
    """Convert name to slug: 'Lab Report' -> 'lab_report'."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _build_extraction_schema(type_slugs: list[str]) -> dict[str, Any]:
    """Build Extend AI extraction schema for Phase 1."""
    properties: dict[str, Any] = {
        "document_type": {
            "type": "string",
            "description": "Document type classification",
        },
        "loinc_codes": {
            "type": ["string", "null"],
            "description": "Comma-separated LOINC codes found in the document",
        },
        "snomed_codes": {
            "type": ["string", "null"],
            "description": "Comma-separated SNOMED codes found in the document",
        },
        "test_names": {
            "type": ["string", "null"],
            "description": "Comma-separated lab test or study names",
        },
        "study_names": {
            "type": ["string", "null"],
            "description": "Comma-separated imaging study names",
        },
        "modality": {
            "type": ["string", "null"],
            "description": "Imaging modality (CT, MRI, X-ray, etc.)",
        },
        "body_part": {
            "type": ["string", "null"],
            "description": "Body part examined",
        },
        "patient_id": {
            "type": ["string", "null"],
            "description": "Patient MRN or ID number",
        },
        "patient_first_name": {
            "type": ["string", "null"],
            "description": "Patient first name",
        },
        "patient_last_name": {
            "type": ["string", "null"],
            "description": "Patient last name",
        },
        "patient_name": {
            "type": ["string", "null"],
            "description": "Patient full name if first/last not separately identified",
        },
        "date_of_birth": {
            "type": ["string", "null"],
            "description": "Patient date of birth in YYYY-MM-DD format",
        },
        "practitioner_npi": {
            "type": ["string", "null"],
            "description": "Ordering/referring provider NPI number",
        },
        "practitioner_first_name": {
            "type": ["string", "null"],
            "description": "Provider first name",
        },
        "practitioner_last_name": {
            "type": ["string", "null"],
            "description": "Provider last name",
        },
        "practitioner_name": {
            "type": ["string", "null"],
            "description": "Provider full name if first/last not separately identified",
        },
    }

    if type_slugs:
        properties["document_type"]["enum"] = type_slugs

    return {
        "type": "EXTRACT",
        "baseProcessor": "extraction_performance",
        "baseVersion": "4.6.0",
        "schema": {"type": "object", "properties": properties},
        "advancedOptions": {"citationsEnabled": True},
    }


def _parse_extraction(raw: dict[str, Any]) -> DocumentExtraction:
    """Parse raw extraction data into DocumentExtraction model."""
    try:
        return DocumentExtraction(**raw)
    except (ValidationError, TypeError):
        log.warning("[EXTEND] Could not parse extraction, using defaults")
        return DocumentExtraction()


def _parse_min_confidence(metadata: dict[str, Any] | None) -> float | None:
    """Extract lowest field confidence from API response metadata."""
    if not isinstance(metadata, dict):
        return None

    scores: list[float] = []
    for value in metadata.values():
        if isinstance(value, dict):
            conf = value.get("ocrConfidence")
            if isinstance(conf, (int, float)):
                scores.append(float(conf))

    return min(scores) if scores else None


def _format_error(response: requests.Response) -> str:
    """Format API error response."""
    try:
        data = response.json()
        msg = data.get("error", {}).get("message") or data.get("message")
        if msg:
            return f"Extend AI error: {msg}"
    except Exception:
        pass
    return f"Extend AI error: HTTP {response.status_code}"
