"""Tests for the Settings Access configuration app and API."""

import json
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from canvas_sdk.effects import EffectType
from django.template import Context, Engine

from hide_settings.applications.settings_admin import SettingsAccessAdmin
from hide_settings.handlers.admin_api import (
    AdminAPI,
    _admin_staff_ids,
    _canonical_staff_id,
    _json_for_script,
    _known_roles,
)

MODULE = "hide_settings.handlers.admin_api"
TEMPLATES = Path(__file__).parent.parent / "hide_settings" / "templates"
ADMIN_ID = "4150cd20de8a470aa570a852859ac87e"
OTHER_ID = "9b2f0e5a1c3d4e6f8a7b9c0d1e2f3a4b"

ROLE_ROWS = [
    {"internal_code": "MD", "name": "Physician", "domain": "CLI", "role_type": "PROVIDER"},
    {"internal_code": "AD", "name": "Administrative Developer", "domain": "ADM", "role_type": ""},
    # A second staff member holding MD: must not produce a duplicate entry.
    {"internal_code": "MD", "name": "Physician", "domain": "CLI", "role_type": "PROVIDER"},
    {"internal_code": "X1", "name": "Custom", "domain": "ZZZ", "role_type": None},
]


def make_api(secrets: dict[str, str] | None = None, body: object = None) -> AdminAPI:
    """Build an AdminAPI with the given secrets and a request whose json() returns body."""
    api = AdminAPI.__new__(AdminAPI)
    api.secrets = secrets or {}
    api.request = Mock()
    if isinstance(body, Exception):
        api.request.json.side_effect = body
    else:
        api.request.json.return_value = body
    return api


def credentials(user: dict[str, str] | None) -> Mock:
    """Session credentials carrying the given logged-in user."""
    creds = Mock()
    creds.logged_in_user = user
    return creds


def body_of(response: object) -> dict:
    """Decode a JSONResponse body."""
    return dict(json.loads(response.content))  # type: ignore[attr-defined]


@pytest.fixture
def roles() -> Iterator[MagicMock]:
    """Patch StaffRole so values() returns ROLE_ROWS."""
    with patch(f"{MODULE}.StaffRole") as model:
        model.objects.values.return_value = ROLE_ROWS
        yield model


@pytest.fixture
def config_model() -> Iterator[MagicMock]:
    """Patch the configuration model; defaults to no saved configuration."""
    with patch(f"{MODULE}.SettingsAccessConfig") as model:
        model.objects.first.return_value = None
        yield model


# ---------------------------------------------------------------------------- helpers


def test_canonical_staff_id_strips_dashes_case_and_space() -> None:
    """Dashed, uppercase, padded ids compare equal to the plain form."""
    assert _canonical_staff_id(" 4150CD20-DE8A-470A-A570-A852859AC87E ") == ADMIN_ID
    assert _canonical_staff_id(None) == ""


def test_admin_staff_ids_parses_comma_list() -> None:
    """The secret is split on commas and blank entries are dropped."""
    ids = _admin_staff_ids({"ADMIN_STAFF_IDS": f"{ADMIN_ID}, ,{OTHER_ID.upper()},"})
    assert ids == {ADMIN_ID, OTHER_ID}
    assert _admin_staff_ids({}) == set()


def test_json_for_script_cannot_close_the_script_tag() -> None:
    """Angle brackets and ampersands are escaped so a role name cannot break out of <script>."""
    out = _json_for_script([{"name": "</script><script>alert(1)</script>&"}])
    assert "<" not in out and ">" not in out and "&" not in out
    assert json.loads(out) == [{"name": "</script><script>alert(1)</script>&"}]


def test_known_roles_dedupes_and_sorts(roles: MagicMock) -> None:
    """One entry per role code, sorted by domain then name, with labels filled in."""
    result = _known_roles()

    assert [r["internal_code"] for r in result] == ["AD", "MD", "X1"]
    assert result[0]["domain_label"] == "Administrative"
    assert result[1]["domain_label"] == "Clinical"
    assert result[2]["domain_label"] == "ZZZ"
    assert result[2]["role_type"] == ""


# ---------------------------------------------------------------------------- authenticate


def test_authenticate_allows_listed_admin() -> None:
    """A staff member listed in ADMIN_STAFF_IDS is allowed, in either id form."""
    api = make_api({"ADMIN_STAFF_IDS": "4150cd20-de8a-470a-a570-a852859ac87e"})
    assert api.authenticate(credentials({"type": "Staff", "id": ADMIN_ID})) is True


def test_authenticate_denies_unlisted_staff() -> None:
    """Staff not in the list are denied."""
    api = make_api({"ADMIN_STAFF_IDS": ADMIN_ID})
    assert api.authenticate(credentials({"type": "Staff", "id": OTHER_ID})) is False


@pytest.mark.parametrize("secret", [None, "", " , "])
def test_authenticate_fails_closed_without_secret(secret: str | None) -> None:
    """A missing or blank ADMIN_STAFF_IDS denies everyone."""
    secrets = {} if secret is None else {"ADMIN_STAFF_IDS": secret}
    api = make_api(secrets)
    assert api.authenticate(credentials({"type": "Staff", "id": ADMIN_ID})) is False


