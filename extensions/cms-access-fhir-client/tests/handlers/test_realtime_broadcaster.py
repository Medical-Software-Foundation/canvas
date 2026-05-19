"""Tests for broadcast_alignment_update utility."""
import pytest
import json


class TestBroadcastAlignmentUpdate:
    def test_returns_broadcast_effect(self):
        from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update
        from canvas_sdk.effects.base import EffectType

        effect = broadcast_alignment_update("patient-abc")
        assert effect.type == EffectType.SIMPLE_API_WEBSOCKET_BROADCAST

    def test_channel_is_patient_scoped(self):
        """Channel must include patient_id to prevent cross-chart data leakage."""
        from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update

        effect = broadcast_alignment_update("SPECIFIC-PID")
        payload = json.loads(effect.payload)
        channel = payload["data"]["channel"]
        assert "SPECIFIC-PID" in channel, (
            "Broadcast channel must include patient_id to be patient-scoped"
        )

    def test_channel_prefix(self):
        from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update

        effect = broadcast_alignment_update("patient-xyz")
        payload = json.loads(effect.payload)
        assert payload["data"]["channel"] == "access-cms_access_fhir_client-patient-xyz"

    def test_message_includes_model_name(self):
        from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update

        effect = broadcast_alignment_update("p-123", model_name="ACCESSWebhookEvent")
        payload = json.loads(effect.payload)
        message = payload["data"].get("message", {})
        assert message.get("model") == "ACCESSWebhookEvent"

    def test_default_model_name_is_access_alignment(self):
        from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update

        effect = broadcast_alignment_update("p-123")
        payload = json.loads(effect.payload)
        message = payload["data"].get("message", {})
        assert message.get("model") == "ACCESSAlignment"

    def test_different_patient_ids_produce_different_channels(self):
        from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update

        e1 = broadcast_alignment_update("patient-1")
        e2 = broadcast_alignment_update("patient-2")
        p1 = json.loads(e1.payload)
        p2 = json.loads(e2.payload)
        assert p1["data"]["channel"] != p2["data"]["channel"]
