"""Shared test fixtures for meta_data_banner plugin."""
import sys
from unittest.mock import MagicMock
import pytest


# Create a real BaseHandler class so MetaDataBanner can inherit from it
class FakeBaseHandler:
    pass


# Mock Canvas SDK modules before any imports
sdk_mock = MagicMock()
sys.modules["canvas_sdk"] = sdk_mock
sys.modules["canvas_sdk.events"] = MagicMock()
sys.modules["canvas_sdk.handlers"] = MagicMock()

base_mod = MagicMock()
base_mod.BaseHandler = FakeBaseHandler
sys.modules["canvas_sdk.handlers.base"] = base_mod


# Real base class so the cron task can inherit and be instantiated in tests
class FakeCronTask:
    pass


cron_mod = MagicMock()
cron_mod.CronTask = FakeCronTask
sys.modules["canvas_sdk.handlers.cron_task"] = cron_mod

sys.modules["canvas_sdk.effects"] = MagicMock()
sys.modules["canvas_sdk.effects.banner_alert"] = MagicMock()
sys.modules["canvas_sdk.caching"] = MagicMock()
sys.modules["canvas_sdk.caching.plugins"] = MagicMock()
sys.modules["canvas_sdk.v1"] = MagicMock()
sys.modules["canvas_sdk.v1.data"] = MagicMock()
sys.modules["canvas_sdk.v1.data.patient"] = MagicMock()

# Mock logger
logger_mock = MagicMock()
logger_mock.log = MagicMock()
sys.modules["logger"] = logger_mock


def make_metadata_entry(key, value):
    """Create a mock metadata entry."""
    entry = MagicMock()
    entry.key = key
    entry.value = value
    return entry


@pytest.fixture
def mock_patient():
    """Create a mock patient with metadata."""
    patient = MagicMock()
    patient.id = "patient-uuid-123"
    patient.dbid = 1
    patient.metadata.all.return_value = [
        make_metadata_entry("ccm_diagnosis", "Active"),
        make_metadata_entry("risk_score", "High"),
    ]
    return patient
