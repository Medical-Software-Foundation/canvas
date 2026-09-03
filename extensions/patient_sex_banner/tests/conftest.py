"""Shared fixtures for the patient_sex_banner tests.

The Canvas SDK is not installed in the test environment, so every canvas_sdk
module the plugin imports is replaced with a mock before the plugin is imported.
"""
import sys
from unittest.mock import MagicMock

import pytest


class FakeBaseProtocol:
    pass


class FakeCronTask:
    pass


sys.modules["canvas_sdk"] = MagicMock()
sys.modules["canvas_sdk.effects"] = MagicMock()
sys.modules["canvas_sdk.effects.banner_alert"] = MagicMock()
sys.modules["canvas_sdk.events"] = MagicMock()

_protocols = MagicMock()
_protocols.BaseProtocol = FakeBaseProtocol
sys.modules["canvas_sdk.protocols"] = _protocols

sys.modules["canvas_sdk.handlers"] = MagicMock()

_cron = MagicMock()
_cron.CronTask = FakeCronTask
sys.modules["canvas_sdk.handlers.cron_task"] = _cron

sys.modules["canvas_sdk.caching"] = MagicMock()
sys.modules["canvas_sdk.caching.plugins"] = MagicMock()

sys.modules["canvas_sdk.v1"] = MagicMock()
sys.modules["canvas_sdk.v1.data"] = MagicMock()
sys.modules["canvas_sdk.v1.data.patient"] = MagicMock()

_logger = MagicMock()
_logger.log = MagicMock()
sys.modules["logger"] = _logger


@pytest.fixture
def protocol():
    from patient_sex_banner.protocols.my_protocol import Protocol

    handler = Protocol.__new__(Protocol)
    handler.event = MagicMock()
    handler.event.target.id = "patient-uuid-123"
    return handler


@pytest.fixture
def mock_patient():
    patient = MagicMock()
    patient.id = "patient-uuid-123"
    patient.sex_at_birth = "O"
    return patient
