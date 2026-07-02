"""Tests for the admin console page handler and the no access page.

The HTML page moved off the admin gated status API onto its own session gated
handler so a logged in staff member who is not on the allowlist sees a styled
explanation instead of the raw framework 401 JSON. The console's data and
control endpoints stay locked. These tests pin that the page branches on admin
membership, that the no access page names the staff id and stays self
contained, and that the strict status API no longer carries the page route.
"""

from __future__ import annotations

import json
from base64 import b64decode
from unittest.mock import MagicMock

from salesforce_to_canvas_integration.handlers.status_api import (
    SalesforceAdminPage,
    SalesforceStatusAPI,
)
from salesforce_to_canvas_integration.templates import (
    render_no_access_page,
    render_not_configured_page,
)

ADMIN_KEY = "4150cd20de8a470aa570a852859ac87e"
OTHER_KEY = "6d3680b8bc224893ad7211bf1ecd33b3"


def _body(effect: object) -> str:
    payload = json.loads(effect.payload)  # type: ignore[attr-defined]
    return b64decode(payload["body"]).decode()


# A complete required secret set so load_config succeeds. The page's admin
# check mirrors the strict status gate, both call load_config, so an admin only
# reaches the console when the config is valid. See services/config.py.
_VALID_SECRETS = {
    "SF_CLIENT_ID": "client-id",
    "SF_CLIENT_SECRET": "client-secret",
    "SF_LOGIN_URL": "https://login.salesforce.com",
    "SF_WEBHOOK_SECRET": "webhook-secret",
    "SF_ADMIN_STAFF_IDS": ADMIN_KEY,
    "SF_SOURCE_SOBJECT": "Contact",
}


def _make_page(*, staff_key: str) -> SalesforceAdminPage:
    handler = SalesforceAdminPage.__new__(SalesforceAdminPage)
    handler.event = MagicMock()
    handler.secrets = dict(_VALID_SECRETS)
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    handler.request = MagicMock()
    handler.request.headers = {"canvas-logged-in-user-id": staff_key}
    return handler


def test_admin_staff_gets_the_full_console() -> None:
    """A staff key on the allowlist renders the console with its tabs."""
    html = _body(_make_page(staff_key=ADMIN_KEY).admin_page()[0])

    assert 'id="tab-records"' in html
    assert "You do not have access" not in html


def test_non_admin_staff_gets_the_no_access_page() -> None:
    """A staff key off the allowlist renders the no access page with the id."""
    html = _body(_make_page(staff_key=OTHER_KEY).admin_page()[0])

    assert "You do not have access" in html
    assert OTHER_KEY in html
    # The console did not render on this path.
    assert 'id="tab-records"' not in html


def test_missing_staff_header_falls_back_without_an_id_box() -> None:
    """No staff id on the session renders the fallback line, no empty id box."""
    html = _body(_make_page(staff_key="").admin_page()[0])

    assert "You do not have access" in html
    assert "did not carry a staff id" in html
    assert 'class="id-box"' not in html


def test_unconfigured_secrets_show_the_not_configured_page() -> None:
    """A config error shows the not configured page, not a permission denial.

    A missing secret raises ConfigError before the allowlist is checked, so
    even an admin key must not see the no access page. The page must report a
    configuration problem and must not leak the missing secret name.
    """
    handler = SalesforceAdminPage.__new__(SalesforceAdminPage)
    handler.event = MagicMock()
    handler.secrets = {}  # SF_ADMIN_STAFF_IDS missing, load_config raises ConfigError
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    handler.request = MagicMock()
    handler.request.headers = {"canvas-logged-in-user-id": ADMIN_KEY}

    html = _body(handler.admin_page()[0])

    assert "is not configured" in html
    assert "Contact an administrator" in html
    assert "You do not have access" not in html
    # The missing secret name must not leak to the page.
    assert "SF_" not in html


def test_admin_page_responses_are_never_cached() -> None:
    """Every branch of the page route sends Cache-Control no-store.

    Without it the browser may reuse a cached copy of the page from an iframe
    reload and pair stale HTML with a stale bundle, so an old broken build
    keeps rendering after a fresh install. All three branches carry the
    header, the console, the no access page, and the not configured page.
    """
    def _cache_control(effect: object) -> str:
        payload = json.loads(effect.payload)  # type: ignore[attr-defined]
        return str(payload["headers"].get("Cache-Control", ""))

    assert _cache_control(_make_page(staff_key=ADMIN_KEY).admin_page()[0]) == "no-store"
    assert _cache_control(_make_page(staff_key=OTHER_KEY).admin_page()[0]) == "no-store"

    unconfigured = _make_page(staff_key=ADMIN_KEY)
    unconfigured.secrets = {}
    assert _cache_control(unconfigured.admin_page()[0]) == "no-store"


def test_status_api_no_longer_serves_the_admin_page() -> None:
    """The strict status API dropped the page route, the new handler owns it."""
    assert not hasattr(SalesforceStatusAPI, "admin_page")
    assert hasattr(SalesforceAdminPage, "admin_page")


def test_no_access_page_escapes_the_staff_id() -> None:
    """A staff id with markup is escaped so it cannot inject into the page."""
    html = render_no_access_page(staff_id='<script>alert(1)</script>')

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_no_access_page_is_self_contained() -> None:
    """The page loads Lato but never the admin gated design system bundle."""
    html = render_no_access_page(staff_id=OTHER_KEY)

    assert "fonts.googleapis.com/css?family=Lato" in html
    assert "canvas-plugin-ui.css" not in html
    assert "canvas-plugin-ui.js" not in html


def test_no_access_page_has_no_banned_characters() -> None:
    """No em dash, en dash, or curly quotes reach the rendered page."""
    html = render_no_access_page(staff_id=OTHER_KEY)

    for ch in ("—", "–", "“", "”", "‘", "’"):
        assert ch not in html


def test_not_configured_page_reports_configuration_not_permission() -> None:
    """The page names a configuration problem, never a permission denial, and
    never leaks a secret name or a staff id."""
    html = render_not_configured_page()

    assert "is not configured" in html
    assert "Contact an administrator" in html
    assert "You do not have access" not in html
    assert "SF_" not in html


def test_not_configured_page_is_self_contained() -> None:
    """The page loads Lato but never the admin gated design system bundle."""
    html = render_not_configured_page()

    assert "fonts.googleapis.com/css?family=Lato" in html
    assert "canvas-plugin-ui.css" not in html
    assert "canvas-plugin-ui.js" not in html


def test_not_configured_page_has_no_banned_characters() -> None:
    """No em dash, en dash, or curly quotes reach the rendered page."""
    html = render_not_configured_page()

    for ch in ("—", "–", "“", "”", "‘", "’"):
        assert ch not in html
