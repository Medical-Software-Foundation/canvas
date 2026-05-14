"""Tests for api/delegation_api.py — admin UI and delegation CRUD."""

from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import call, patch


def _make_handler(
    secrets: dict | None = None,
    headers: dict | None = None,
    body: str | bytes = "",
    admin: bool = False,
):
    from dea_prescriber_filter.api.delegation_api import DelegationUIApi

    handler = DelegationUIApi.__new__(DelegationUIApi)
    if admin:
        secrets = {**(secrets or {}), "ADMIN_STAFF_IDS": "admin-test"}
        headers = {**(headers or {}), "canvas-logged-in-user-id": "admin-test"}
    handler.secrets = secrets or {}
    handler.request = SimpleNamespace(headers=headers or {}, body=body)
    return handler


# ─────────────────────────────────────────────────────────────
# _is_admin_user — auth check
# ─────────────────────────────────────────────────────────────

def test_is_admin_user_denies_when_secret_empty() -> None:
    """Empty ADMIN_STAFF_IDS secret denies admin access (fail-closed)."""
    tested = _make_handler(secrets={"ADMIN_STAFF_IDS": ""})

    result = tested._is_admin_user()

    assert result is False


def test_is_admin_user_denies_when_secret_missing() -> None:
    """Missing ADMIN_STAFF_IDS secret denies admin access (fail-closed)."""
    tested = _make_handler(secrets={})

    result = tested._is_admin_user()

    assert result is False


def test_is_admin_user_restricts_when_secret_set_and_user_not_listed() -> None:
    """A logged-in user not on the admin list is denied access."""
    tested = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a,admin-b"},
        headers={"canvas-logged-in-user-id": "some-other-user"},
    )

    result = tested._is_admin_user()

    assert result is False


def test_is_admin_user_allows_when_user_in_admin_list() -> None:
    """A user whose id appears in ADMIN_STAFF_IDS is granted admin access."""
    tested = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a,admin-b"},
        headers={"canvas-logged-in-user-id": "admin-a"},
    )

    result = tested._is_admin_user()

    assert result is True


def test_is_admin_user_handles_whitespace_in_secret() -> None:
    """Whitespace around admin ids in the secret is stripped before matching."""
    tested = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "  admin-a  ,  admin-b  "},
        headers={"canvas-logged-in-user-id": "admin-a"},
    )

    result = tested._is_admin_user()

    assert result is True


def test_is_admin_user_rejects_when_no_user_id_and_secret_set() -> None:
    """Missing canvas-logged-in-user-id header denies access even with valid secret."""
    tested = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a"},
        headers={},
    )

    result = tested._is_admin_user()

    assert result is False


# ─────────────────────────────────────────────────────────────
# _is_same_origin — CSRF check
# ─────────────────────────────────────────────────────────────

def test_is_same_origin_allows_when_origin_matches() -> None:
    """Origin host equal to Host header passes the CSRF check."""
    tested = _make_handler(headers={"Host": "foo.example.com", "Origin": "https://foo.example.com"})

    result = tested._is_same_origin()

    assert result is True


def test_is_same_origin_rejects_when_origin_differs() -> None:
    """Origin host different from Host header fails the CSRF check."""
    tested = _make_handler(headers={"Host": "foo.example.com", "Origin": "https://evil.com"})

    result = tested._is_same_origin()

    assert result is False


def test_is_same_origin_falls_back_to_referer() -> None:
    """Absent Origin, Referer host is used to validate the request."""
    tested = _make_handler(headers={"Host": "foo.example.com", "Referer": "https://foo.example.com/app"})

    result = tested._is_same_origin()

    assert result is True


def test_is_same_origin_rejects_when_no_origin_or_referer() -> None:
    """Without Origin or Referer headers, the CSRF check fails closed."""
    tested = _make_handler(headers={"Host": "foo.example.com"})

    result = tested._is_same_origin()

    assert result is False


def test_is_same_origin_rejects_substring_attack_via_origin() -> None:
    """Host-suffix tricks (e.g. foo.example.com.attacker.com) do not bypass Origin check."""
    tested = _make_handler(headers={
        "Host": "foo.example.com",
        "Origin": "https://foo.example.com.attacker.com",
    })

    result = tested._is_same_origin()

    assert result is False


