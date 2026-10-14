"""Tests for the admin API: access gating, CSRF defence, body parsing, and each endpoint.

Mocked throughout, per CPA's testing rules: these are about what the code does
with a request, not about what the database returns.
"""

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse
from canvas_sdk.events import Event, EventType

from preventive_screenings.api.admin_page import ACCESS_DENIED_HTML
from preventive_screenings.api.routes import ScreeningAdminAPI
from preventive_screenings.services.config_store import MAX_SCREENINGS

MODULE = "preventive_screenings.api.routes"
READ_STAFF_ID = call.headers.get("canvas-logged-in-user-id", "")
READ_ADMIN_KEYS = call.get("ADMIN_STAFF_KEYS")
UNCONFIGURED_WARNING = call.warning(
    "ADMIN_STAFF_KEYS not configured, denying Preventive Screenings access"
)

ADMIN = "staff-key-1"
FORBIDDEN = JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)

# Every route, what a non-admin gets back from it, and the dependency that must
# not be touched on the way. `test_denial_cases_cover_every_route` keeps this in
# step with the routes actually registered, so a new route cannot ship ungated.
DENIAL_CASES = [
    (
        "GET",
        "/admin/ui",
        "serve_admin",
        "build_admin_html",
        HTMLResponse(ACCESS_DENIED_HTML, status_code=HTTPStatus.FORBIDDEN),
    ),
    ("GET", "/admin/config", "get_config", "load_config", FORBIDDEN),
    (
        "POST",
        "/admin/config",
        "put_config",
        "save_config",
        JSONResponse({"success": False, "error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN),
    ),
]


def denied_warning(staff_id: str) -> Any:
    return call.warning(f"Preventive Screenings access denied for staff key '{staff_id}'")


def event(method: str, path: str, **context: Any) -> Event:
    return Event(
        EventRequest(
            type=EventType.SIMPLE_API_REQUEST,
            context=json.dumps({"method": method, "path": path, **context}),
        )
    )


def api(
    method: str, path: str, request: MagicMock, secrets: MagicMock | None = None
) -> ScreeningAdminAPI:
    instance = ScreeningAdminAPI(event=event(method, path))
    instance.request = request
    if secrets is not None:
        instance.secrets = secrets
    return instance


def a_request(staff_id: str, content_type: str | None = None) -> MagicMock:
    request = MagicMock()
    request.headers.get.return_value = staff_id
    request.content_type = content_type
    return request


def secrets_with(admin_staff_keys: str | None) -> MagicMock:
    secrets = MagicMock()
    secrets.get.return_value = admin_staff_keys
    return secrets


def a_config(count: int = 1) -> dict:
    return {"screenings": [{"name": f"S{index}"} for index in range(count)]}


# --- access gating -----------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "handler", "dependency", "expected"), DENIAL_CASES)
def test_a_non_admin_is_refused_on_every_route(
    method: str, path: str, handler: str, dependency: str, expected: Any
) -> None:
    """Every route is gated, not just the one that serves the page."""
    request = a_request("someone-else", "application/json")
    secrets = secrets_with(ADMIN)

    with patch(f"{MODULE}.{dependency}") as guarded, patch(f"{MODULE}.log") as log:
        responses = getattr(api(method, path, request, secrets), handler)()

    assert responses[0].status_code == expected.status_code
    assert responses[0].content == expected.content
    assert guarded.mock_calls == []
    assert log.mock_calls == [denied_warning("someone-else")]


@pytest.mark.parametrize(("method", "path", "handler", "dependency", "expected"), DENIAL_CASES)
def test_unset_admin_keys_lock_everyone_out(
    method: str, path: str, handler: str, dependency: str, expected: Any
) -> None:
    """It fails closed: with the variable unset, nobody gets in."""
    with patch(f"{MODULE}.{dependency}") as guarded, patch(f"{MODULE}.log") as log:
        responses = getattr(
            api(method, path, a_request(ADMIN, "application/json"), secrets_with("")), handler
        )()

    assert responses[0].status_code == expected.status_code
    assert guarded.mock_calls == []
    assert log.mock_calls == [UNCONFIGURED_WARNING]


def test_denial_cases_cover_every_route() -> None:
    """Adding a route fails this until it is listed above, which runs it through
    the non-admin denial test.

    **Do not update DENIAL_CASES just to make this pass. Add the admin check to
    the new route.**
    """
    # Routes are stored as (compiled pattern, handler) per method.
    registered = {
        (method, pattern.pattern)
        for method, routes in ScreeningAdminAPI._ROUTES.items()
        for pattern, _handler in routes
    }
    assert registered == {(method, path) for method, path, _h, _d, _e in DENIAL_CASES}


def test_a_listed_admin_is_allowed() -> None:
    with patch(f"{MODULE}.load_config", return_value=a_config()), patch(
        f"{MODULE}.catalog_for_ui", return_value={}
    ):
        responses = api("GET", "/admin/config", a_request(ADMIN), secrets_with(ADMIN)).get_config()

    assert responses[0].status_code == HTTPStatus.OK


def test_one_of_several_listed_admins_is_allowed() -> None:
    keys = " staff-a , staff-b ,staff-c "

    with patch(f"{MODULE}.load_config", return_value=a_config()), patch(
        f"{MODULE}.catalog_for_ui", return_value={}
    ):
        responses = api(
            "GET", "/admin/config", a_request("staff-b"), secrets_with(keys)
        ).get_config()

    assert responses[0].status_code == HTTPStatus.OK


def test_a_prefix_of_a_listed_key_is_not_allowed() -> None:
    """The key match is exact, not a substring."""
    with patch(f"{MODULE}.load_config") as load, patch(f"{MODULE}.log"):
        responses = api(
            "GET", "/admin/config", a_request("staff-key"), secrets_with("staff-key-1")
        ).get_config()

    assert responses[0].status_code == HTTPStatus.FORBIDDEN
    assert load.mock_calls == []


def test_an_empty_staff_id_is_not_allowed() -> None:
    """A request arriving with no staff header is not an admin."""
    with patch(f"{MODULE}.load_config") as load, patch(f"{MODULE}.log"):
        responses = api("GET", "/admin/config", a_request(""), secrets_with(ADMIN)).get_config()

    assert responses[0].status_code == HTTPStatus.FORBIDDEN
    assert load.mock_calls == []


def test_no_staff_key_bypasses_the_setting() -> None:
    """There is deliberately no hardcoded bypass key, and this keeps it that way.

    An earlier version of the sibling plugin always allowed a supposed "Canvas
    root key". The claim behind it was never verified, and the lockout it
    guarded against cannot happen: ADMIN_STAFF_KEYS is set outside this page.
    """
    candidates = [
        "4150cd20de8a470aa570a852859ac87e",
        "root",
        "admin",
        "00000000000000000000000000000000",
    ]

    for candidate in candidates:
        with patch(f"{MODULE}.load_config") as load, patch(f"{MODULE}.log"):
            responses = api(
                "GET", "/admin/config", a_request(candidate), secrets_with("only-this-one")
            ).get_config()

        assert responses[0].status_code == HTTPStatus.FORBIDDEN, candidate
        assert load.mock_calls == []


def test_the_access_denied_page_returns_403_not_200() -> None:
    """A 200 would let a browser cache it, and hides the refusal from monitoring."""
    with patch(f"{MODULE}.log"):
        responses = api(
            "GET", "/admin/ui", a_request("nobody"), secrets_with(ADMIN)
        ).serve_admin()

    assert responses[0].status_code == HTTPStatus.FORBIDDEN
    assert "Access restricted" in responses[0].content.decode()


# --- CSRF --------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", "", None],
)
def test_a_save_with_the_wrong_content_type_is_refused(content_type: str | None) -> None:
    """The SDK parses a JSON body whatever its declared type, so a cross-site
    `<form enctype="text/plain">` could otherwise post a forged config using an
    admin's session. A cross-origin application/json request needs a CORS
    preflight a foreign site cannot pass."""
    request = a_request(ADMIN, content_type)
    request.json.return_value = {"config": a_config()}

    with patch(f"{MODULE}.save_config") as save:
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert responses[0].status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert save.mock_calls == []


def test_the_content_type_check_runs_after_the_admin_check() -> None:
    """A non-admin is refused as a non-admin, whatever they send."""
    request = a_request("nobody", "text/plain")

    with patch(f"{MODULE}.save_config") as save, patch(f"{MODULE}.log"):
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert responses[0].status_code == HTTPStatus.FORBIDDEN
    assert save.mock_calls == []


# --- saving ------------------------------------------------------------------


def test_a_valid_save_persists_the_config() -> None:
    request = a_request(ADMIN, "application/json")
    request.json.return_value = {"config": a_config()}

    with patch(f"{MODULE}.save_config", return_value=True) as save:
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert json.loads(responses[0].content) == {"success": True}
    assert save.mock_calls == [call(a_config())]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"config": None},
        {"config": "not a dict"},
        {"config": {}},
        {"config": {"screenings": "not a list"}},
        {"config": {"screenings": None}},
    ],
)
def test_a_malformed_body_is_rejected(body: dict) -> None:
    request = a_request(ADMIN, "application/json")
    request.json.return_value = body

    with patch(f"{MODULE}.save_config") as save:
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert save.mock_calls == []


