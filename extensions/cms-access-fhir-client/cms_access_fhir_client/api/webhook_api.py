"""Public webhook endpoint receiving CMS FHIR Subscription notifications.

Authentication: shared secret in X-Access-Webhook-Secret header, validated with
hmac.compare_digest() to prevent timing attacks. Fails closed if the secret is
not configured. Missing or wrong header → 401, no further processing.

TODO: Swap to HMAC signature once CMS publishes their authentication spec.
"""
from datetime import datetime, timezone
from hmac import compare_digest
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.task import AddTask
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from logger import log

from cms_access_fhir_client.models import ACCESSAlignment, ACCESSWebhookEvent
from cms_access_fhir_client.models.access_alignment import CustomPatient


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AccessWebhookApi(SimpleAPI):
    """Receive and dispatch CMS FHIR Subscription notification events.

    External-facing endpoint called by CMS, not Canvas staff.
    Authentication via shared secret in X-Access-Webhook-Secret header.
    """

    def authenticate(self, credentials: Credentials) -> bool:
        """Validate the X-Access-Webhook-Secret header. Fails closed."""
        expected_secret = self.secrets.get("ACCESS_WEBHOOK_SECRET")
        if not expected_secret:
            log.error(
                "[cms-access] ACCESS_WEBHOOK_SECRET not configured — "
                "rejecting all webhook requests (fail closed)"
            )
            return False

        provided_secret = self.request.headers.get("X-Access-Webhook-Secret", "")
        if not provided_secret:
            log.warning("[cms-access] Webhook rejected: missing X-Access-Webhook-Secret header")
            return False

        # compare_digest prevents timing-based secret inference
        if not compare_digest(provided_secret.encode(), expected_secret.encode()):
            log.warning("[cms-access] Webhook rejected: bad X-Access-Webhook-Secret")
            return False

        return True

    @api.post("/webhook")
    def receive_webhook(self) -> list[Response | Effect]:

        payload = self.request.json()
        event_type = _extract_event_type(payload)
        patient_id = _extract_patient_id(payload)
        alignment_id = _extract_alignment_id(payload)

        webhook_event = ACCESSWebhookEvent(
            event_type=event_type,
            alignment_id=alignment_id or "",
            raw_payload=payload,
            processing_status=ACCESSWebhookEvent.STATUS_PENDING,
        )
        if patient_id:
            try:
                patient = CustomPatient.objects.get(id=patient_id)
                webhook_event.patient = patient
            except CustomPatient.DoesNotExist:
                log.warning(
                    f"[cms-access] Webhook patient_id {patient_id!r} not found in Canvas"
                )
        webhook_event.save()

        effects = _dispatch(event_type, payload, webhook_event, self.secrets)

        webhook_event.processed_at = _utcnow()
        webhook_event.processing_status = ACCESSWebhookEvent.STATUS_OK
        webhook_event.save()

        return [JSONResponse({"received": True}, status_code=HTTPStatus.OK)] + effects


def _dispatch(
    event_type: str,
    payload: dict,
    webhook_event: ACCESSWebhookEvent,
    secrets: dict,
) -> list[Effect]:
    """Route to the appropriate handler based on CMS event type."""
    handlers = {
        ACCESSWebhookEvent.EVENT_LOCK_IN_ENDING: _handle_lock_in_ending,
        ACCESSWebhookEvent.EVENT_REPORTING_DUE_BASELINE: _handle_reporting_due,
        ACCESSWebhookEvent.EVENT_REPORTING_DUE_QUARTERLY: _handle_reporting_due,
        ACCESSWebhookEvent.EVENT_REPORTING_DUE_END_OF_PERIOD: _handle_reporting_due,
        ACCESSWebhookEvent.EVENT_RENEWAL_DUE: _handle_renewal_due,
        ACCESSWebhookEvent.EVENT_UNALIGNMENT_CMS: _handle_unalignment_cms,
        ACCESSWebhookEvent.EVENT_UNALIGNMENT_PARTICIPANT: _handle_unalignment_participant,
    }

    handler = handlers.get(event_type)
    if not handler:
        log.warning(f"[cms-access] Unrecognised webhook event_type: {event_type!r}")
        return []

    return handler(payload, webhook_event)


def _handle_lock_in_ending(payload: dict, webhook_event: ACCESSWebhookEvent) -> list[Effect]:
    """Provider Lock-In Period Ending — update local state and surface a banner."""
    alignment = _find_alignment(webhook_event)
    if alignment:
        alignment.save()

    effects: list[Effect] = []
    patient_id = _webhook_patient_id(webhook_event)
    if patient_id:
        effects.append(
            AddBannerAlert(
                patient_id=patient_id,
                key="access-lock-in-ending",
                narrative="ACCESS lock-in period ending soon — review alignment",
                placement=[AddBannerAlert.Placement.CHART],
                intent=AddBannerAlert.Intent.WARNING,
            ).apply()
        )
    return effects


