"""Tests for the app-drawer entry point that opens the pairing editor."""

import json
from typing import Any

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType

from questionnaire_followup.api.routes import FollowUpAdminAPI
from questionnaire_followup.applications.admin_app import _CACHE_BUST, FollowUpAdminApplication


def _app(target: str = "") -> FollowUpAdminApplication:
    event = Event(EventRequest(type=EventType.APPLICATION__ON_OPEN, target=target))
    return FollowUpAdminApplication(event=event)


def test_on_open_launches_the_editor_as_a_full_page(manifest: dict[str, Any]) -> None:
    """Opening the app loads the editor route for this plugin, full-page."""
    effect = _app().on_open()

    assert effect.type == EffectType.LAUNCH_MODAL
    data = json.loads(effect.payload)["data"]
    assert data["url"] == f"/plugin-io/api/{manifest['name']}/admin/ui?v={_CACHE_BUST}"
    assert data["target"] == "page"


def test_editor_url_points_at_a_registered_route() -> None:
    """The launched URL is one the admin API actually serves."""
    effect = _app().on_open()
    path = json.loads(effect.payload)["data"]["url"].split("?")[0]

    registered = {pattern.pattern for pattern, _handler in FollowUpAdminAPI._ROUTES["GET"]}

    assert path.removeprefix("/plugin-io/api/questionnaire_followup") in registered


def test_cache_bust_is_a_deploy_timestamp() -> None:
    """The cache-bust value is a whole-second timestamp, so it changes per deploy."""
    assert _CACHE_BUST.isdigit()


def test_open_event_for_this_app_launches_the_editor(manifest: dict[str, Any]) -> None:
    """The manifest's class path is the id Canvas opens this app by."""
    identifier = manifest["components"]["applications"][0]["class"]
    app = _app(target=identifier)

    assert app.compute() == [app.on_open()]


def test_open_event_for_another_app_is_ignored() -> None:
    """Opening a different application does not launch this editor."""
    assert _app(target="some_other_plugin.apps:OtherApp").compute() == []