def test_an_unparseable_body_is_rejected_rather_than_raising() -> None:
    """ValueError covers every way the SDK's json() fails: base64, UTF-8 and
    JSON decoding errors all subclass it."""
    request = a_request(ADMIN, "application/json")
    request.json.side_effect = ValueError("bad body")

    with patch(f"{MODULE}.save_config") as save:
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert save.mock_calls == []


def test_a_non_object_body_is_rejected() -> None:
    request = a_request(ADMIN, "application/json")
    request.json.return_value = ["a", "list"]

    with patch(f"{MODULE}.save_config") as save:
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert save.mock_calls == []


def test_too_many_screenings_are_refused() -> None:
    """Every chart open reads the whole set, so the cap is enforced on the way in."""
    request = a_request(ADMIN, "application/json")
    request.json.return_value = {"config": a_config(MAX_SCREENINGS + 1)}

    with patch(f"{MODULE}.save_config") as save:
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert f"At most {MAX_SCREENINGS}" in json.loads(responses[0].content)["error"]
    assert save.mock_calls == []


def test_exactly_the_cap_is_accepted() -> None:
    request = a_request(ADMIN, "application/json")
    request.json.return_value = {"config": a_config(MAX_SCREENINGS)}

    with patch(f"{MODULE}.save_config", return_value=True):
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    assert json.loads(responses[0].content) == {"success": True}


