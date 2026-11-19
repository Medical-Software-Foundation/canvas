"""Document intake handler — starts async extraction and caches context."""

import json

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from logger import log

from doc_intake_ai.constants import CACHE_TIMEOUT
from doc_intake_ai.extend_client import start_categorization
from doc_intake_ai.models import FeatureConfig


class DocumentIntakeHandler(BaseProtocol):
    """Starts async Extend AI extraction and caches context for webhook delivery.

    Responds to DOCUMENT_RECEIVED events. Validates the document, starts an
    async Phase 1 extraction run, and stores context in the plugin cache
    keyed by the Extend AI run ID. The webhook handler picks up from there.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.DOCUMENT_RECEIVED),
    ]

    def compute(self) -> list[Effect]:
        """Start async extraction and cache context for webhook handler."""
        doc = self.event.context.get("document", {})
        doc_id = doc.get("id")
        content_url = doc.get("content_url")
        if not doc_id or not content_url:
            log.warning("[HANDLER] Missing document id or content_url")
            return []

        channel = doc.get("channel", "")
        config = FeatureConfig.from_secrets(self.secrets)

        if not config.is_channel_enabled(channel):
            log.info("[HANDLER] Skipping document %s from channel %s (channel not enabled)", doc_id, channel)
            return []

        log.info("[HANDLER] Feature config: %s", config.model_dump())

        available_types = self.event.context.get("available_document_types", [])

        api_key = self.secrets.get("EXTEND_API_KEY")
        processor_id = self.secrets.get("EXTEND_EXTRACTOR_ID")
        if not api_key or not processor_id:
            log.error("[HANDLER] Missing Extend AI credentials")
            return []

        run_id = start_categorization(content_url, available_types, api_key, processor_id)
        if not run_id:
            log.error("[HANDLER] Failed to start categorization for document %s", doc_id)
            return []

        cache = get_cache()
        cache_key = f"extend_run:{run_id}"
        cache_payload = json.dumps({
            "phase": 1,
            "document_id": doc_id,
            "content_url": content_url,
            "available_types": available_types,
            "config": config.model_dump(),
        })
        cache.set(cache_key, cache_payload, CACHE_TIMEOUT)

        log.info("[HANDLER] Cached context for run %s, document %s", run_id, doc_id)
        return []