def test_is_same_origin_rejects_substring_attack_via_referer() -> None:
    """Host-suffix tricks (e.g. foo.example.com.attacker.com) do not bypass Referer check."""
    tested = _make_handler(headers={
        "Host": "foo.example.com",
        "Referer": "https://foo.example.com.attacker.com/path",
    })

    result = tested._is_same_origin()

    assert result is False


def test_is_same_origin_rejects_when_host_header_missing() -> None:
    """Missing Host header denies access even if Origin is present."""
    tested = _make_handler(headers={"Origin": "https://foo.example.com"})

    result = tested._is_same_origin()

    assert result is False


# ─────────────────────────────────────────────────────────────
# _forbidden
# ─────────────────────────────────────────────────────────────

def test_forbidden_returns_403_html_response() -> None:
    """_forbidden returns a single HTMLResponse with status 403."""
    tested = _make_handler()

    result = tested._forbidden()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.FORBIDDEN


# ─────────────────────────────────────────────────────────────
# get_admin_ui
# ─────────────────────────────────────────────────────────────

def test_get_admin_ui_returns_forbidden_when_not_admin() -> None:
    """Non-admin callers receive a 403 from get_admin_ui."""
    tested = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a"},
        headers={"canvas-logged-in-user-id": "other-user"},
    )

    result = tested.get_admin_ui()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.FORBIDDEN


def test_get_admin_ui_returns_html_when_authorized() -> None:
    """Admin callers receive the rendered admin HTML with HTTP 200."""
    tested = _make_handler(admin=True)
    exp_providers_calls = [call()]
    exp_staff_calls = [call()]
    exp_delegations_calls = [call()]
    exp_name_calls = [call("p1"), call("s1")]

    with (
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[{"id": "p1", "name": "Provider 1"}]) as mock_providers,
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[{"id": "s1", "name": "Staff 1"}]) as mock_staff,
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={"p1": ["s1"]}) as mock_delegations,
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="Name") as mock_name,
    ):
        result = tested.get_admin_ui()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.OK
    assert mock_providers.mock_calls == exp_providers_calls
    assert mock_staff.mock_calls == exp_staff_calls
    assert mock_delegations.mock_calls == exp_delegations_calls
    assert mock_name.mock_calls == exp_name_calls


def test_get_admin_ui_filters_delegations_to_active_providers() -> None:
    """Delegations for providers not in the active list are filtered out of the HTML."""
    tested = _make_handler(admin=True)
    exp_providers_calls = [call()]
    exp_staff_calls = [call()]
    exp_delegations_calls = [call()]
    exp_name_calls = [call("p1"), call("s1")]

    with (
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[{"id": "p1", "name": "P1"}]) as mock_providers,
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]) as mock_staff,
        # p2 in delegations but not in active providers — should be filtered out
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={"p1": ["s1"], "p2": ["s2"]}) as mock_delegations,
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="Name") as mock_name,
    ):
        result = tested.get_admin_ui()

    html = result[0].content.decode("utf-8") if isinstance(result[0].content, bytes) else result[0].content
    assert "p1" in html
    # p2 should be absent because it's not an active provider
    assert '"p2"' not in html
    assert mock_providers.mock_calls == exp_providers_calls
    assert mock_staff.mock_calls == exp_staff_calls
    assert mock_delegations.mock_calls == exp_delegations_calls
    assert mock_name.mock_calls == exp_name_calls


# ─────────────────────────────────────────────────────────────
# handle_form_action
# ─────────────────────────────────────────────────────────────

def test_handle_form_action_forbidden_when_not_admin() -> None:
    """Non-admin callers receive a 403 from handle_form_action."""
    tested = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a"},
        headers={"canvas-logged-in-user-id": "other"},
    )

    result = tested.handle_form_action()

    assert result[0].status_code == HTTPStatus.FORBIDDEN


def test_handle_form_action_forbidden_when_not_same_origin() -> None:
    """Admin callers from a mismatched origin receive a 403 (CSRF defense)."""
    tested = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://evil.com"},
    )

    result = tested.handle_form_action()

    assert result[0].status_code == HTTPStatus.FORBIDDEN


