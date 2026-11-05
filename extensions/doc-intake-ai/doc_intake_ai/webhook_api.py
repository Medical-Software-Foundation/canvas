"""Extend AI webhook receiver for async extraction results."""

import json
from http import HTTPStatus
from typing import Any

import requests

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPIRoute
from logger import log

from doc_intake_ai.constants import CACHE_TIMEOUT
from doc_intake_ai.effects import (
    build_assign_reviewer_effect,
    build_categorize_effect,
    build_link_patient_effect,
)
from doc_intake_ai.extend_client import (
    parse_categorization_result,
    parse_template_result,
    start_template_extraction,
)
from doc_intake_ai.match import find_patient, find_reviewer
from doc_intake_ai.models import FeatureConfig, PatientMatch, ReviewerMatch
from doc_intake_ai.templates import (
    build_prefill_effect,
    build_prefill_fields_for_candidate,
    get_template_extraction_context,
    score_and_match_templates,
)
from doc_intake_ai.webhook_auth import verify_hmac


class ExtendWebhookAPI(SimpleAPIRoute):
    """Receives Extend AI webhook callbacks for async extraction results."""

    PATH = "/webhook/result"

    def authenticate(self, credentials: Credentials) -> bool:
        return True

    def post(self) -> list[Response | Effect]:
        raw_body = self.request.body
        timestamp = self.request.headers.get("x-extend-request-timestamp", "")
        signature = self.request.headers.get("x-extend-request-signature", "")
        secret = self.secrets.get("EXTEND_WEBHOOK_SECRET", "")

        if not verify_hmac(raw_body, timestamp, signature, secret):
            log.warning("[WEBHOOK] HMAC verification failed")
            return [JSONResponse({"error": "invalid signature"}, status_code=HTTPStatus.UNAUTHORIZED)]

        event = self.request.json()
        event_type = event.get("eventType", "")
        data = event.get("payload")

        processor_run = _resolve_data(data)
        if processor_run is None:
            log.error("[WEBHOOK] Could not resolve processor run data")
            return [JSONResponse({"status": "ok"})]

        run_id = processor_run.get("id", "")
        if not run_id:
            log.error("[WEBHOOK] Missing run ID in webhook payload")
            return [JSONResponse({"status": "ok"})]

        cache = get_cache()
        cache_key = f"extend_run:{run_id}"
        cached_raw = cache.get(cache_key)

        if not cached_raw:
            log.info("[WEBHOOK] Cache miss for run %s (already processed or expired)", run_id)
            return [JSONResponse({"status": "ok"})]

        cache.delete(cache_key)
        context = json.loads(cached_raw)

        if event_type == "extract_run.failed":
            reason = processor_run.get("error", {}).get("message", "unknown")
            log.error("[WEBHOOK] Run %s failed: %s", run_id, reason)
            return [JSONResponse({"status": "ok"})]

        phase = context.get("phase")
        if phase == 1:
            return self._handle_phase1(processor_run, context)
        if phase == 2:
            return self._handle_phase2(processor_run, context)

        log.error("[WEBHOOK] Unknown phase %s for run %s", phase, run_id)
        return [JSONResponse({"status": "ok"})]

    def _handle_phase1(
        self,
        processor_run: dict[str, Any],
        context: dict[str, Any],
    ) -> list[Response | Effect]:
        """Process Phase 1 webhook: categorize, match, assign, start Phase 2."""
        doc_id = context["document_id"]
        available_types = context["available_types"]
        config = FeatureConfig(**context["config"])
        content_url = context["content_url"]

        api_key = self.secrets.get("EXTEND_API_KEY")
        processor_id = self.secrets.get("EXTEND_EXTRACTOR_ID")
        default_reviewer = self.secrets.get("DEFAULT_REVIEWER")

        result = parse_categorization_result(processor_run, available_types)
        if result.error:
            log.error("[WEBHOOK] Categorization parse error: %s", result.error)
            return [JSONResponse({"status": "ok"})]

        patient_match = find_patient(result.extraction) if config.match_patient else PatientMatch()
        reviewer_match = (
            find_reviewer(result.extraction, default_reviewer=default_reviewer)
            if config.assign_reviewer
            else ReviewerMatch()
        )

        if patient_match.error:
            log.warning("[WEBHOOK] Patient match issue: %s", patient_match.error)

        effects: list[Effect] = []

        if result.document_type and config.classify:
            effect = build_categorize_effect(
                doc_id, result.document_type, result.confidence, patient_match.error,
            )
            if effect:
                effects.append(effect)

        if config.match_patient and patient_match.found:
            effect = build_link_patient_effect(
                doc_id, patient_match.patient, result.confidence,
            )
            if effect:
                effects.append(effect)

        if config.assign_reviewer and reviewer_match.found:
            effect = build_assign_reviewer_effect(
                doc_id, reviewer_match.reviewer, reviewer_match.auto_assigned,
                result.confidence, patient_match.error,
            )
            if effect:
                effects.append(effect)

        if result.document_type and config.prefill_templates:
            template_type = result.document_type.get("template_type")
            if template_type and api_key and processor_id:
                self._start_phase2(
                    template_type, result, content_url,
                    doc_id, api_key, processor_id, config, default_reviewer,
                )
            elif template_type:
                log.error("[WEBHOOK] Missing Extend AI credentials, skipping Phase 2 for document %s", doc_id)

        log.info("[WEBHOOK] Phase 1 complete for document %s, %d effects", doc_id, len(effects))
        return [JSONResponse({"status": "ok"})] + effects

    def _start_phase2(
        self,
        template_type: str,
        result: Any,
        content_url: str,
        doc_id: str,
        api_key: str,
        processor_id: str,
        config: FeatureConfig,
        default_reviewer: str | None,
    ) -> None:
        """Start one combined Phase 2 extraction for all matched templates."""
        match_result = score_and_match_templates(template_type, result.extraction, content_url)
        if not match_result:
            return

        candidates, field_model, codes = match_result
        matched_codes: set[str] = set()
        combined_properties: dict[str, Any] = {}
        qualified: list[dict[str, Any]] = []

        for i, candidate in enumerate(candidates):
            is_gap_fill = i > 0
            extraction_ctx = get_template_extraction_context(
                candidate, codes, matched_codes, field_model, is_gap_fill,
            )
            if not extraction_ctx:
                continue

            schema, key_map = extraction_ctx
            combined_properties.update(schema["schema"]["properties"])

            serializable_key_map = {
                k: {"code": getattr(v, "code", None), "label": getattr(v, "label", None), "units": getattr(v, "units", None)}
                for k, v in key_map.items()
            }
            qualified.append({"candidate": candidate, "key_map": serializable_key_map})
            matched_codes.update(candidate["codes"])

            if matched_codes >= codes:
                break

        if not qualified:
            return

        combined_schema = {
            "type": "EXTRACT",
            "baseProcessor": "extraction_performance",
            "baseVersion": "4.6.0",
            "schema": {"type": "object", "properties": combined_properties},
            "advancedOptions": {"citationsEnabled": True},
        }

        run_id = start_template_extraction(content_url, combined_schema, api_key, processor_id)
        if not run_id:
            log.warning("[WEBHOOK] Failed to start combined Phase 2")
            return

        cache_payload = json.dumps({
            "phase": 2,
            "document_id": doc_id,
            "candidates": qualified,
            "confidence": result.confidence,
        })
        get_cache().set(f"extend_run:{run_id}", cache_payload, CACHE_TIMEOUT)
        log.info("[WEBHOOK] Started combined Phase 2 run %s for %d templates", run_id, len(qualified))

    def _handle_phase2(
        self,
        processor_run: dict[str, Any],
        context: dict[str, Any],
    ) -> list[Response | Effect]:
        """Process Phase 2 webhook: build one prefill effect from all candidates."""
        doc_id = context["document_id"]
        candidates_raw = context["candidates"]
        confidence = context.get("confidence")

        extraction_data, metadata = parse_template_result(processor_run)

        class FieldProxy:
            def __init__(self, data: dict[str, Any]) -> None:
                self.code = data.get("code")
                self.label = data.get("label")
                self.units = data.get("units")

        templates: list[dict[str, Any]] = []
        for entry in candidates_raw:
            candidate = entry["candidate"]
            key_map = {k: FieldProxy(v) for k, v in entry["key_map"].items()}

            template = build_prefill_fields_for_candidate(
                extraction_data, metadata, key_map, candidate, confidence,
            )
            if template:
                templates.append(template)

        effects: list[Effect] = []
        if templates:
            effect = build_prefill_effect(doc_id, templates, confidence)
            if effect:
                effects.append(effect)

        log.info("[WEBHOOK] Phase 2 complete for document %s, %d templates, %d effects", doc_id, len(templates), len(effects))
        return [JSONResponse({"status": "ok"})] + effects


def _resolve_data(data: Any) -> dict[str, Any] | None:
    """Resolve webhook data, handling signed URL payloads."""
    if isinstance(data, str):
        try:
            response = requests.get(data, timeout=30)
            if response.status_code != 200:
                log.error("[WEBHOOK] Failed to fetch signed URL: %s", response.status_code)
                return None
            resolved: dict[str, Any] = response.json()
            return resolved
        except requests.RequestException as e:
            log.error("[WEBHOOK] Error fetching signed URL: %s", e)
            return None

    if isinstance(data, dict):
        return data

    return None
