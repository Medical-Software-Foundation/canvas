"""Pytest configuration and fixtures for testing Canvas plugins locally.

This module provides mocks for the Canvas SDK to allow local testing without
requiring the full Canvas environment.
"""
import sys
from unittest.mock import MagicMock
from typing import Any


# Create mock modules for canvas_sdk
def create_mock_module(name, **attrs):
    """Create a mock module with specified attributes."""
    mock = MagicMock()
    for attr_name, attr_value in attrs.items():
        setattr(mock, attr_name, attr_value)
    sys.modules[name] = mock
    return mock


# Create mock base classes that can be properly subclassed
class MockBaseProtocol:
    """Mock BaseProtocol class."""
    RESPONDS_TO = []
    def compute(self): return []


class MockBaseHandler:
    """Mock BaseHandler class."""
    RESPONDS_TO = None
    def compute(self): return []


class MockSimpleAPI:
    """Mock SimpleAPI class."""
    PREFIX = ""
    BASE_PATH = ""


class MockStaffSessionAuthMixin:
    """Mock StaffSessionAuthMixin class."""
    pass


class MockApplication:
    """Mock Application class."""
    def on_open(self): pass


class MockCronTask:
    """Mock CronTask class."""
    SCHEDULE = ""
    def execute(self): return []


# Mock canvas_sdk and all its submodules
canvas_sdk = create_mock_module('canvas_sdk')
create_mock_module('canvas_sdk.effects')
create_mock_module('canvas_sdk.effects.banner_alert')
create_mock_module('canvas_sdk.effects.launch_modal')
create_mock_module('canvas_sdk.effects.note')
create_mock_module('canvas_sdk.effects.simple_api')
create_mock_module('canvas_sdk.effects.billing_line_item')
create_mock_module('canvas_sdk.effects.patient_metadata')
create_mock_module('canvas_sdk.events')

# Set up protocol and handler modules with proper base classes
protocols_module = create_mock_module('canvas_sdk.protocols')
protocols_module.BaseProtocol = MockBaseProtocol

handlers_module = create_mock_module('canvas_sdk.handlers')
handlers_module.BaseHandler = MockBaseHandler

create_mock_module('canvas_sdk.handlers.base_handler', BaseHandler=MockBaseHandler)
create_mock_module('canvas_sdk.handlers.application', Application=MockApplication)

# Create a mock api object that acts as a pass-through decorator
class MockApi:
    """Mock api decorator that passes through the function unchanged."""
    @staticmethod
    def get(path):
        """Mock @api.get decorator - returns function unchanged."""
        def decorator(func):
            return func
        return decorator

    @staticmethod
    def post(path):
        """Mock @api.post decorator - returns function unchanged."""
        def decorator(func):
            return func
        return decorator

simple_api_module = create_mock_module('canvas_sdk.handlers.simple_api')
simple_api_module.SimpleAPI = MockSimpleAPI
simple_api_module.api = MockApi()  # Add api to this module too

api_module = create_mock_module('canvas_sdk.handlers.simple_api.api')
api_module.SimpleAPI = MockSimpleAPI
api_module.api = MockApi()

security_module = create_mock_module('canvas_sdk.handlers.simple_api.security')
security_module.StaffSessionAuthMixin = MockStaffSessionAuthMixin

cron_module = create_mock_module('canvas_sdk.handlers.cron_task')
cron_module.CronTask = MockCronTask

create_mock_module('canvas_sdk.commands')
create_mock_module('canvas_sdk.commands.commands')
create_mock_module('canvas_sdk.commands.commands.questionnaire')
create_mock_module('canvas_sdk.commands.commands.diagnose')
create_mock_module('canvas_sdk.templates')
create_mock_module('canvas_sdk.templates.utils')
create_mock_module('canvas_sdk.v1')
create_mock_module('canvas_sdk.v1.data')
create_mock_module('canvas_sdk.v1.data.patient')
create_mock_module('canvas_sdk.v1.data.staff')
create_mock_module('canvas_sdk.v1.data.note')
create_mock_module('canvas_sdk.v1.data.appointment')
create_mock_module('canvas_sdk.v1.data.questionnaire')
create_mock_module('canvas_sdk.v1.data.care_team')

# Mock logger module
create_mock_module('logger')

# Mock common Canvas SDK enums
EventType = MagicMock()
EventType.PATIENT_UPDATED = "PATIENT_UPDATED"
EventType.PLUGIN_CREATED = "PLUGIN_CREATED"
EventType.PLUGIN_UPDATED = "PLUGIN_UPDATED"
EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS = "PATIENT_METADATA__GET_ADDITIONAL_FIELDS"
EventType.Name = MagicMock(side_effect=lambda x: x)
sys.modules['canvas_sdk.events'].EventType = EventType
