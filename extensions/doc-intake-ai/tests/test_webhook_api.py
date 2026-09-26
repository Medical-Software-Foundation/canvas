"""Tests for ExtendWebhookAPI webhook handler."""

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from doc_intake_ai.models import (
    CategorizationResult,
    DocumentExtraction,
    PatientMatch,
    ReviewerMatch,
)


WEBHOOK_SECRET = "test-webhook-secret"

PHASE1_CONTEXT: dict[str, Any] = {
    "phase": 1,
    "document_id": "doc-123",
    "content_url": "https://s3/doc.pdf",
    "available_types": [
        {"key": "lab_report", "name": "Lab Report", "report_type": "LAB", "template_type": "LabReportTemplate"},
    ],
    "config": {
        "classify": True,
        "match_patient": True,
        "assign_reviewer": True,
        "prefill_templates": False,
        "channel_fax": True,
        "channel_document_upload": False,
        "channel_integration_engine": False,
        "channel_patient_portal": False,
    },
}

PHASE2_CONTEXT = {
    "phase": 2,
    "document_id": "doc-123",
    "candidates": [
        {
            "candidate": {"id": 1, "name": "CBC Panel", "score": 0.8, "codes": ["11580-8"]},
            "key_map": {"11580-8": {"code": "11580-8", "label": "TSH", "units": "mIU/L"}},
        },
    ],
    "confidence": 0.92,
}

COMPLETED_PROCESSOR_RUN = {
    "id": "dpr_run123",
    "output": {
        "value": {
            "document_type": "lab_report",
            "patient_first_name": "John",
            "patient_last_name": "Doe",
        },
        "metadata": {"document_type": {"ocrConfidence": 0.95}},
    },
}

PHASE2_PROCESSOR_RUN = {
    "id": "dpr_run456",
    "output": {
        "value": {"11580-8": "4.5"},
        "metadata": {"11580-8": {"ocrConfidence": 0.92}},
    },
}


def _make_handler(
    body: dict | None = None,
    cached_context: dict | None = None,
    webhook_secret: str = WEBHOOK_SECRET,
) -> MagicMock:
    """Create an ExtendWebhookAPI instance with mocked request and cache."""
    from doc_intake_ai.webhook_api import ExtendWebhookAPI

    handler = ExtendWebhookAPI.__new__(ExtendWebhookAPI)

    if body is None:
        body = {
            "eventType": "extract_run.completed",
            "payload": COMPLETED_PROCESSOR_RUN,
        }

    raw_body = json.dumps(body).encode("utf-8")

    request = MagicMock()
    request.body = raw_body
    request.json.return_value = body
    request.headers = {
        "x-extend-request-timestamp": "9999999999",
        "x-extend-request-signature": "valid-sig",
    }
    handler.request = request

    handler.secrets = {
        "EXTEND_WEBHOOK_SECRET": webhook_secret,
        "EXTEND_API_KEY": "test-key",
        "EXTEND_EXTRACTOR_ID": "test-proc",
        "DEFAULT_REVIEWER": "Jane Smith",
    }

    return handler


class TestHmacRejection:
    """Test HMAC verification at the top of post()."""

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=False)
    def test_invalid_signature_returns_401(self, mock_verify: MagicMock) -> None:
        handler = _make_handler()
        result = handler.post()

        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    def test_valid_signature_proceeds(self, mock_cache: MagicMock, mock_verify: MagicMock) -> None:
        mock_cache.return_value.get.return_value = None
        handler = _make_handler()
        result = handler.post()

        assert result[0].status_code != HTTPStatus.UNAUTHORIZED


class TestCacheMiss:
    """Test behavior when cache entry is missing."""

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    def test_cache_miss_returns_200(self, mock_cache: MagicMock, mock_verify: MagicMock) -> None:
        mock_cache.return_value.get.return_value = None
        handler = _make_handler()
        result = handler.post()

        assert len(result) == 1


class TestProcessorRunFailed:
    """Test processor_run.failed event handling."""

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    def test_failed_event_cleans_cache_returns_200(
        self, mock_cache: MagicMock, mock_verify: MagicMock,
    ) -> None:
        failed_run = {"id": "dpr_run123", "error": {"message": "extraction failed"}}
        body = {
            "eventType": "extract_run.failed",
            "payload": failed_run,
        }
        mock_cache.return_value.get.return_value = json.dumps(PHASE1_CONTEXT)

        handler = _make_handler(body=body)
        result = handler.post()

        assert len(result) == 1
        mock_cache.return_value.delete.assert_called_once_with("extend_run:dpr_run123")


