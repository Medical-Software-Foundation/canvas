import sys
import types
from enum import Enum
from unittest.mock import MagicMock


# Create a real BaseHandler class so our handler can properly inherit
class BaseHandler:
    RESPONDS_TO = ""

    def __init__(self):
        self.event = None

    @property
    def target(self):
        return self.event.target if self.event else None

    def compute(self):
        return []


class TaskStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    COMPLETED = "completed"


class Effect:
    pass


class AddTask:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id") or f"task-{id(self)}"
        for k, v in kwargs.items():
            setattr(self, k, v)

    def apply(self):
        return MagicMock(name="AddTask.apply()")


class AddTaskComment:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def apply(self):
        return MagicMock(name="AddTaskComment.apply()")


class EventType:
    PRESCRIPTION_ERRORED = "PRESCRIPTION_ERRORED"

    @staticmethod
    def Name(val):
        return val


class Prescription:
    class DoesNotExist(Exception):
        pass

    class objects:
        @staticmethod
        def select_related(*args):
            return Prescription.objects

        @staticmethod
        def get(**kwargs):
            return MagicMock()


# Build module mocks with real classes
handlers_mod = types.ModuleType("canvas_sdk.handlers")
handlers_mod.BaseHandler = BaseHandler

events_mod = types.ModuleType("canvas_sdk.events")
events_mod.EventType = EventType

effects_mod = types.ModuleType("canvas_sdk.effects")
effects_mod.Effect = Effect

task_mod = types.ModuleType("canvas_sdk.effects.task")
task_mod.AddTask = AddTask
task_mod.AddTaskComment = AddTaskComment
task_mod.TaskStatus = TaskStatus

prescription_mod = types.ModuleType("canvas_sdk.v1.data.prescription")
prescription_mod.Prescription = Prescription

logger_mod = types.ModuleType("logger")
logger_mod.log = MagicMock()

# Register all modules
sys.modules["canvas_sdk"] = types.ModuleType("canvas_sdk")
sys.modules["canvas_sdk.handlers"] = handlers_mod
sys.modules["canvas_sdk.events"] = events_mod
sys.modules["canvas_sdk.effects"] = effects_mod
sys.modules["canvas_sdk.effects.task"] = task_mod
sys.modules["canvas_sdk.v1"] = types.ModuleType("canvas_sdk.v1")
sys.modules["canvas_sdk.v1.data"] = types.ModuleType("canvas_sdk.v1.data")
sys.modules["canvas_sdk.v1.data.prescription"] = prescription_mod
sys.modules["logger"] = logger_mod
