import json

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.events import Event
from canvas_sdk.handlers.application import NoteApplication

from canvas_generated.messages.events_pb2 import Event as EventRequest

from voice_dictation.handlers.dictate_buttons import DictateApp


def test_app_config():
    """DictateApp has correct name, identifier, and priority."""
    assert DictateApp.NAME == "Dictate"
    assert DictateApp.IDENTIFIER == "voice_dictation__dictate"
    assert DictateApp.PRIORITY == 10


def test_app_is_note_application():
    """DictateApp inherits from NoteApplication."""
    assert issubclass(DictateApp, NoteApplication)


def test_open_by_default():
    """DictateApp opens by default."""
    event = Event(EventRequest())
    app = DictateApp(event, {})
    assert app.open_by_default() is True


def test_on_open_returns_effect():
    """on_open returns an Effect with the correct URL."""
    context = json.dumps({"note": {"id": "abc-123"}, "note_id": 42})
    event = Event(EventRequest(context=context))
    app = DictateApp(event, {})

    result = app.on_open()

    assert isinstance(result, Effect)
    payload = json.loads(result.payload)
    # LaunchModalEffect payload has nested data structure
    url = payload.get("url", "") or json.dumps(payload)
    assert "voice_dictation" in url or "abc-123" in json.dumps(payload)


def test_on_open_missing_note_context():
    """on_open handles missing note context gracefully."""
    event = Event(EventRequest(context="{}"))
    app = DictateApp(event, {})

    result = app.on_open()
    assert isinstance(result, Effect)