class TestPhase1:
    """Test Phase 1 webhook processing."""

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.build_assign_reviewer_effect")
    @patch("doc_intake_ai.webhook_api.build_link_patient_effect")
    @patch("doc_intake_ai.webhook_api.build_categorize_effect")
    @patch("doc_intake_ai.webhook_api.find_reviewer")
    @patch("doc_intake_ai.webhook_api.find_patient")
    def test_phase1_happy_path(
        self,
        mock_find_patient: MagicMock,
        mock_find_reviewer: MagicMock,
        mock_categorize: MagicMock,
        mock_link: MagicMock,
        mock_assign: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        mock_find_patient.return_value = PatientMatch(patient=MagicMock(id="patient-1"))
        mock_find_reviewer.return_value = ReviewerMatch(reviewer=MagicMock(id="staff-1"))
        mock_categorize.return_value = MagicMock()
        mock_link.return_value = MagicMock()
        mock_assign.return_value = MagicMock()

        mock_cache.return_value.get.return_value = json.dumps(PHASE1_CONTEXT)

        handler = _make_handler()
        result = handler.post()

        # JSONResponse + 3 effects
        assert len(result) == 4
        mock_categorize.assert_called_once()
        mock_link.assert_called_once()
        mock_assign.assert_called_once()
        mock_cache.return_value.delete.assert_called_once()

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.build_categorize_effect")
    @patch("doc_intake_ai.webhook_api.find_reviewer")
    @patch("doc_intake_ai.webhook_api.find_patient")
    def test_phase1_no_patient_match_skips_link(
        self,
        mock_find_patient: MagicMock,
        mock_find_reviewer: MagicMock,
        mock_categorize: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        mock_find_patient.return_value = PatientMatch()
        mock_find_reviewer.return_value = ReviewerMatch()
        mock_categorize.return_value = MagicMock()

        mock_cache.return_value.get.return_value = json.dumps(PHASE1_CONTEXT)

        handler = _make_handler()
        result = handler.post()

        # JSONResponse + categorize effect only
        assert len(result) == 2

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.find_reviewer")
    @patch("doc_intake_ai.webhook_api.find_patient")
    def test_phase1_classify_disabled_no_categorize(
        self,
        mock_find_patient: MagicMock,
        mock_find_reviewer: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        ctx = {**PHASE1_CONTEXT, "config": {**PHASE1_CONTEXT["config"], "classify": False}}
        mock_cache.return_value.get.return_value = json.dumps(ctx)
        mock_find_patient.return_value = PatientMatch()
        mock_find_reviewer.return_value = ReviewerMatch()

        handler = _make_handler()
        result = handler.post()

        # Only JSONResponse, no effects
        assert len(result) == 1


class TestPhase2:
    """Test Phase 2 webhook processing."""

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.build_prefill_effect")
    @patch("doc_intake_ai.webhook_api.build_prefill_fields_for_candidate")
    def test_phase2_happy_path(
        self,
        mock_fields: MagicMock,
        mock_effect: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        mock_fields.return_value = {"template_id": 1, "template_name": "CBC Panel", "fields": {"11580-8": {"value": "4.5"}}}
        mock_effect.return_value = MagicMock()
        mock_cache.return_value.get.return_value = json.dumps(PHASE2_CONTEXT)

        body = {
            "eventType": "extract_run.completed",
            "payload": PHASE2_PROCESSOR_RUN,
        }
        handler = _make_handler(body=body)
        result = handler.post()

        # JSONResponse + prefill effect
        assert len(result) == 2
        mock_fields.assert_called_once()
        mock_effect.assert_called_once()

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.build_prefill_fields_for_candidate")
    def test_phase2_no_prefill_returns_only_response(
        self,
        mock_fields: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        mock_fields.return_value = None
        mock_cache.return_value.get.return_value = json.dumps(PHASE2_CONTEXT)

        body = {
            "eventType": "extract_run.completed",
            "payload": PHASE2_PROCESSOR_RUN,
        }
        handler = _make_handler(body=body)
        result = handler.post()

        assert len(result) == 1

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.build_prefill_effect")
    @patch("doc_intake_ai.webhook_api.build_prefill_fields_for_candidate")
    def test_phase2_multiple_candidates(
        self,
        mock_fields: MagicMock,
        mock_effect: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        ctx = {
            "phase": 2,
            "document_id": "doc-123",
            "candidates": [
                {
                    "candidate": {"id": 1, "name": "CBC Panel", "score": 0.8, "codes": ["11580-8"]},
                    "key_map": {"11580-8": {"code": "11580-8", "label": "WBC", "units": "K/uL"}},
                },
                {
                    "candidate": {"id": 2, "name": "Metabolic Panel", "score": 0.6, "codes": ["2345-7"]},
                    "key_map": {"2345-7": {"code": "2345-7", "label": "Glucose", "units": "mg/dL"}},
                },
            ],
            "confidence": 0.90,
        }
        mock_fields.side_effect = [
            {"template_id": 1, "template_name": "CBC Panel", "fields": {"11580-8": {"value": "7.2"}}},
            {"template_id": 2, "template_name": "Metabolic Panel", "fields": {"2345-7": {"value": "95"}}},
        ]
        mock_effect.return_value = MagicMock()
        mock_cache.return_value.get.return_value = json.dumps(ctx)

        body = {
            "eventType": "extract_run.completed",
            "payload": PHASE2_PROCESSOR_RUN,
        }
        handler = _make_handler(body=body)
        result = handler.post()

        assert len(result) == 2
        assert mock_fields.call_count == 2
        templates_arg = mock_effect.call_args[0][1]
        assert len(templates_arg) == 2


class TestDuplicateDelivery:
    """Test idempotency on duplicate webhook delivery."""

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.find_patient")
    @patch("doc_intake_ai.webhook_api.find_reviewer")
    @patch("doc_intake_ai.webhook_api.build_categorize_effect")
    @patch("doc_intake_ai.webhook_api.build_link_patient_effect")
    @patch("doc_intake_ai.webhook_api.build_assign_reviewer_effect")
    def test_second_delivery_returns_no_effects(
        self,
        mock_assign: MagicMock,
        mock_link: MagicMock,
        mock_categorize: MagicMock,
        mock_find_reviewer: MagicMock,
        mock_find_patient: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        mock_find_patient.return_value = PatientMatch(patient=MagicMock(id="p-1"))
        mock_find_reviewer.return_value = ReviewerMatch(reviewer=MagicMock(id="s-1"))
        mock_categorize.return_value = MagicMock()
        mock_link.return_value = MagicMock()
        mock_assign.return_value = MagicMock()

        cache_instance = mock_cache.return_value
        # First call returns context, second returns None (cache deleted)
        cache_instance.get.side_effect = [json.dumps(PHASE1_CONTEXT), None]

        handler = _make_handler()
        first_result = handler.post()
        second_result = handler.post()

        # First delivery produces effects
        assert len(first_result) == 4
        # Second delivery is a cache miss, just response
        assert len(second_result) == 1


class TestSignedUrlPayload:
    """Test handling of signed URL payloads."""

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.get_cache")
    @patch("doc_intake_ai.webhook_api.requests.get")
    @patch("doc_intake_ai.webhook_api.find_patient")
    @patch("doc_intake_ai.webhook_api.find_reviewer")
    @patch("doc_intake_ai.webhook_api.build_categorize_effect")
    def test_signed_url_fetched_and_processed(
        self,
        mock_categorize: MagicMock,
        mock_find_reviewer: MagicMock,
        mock_find_patient: MagicMock,
        mock_requests_get: MagicMock,
        mock_cache: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        mock_requests_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=COMPLETED_PROCESSOR_RUN),
        )
        mock_find_patient.return_value = PatientMatch()
        mock_find_reviewer.return_value = ReviewerMatch()
        mock_categorize.return_value = MagicMock()
        mock_cache.return_value.get.return_value = json.dumps(PHASE1_CONTEXT)

        body = {
            "eventType": "extract_run.completed",
            "payload": "https://signed-url.example.com/payload",
        }
        handler = _make_handler(body=body)
        result = handler.post()

        mock_requests_get.assert_called_once_with("https://signed-url.example.com/payload", timeout=30)
        mock_categorize.assert_called_once()

    @patch("doc_intake_ai.webhook_api.verify_hmac", return_value=True)
    @patch("doc_intake_ai.webhook_api.requests.get")
    def test_signed_url_fetch_failure_returns_ok(
        self,
        mock_requests_get: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        mock_requests_get.return_value = MagicMock(status_code=500)

        body = {
            "eventType": "extract_run.completed",
            "payload": "https://signed-url.example.com/payload",
        }
        handler = _make_handler(body=body)
        result = handler.post()

        assert len(result) == 1
