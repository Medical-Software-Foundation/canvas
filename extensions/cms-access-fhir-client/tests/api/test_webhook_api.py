"""Tests for AccessWebhookApi — authentication, dispatch, all 7 event types."""
import pytest
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(secrets=None):
    from cms_access_fhir_client.api.webhook_api import AccessWebhookApi
    handler = AccessWebhookApi.__new__(AccessWebhookApi)
    handler.secrets = {"ACCESS_WEBHOOK_SECRET": "correct-secret"} if secrets is None else secrets
    mock_request = MagicMock()
    handler.request = mock_request
    return handler, mock_request


def _subscription_payload(event_type, patient_ref=None, alignment_id=None, reason_code=None):
    """Build a minimal CMS FHIR SubscriptionStatus bundle."""
    params = [{"name": "eventType", "valueCode": event_type}]
    if alignment_id:
        params.append({"name": "alignmentId", "valueString": alignment_id})
    if reason_code:
        params.append({"name": "reasonCode", "valueCode": reason_code})

    resource: dict = {"resourceType": "SubscriptionStatus", "parameter": params}
    if patient_ref:
        resource["subject"] = {"reference": f"Patient/{patient_ref}"}

    entry = [{"resource": resource}]
    if patient_ref:
        entry.append({"resource": {"subject": {"reference": f"Patient/{patient_ref}"}}})

    return {"entry": entry}


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------

class TestAccessWebhookApiAuthentication:
    def test_returns_false_when_secret_not_configured(self):
        handler, mock_request = _make_handler(secrets={})
        mock_credentials = MagicMock()

        result = handler.authenticate(mock_credentials)

        assert result is False
        # Fails closed immediately — never touches the request headers
        assert mock_request.mock_calls == []
        assert mock_credentials.mock_calls == []

    def test_returns_false_when_header_missing(self):
        handler, mock_request = _make_handler()
        mock_request.headers.get.return_value = ""
        mock_credentials = MagicMock()

        result = handler.authenticate(mock_credentials)

        assert result is False
        assert mock_request.mock_calls == [
            call.headers.get("X-Access-Webhook-Secret", ""),
        ]
        assert mock_credentials.mock_calls == []

    def test_returns_false_when_secret_wrong(self):
        handler, mock_request = _make_handler()
        mock_request.headers.get.return_value = "wrong-secret"
        mock_credentials = MagicMock()

        result = handler.authenticate(mock_credentials)

        assert result is False
        assert mock_request.mock_calls == [
            call.headers.get("X-Access-Webhook-Secret", ""),
        ]
        assert mock_credentials.mock_calls == []

    def test_returns_true_when_secret_matches(self):
        handler, mock_request = _make_handler()
        mock_request.headers.get.return_value = "correct-secret"
        mock_credentials = MagicMock()

        result = handler.authenticate(mock_credentials)

        assert result is True
        assert mock_request.mock_calls == [
            call.headers.get("X-Access-Webhook-Secret", ""),
        ]
        assert mock_credentials.mock_calls == []

    def test_uses_compare_digest_not_plain_equality(self):
        """Verify we're using hmac.compare_digest to prevent timing attacks."""
        import cms_access_fhir_client.api.webhook_api as module
        import inspect
        source = inspect.getsource(module.AccessWebhookApi.authenticate)
        assert "compare_digest" in source, (
            "authenticate() must use hmac.compare_digest() for constant-time comparison"
        )


# ---------------------------------------------------------------------------
# Webhook event dispatch tests
# ---------------------------------------------------------------------------

