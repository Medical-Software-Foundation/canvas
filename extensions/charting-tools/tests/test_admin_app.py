import json

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.events import EventType

from charting_tools.applications.admin_app import NoteTemplatesAdminApp
from tests.conftest import make_event


def test_opens_builder_page() -> None:
    app = NoteTemplatesAdminApp(event=make_event(EventType.APPLICATION__ON_OPEN))
    effect = app.on_open()
    assert effect.type == EffectType.LAUNCH_MODAL
    data = json.loads(effect.payload)["data"]
    assert data["url"] == "/plugin-io/api/charting_tools/admin"
    assert data["target"] == "page"
