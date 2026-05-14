"""Tests for api/delegation_api.py — admin UI and delegation CRUD."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import MagicMock, call, patch


# ─────────────────────────────────────────────────────────────
# _is_admin_user — auth check
# ─────────────────────────────────────────────────────────────

def _make_handler(
    secrets: dict | None = None,
    headers: dict | None = None,
    body: str = "",
    admin: bool = False,
) -> MagicMock:
    from dea_prescriber_filter.api.delegation_api import DelegationUIApi

    handler = DelegationUIApi.__new__(DelegationUIApi)
    if admin:
        secrets = {**(secrets or {}), "ADMIN_STAFF_IDS": "admin-test"}
        headers = {**(headers or {}), "canvas-logged-in-user-id": "admin-test"}
    handler.secrets = secrets or {}
    handler.request = MagicMock()
    handler.request.headers = headers or {}
    handler.request.body = body
    return handler


def test_is_admin_user_denies_when_secret_empty() -> None:
    handler = _make_handler(secrets={"ADMIN_STAFF_IDS": ""})

    assert handler._is_admin_user() is False


def test_is_admin_user_denies_when_secret_missing() -> None:
    handler = _make_handler(secrets={})

    assert handler._is_admin_user() is False


def test_is_admin_user_restricts_when_secret_set_and_user_not_listed() -> None:
    handler = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a,admin-b"},
        headers={"canvas-logged-in-user-id": "some-other-user"},
    )

    assert handler._is_admin_user() is False


def test_is_admin_user_allows_when_user_in_admin_list() -> None:
    handler = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a,admin-b"},
        headers={"canvas-logged-in-user-id": "admin-a"},
    )

    assert handler._is_admin_user() is True


def test_is_admin_user_handles_whitespace_in_secret() -> None:
    handler = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "  admin-a  ,  admin-b  "},
        headers={"canvas-logged-in-user-id": "admin-a"},
    )

    assert handler._is_admin_user() is True


def test_is_admin_user_rejects_when_no_user_id_and_secret_set() -> None:
    handler = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a"},
        headers={},
    )

    assert handler._is_admin_user() is False


def test_is_admin_user_handles_exception() -> None:
    from dea_prescriber_filter.api.delegation_api import DelegationUIApi

    handler = DelegationUIApi.__new__(DelegationUIApi)
    # secrets attribute missing entirely → raises AttributeError
    handler.request = MagicMock()

    assert handler._is_admin_user() is False


# ─────────────────────────────────────────────────────────────
# _is_same_origin — CSRF check
# ─────────────────────────────────────────────────────────────

def test_is_same_origin_allows_when_origin_matches() -> None:
    handler = _make_handler(headers={"Host": "foo.example.com", "Origin": "https://foo.example.com"})

    assert handler._is_same_origin() is True


def test_is_same_origin_rejects_when_origin_differs() -> None:
    handler = _make_handler(headers={"Host": "foo.example.com", "Origin": "https://evil.com"})

    assert handler._is_same_origin() is False


def test_is_same_origin_falls_back_to_referer() -> None:
    handler = _make_handler(headers={"Host": "foo.example.com", "Referer": "https://foo.example.com/app"})

    assert handler._is_same_origin() is True


def test_is_same_origin_rejects_when_no_origin_or_referer() -> None:
    handler = _make_handler(headers={"Host": "foo.example.com"})

    assert handler._is_same_origin() is False


def test_is_same_origin_rejects_substring_attack_via_origin() -> None:
    handler = _make_handler(headers={
        "Host": "foo.example.com",
        "Origin": "https://foo.example.com.attacker.com",
    })

    assert handler._is_same_origin() is False


def test_is_same_origin_rejects_substring_attack_via_referer() -> None:
    handler = _make_handler(headers={
        "Host": "foo.example.com",
        "Referer": "https://foo.example.com.attacker.com/path",
    })

    assert handler._is_same_origin() is False


def test_is_same_origin_handles_exception() -> None:
    from dea_prescriber_filter.api.delegation_api import DelegationUIApi

    handler = DelegationUIApi.__new__(DelegationUIApi)
    # No request attribute → raises AttributeError → caught
    assert handler._is_same_origin() is False


# ─────────────────────────────────────────────────────────────
# _valid_staff_id
# ─────────────────────────────────────────────────────────────

class _StaffDoesNotExist(Exception):
    pass


def test_valid_staff_id_returns_false_for_empty_string() -> None:
    from dea_prescriber_filter.api.delegation_api import _valid_staff_id

    assert _valid_staff_id("") is False


def test_valid_staff_id_returns_false_for_non_string() -> None:
    from dea_prescriber_filter.api.delegation_api import _valid_staff_id

    assert _valid_staff_id(None) is False  # type: ignore[arg-type]
    assert _valid_staff_id(123) is False  # type: ignore[arg-type]


def test_valid_staff_id_returns_true_when_staff_exists() -> None:
    with patch("dea_prescriber_filter.api.delegation_api.Staff") as mock_staff:
        mock_staff.objects.filter.return_value.exists.return_value = True

        from dea_prescriber_filter.api.delegation_api import _valid_staff_id

        assert _valid_staff_id("staff-a") is True
        assert mock_staff.objects.mock_calls == [
            call.filter(id="staff-a"),
            call.filter().exists(),
        ]


def test_valid_staff_id_returns_false_when_staff_missing() -> None:
    with patch("dea_prescriber_filter.api.delegation_api.Staff") as mock_staff:
        mock_staff.objects.filter.return_value.exists.return_value = False

        from dea_prescriber_filter.api.delegation_api import _valid_staff_id

        assert _valid_staff_id("missing") is False


def test_valid_staff_id_handles_exception() -> None:
    with patch("dea_prescriber_filter.api.delegation_api.Staff") as mock_staff:
        mock_staff.objects.filter.side_effect = RuntimeError("db down")

        from dea_prescriber_filter.api.delegation_api import _valid_staff_id

        assert _valid_staff_id("staff-a") is False


# ─────────────────────────────────────────────────────────────
# get_admin_ui
# ─────────────────────────────────────────────────────────────

def test_get_admin_ui_returns_forbidden_when_not_admin() -> None:
    handler = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a"},
        headers={"canvas-logged-in-user-id": "other-user"},
    )

    result = handler.get_admin_ui()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.FORBIDDEN


def test_get_admin_ui_returns_html_when_authorized() -> None:
    handler = _make_handler(admin=True)

    with (
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[{"id": "p1", "name": "Provider 1"}]),
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[{"id": "s1", "name": "Staff 1"}]),
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={"p1": ["s1"]}),
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="Name"),
    ):
        result = handler.get_admin_ui()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.OK


def test_get_admin_ui_filters_delegations_to_active_providers() -> None:
    handler = _make_handler(admin=True)

    with (
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[{"id": "p1", "name": "P1"}]),
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]),
        # p2 in delegations but not in active providers — should be filtered out
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={"p1": ["s1"], "p2": ["s2"]}),
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="Name"),
    ):
        result = handler.get_admin_ui()

    html = result[0].content.decode("utf-8") if isinstance(result[0].content, bytes) else result[0].content
    assert "p1" in html
    # p2 should be absent because it's not an active provider
    assert '"p2"' not in html


def test_get_admin_ui_handles_data_load_exception() -> None:
    handler = _make_handler(admin=True)

    with (
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", side_effect=RuntimeError("boom")),
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}),
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value="Name"),
    ):
        result = handler.get_admin_ui()

    # Should still return HTML OK, just with empty data
    assert result[0].status_code == HTTPStatus.OK


# ─────────────────────────────────────────────────────────────
# handle_form_action
# ─────────────────────────────────────────────────────────────

def test_handle_form_action_forbidden_when_not_admin() -> None:
    handler = _make_handler(
        secrets={"ADMIN_STAFF_IDS": "admin-a"},
        headers={"canvas-logged-in-user-id": "other"},
    )

    result = handler.handle_form_action()

    assert result[0].status_code == HTTPStatus.FORBIDDEN


def test_handle_form_action_forbidden_when_not_same_origin() -> None:
    handler = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://evil.com"},
    )

    result = handler.handle_form_action()

    assert result[0].status_code == HTTPStatus.FORBIDDEN


def test_handle_form_action_save_calls_set_delegation() -> None:
    handler = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body='_action=save&_data=%7B%22provider_id%22%3A%22p1%22%2C%22staff_ids%22%3A%5B%22s1%22%5D%7D',
    )

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=True),
        patch("dea_prescriber_filter.api.delegation_api.set_delegation") as mock_set,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}),
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value=""),
    ):
        handler.handle_form_action()

    assert mock_set.mock_calls == [call("p1", ["s1"])]


def test_handle_form_action_remove_calls_remove_delegation() -> None:
    handler = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body='_action=remove&_data=%7B%22provider_id%22%3A%22p1%22%7D',
    )

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=True),
        patch("dea_prescriber_filter.api.delegation_api.remove_delegation") as mock_remove,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}),
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value=""),
    ):
        handler.handle_form_action()

    assert mock_remove.mock_calls == [call("p1")]


def test_handle_form_action_skips_invalid_provider_id() -> None:
    handler = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body='_action=save&_data=%7B%22provider_id%22%3A%22bogus%22%2C%22staff_ids%22%3A%5B%22s1%22%5D%7D',
    )

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=False),
        patch("dea_prescriber_filter.api.delegation_api.set_delegation") as mock_set,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}),
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value=""),
    ):
        handler.handle_form_action()

    assert mock_set.mock_calls == []


def test_handle_form_action_handles_bytes_body() -> None:
    handler = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
    )
    handler.request.body = b'_action=save&_data=%7B%22provider_id%22%3A%22p1%22%2C%22staff_ids%22%3A%5B%5D%7D'

    with (
        patch("dea_prescriber_filter.api.delegation_api._valid_staff_id", return_value=True),
        patch("dea_prescriber_filter.api.delegation_api.set_delegation") as mock_set,
        patch("dea_prescriber_filter.api.delegation_api.get_active_providers", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_active_staff", return_value=[]),
        patch("dea_prescriber_filter.api.delegation_api.get_all_delegations", return_value={}),
        patch("dea_prescriber_filter.api.delegation_api.get_staff_name", return_value=""),
    ):
        handler.handle_form_action()

    assert mock_set.mock_calls == [call("p1", [])]


def test_handle_form_action_handles_exception() -> None:
    handler = _make_handler(
        admin=True,
        headers={"Host": "foo.com", "Origin": "https://foo.com"},
        body="garbage-body",  # will fail JSON decode
    )

    result = handler.handle_form_action()

    # Should still redirect back to admin UI (303) even when body parsing fails.
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.SEE_OTHER
    assert result[0].headers["Location"] == "/plugin-io/api/dea_prescriber_filter/app/delegation-admin"
