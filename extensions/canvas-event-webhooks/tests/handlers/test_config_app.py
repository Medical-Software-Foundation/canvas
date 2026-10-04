"""Tests for the global application that opens the webhook configuration page."""

from __future__ import annotations

import json
from types import SimpleNamespace

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from canvas_event_webhooks.handlers.config_api import WebhookConfigAPI
from canvas_event_webhooks.handlers.config_app import CONFIG_PATH, WebhookConfigApplication

APP_IDENTIFIER = "canvas_event_webhooks.handlers.config_app:WebhookConfigApplication"


def _open_event(target_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type=EventType.APPLICATION__ON_OPEN,
        target=SimpleNamespace(id=target_id),
        context={},
    )


def test_opening_the_app_launches_the_config_page():
    effects = WebhookConfigApplication(event=_open_event(APP_IDENTIFIER)).compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.LAUNCH_MODAL
    data = json.loads(effects[0].payload)["data"]
    url = data.pop("url")
    assert url.startswith(f"{CONFIG_PATH}?v=")
    # The cache-bust token is a positive integer timestamp string.
    assert url.split("?v=", 1)[1].isdigit()
    assert data == {
        "content": None,
        "target": "page",
        "title": "Canvas Event Webhooks",
    }


def test_config_path_points_at_the_config_api():
    assert CONFIG_PATH == f"/plugin-io/api/canvas_event_webhooks{WebhookConfigAPI.PREFIX}/"


def test_open_event_for_another_application_is_ignored():
    event = _open_event("some_other_plugin.apps:OtherApplication")

    assert WebhookConfigApplication(event=event).compute() == []
