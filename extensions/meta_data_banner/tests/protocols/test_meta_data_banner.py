"""Tests for the MetaDataBanner event handler."""
from unittest.mock import MagicMock, patch
import pytest

from meta_data_banner.protocols.meta_data_banner import MetaDataBanner


@pytest.fixture
def handler():
    """Create a MetaDataBanner handler instance."""
    h = MetaDataBanner.__new__(MetaDataBanner)
    h.secrets = {}
    h.event = MagicMock()
    h.event.type = "PATIENT_METADATA_UPDATED"
    h.context = {"patient": {"id": "patient-uuid-123"}}
    return h


class TestCompute:
    def test_no_template_returns_empty(self, handler):
        handler.secrets = {}
        assert handler.compute() == []

    def test_empty_template_returns_empty(self, handler):
        handler.secrets = {"BANNER_TEMPLATE": ""}
        assert handler.compute() == []

    @patch("meta_data_banner.protocols.meta_data_banner.Patient")
    def test_metadata_event_uses_context_patient_id(self, mock_patient_cls, handler, mock_patient):
        mock_patient_cls.objects.get.return_value = mock_patient
        handler.secrets = {"BANNER_TEMPLATE": "Status: {ccm_diagnosis}"}

        result = handler.compute()

        mock_patient_cls.objects.get.assert_called_once_with(id="patient-uuid-123")
        assert len(result) == 1

    @patch("meta_data_banner.protocols.meta_data_banner.Patient")
    def test_no_match_returns_remove_effect(self, mock_patient_cls, handler, mock_patient):
        mock_patient.metadata.all.return_value = []
        mock_patient_cls.objects.get.return_value = mock_patient
        handler.secrets = {"BANNER_TEMPLATE": "Status: {ccm_diagnosis}"}

        result = handler.compute()

        assert len(result) == 1

    @patch("meta_data_banner.protocols.meta_data_banner.Patient")
    def test_deleted_patient_returns_empty(self, mock_patient_cls, handler):
        """A metadata event for a deleted/stale patient returns [] instead of crashing."""
        class DoesNotExist(Exception):
            pass

        mock_patient_cls.DoesNotExist = DoesNotExist
        mock_patient_cls.objects.get.side_effect = DoesNotExist()
        handler.secrets = {"BANNER_TEMPLATE": "Status: {ccm_diagnosis}"}

        assert handler.compute() == []
