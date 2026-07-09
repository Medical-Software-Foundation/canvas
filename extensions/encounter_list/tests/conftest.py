"""Pytest configuration for local testing of the Encounter List plugin.

Mocks the Canvas SDK via ``sys.modules`` so the handler module imports without the
full Canvas runtime, and puts the extensions directory on the path so the plugin
package is importable as ``encounter_list``.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def create_mock_module(name, **attrs):
    """Register a MagicMock module under ``name`` with the given attributes."""
    mock = MagicMock()
    for attr_name, attr_value in attrs.items():
        setattr(mock, attr_name, attr_value)
    sys.modules[name] = mock
    return mock


class MockSimpleAPI:
    """Stand-in base class for canvas_sdk SimpleAPI."""

    PREFIX = ""
    BASE_PATH = ""


class MockStaffSessionAuthMixin:
    """Stand-in base class for canvas_sdk StaffSessionAuthMixin."""


class MockApplication:
    """Stand-in base class for canvas_sdk Application."""

    def on_open(self):
        """No-op on_open."""


class MockApi:
    """Pass-through stand-in for the ``@api.get``/``@api.post`` decorators."""

    @staticmethod
    def get(path):
        """Return the handler function unchanged."""
        def decorator(func):
            return func
        return decorator

    @staticmethod
    def post(path):
        """Return the handler function unchanged."""
        def decorator(func):
            return func
        return decorator


create_mock_module("canvas_sdk")
create_mock_module("canvas_sdk.effects")
create_mock_module("canvas_sdk.effects.launch_modal")
create_mock_module("canvas_sdk.effects.simple_api")
create_mock_module("canvas_sdk.handlers")
create_mock_module("canvas_sdk.handlers.application", Application=MockApplication)

simple_api_module = create_mock_module("canvas_sdk.handlers.simple_api")
simple_api_module.SimpleAPI = MockSimpleAPI
simple_api_module.StaffSessionAuthMixin = MockStaffSessionAuthMixin
simple_api_module.api = MockApi()

create_mock_module("canvas_sdk.templates")
create_mock_module("canvas_sdk.v1")
create_mock_module("canvas_sdk.v1.data")
create_mock_module("canvas_sdk.v1.data.claim")
create_mock_module("canvas_sdk.v1.data.note")
create_mock_module("canvas_sdk.v1.data.task")