def test_handle_form_action_save_calls_set_delegation() -> None:
    """A save action with valid ids invokes set_delegation with the parsed payload."""
    tested = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body='_action=save&_data=%7B%22provider_id%22%3A%22p1%22%2C%22staff_ids%22%3A%5B%22s1%22%5D%7D',
    )
    exp_set_calls = [call("p1", ["s1"])]
    exp_valid_calls = [call("p1"), call("s1")]
    exp_providers_calls = []
    exp_staff_calls = []
    exp_delegations_calls = []
    exp_name_calls = []

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=True) as mock_valid,
        patch("dea_prescriber_filter.api.delegation_api.set_delegation") as mock_set,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]) as mock_providers,
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]) as mock_staff,
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}) as mock_delegations,
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="") as mock_name,
    ):
        tested.handle_form_action()

    assert mock_set.mock_calls == exp_set_calls
    assert mock_valid.mock_calls == exp_valid_calls
    assert mock_providers.mock_calls == exp_providers_calls
    assert mock_staff.mock_calls == exp_staff_calls
    assert mock_delegations.mock_calls == exp_delegations_calls
    assert mock_name.mock_calls == exp_name_calls


def test_handle_form_action_remove_calls_remove_delegation() -> None:
    """A remove action with a valid provider id invokes remove_delegation."""
    tested = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body='_action=remove&_data=%7B%22provider_id%22%3A%22p1%22%7D',
    )
    exp_remove_calls = [call("p1")]
    exp_valid_calls = [call("p1")]
    exp_providers_calls = []
    exp_staff_calls = []
    exp_delegations_calls = []
    exp_name_calls = []

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=True) as mock_valid,
        patch("dea_prescriber_filter.api.delegation_api.remove_delegation") as mock_remove,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]) as mock_providers,
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]) as mock_staff,
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}) as mock_delegations,
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="") as mock_name,
    ):
        tested.handle_form_action()

    assert mock_remove.mock_calls == exp_remove_calls
    assert mock_valid.mock_calls == exp_valid_calls
    assert mock_providers.mock_calls == exp_providers_calls
    assert mock_staff.mock_calls == exp_staff_calls
    assert mock_delegations.mock_calls == exp_delegations_calls
    assert mock_name.mock_calls == exp_name_calls


def test_handle_form_action_skips_invalid_provider_id() -> None:
    """An invalid provider id short-circuits before set_delegation is called."""
    tested = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body='_action=save&_data=%7B%22provider_id%22%3A%22bogus%22%2C%22staff_ids%22%3A%5B%22s1%22%5D%7D',
    )
    exp_set_calls = []
    exp_valid_calls = [call("bogus")]
    exp_providers_calls = []
    exp_staff_calls = []
    exp_delegations_calls = []
    exp_name_calls = []

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=False) as mock_valid,
        patch("dea_prescriber_filter.api.delegation_api.set_delegation") as mock_set,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]) as mock_providers,
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]) as mock_staff,
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}) as mock_delegations,
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="") as mock_name,
    ):
        tested.handle_form_action()

    assert mock_set.mock_calls == exp_set_calls
    assert mock_valid.mock_calls == exp_valid_calls
    assert mock_providers.mock_calls == exp_providers_calls
    assert mock_staff.mock_calls == exp_staff_calls
    assert mock_delegations.mock_calls == exp_delegations_calls
    assert mock_name.mock_calls == exp_name_calls


def test_handle_form_action_handles_bytes_body() -> None:
    """A bytes request body is decoded and parsed before save is invoked."""
    tested = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body=b'_action=save&_data=%7B%22provider_id%22%3A%22p1%22%2C%22staff_ids%22%3A%5B%5D%7D',
    )
    exp_set_calls = [call("p1", [])]
    exp_valid_calls = [call("p1")]
    exp_providers_calls = []
    exp_staff_calls = []
    exp_delegations_calls = []
    exp_name_calls = []

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=True) as mock_valid,
        patch("dea_prescriber_filter.api.delegation_api.set_delegation") as mock_set,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]) as mock_providers,
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]) as mock_staff,
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}) as mock_delegations,
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="") as mock_name,
    ):
        tested.handle_form_action()

    assert mock_set.mock_calls == exp_set_calls
    assert mock_valid.mock_calls == exp_valid_calls
    assert mock_providers.mock_calls == exp_providers_calls
    assert mock_staff.mock_calls == exp_staff_calls
    assert mock_delegations.mock_calls == exp_delegations_calls
    assert mock_name.mock_calls == exp_name_calls