def _dispatch_webhook(event_type, patient_ref=None, alignment_id=None, reason_code=None, extra_secrets=None):
    """Helper: dispatch a webhook and return (effects, mock_event_saved)."""
    from cms_access_fhir_client.api.webhook_api import AccessWebhookApi
    handler = AccessWebhookApi.__new__(AccessWebhookApi)
    handler.secrets = {"ACCESS_WEBHOOK_SECRET": "correct-secret"}

    payload = _subscription_payload(
        event_type,
        patient_ref=patient_ref,
        alignment_id=alignment_id,
        reason_code=reason_code,
    )

    mock_request = MagicMock()
    mock_request.headers.get.return_value = "correct-secret"
    mock_request.json.return_value = payload
    handler.request = mock_request

    mock_patient = MagicMock()
    mock_patient.id = patient_ref or ""
    mock_patient.dbid = 1

    mock_alignment = MagicMock()
    mock_alignment.status = "aligned"
    mock_alignment.tier = "initial"
    mock_alignment.dbid = 1

    saved_events = []

    mock_webhook_event = MagicMock()
    mock_webhook_event.event_type = event_type
    mock_webhook_event.alignment_id = alignment_id or ""
    mock_webhook_event.patient_id = mock_patient.dbid if patient_ref else None
    mock_webhook_event.patient = mock_patient

    def fake_save():
        saved_events.append("saved")

    mock_webhook_event.save = fake_save

    with (
        patch(
            "cms_access_fhir_client.api.webhook_api.CustomPatient.objects"
        ) as mock_patient_objects,
        patch(
            "cms_access_fhir_client.api.webhook_api.ACCESSWebhookEvent"
        ) as mock_event_cls,
        patch(
            "cms_access_fhir_client.api.webhook_api.ACCESSAlignment.objects"
        ) as mock_alignment_objects,
    ):
        mock_patient_objects.get.return_value = mock_patient
        mock_event_cls.return_value = mock_webhook_event
        # Preserve string constants so the dispatch table keys are strings, not MagicMocks
        mock_event_cls.EVENT_LOCK_IN_ENDING = "provider-lock-in-period-ending"
        mock_event_cls.EVENT_REPORTING_DUE_BASELINE = "data-reporting-due-baseline"
        mock_event_cls.EVENT_REPORTING_DUE_QUARTERLY = "data-reporting-due-quarterly"
        mock_event_cls.EVENT_REPORTING_DUE_END_OF_PERIOD = "data-reporting-due-end-of-period"
        mock_event_cls.EVENT_RENEWAL_DUE = "alignment-renewal-due"
        mock_event_cls.EVENT_UNALIGNMENT_CMS = "unalignment-cms-initiated"
        mock_event_cls.EVENT_UNALIGNMENT_PARTICIPANT = "unalignment-participant-initiated"
        mock_event_cls.STATUS_PENDING = "pending"
        mock_event_cls.STATUS_OK = "ok"
        mock_alignment_objects.filter.return_value.first.return_value = mock_alignment

        effects = handler.receive_webhook()

    return effects, mock_patient_objects, mock_event_cls, mock_alignment_objects


