import json
from base64 import b64decode, b64encode
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from canvas_sdk.events import EventType

import failed_fax_dashboard.api.dashboard_api as dashboard_api

CallApi = Callable[..., tuple[int, Any, list[Any]]]

PLUGIN_DIR = Path(dashboard_api.__file__).resolve().parent.parent


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
def fax_dismissal_table(django_db_setup: None, django_db_blocker: Any) -> Iterator[None]:
    """The test database is built without plugin custom data tables, so create ours once."""
    from django.db import connection

    from failed_fax_dashboard.models import FaxDismissal

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.create_model(FaxDismissal)
    yield