def _handle_reporting_due(payload: dict, webhook_event: ACCESSWebhookEvent) -> list[Effect]:
    """Data Reporting Due (any variant) — mark reporting period and create a staff task."""
    variant_map = {
        ACCESSWebhookEvent.EVENT_REPORTING_DUE_BASELINE: "Baseline",
        ACCESSWebhookEvent.EVENT_REPORTING_DUE_QUARTERLY: "Quarterly",
        ACCESSWebhookEvent.EVENT_REPORTING_DUE_END_OF_PERIOD: "End-of-Period",
    }
    variant = variant_map.get(webhook_event.event_type, "")

    patient_id = _webhook_patient_id(webhook_event)
    if not patient_id:
        log.warning("[cms-access] reporting-due event had no patient_id — cannot create task")
        return []

    # TODO: When $report-data is implemented, link the task to the actual API call.
    task = AddTask(
        patient_id=patient_id,
        title=f"ACCESS {variant} data reporting due — submit $report-data",
        labels=["ACCESS", "reporting"],
    )
    return [task.apply()]


def _handle_renewal_due(payload: dict, webhook_event: ACCESSWebhookEvent) -> list[Effect]:
    """Alignment Renewal Due — update local state and create a staff task."""
    alignment = _find_alignment(webhook_event)
    if alignment:
        alignment.tier = ACCESSAlignment.TIER_RENEWAL
        alignment.save()

    patient_id = _webhook_patient_id(webhook_event)
    if not patient_id:
        return []

    task = AddTask(
        patient_id=patient_id,
        title="ACCESS alignment renewal due — confirm renewal with patient",
        labels=["ACCESS", "renewal"],
    )
    return [task.apply()]


def _handle_unalignment_cms(payload: dict, webhook_event: ACCESSWebhookEvent) -> list[Effect]:
    """CMS-initiated unalignment — mark alignment inactive, store reason, log."""
    alignment = _find_alignment(webhook_event)
    if alignment:
        alignment.status = ACCESSAlignment.STATUS_UNALIGNED
        alignment.unalignment_reason = _extract_reason(payload)
        alignment.save()
        log.info(
            f"[cms-access] CMS-initiated unalignment for alignment_id="
            f"{webhook_event.alignment_id!r}"
        )
    return []


def _handle_unalignment_participant(
    payload: dict, webhook_event: ACCESSWebhookEvent
) -> list[Effect]:
    """Participant-initiated unalignment confirmation — mark alignment inactive."""
    alignment = _find_alignment(webhook_event)
    if alignment:
        alignment.status = ACCESSAlignment.STATUS_UNALIGNED
        alignment.save()
        log.info(
            f"[cms-access] Participant-initiated unalignment confirmed for "
            f"alignment_id={webhook_event.alignment_id!r}"
        )
    return []


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _extract_event_type(payload: dict) -> str:
    """Extract subscription event type from FHIR SubscriptionStatus resource."""
    # CMS sends a Bundle containing a SubscriptionStatus resource
    for entry in payload.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "SubscriptionStatus":
            for param in resource.get("parameter", []):
                if param.get("name") == "eventType":
                    return param.get("valueCode", "")
    # Fallback: top-level type field (simpler implementations)
    return payload.get("eventType", "unknown")


def _extract_patient_id(payload: dict) -> str | None:
    """Best-effort extraction of Canvas patient ID from the notification."""
    for entry in payload.get("entry", []):
        resource = entry.get("resource", {})
        subject = resource.get("subject", {})
        ref = subject.get("reference", "")
        if ref.startswith("Patient/"):
            return ref.split("/", 1)[1]
    return None


def _extract_alignment_id(payload: dict) -> str | None:
    for entry in payload.get("entry", []):
        resource = entry.get("resource", {})
        for param in resource.get("parameter", []):
            if param.get("name") == "alignmentId":
                return param.get("valueString")
    return None


def _extract_reason(payload: dict) -> str:
    for entry in payload.get("entry", []):
        resource = entry.get("resource", {})
        for param in resource.get("parameter", []):
            if param.get("name") == "reasonCode":
                return param.get("valueCode", "")
    return ""


def _find_alignment(webhook_event: ACCESSWebhookEvent) -> ACCESSAlignment | None:
    if not webhook_event.alignment_id:
        return None
    return ACCESSAlignment.objects.filter(
        alignment_id=webhook_event.alignment_id
    ).first()


def _webhook_patient_id(webhook_event: ACCESSWebhookEvent) -> str | None:
    try:
        return str(webhook_event.patient.id) if webhook_event.patient_id else None
    except AttributeError:
        return None
