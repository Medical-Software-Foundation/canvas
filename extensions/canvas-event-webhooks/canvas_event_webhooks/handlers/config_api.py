"""Admin-only SimpleAPI for configuring up to three independent webhooks.

Destinations configured here receive PHI, so every data route requires a staff
session whose id is listed in the ``config-admin-staff-ids`` variable. Access
fails closed when that variable is unset.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.effects.http_request import HttpRequestEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
)
from canvas_sdk.handlers.simple_api.api import delete, get, post, put
from logger import log

from canvas_event_webhooks.config_page import CONFIG_HTML

from canvas_event_webhooks.config_store import (
    MAX_WEBHOOKS,
    WebhookConfig,
    WebhookConfigError,
    WebhookConfigLimitError,
    WebhookConfigStore,
    WebhookConfigValidationError,
    WebhookNotFoundError,
    validate_webhook_url,
    webhook_host,
)
from canvas_event_webhooks.events_catalog import catalog_for_ui
from canvas_event_webhooks.handlers.base import (
    _MAX_RETRIES,
    _RETRY_ON,
    signature_headers,
)

TEST_EVENT_NAME = "webhook.test"
ADMIN_STAFF_IDS_VARIABLE = "config-admin-staff-ids"
STAFF_ID_HEADER = "canvas-logged-in-user-id"
SECRET_MASK = "••••"


def _store(api: WebhookConfigAPI) -> WebhookConfigStore:
    return WebhookConfigStore(secrets=api.secrets)


def _error(message: str, status: HTTPStatus) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _canonical_staff_id(value: object) -> str:
    """Staff ids compare dashless and lowercase, so either UUID form can be configured."""
    return str(value or "").strip().replace("-", "").lower()


def _admin_staff_ids(secrets: dict) -> set[str]:
    raw = secrets.get(ADMIN_STAFF_IDS_VARIABLE) or ""
    return {_canonical_staff_id(part) for part in raw.split(",") if part.strip()}


def _secret_hint(secret: str) -> str:
    if not secret:
        return ""
    # Short (legacy CLI) secrets get no suffix so the hint never reveals much of them.
    return SECRET_MASK + secret[-4:] if len(secret) >= 16 else SECRET_MASK


def _public(webhook: WebhookConfig, *, reveal_secret: bool = False) -> dict:
    """Webhook as sent to the page. The secret is included only when newly issued."""
    return {
        **webhook.to_dict(),
        "secret": webhook.secret if reveal_secret else "",
        "has_secret": bool(webhook.secret),
        "secret_hint": _secret_hint(webhook.secret),
    }


def _list_payload(api: WebhookConfigAPI) -> dict:
    items = _store(api).list()
    return {
        "webhooks": [_public(wh) for wh in items],
        "max": MAX_WEBHOOKS,
        "count": len(items),
    }


def _unsupported_media_type(api: WebhookConfigAPI) -> list[Response]:
    """Refuse state-changing requests that are not JSON.

    The config page always sends ``application/json``. Requiring it means a
    cross-site form post cannot drive these routes with a staff member's session.
    """
    if (api.request.content_type or "").lower() == "application/json":
        return []
    return [_error("Content-Type must be application/json.", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)]


def _audit(api: WebhookConfigAPI, action: str, webhook: WebhookConfig) -> None:
    """Record who acted on which destination. Never logs secrets, paths, or query strings."""
    log.info(
        "[Webhooks] Config %s by staff=%s webhook_id=%s host=%s enabled=%s include_details=%s",
        action,
        api.request.headers.get(STAFF_ID_HEADER) or "",
        webhook.id,
        webhook_host(webhook.url),
        webhook.enabled,
        webhook.include_details,
    )


class WebhookConfigAPI(StaffSessionAuthMixin, SimpleAPI):
    """CRUD + test endpoints for webhook configuration. Listed admin staff only."""

    PREFIX = "/config"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Require a staff session and, for everything except the static page, a listed admin."""
        super().authenticate(credentials)
        if self.request.method == "GET" and self.request.path == f"{self.PREFIX}/":
            # Static HTML with no configuration data; the calls it makes are checked below.
            return True
        staff_id = _canonical_staff_id(credentials.logged_in_user.get("id"))
        admin_ids = _admin_staff_ids(self.secrets)
        if not admin_ids:
            log.warning(
                "[Webhooks] %s is not set; denying webhook configuration access for staff=%s.",
                ADMIN_STAFF_IDS_VARIABLE,
                staff_id,
            )
            return False
        if staff_id not in admin_ids:
            log.warning("[Webhooks] Denied webhook configuration access for staff=%s.", staff_id)
            return False
        return True

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
        if rejected := _unsupported_media_type(self):
            return rejected
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
        _audit(self, "created", webhook)
        payload: dict = {"webhook": _public(webhook, reveal_secret=True), **_list_payload(self)}
        if warning:
            payload["warning"] = warning
        return [JSONResponse(payload, status_code=HTTPStatus.CREATED)]

    @put("/webhooks/<webhook_id>")
    def update_webhook(self) -> list[Response]:
        if rejected := _unsupported_media_type(self):
            return rejected
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
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        _audit(self, "updated", webhook)
        payload = {"webhook": _public(webhook), **_list_payload(self)}
        if warning:
            payload["warning"] = warning
        return [JSONResponse(payload)]

    @delete("/webhooks/<webhook_id>")
    def delete_webhook(self) -> list[Response]:
        if rejected := _unsupported_media_type(self):
            return rejected
        webhook_id = self.request.path_params["webhook_id"]
        try:
            webhook = _store(self).delete(webhook_id)
        except WebhookNotFoundError as exc:
            return [_error(str(exc), HTTPStatus.NOT_FOUND)]
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        _audit(self, "deleted", webhook)
        return [JSONResponse({"ok": True, **_list_payload(self)})]

    @post("/webhooks/<webhook_id>/regenerate")
    def regenerate(self) -> list[Response]:
        if rejected := _unsupported_media_type(self):
            return rejected
        webhook_id = self.request.path_params["webhook_id"]
        try:
            webhook = _store(self).regenerate_secret(webhook_id)
        except WebhookNotFoundError as exc:
            return [_error(str(exc), HTTPStatus.NOT_FOUND)]
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        _audit(self, "secret_regenerated", webhook)
        return [
            JSONResponse({"webhook": _public(webhook, reveal_secret=True), **_list_payload(self)})
        ]

    @get("/webhooks/<webhook_id>/secret")
    def reveal_secret(self) -> list[Response]:
        webhook_id = self.request.path_params["webhook_id"]
        try:
            webhook = _store(self).get(webhook_id)
        except WebhookNotFoundError as exc:
            return [_error(str(exc), HTTPStatus.NOT_FOUND)]
        _audit(self, "secret_revealed", webhook)
        return [JSONResponse({"id": webhook.id, "secret": webhook.secret})]

    @post("/webhooks/import-legacy")
    def import_legacy(self) -> list[Response]:
        if rejected := _unsupported_media_type(self):
            return rejected
        try:
            webhook = _store(self).import_legacy()
        except WebhookConfigValidationError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        except WebhookConfigError as exc:
            return [_error(str(exc), HTTPStatus.BAD_REQUEST)]
        _audit(self, "legacy_imported", webhook)
        return [
            JSONResponse(
                {"webhook": _public(webhook, reveal_secret=True), **_list_payload(self)},
                status_code=HTTPStatus.CREATED,
            )
        ]

    @post("/webhooks/<webhook_id>/test")
    def test_webhook(self) -> list[Response]:
        if rejected := _unsupported_media_type(self):
            return rejected
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
        _audit(self, "test_sent", webhook)
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
