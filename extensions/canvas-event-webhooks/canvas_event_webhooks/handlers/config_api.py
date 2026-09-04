"""Staff-facing SimpleAPI for configuring up to three independent webhooks."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.effects.http_request import HttpRequestEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin
from canvas_sdk.handlers.simple_api.api import delete, get, post, put
from logger import log

from canvas_event_webhooks.config_page import CONFIG_HTML

from canvas_event_webhooks.config_store import (
    MAX_WEBHOOKS,
    WebhookConfigError,
    WebhookConfigLimitError,
    WebhookConfigStore,
    WebhookConfigValidationError,
    WebhookNotFoundError,
    validate_webhook_url,
)
from canvas_event_webhooks.events_catalog import catalog_for_ui
from canvas_event_webhooks.handlers.base import (
    _MAX_RETRIES,
    _RETRY_ON,
    signature_headers,
)

TEST_EVENT_NAME = "webhook.test"


def _store(api: WebhookConfigAPI) -> WebhookConfigStore:
    return WebhookConfigStore(secrets=api.secrets)


def _error(message: str, status: HTTPStatus) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _list_payload(api: WebhookConfigAPI) -> dict:
    items = _store(api).list()
    return {
        "webhooks": [wh.to_dict() for wh in items],
        "max": MAX_WEBHOOKS,
        "count": len(items),
    }


class WebhookConfigAPI(StaffSessionAuthMixin, SimpleAPI):
    """CRUD + test endpoints for webhook configuration. Staff session required."""

    PREFIX = "/config"

    @get("/")
    def page(self) -> list[Response]:
        return [HTMLResponse(CONFIG_HTML)]

    @get("/catalog")
    def catalog(self) -> list[Response]:
        return [JSONResponse({"categories": catalog_for_ui()})]

    @get("/webhooks")
    def list_webhooks(self) -> list[Response]:
        return [JSONResponse(_list_payload(self))]

    @post("/webhooks")
    def create_webhook(self) -> list[Response]:
        try:
            body = self.request.json() or {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return [_error("Request body must be JSON.", HTTPStatus.BAD_REQUEST)]
        if not isinstance(body, dict):
            return [_error("Request body must be a JSON object.", HTTPStatus.BAD_REQUEST)]
        try:
            webhook, warning = _store(self).create(
                name=str(body.get("name") or ""),
                url=str(body.get("url") or ""),
                events=list(body.get("events") or []),
                enabled=bool(body.get("enabled", True)),
                include_details=bool(body.get("include_details", False)),
            )
        except WebhookConfigLimitError as exc:
            return [_error(str(exc), HTTPStatus.CONFLICT)]
        except WebhookConfigValidationError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        payload: dict = {"webhook": webhook.to_dict(), **_list_payload(self)}
        if warning:
            payload["warning"] = warning
        return [JSONResponse(payload, status_code=HTTPStatus.CREATED)]

    @put("/webhooks/<webhook_id>")
    def update_webhook(self) -> list[Response]:
        webhook_id = self.request.path_params["webhook_id"]
        try:
            body = self.request.json() or {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return [_error("Request body must be JSON.", HTTPStatus.BAD_REQUEST)]
        if not isinstance(body, dict):
            return [_error("Request body must be a JSON object.", HTTPStatus.BAD_REQUEST)]
        kwargs: dict = {}
        if "name" in body:
            kwargs["name"] = str(body.get("name") or "")
        if "url" in body:
            kwargs["url"] = str(body.get("url") or "")
        if "events" in body:
            kwargs["events"] = list(body.get("events") or [])
        if "enabled" in body:
            kwargs["enabled"] = bool(body["enabled"])
        if "include_details" in body:
            kwargs["include_details"] = bool(body["include_details"])
        try:
            webhook, warning = _store(self).update(webhook_id, **kwargs)
        except WebhookNotFoundError as exc:
            return [_error(str(exc), HTTPStatus.NOT_FOUND)]
        except WebhookConfigValidationError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except WebhookConfigError as rec:
            return [_error(str(rec), HTTPStatus.BAD_REQUEST)]
        payload = {"webhook": webhook.to_dict(), **_list_payload(self)}
        if warning:
            payload["warning"] = warning
        return [JSONResponse(payload)]

    @delete("/webhooks/<webhook_id>")
    def delete_webhook(self) -> list[Response]:
        webhook_id = self.request.path_params["webhook_id"]
        try:
            _store(self).delete(webhook_id)
        except WebhookNotFoundError as exc:
            return [_error(str(exc), HTTPStatus.NOT_FOUND)]
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"ok": True, **_list_payload(self)})]

    @post("/webhooks/<webhook_id>/regenerate")
    def regenerate(self) -> list[Response]:
        webhook_id = self.request.path_params["webhook_id"]
        try:
            webhook = _store(self).regenerate_secret(webhook_id)
        except WebhookNotFoundError as exc:
            return [_error(str(exc), HTTPStatus.NOT_FOUND)]
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"webhook": webhook.to_dict(), **_list_payload(self)})]

    @post("/webhooks/import-legacy")
    def import_legacy(self) -> list[Response]:
        try:
            webhook = _store(self).import_legacy()
        except WebhookConfigValidationError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"webhook": webhook.to_dict(), **_list_payload(self)}, status_code=HTTPStatus.CREATED)]

    @post("/webhooks/<webhook_id>/test")
    def test_webhook(self) -> list[Response]:
        webhook_id = self.request.path_params["webhook_id"]
        try:
            webhook = _store(self).get(webhook_id)
        except WebhookNotFoundError as exc:
            return [_error(str(exc), HTTPStatus.NOT_FOUND)]

        error, warning = validate_webhook_url(webhook.url)
        if error:
            return [_error(error, HTTPStatus.BAD_REQUEST)]
        if not webhook.secret:
            return [_error("This webhook has no secret to sign the test with.", HTTPStatus.BAD_REQUEST)]

        payload = {
            "id": str(uuid.uuid4()),
            "event": TEST_EVENT_NAME,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "canvas",
            "version": "1",
            "test": True,
            "message": "This is a test event from Canvas Event Webhooks.",
        }
        if webhook.include_details:
            payload["description"] = (
                "Canvas — Test event from Canvas Event Webhooks (names and details enabled)."
            )
            payload["data"] = {"record_type": "test"}
        body = json.dumps(payload)
        headers = {
            "Content-Type": "application/json",
            **signature_headers(webhook.secret, body),
        }
        log.info(
            "[Webhooks] Test delivery started webhook=%s event=%s",
            webhook.name,
            TEST_EVENT_NAME,
        )
        message = (
            "Test event sent. Canvas delivers webhooks asynchronously, so this "
            "page cannot show the remote HTTP status. Confirm receipt at your "
            "endpoint or with `canvas logs`."
        )
        response_body: dict = {"ok": True, "message": message}
        if warning:
            response_body["warning"] = warning
        return [
            JSONResponse(response_body),
            HttpRequestEffect(
                url=webhook.url,
                method="POST",
                headers=headers,
                body=body,
                retry_on_status_codes=_RETRY_ON,
            )
            .apply()
            .set_async(max_retries=_MAX_RETRIES),
        ]
