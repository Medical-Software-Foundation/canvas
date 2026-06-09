"""Shared fixtures for rx_status tests."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make `rx_status` importable as a package when pytest runs from this dir.
_PLUGIN_PARENT = Path(__file__).resolve().parent.parent.parent
if str(_PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_PARENT))


def _stub_missing_sdk_modules() -> None:
    """Stub SDK submodules the local environment doesn't ship.

    Some PRESCRIPTION_* events and `canvas_sdk.v1.data.prescription` are
    introduced in a newer SDK than the one installed locally, so we register
    stand-ins before the plugin code tries to import them. Tests don't touch
    real SDK behaviour — they patch these names directly.
    """
    if "canvas_sdk.v1.data.prescription" not in sys.modules:
        try:
            __import__("canvas_sdk.v1.data.prescription")
        except ModuleNotFoundError:
            stub = types.ModuleType("canvas_sdk.v1.data.prescription")
            prescription = type(
                "Prescription",
                (),
                {"DoesNotExist": type("DoesNotExist", (Exception,), {})},
            )
            prescription.objects = MagicMock()
            stub.Prescription = prescription
            sys.modules["canvas_sdk.v1.data.prescription"] = stub

    # Ensure EventType has the PRESCRIPTION_* enum names the plugin uses.
    try:
        from canvas_sdk.events import EventType  # noqa: WPS433
    except Exception:  # pragma: no cover - defensive
        return

    prescription_event_names = [
        "PRESCRIPTION_OPENED",
        "PRESCRIPTION_PENDING",
        "PRESCRIPTION_ACCEPTED",
        "PRESCRIPTION_ERRORED",
        "PRESCRIPTION_CANCEL_REQUESTED",
        "PRESCRIPTION_CANCELED",
        "PRESCRIPTION_CANCEL_DENIED",
        "PRESCRIPTION_RECEIVED",
        "PRESCRIPTION_SIGNED",
        "PRESCRIPTION_INQUEUE",
        "PRESCRIPTION_TRANSMITTED",
        "PRESCRIPTION_DELIVERED",
    ]

    missing = [n for n in prescription_event_names if not hasattr(EventType, n)]
    if not missing:
        return

    class _EventTypeShim:
        _name_by_value = {}
        _value_by_name = {}

        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __getattr__(self, name):
            if name in self._value_by_name:
                return self._value_by_name[name]
            return getattr(self._wrapped, name)

        def Name(self, value):
            if value in self._name_by_value:
                return self._name_by_value[value]
            return self._wrapped.Name(value)

    shim = _EventTypeShim(EventType)
    next_value = 900000
    for name in prescription_event_names:
        if hasattr(EventType, name):
            continue
        shim._value_by_name[name] = next_value
        shim._name_by_value[next_value] = name
        next_value += 1

    import canvas_sdk.events as events_module

    events_module.EventType = shim


_stub_missing_sdk_modules()


@pytest.fixture
def mock_cache() -> MagicMock:
    """In-memory cache backed by a dict, mirroring canvas_sdk's get_cache() contract."""
    store: dict = {}

    cache = MagicMock()
    cache.get.side_effect = lambda key, default=None: store.get(key, default)

    def _set(key, value):
        store[key] = value

    cache.set.side_effect = _set
    cache._store = store
    return cache


@pytest.fixture
def mock_event() -> MagicMock:
    event = MagicMock()
    event.type = 1
    event.target.id = "rx-abc-123"
    event.context = {"patient": {"id": "patient-xyz-999"}}
    return event


@pytest.fixture
def mock_prescription() -> MagicMock:
    rx = MagicMock()
    rx.id = "rx-abc-123"
    rx.status = "pending"
    rx.modified = "2026-04-10T12:00:00+00:00"
    rx.written_date = None
    rx.patient.id = "patient-xyz-999"
    rx.patient.first_name = "Solomon"
    rx.patient.last_name = "Test"
    rx.prescriber.first_name = "Wayne"
    rx.prescriber.last_name = "Best"
    rx.medication.codings.first.return_value.display = "Lisinopril 10 mg"
    rx.compound_medication = None
    rx.pharmacy_name = "Test Pharmacy"
    rx.is_refill = False
    rx.is_adjustment = False
    rx.response_type = None
    rx.error_message = ""
    rx.note.dbid = 42
    return rx


@pytest.fixture
def immediate_rule() -> dict:
    return {
        "id": "rule-immediate",
        "status": "error",
        "duration_value": 0,
        "duration_unit": "h",
        "task_title": "Error rule",
        "assignee_type": "staff",
        "assignee_id": "staff-1",
        "assignee_name": "Dr. Smith",
        "label": "",
    }


@pytest.fixture
def duration_rule() -> dict:
    return {
        "id": "rule-duration",
        "status": "pending",
        "duration_value": 24,
        "duration_unit": "h",
        "task_title": "Pending > 24h",
        "assignee_type": "team",
        "assignee_id": "team-oncology",
        "assignee_name": "Oncology",
        "label": "label-1",
    }


@pytest.fixture
def mock_request() -> MagicMock:
    request = MagicMock()
    request.query_params = {}
    request.body = "{}"
    request.path_params = {}
    request.headers = {}
    return request
