"""Pytest configuration for extend-lab-intake tests."""

import sys
from unittest.mock import MagicMock

# Mock the Canvas SDK logger before any imports
mock_logger = MagicMock()
mock_logger.log = MagicMock()
sys.modules['logger'] = mock_logger


# Create a proper base class for BaseProtocol
class MockBaseProtocol:
    """Mock base class for BaseProtocol that allows inheritance."""

    RESPONDS_TO = ""

    def __init__(self, event=None):
        self.event = event
        self.secrets = {}


# Create a proper base class for SimpleAPI
class MockSimpleAPI:
    """Mock base class for SimpleAPI that allows inheritance."""

    PREFIX = ""

    def __init__(self):
        self.secrets = {}
        self.environment = {}
        self.request = MagicMock()


# Create a proper base class for Application
class MockApplication:
    """Mock base class for Application that allows inheritance."""

    def __init__(self):
        self.secrets = {}
        self.environment = {}


# Mock Canvas SDK modules
canvas_sdk_mock = MagicMock()
sys.modules['canvas_sdk'] = canvas_sdk_mock

effects_mock = MagicMock()
effects_mock.Effect = MagicMock
effects_mock.EffectType = MagicMock()
sys.modules['canvas_sdk.effects'] = effects_mock

# Mock simple_api effects
simple_api_effects_mock = MagicMock()
simple_api_effects_mock.JSONResponse = MagicMock
simple_api_effects_mock.Response = MagicMock
sys.modules['canvas_sdk.effects.simple_api'] = simple_api_effects_mock

# Mock task effects
task_effects_mock = MagicMock()
task_effects_mock.AddTask = MagicMock
task_effects_mock.TaskStatus = MagicMock()
task_effects_mock.TaskStatus.COMPLETED = "COMPLETED"
task_effects_mock.TaskStatus.OPEN = "OPEN"
sys.modules['canvas_sdk.effects.task'] = task_effects_mock

# Mock launch_modal effects
launch_modal_mock = MagicMock()
mock_launch_modal_effect = MagicMock()
mock_launch_modal_effect.TargetType = MagicMock()
mock_launch_modal_effect.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"
launch_modal_mock.LaunchModalEffect = mock_launch_modal_effect
sys.modules['canvas_sdk.effects.launch_modal'] = launch_modal_mock

events_mock = MagicMock()
events_mock.EventType = MagicMock()
events_mock.EventType.Name = lambda x: x
sys.modules['canvas_sdk.events'] = events_mock

protocols_mock = MagicMock()
protocols_mock.BaseProtocol = MockBaseProtocol
sys.modules['canvas_sdk.protocols'] = protocols_mock

# Mock SimpleAPI handlers
simple_api_handlers_mock = MagicMock()
simple_api_handlers_mock.SimpleAPI = MockSimpleAPI
simple_api_handlers_mock.APIKeyCredentials = MagicMock
simple_api_handlers_mock.api = MagicMock()
simple_api_handlers_mock.api.post = lambda path: lambda f: f
simple_api_handlers_mock.api.get = lambda path: lambda f: f
sys.modules['canvas_sdk.handlers.simple_api'] = simple_api_handlers_mock

# Mock Application handlers
application_handlers_mock = MagicMock()
application_handlers_mock.Application = MockApplication
sys.modules['canvas_sdk.handlers.application'] = application_handlers_mock

# Mock templates
templates_mock = MagicMock()
templates_mock.render_to_string = MagicMock(return_value="<html></html>")
sys.modules['canvas_sdk.templates'] = templates_mock

# Mock v1 data modules
sys.modules['canvas_sdk.v1'] = MagicMock()
sys.modules['canvas_sdk.v1.data'] = MagicMock()

task_mock = MagicMock()
task_mock.Task = MagicMock()
sys.modules['canvas_sdk.v1.data.task'] = task_mock

patient_mock = MagicMock()
patient_mock.Patient = MagicMock()
sys.modules['canvas_sdk.v1.data.patient'] = patient_mock

team_mock = MagicMock()
team_mock.Team = MagicMock()
sys.modules['canvas_sdk.v1.data.team'] = team_mock
