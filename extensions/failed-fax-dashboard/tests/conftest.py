import json
from base64 import b64decode, b64encode
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from canvas_sdk.events import EventType

import failed_fax_dashboard.api.dashboard_api as dashboard_api
import failed_fax_dashboard.services.saved_directory as saved_directory

CallApi = Callable[..., tuple[int, Any, list[Any]]]

PLUGIN_DIR = Path(dashboard_api.__file__).resolve().parent.parent


class FakeCache:
    """The plugin cache, which needs the Canvas runtime, as a dict."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def get_many(self, keys: Any) -> dict[str, Any]:
        return {f"failed_fax_dashboard:{key}": self.values[key] for key in keys if key in self.values}

    def set(self, key: str, value: Any, timeout_seconds: int | None = None) -> None:
        self.values[key] = value


class FakeSavedDirectory:
    """The Saved Directory service: contacts to answer with, and the paths asked for."""

    def __init__(self) -> None:
        self.contacts: list[dict[str, Any]] = []
        self.status_code = 200
        self.error: Exception | None = None
        self.paths: list[str] = []

    def get_json(self, path: str) -> Any:
        self.paths.append(path)
        if self.error is not None:
            raise self.error
        body = {"results": self.contacts}
        return SimpleNamespace(status_code=self.status_code, json=lambda: body)


@pytest.fixture(autouse=True)
def saved_directory_service(monkeypatch: pytest.MonkeyPatch) -> FakeSavedDirectory:
    """Every test gets an empty Saved Directory and a fresh cache, so nothing calls out."""
    service = FakeSavedDirectory()
    cache = FakeCache()
    monkeypatch.setattr(saved_directory, "science_http", service)
    monkeypatch.setattr(saved_directory, "get_cache", lambda: cache)
    return service


@pytest.fixture(autouse=True)
def render_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    """render_to_string only works inside the Canvas runtime, so read the file directly."""

    def fake_render(template_name: str, context: dict[str, Any] | None = None) -> str:
        text = (PLUGIN_DIR / template_name).read_text()
        for key, value in (context or {}).items():
            text = text.replace("{{ " + key + " }}", str(value))
        return text

    monkeypatch.setattr(dashboard_api, "render_to_string", fake_render)


@pytest.fixture
def call_api() -> CallApi:
    """Call the dashboard API end to end and return (status, decoded body, other effects)."""

    def call(
        method: str,
        path: str,
        *,
        body: Any = None,
        query: str = "",
        secrets: dict[str, str] | None = None,
        staff_id: str = "staff-1",
        user_type: str = "Staff",
        raw_body: bytes | None = None,
        event_type: int = EventType.SIMPLE_API_REQUEST,
    ) -> tuple[int, Any, list[Any]]:
        payload = raw_body if raw_body is not None else json.dumps(body).encode()
        event = SimpleNamespace(
            type=event_type,
            context={
                "method": method,
                "path": f"/app{path}",
                "query_string": query,
                "body": b64encode(payload if (body is not None or raw_body is not None) else b"").decode(),
                "headers": {
                    "canvas-logged-in-user-id": staff_id,
                    "canvas-logged-in-user-type": user_type,
                    "Content-Type": "application/json",
                },
            },
        )
        handler = dashboard_api.FailedFaxDashboardAPI(event, secrets=secrets or {})
        effects = handler.compute()
        response = effects[0]
        data = json.loads(response.payload)
        raw = b64decode(data["body"]) if data.get("body") else b""
        decoded: Any = raw
        if "json" in data["headers"].get("Content-Type", ""):
            decoded = json.loads(raw)
        elif data["headers"].get("Content-Type", "").startswith("text") or data["headers"].get(
            "Content-Type", ""
        ).startswith("application/javascript"):
            decoded = raw.decode()
        return data["status_code"], decoded, effects[1:]

    return call


@pytest.fixture(scope="session", autouse=True)
def custom_data_tables(django_db_setup: None, django_db_blocker: Any) -> Iterator[None]:
    """The test database is built without plugin custom data tables, so create ours once."""
    from django.db import connection

    from failed_fax_dashboard.models import (
        AlertStart,
        DashboardPreference,
        FaxAlert,
        FaxDismissal,
        FaxResend,
    )

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            for model in (AlertStart, DashboardPreference, FaxAlert, FaxDismissal, FaxResend):
                editor.create_model(model)
    yield
