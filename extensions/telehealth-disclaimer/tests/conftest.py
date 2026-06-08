"""Shared fixtures for telehealth_disclaimer tests."""

from unittest.mock import MagicMock

import pytest

from telehealth_disclaimer.protocols.telehealth_disclaimer import TelehealthDisclaimer


@pytest.fixture
def handler():
    """A TelehealthDisclaimer instance built without running BaseProtocol.__init__."""
    instance = TelehealthDisclaimer.__new__(TelehealthDisclaimer)
    instance.event = MagicMock()
    instance.secrets = {}
    return instance
