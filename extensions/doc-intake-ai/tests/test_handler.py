"""Tests for DocumentIntakeHandler.compute() (fire-and-cache behavior)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from doc_intake_ai.models import FeatureConfig


ALL_ENABLED_SECRETS = {
    "ENABLE_CLASSIFY": "true",
    "ENABLE_MATCH_PATIENT": "true",
    "ENABLE_ASSIGN_REVIEWER": "true",
    "ENABLE_PREFILL_TEMPLATES": "true",
    "ENABLE_CHANNEL_FAX": "true",
    "ENABLE_CHANNEL_DOCUMENT_UPLOAD": "true",
    "ENABLE_CHANNEL_INTEGRATION_ENGINE": "true",
    "ENABLE_CHANNEL_PATIENT_PORTAL": "true",
}


class TestDocumentIntakeHandler:
    """Test handler compute() fire-and-cache behavior."""

    def _make_handler(
        self,
        doc_id: str = "doc-123",
        content_url: str = "https://s3/doc.pdf",
        available_types: list | None = None,
        secrets: dict | None = None,
        channel: str = "FAX",
    ) -> MagicMock:
        from doc_intake_ai.protocols.handler import DocumentIntakeHandler

        handler = DocumentIntakeHandler.__new__(DocumentIntakeHandler)

        event = MagicMock()
        event.context = {
            "document": {"id": doc_id, "content_url": content_url, "channel": channel},
            "available_document_types": available_types or [],
        }

        handler.event = event
        handler.secrets = secrets or {
            "EXTEND_API_KEY": "test-key",
            "EXTEND_EXTRACTOR_ID": "test-proc",
            "DEFAULT_REVIEWER": "Jane Smith",
            **ALL_ENABLED_SECRETS,
        }
        handler.environment = MagicMock()

        return handler

    def test_missing_document_id_returns_empty(self) -> None:
        from doc_intake_ai.protocols.handler import DocumentIntakeHandler

        handler = DocumentIntakeHandler.__new__(DocumentIntakeHandler)
        handler.event = MagicMock()
        handler.event.context = {"document": {}}
        handler.secrets = {}

        assert handler.compute() == []

    def test_missing_secrets_returns_empty(self) -> None:
        handler = self._make_handler(secrets={
            "EXTEND_API_KEY": "",
            "EXTEND_EXTRACTOR_ID": "",
            **ALL_ENABLED_SECRETS,
        })
        assert handler.compute() == []

    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_extraction_failure_returns_empty(self, mock_start: MagicMock) -> None:
        mock_start.return_value = None

        handler = self._make_handler()
        assert handler.compute() == []

    @patch("doc_intake_ai.protocols.handler.get_cache")
    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_successful_start_caches_context_and_returns_empty(self, mock_start: MagicMock, mock_get_cache: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"

        handler = self._make_handler(
            available_types=[{"key": "lab", "name": "Lab Report", "report_type": "LAB"}],
        )
        effects = handler.compute()

        assert effects == []
        mock_start.assert_called_once()

        cache = mock_get_cache.return_value
        cache.set.assert_called_once()
        call_args = cache.set.call_args
        assert call_args[0][0] == "extend_run:dpr_run123"

        cached = json.loads(call_args[0][1])
        assert cached["phase"] == 1
        assert cached["document_id"] == "doc-123"
        assert cached["content_url"] == "https://s3/doc.pdf"
        # Secrets must never enter the plugin cache. The webhook re-reads them
        # from self.secrets when the callback arrives.
        assert "api_key" not in cached
        assert "processor_id" not in cached
        assert "default_reviewer" not in cached

    @patch("doc_intake_ai.protocols.handler.get_cache")
    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_cache_includes_config(self, mock_start: MagicMock, mock_get_cache: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"

        handler = self._make_handler()
        handler.compute()

        cache = mock_get_cache.return_value
        cached = json.loads(cache.set.call_args[0][1])
        config = cached["config"]
        assert config["classify"] is True
        assert config["match_patient"] is True

    @patch("doc_intake_ai.protocols.handler.get_cache")
    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_cache_includes_available_types(self, mock_start: MagicMock, mock_get_cache: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"
        types = [{"key": "lab", "name": "Lab Report", "report_type": "LAB"}]

        handler = self._make_handler(available_types=types)
        handler.compute()

        cache = mock_get_cache.return_value
        cached = json.loads(cache.set.call_args[0][1])
        assert cached["available_types"] == types


class TestHandlerChannelFiltering:
    """Test handler channel gate behavior with ENABLE_CHANNEL_* secrets."""

    def _make_handler(
        self,
        channel: str = "FAX",
        toggle_secrets: dict[str, str] | None = None,
    ) -> MagicMock:
        from doc_intake_ai.protocols.handler import DocumentIntakeHandler

        handler = DocumentIntakeHandler.__new__(DocumentIntakeHandler)

        event = MagicMock()
        event.context = {
            "document": {"id": "doc-123", "content_url": "https://s3/doc.pdf", "channel": channel},
            "available_document_types": [],
        }

        handler.event = event
        secrets = {
            "EXTEND_API_KEY": "test-key",
            "EXTEND_EXTRACTOR_ID": "test-proc",
            "DEFAULT_REVIEWER": "Jane Smith",
        }
        if toggle_secrets is not None:
            secrets.update(toggle_secrets)
        handler.secrets = secrets
        handler.environment = MagicMock()

        return handler

    @patch("doc_intake_ai.protocols.handler.get_cache")
    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_fax_default_config_proceeds(self, mock_start: MagicMock, mock_get_cache: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"
        handler = self._make_handler(channel="FAX", toggle_secrets=ALL_ENABLED_SECRETS)
        handler.compute()
        mock_start.assert_called_once()

    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_fax_explicitly_disabled_returns_empty(self, mock_start: MagicMock) -> None:
        handler = self._make_handler(
            channel="FAX",
            toggle_secrets={**ALL_ENABLED_SECRETS, "ENABLE_CHANNEL_FAX": "false"},
        )
        effects = handler.compute()
        assert effects == []
        mock_start.assert_not_called()

    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_document_upload_default_returns_empty(self, mock_start: MagicMock) -> None:
        handler = self._make_handler(channel="DOCUMENT_UPLOAD")
        effects = handler.compute()
        assert effects == []
        mock_start.assert_not_called()

    @patch("doc_intake_ai.protocols.handler.get_cache")
    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_document_upload_enabled_proceeds(self, mock_start: MagicMock, mock_get_cache: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"
        handler = self._make_handler(
            channel="DOCUMENT_UPLOAD",
            toggle_secrets={**ALL_ENABLED_SECRETS, "ENABLE_CHANNEL_DOCUMENT_UPLOAD": "true"},
        )
        handler.compute()
        mock_start.assert_called_once()

    @patch("doc_intake_ai.protocols.handler.get_cache")
    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_unknown_channel_passes_through(self, mock_start: MagicMock, mock_get_cache: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"
        handler = self._make_handler(
            channel="SOME_NEW_CHANNEL",
            toggle_secrets=ALL_ENABLED_SECRETS,
        )
        handler.compute()
        mock_start.assert_called_once()

    @patch("doc_intake_ai.protocols.handler.get_cache")
    @patch("doc_intake_ai.protocols.handler.start_categorization")
    def test_empty_channel_passes_through(self, mock_start: MagicMock, mock_get_cache: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"
        handler = self._make_handler(channel="", toggle_secrets=ALL_ENABLED_SECRETS)
        handler.compute()
        mock_start.assert_called_once()