def test_a_failed_save_tells_the_admin_what_to_do() -> None:
    """A missing custom-data namespace is actionable: reinstall."""
    request = a_request(ADMIN, "application/json")
    request.json.return_value = {"config": a_config()}

    with patch(f"{MODULE}.save_config", return_value=False):
        responses = api("POST", "/admin/config", request, secrets_with(ADMIN)).put_config()

    body = json.loads(responses[0].content)
    assert body["success"] is False
    assert "Reinstall the plugin." in body["error"]


# --- reading -----------------------------------------------------------------


def test_the_config_endpoint_returns_the_rules_and_the_catalog() -> None:
    """One endpoint, so the editor needs one round trip to render."""
    with patch(f"{MODULE}.load_config", return_value=a_config()), patch(
        f"{MODULE}.catalog_for_ui", return_value={"value_sets": []}
    ), patch(f"{MODULE}.order_code_warnings", return_value=["77067"]):
        responses = api("GET", "/admin/config", a_request(ADMIN), secrets_with(ADMIN)).get_config()

    body = json.loads(responses[0].content)
    assert body == {
        "config": a_config(),
        "catalog": {"value_sets": []},
        "unresolvable_order_codes": ["77067"],
    }


def test_the_catalog_check_cannot_stop_the_editor_loading() -> None:
    """It reads the practice's own catalogs, which may be unreadable or absent
    on any given instance. The rules still have to be editable."""
    with patch(f"{MODULE}.load_config", return_value=a_config()), patch(
        f"{MODULE}.catalog_for_ui", return_value={"value_sets": []}
    ), patch(f"{MODULE}.order_code_warnings", return_value=[]):
        responses = api("GET", "/admin/config", a_request(ADMIN), secrets_with(ADMIN)).get_config()

    assert responses[0].status_code == HTTPStatus.OK
    assert json.loads(responses[0].content)["unresolvable_order_codes"] == []


def test_the_admin_page_is_served_to_an_admin() -> None:
    with patch(f"{MODULE}.build_admin_html", return_value="<html>editor</html>"):
        responses = api("GET", "/admin/ui", a_request(ADMIN), secrets_with(ADMIN)).serve_admin()

    assert responses[0].status_code == HTTPStatus.OK
    assert responses[0].content.decode() == "<html>editor</html>"
