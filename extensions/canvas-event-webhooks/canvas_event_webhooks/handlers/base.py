"""
Shared webhook dispatch logic for all canvas_event_webhooks handlers.

Every handler in this plugin inherits from ``WebhookDispatcherBase`` and
calls ``self._dispatch()`` from its ``compute()`` method. The base class
handles payload construction, per-webhook HMAC-SHA256 signing, async
delivery, and automatic retries on transient failures — keeping each
per-category handler thin and focused on just its ``RESPONDS_TO`` list.

PHI / HIPAA notice
------------------
Canvas is a healthcare EMR. Event contexts can contain Protected Health
Information. This plugin defaults to a **minimal, ID-only payload** — the
``context`` block contains only opaque record identifiers (UUIDs / integer
keys), never clinical content, document URLs, free-text notes, or payment
details.

To receive the full raw Canvas context (which *may* include PHI fields such
as ``content_url``, ``message_to_patient``, ``internal_comment``, and payment
amounts) set ``include-context`` to ``"true"``. Do so only when:
  - your receiving endpoint is within your own HIPAA-compliant infrastructure,
  - the data transfer is covered by your BAA with Canvas Medical, and
  - you understand which event types carry rich context (see README).

Per-webhook ``include_details`` (UI toggle, default off) adds names and major
record fields without dumping the raw Canvas context. That toggle is PHI.

Payload format
--------------
Default (``include-context`` not set / ``false``, ``include_details`` off):

    {
        "id":          "<uuid4>",
        "event":       "APPOINTMENT_CREATED",
        "occurred_at": "2026-09-01T12:00:00.123456+00:00",
        "source":      "canvas",
        "version":     "1",
        "patient_id":  "<pt_key>",   // patient-related events only
        "target": {
            "id":   "<record UUID or integer key>",
            "type": "<model name, e.g. Appointment>"
        },
        "context": {                    // IDs only — no PHI
            "patient_id": "<pt_key>",   // present when available
            "note_id":    "<note_uuid>",
            "state":      "<str>"       // note-state events only
        }
    }

With ``include_details`` enabled the same envelope also includes
``description``, ``actor``, ``patient`` (with names), and ``data``.

If a webhook secret is configured the request also carries:

    X-Canvas-Timestamp: <unix seconds>
    X-Canvas-Signature: t=<unix seconds>,v1=<HMAC-SHA256 hex of "{timestamp}.{body}">

Receivers should validate the signature and reject timestamps older than
five minutes (replay protection). Each webhook is signed with **its own**
secret. HTTP URLs are rejected; only HTTPS is delivered.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.http_request import HttpRequestEffect
from canvas_sdk.handlers import BaseHandler
from logger import log

from canvas_event_webhooks.config_store import (
    WebhookConfig,
    WebhookConfigStore,
    is_https_url,
)
from canvas_event_webhooks.event_details import enrich_event
from canvas_event_webhooks.events_catalog import is_patient_related

# Retry on these HTTP status codes — covers rate-limits and transient
# server/gateway errors without retrying permanent client-side failures.
_RETRY_ON: list[int] = [429, 500, 502, 503, 504]
_MAX_RETRIES: int = 3

SIGNATURE_HEADER = "X-Canvas-Signature"
TIMESTAMP_HEADER = "X-Canvas-Timestamp"
# Receivers should reject signatures whose timestamp is older than this.
SIGNATURE_MAX_AGE_SECONDS = 300


def extract_patient_id(event: Any) -> str | None:
    """
    Extract a patient identifier from a Canvas event.

    Checks, in order:
      1. ``context["patient"]["id"]`` (nested patient object)
      2. ``context["patient_id"]`` (top-level key used by some note-state events)
      3. ``patient_id`` nested on common related-record dicts (appointment, note,
         task, prescription, etc.)
    Returns None when no patient relationship can be found. Never fabricates an id.
    """
    raw = getattr(event, "context", None) or {}
    if not isinstance(raw, dict):
        return None

    patient = raw.get("patient")
    if isinstance(patient, dict) and patient.get("id") not in (None, ""):
        return str(patient["id"])

    if raw.get("patient_id") not in (None, ""):
        return str(raw["patient_id"])

    for key in (
        "appointment",
        "note",
        "task",
        "prescription",
        "medication",
        "document",
        "message",
        "order",
        "lab_order",
        "lab_report",
        "claim",
        "coverage",
        "letter",
    ):
        obj = raw.get(key)
        if not isinstance(obj, dict):
            continue
        if obj.get("patient_id") not in (None, ""):
            return str(obj["patient_id"])
        nested = obj.get("patient")
        if isinstance(nested, dict) and nested.get("id") not in (None, ""):
            return str(nested["id"])

    return None


def sign_body(secret: str, body: str, timestamp: int) -> str:
    """Return ``t=<unix>,v1=<hex>`` for HMAC-SHA256(secret, ``{timestamp}.{body}``)."""
    digest = hmac.new(
        secret.encode(),
        f"{timestamp}.{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def signature_headers(secret: str, body: str, timestamp: int | None = None) -> dict[str, str]:
    """Timestamp + signature headers for an outbound webhook POST."""
    ts = int(datetime.now(timezone.utc).timestamp()) if timestamp is None else int(timestamp)
    return {
        TIMESTAMP_HEADER: str(ts),
        SIGNATURE_HEADER: sign_body(secret, body, ts),
    }


class WebhookDispatcherBase(BaseHandler):
    """
    Base class for all webhook-dispatching event handlers.

    Subclasses only need to declare ``RESPONDS_TO`` and call
    ``return self._dispatch()`` from ``compute()``.
    """

    def _safe_context(self, raw: dict) -> dict:
        """
        Extract only opaque record identifiers from the raw Canvas event
        context — no clinical content, document URLs, free-text, or payment
        details.

        This is the default behaviour. To receive the full, unfiltered context
        set the ``include-context`` plugin secret to ``"true"``.
        """
        safe: dict = {}
        # Patient key — present on almost every clinical event.
        patient = raw.get("patient")
        if isinstance(patient, dict) and patient.get("id"):
            safe["patient_id"] = patient["id"]
        # Some note-state events use top-level keys instead of nested dicts.
        for key in ("patient_id", "note_id"):
            if key in raw and key not in safe:
                safe[key] = raw[key]
        # Note UUID nested dict form.
        note = raw.get("note")
        if isinstance(note, dict) and note.get("uuid"):
            safe.setdefault("note_id", note["uuid"])
        # Appointment key.
        appt = raw.get("appointment")
        if isinstance(appt, dict) and appt.get("id"):
            safe["appointment_id"] = appt["id"]
        # Note state string — not PHI.
        if "state" in raw:
            safe["state"] = raw["state"]
        return safe

    def _event_name(self) -> str:
        from canvas_sdk.events import EventType  # local import avoids circular

        try:
            return EventType.Name(self.event.type)
        except ValueError:
            return str(self.event.type)

    def _build_payload(self, event_name: str) -> dict:
        target_id: str | None = None
        target_type: str | None = None
        if self.event.target:
            raw_id = getattr(self.event.target, "id", None)
            target_id = str(raw_id) if raw_id is not None else None
            raw_type = getattr(self.event.target, "type", None)
            if raw_type is not None:
                # type is sometimes a model class, sometimes already a string
                target_type = getattr(raw_type, "__name__", str(raw_type))

        include_context = (
            (self.secrets.get("include-context") or "").strip().lower() == "true"
        )
        raw_ctx: dict = self.event.context or {}
        context_block = raw_ctx if include_context else self._safe_context(raw_ctx)

        payload: dict = {
            "id": str(uuid.uuid4()),
            "event": event_name,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "canvas",
            "version": "1",
            "target": {"id": target_id, "type": target_type},
            "context": context_block,
        }
        if is_patient_related(event_name):
            payload["patient_id"] = extract_patient_id(self.event)
        return payload

    def _effect_for_webhook(self, webhook: WebhookConfig, body: str) -> Effect:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        secret = (webhook.secret or "").strip()
        if secret:
            headers.update(signature_headers(secret, body))
        return (
            HttpRequestEffect(
                url=webhook.url,
                method="POST",
                headers=headers,
                body=body,
                retry_on_status_codes=_RETRY_ON,
            )
            .apply()
            .set_async(max_retries=_MAX_RETRIES)
        )

    def _resolve_webhooks(self, event_name: str) -> list[WebhookConfig]:
        return WebhookConfigStore(secrets=self.secrets).active_webhooks_for_event(
            event_name
        )

    def _dispatch(self, webhooks: list[WebhookConfig] | None = None) -> list[Effect]:
        """
        Build the outbound webhook payload and return one async
        ``HttpRequestEffect`` per matching enabled webhook.

        ``webhooks`` may be injected by tests. When omitted, configs are
        loaded from the store (UI-saved AttributeHub records, or the legacy
        CLI ``webhook-url`` / ``webhook-secret`` fallback).

        Returns an empty list when no matching webhook is configured.

        Retries are handled by the Canvas platform's async task runner
        (not inline) — ``compute()`` returns immediately. One webhook's
        failure does not prevent the others from being queued.
        """
        event_name = self._event_name()
        payload = self._build_payload(event_name)

        if webhooks is None:
            webhooks = self._resolve_webhooks(event_name)
        else:
            webhooks = [wh for wh in webhooks if wh.accepts(event_name)]

        if not webhooks:
            log.info(
                "[Webhooks] No matching webhooks for event=%s; dropping.",
                event_name,
            )
            return []

        details = None
        if any(wh.include_details for wh in webhooks):
            details = enrich_event(self.event, event_name, payload.get("patient_id"))

        effects: list[Effect] = []
        for webhook in webhooks:
            if not is_https_url(webhook.url):
                log.warning(
                    "[Webhooks] Skipping non-HTTPS webhook=%s event=%s",
                    webhook.name,
                    event_name,
                )
                continue
            log.info(
                "[Webhooks] Delivery started webhook=%s event=%s retries=%s",
                webhook.name,
                event_name,
                _MAX_RETRIES,
            )
            try:
                body_payload = payload
                if webhook.include_details and details:
                    body_payload = dict(payload)
                    body_payload.update(details)
                body = json.dumps(body_payload, default=str)
                effects.append(self._effect_for_webhook(webhook, body))
            except Exception:
                # Never let one webhook's construction failure block the rest.
                log.exception(
                    "[Webhooks] Delivery failed webhook=%s event=%s",
                    webhook.name,
                    event_name,
                )
        return effects