@pytest.mark.parametrize("user", [None, {}, {"type": "Patient", "id": ADMIN_ID}])
def test_authenticate_denies_non_staff(user: dict[str, str] | None) -> None:
    """Patients and missing users are denied even if their id is listed."""
    api = make_api({"ADMIN_STAFF_IDS": ADMIN_ID})
    assert api.authenticate(credentials(user)) is False


# ---------------------------------------------------------------------------- GET /config


def test_config_page_marks_allowed_roles(roles: MagicMock, config_model: MagicMock) -> None:
    """The page embeds every known role with its current allowed state."""
    config_model.objects.first.return_value = MagicMock(allowed_role_codes=["AD"])

    with patch(f"{MODULE}.render_to_string", return_value="<html>") as render:
        responses = make_api().config_page()

    assert responses[0].content == b"<html>"
    template, context = render.call_args.args
    assert template == "templates/admin.html"
    embedded = json.loads(context["roles_json"])
    assert {r["internal_code"]: r["allowed"] for r in embedded} == {
        "AD": True,
        "MD": False,
        "X1": False,
    }
    assert context["cache_bust"]


def test_config_page_without_saved_config(roles: MagicMock, config_model: MagicMock) -> None:
    """With nothing saved, every role shows as not allowed."""
    with patch(f"{MODULE}.render_to_string", return_value="") as render:
        make_api().config_page()

    embedded = json.loads(render.call_args.args[1]["roles_json"])
    assert not any(r["allowed"] for r in embedded)


def test_admin_template_embeds_roles_and_versions_assets() -> None:
    """The real template places the escaped roles in the page and cache-busts asset URLs."""
    template = (TEMPLATES / "admin.html").read_text()
    roles_json = _json_for_script([{"internal_code": "MD", "name": "</script>"}])
    html = (
        Engine()
        .from_string(template)
        .render(Context({"roles_json": roles_json, "cache_bust": "9.9.9"}))
    )

    assert "window.__ROLES__ = " + roles_json + ";" in html
    assert "</script><" not in html.split("window.__ROLES__")[1].split(";")[0]
    assert "styles.css?v=9.9.9" in html
    assert "app.js?v=9.9.9" in html


# ---------------------------------------------------------------------------- POST /config


def test_save_creates_config(roles: MagicMock, config_model: MagicMock) -> None:
    """The first save creates the configuration, deduped and sorted."""
    responses = make_api(body={"allowed_role_codes": ["MD", "AD", "MD"]}).save_config()

    assert responses[0].status_code == HTTPStatus.OK
    assert body_of(responses[0])["allowed_role_codes"] == ["AD", "MD"]
    config_model.objects.create.assert_called_once_with(allowed_role_codes=["AD", "MD"])


def test_save_updates_existing_config(roles: MagicMock, config_model: MagicMock) -> None:
    """A later save updates the existing row instead of creating another."""
    existing = MagicMock(allowed_role_codes=["MD"])
    config_model.objects.first.return_value = existing

    make_api(body={"allowed_role_codes": []}).save_config()

    assert existing.allowed_role_codes == []
    existing.save.assert_called_once()
    config_model.objects.create.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"allowed_role_codes": "AD"},
        {"allowed_role_codes": ["AD", 3]},
    ],
)
def test_save_rejects_malformed_body(
    roles: MagicMock, config_model: MagicMock, body: object
) -> None:
    """Anything other than a list of strings is a 400 and nothing is saved."""
    responses = make_api(body=body).save_config()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    config_model.objects.create.assert_not_called()


def test_save_rejects_non_json(roles: MagicMock, config_model: MagicMock) -> None:
    """A body that is not JSON is a 400."""
    responses = make_api(body=ValueError("bad json")).save_config()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert "JSON" in body_of(responses[0])["error"]


def test_save_rejects_unknown_role_codes(roles: MagicMock, config_model: MagicMock) -> None:
    """Role codes nobody holds are rejected by name."""
    responses = make_api(body={"allowed_role_codes": ["AD", "NOPE"]}).save_config()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert "NOPE" in body_of(responses[0])["error"]
    config_model.objects.create.assert_not_called()


# ---------------------------------------------------------------------------- assets and app


def test_css_and_js_routes_serve_content_types() -> None:
    """The stylesheet and script are served from their templates with the right content types."""
    api = make_api()
    with patch(f"{MODULE}.render_to_string", side_effect=lambda name: f"/* {name} */") as render:
        css = api.get_css()[0]
        js = api.get_js()[0]

    assert [c.args[0] for c in render.call_args_list] == [
        "templates/admin.css",
        "templates/admin.js",
    ]
    assert css.headers["Content-Type"] == "text/css"
    assert js.headers["Content-Type"] == "text/javascript"
    assert css.content == b"/* templates/admin.css */"


def test_asset_templates_exist() -> None:
    """The files the asset routes render are present."""
    assert "role-row" in (TEMPLATES / "admin.css").read_text()
    assert "allowed_role_codes" in (TEMPLATES / "admin.js").read_text()


def test_application_opens_config_modal() -> None:
    """Opening the app launches the configuration page in a modal."""
    app = SettingsAccessAdmin.__new__(SettingsAccessAdmin)
    effect = app.on_open()

    assert effect.type == EffectType.LAUNCH_MODAL
    assert "/plugin-io/api/hide_settings/admin/config?v=" in effect.payload