def test_handle_form_action_redirects_when_json_decode_fails() -> None:
    """Malformed JSON in _data is caught and the handler issues a 303 redirect."""
    tested = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body="_action=save&_data=not-json",  # _data is not valid JSON
    )
    expected_location = "/plugin-io/api/dea_prescriber_filter/app/delegation-admin"

    result = tested.handle_form_action()

    # Malformed _data → JSONDecodeError is caught, request is a no-op redirect.
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.SEE_OTHER
    assert result[0].headers["Location"] == expected_location


def test_handle_form_action_redirects_when_bytes_body_is_invalid_utf8() -> None:
    """Non-utf8 bytes in the request body are tolerated; the handler redirects."""
    tested = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body=b"\xff\xfe\xfd",  # not valid UTF-8
    )
    expected_location = "/plugin-io/api/dea_prescriber_filter/app/delegation-admin"

    result = tested.handle_form_action()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.SEE_OTHER
    assert result[0].headers["Location"] == expected_location


# ─────────────────────────────────────────────────────────────
# _valid_staff_id
# ─────────────────────────────────────────────────────────────

def test_valid_staff_id_returns_false_for_empty_string() -> None:
    """An empty string is rejected without touching the database."""
    from dea_prescriber_filter.api.delegation_api import _valid_staff_id

    result = _valid_staff_id("")

    assert result is False


def test_valid_staff_id_returns_false_for_non_string() -> None:
    """Non-string staff ids (None, int) are rejected before any DB lookup."""
    from dea_prescriber_filter.api.delegation_api import _valid_staff_id

    result_none = _valid_staff_id(None)  # type: ignore[arg-type]
    result_int = _valid_staff_id(123)  # type: ignore[arg-type]

    assert result_none is False
    assert result_int is False


def test_valid_staff_id_returns_true_when_staff_exists() -> None:
    """When the Staff record exists, the validator returns True."""
    exp_staff_calls = [
        call.objects.filter(id="staff-a"),
        call.objects.filter().exists(),
    ]
    with patch("dea_prescriber_filter.api.delegation_api.Staff") as mock_staff:
        mock_staff.objects.filter.return_value.exists.return_value = True

        from dea_prescriber_filter.api.delegation_api import _valid_staff_id

        result = _valid_staff_id("staff-a")

    assert result is True
    assert mock_staff.mock_calls == exp_staff_calls


def test_valid_staff_id_returns_false_when_staff_missing() -> None:
    """When no Staff record matches, the validator returns False."""
    exp_staff_calls = [
        call.objects.filter(id="missing"),
        call.objects.filter().exists(),
    ]
    with patch("dea_prescriber_filter.api.delegation_api.Staff") as mock_staff:
        mock_staff.objects.filter.return_value.exists.return_value = False

        from dea_prescriber_filter.api.delegation_api import _valid_staff_id

        result = _valid_staff_id("missing")

    assert result is False
    assert mock_staff.mock_calls == exp_staff_calls


# ─────────────────────────────────────────────────────────────
# _extract_url_host
# ─────────────────────────────────────────────────────────────

def test_extract_url_host_returns_empty_for_url_without_scheme() -> None:
    """A URL missing :// returns "" so a bare value never matches a real Host header."""
    from dea_prescriber_filter.api.delegation_api import _extract_url_host

    result = _extract_url_host("foo.example.com/path")

    assert result == ""


def test_extract_url_host_returns_empty_for_empty_string() -> None:
    """An empty url returns "" rather than raising."""
    from dea_prescriber_filter.api.delegation_api import _extract_url_host

    result = _extract_url_host("")

    assert result == ""


def test_extract_url_host_lowercases_host_component() -> None:
    """The host[:port] component is extracted from a full URL and lowercased."""
    from dea_prescriber_filter.api.delegation_api import _extract_url_host

    result = _extract_url_host("https://Foo.Example.com:8080/some/path")

    assert result == "foo.example.com:8080"