class TestWebhookDispatch:
    def test_lock_in_ending_produces_banner_alert(self):
        effects, mock_patient_objects, mock_event_cls, mock_alignment_objects = (
            _dispatch_webhook(
                "provider-lock-in-period-ending",
                patient_ref="patient-uuid-123",
                alignment_id="align-abc",
            )
        )
        from canvas_sdk.effects.base import EffectType

        # First effect is JSONResponse (200), second should be banner
        non_json = [e for e in effects if hasattr(e, "type") and e.type == EffectType.ADD_BANNER_ALERT]
        assert len(non_json) == 1

        assert mock_patient_objects.mock_calls == [call.get(id="patient-uuid-123")]
        assert mock_event_cls.mock_calls != []

    def test_reporting_due_baseline_creates_task(self):
        effects, *_ = _dispatch_webhook(
            "data-reporting-due-baseline",
            patient_ref="patient-uuid-123",
            alignment_id="align-abc",
        )
        from canvas_sdk.effects.base import EffectType
        task_effects = [e for e in effects if hasattr(e, "type") and e.type == EffectType.CREATE_TASK]
        assert len(task_effects) == 1

    def test_reporting_due_quarterly_creates_task(self):
        effects, *_ = _dispatch_webhook(
            "data-reporting-due-quarterly",
            patient_ref="patient-uuid-123",
            alignment_id="align-abc",
        )
        from canvas_sdk.effects.base import EffectType
        task_effects = [e for e in effects if hasattr(e, "type") and e.type == EffectType.CREATE_TASK]
        assert len(task_effects) == 1

    def test_reporting_due_end_of_period_creates_task(self):
        effects, *_ = _dispatch_webhook(
            "data-reporting-due-end-of-period",
            patient_ref="patient-uuid-123",
            alignment_id="align-abc",
        )
        from canvas_sdk.effects.base import EffectType
        task_effects = [e for e in effects if hasattr(e, "type") and e.type == EffectType.CREATE_TASK]
        assert len(task_effects) == 1

    def test_renewal_due_creates_task_and_updates_tier(self):
        effects, _, _, mock_alignment_objects = _dispatch_webhook(
            "alignment-renewal-due",
            patient_ref="patient-uuid-123",
            alignment_id="align-abc",
        )
        from canvas_sdk.effects.base import EffectType
        task_effects = [e for e in effects if hasattr(e, "type") and e.type == EffectType.CREATE_TASK]
        assert len(task_effects) == 1

        # Alignment should have been updated
        mock_alignment = mock_alignment_objects.filter.return_value.first.return_value
        assert mock_alignment.tier == "renewal"

    def test_unalignment_cms_marks_alignment_inactive(self):
        effects, _, _, mock_alignment_objects = _dispatch_webhook(
            "unalignment-cms-initiated",
            alignment_id="align-abc",
            reason_code="patient-request",
        )
        mock_alignment = mock_alignment_objects.filter.return_value.first.return_value
        assert mock_alignment.status == "unaligned"
        assert mock_alignment.unalignment_reason == "patient-request"

    def test_unalignment_participant_marks_alignment_inactive(self):
        effects, _, _, mock_alignment_objects = _dispatch_webhook(
            "unalignment-participant-initiated",
            alignment_id="align-abc",
        )
        mock_alignment = mock_alignment_objects.filter.return_value.first.return_value
        assert mock_alignment.status == "unaligned"

    def test_unknown_event_type_returns_ok_with_no_extra_effects(self):
        effects, *_ = _dispatch_webhook("unknown-future-event-type")
        from canvas_sdk.effects.base import EffectType
        # Only the JSONResponse 200 should be present; no task or banner
        other_effects = [
            e for e in effects
            if hasattr(e, "type") and e.type in (EffectType.CREATE_TASK, EffectType.ADD_BANNER_ALERT)
        ]
        assert other_effects == []


# ---------------------------------------------------------------------------
# Parsing helper unit tests
# ---------------------------------------------------------------------------

class TestParsingHelpers:
    def test_extract_event_type_from_bundle(self):
        from cms_access_fhir_client.api.webhook_api import _extract_event_type
        payload = _subscription_payload("provider-lock-in-period-ending")
        assert _extract_event_type(payload) == "provider-lock-in-period-ending"

    def test_extract_event_type_fallback_to_top_level(self):
        from cms_access_fhir_client.api.webhook_api import _extract_event_type
        assert _extract_event_type({"eventType": "my-event"}) == "my-event"

    def test_extract_patient_id_from_bundle(self):
        from cms_access_fhir_client.api.webhook_api import _extract_patient_id
        payload = {"entry": [{"resource": {"subject": {"reference": "Patient/abc-123"}}}]}
        assert _extract_patient_id(payload) == "abc-123"

    def test_extract_patient_id_returns_none_when_absent(self):
        from cms_access_fhir_client.api.webhook_api import _extract_patient_id
        assert _extract_patient_id({}) is None

    def test_extract_alignment_id(self):
        from cms_access_fhir_client.api.webhook_api import _extract_alignment_id
        payload = {
            "entry": [
                {
                    "resource": {
                        "parameter": [{"name": "alignmentId", "valueString": "align-xyz"}]
                    }
                }
            ]
        }
        assert _extract_alignment_id(payload) == "align-xyz"

    def test_extract_reason_code(self):
        from cms_access_fhir_client.api.webhook_api import _extract_reason
        payload = {
            "entry": [
                {
                    "resource": {
                        "parameter": [{"name": "reasonCode", "valueCode": "provider-decision"}]
                    }
                }
            ]
        }
        assert _extract_reason(payload) == "provider-decision"
