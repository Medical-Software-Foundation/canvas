import json
from urllib.parse import parse_qs, urlparse

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
    """on_open returns a LaunchModalEffect with the correct note_id in the URL."""
    context = json.dumps({"note": {"id": "abc-123"}, "note_id": 42})
    event = Event(EventRequest(context=context))
    app = DictateApp(event, {})

    result = app.on_open()

    assert isinstance(result, Effect)
    payload = json.loads(result.payload)
    url = payload["data"]["url"]
    parsed = urlparse(url)
    assert parsed.path == "/plugin-io/api/voice_dictation/dictate/app"
    assert parse_qs(parsed.query)["note_id"] == ["abc-123"]


def test_on_open_missing_note_context():
    """on_open produces an empty note_id when note context is missing."""
    event = Event(EventRequest(context="{}"))
    app = DictateApp(event, {})

    result = app.on_open()
    assert isinstance(result, Effect)
    payload = json.loads(result.payload)
    url = payload["data"]["url"]
    parsed = urlparse(url)
    assert parse_qs(parsed.query).get("note_id", [""]) == [""]
