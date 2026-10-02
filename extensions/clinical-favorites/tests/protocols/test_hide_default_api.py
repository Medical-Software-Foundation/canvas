"""Tests for HideDefaultAPI."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from clinical_favorites.protocols.hide_default_api import HideDefaultAPI, _parse_body


def _api(
    method: str,
    body: dict | None = None,
    query: dict | None = None,
    staff_id: str | None = "staff-uuid-1",
) -> HideDefaultAPI:
    api = HideDefaultAPI(MagicMock())
    api.request = MagicMock()
    api.request.method = method
    api.request.query_params = query or {}
    api.request.headers = {"canvas-logged-in-user-id": staff_id} if staff_id else {}
    if body is not None:
        api.request.body = json.dumps(body).encode("utf-8")
        api.request.json.return_value = body
    return api


@patch("clinical_favorites.protocols.hide_default_api.FavoritesService")
def test_post_hides_default(mock_service_cls: MagicMock) -> None:
    mock_service_cls.return_value.hide_default.return_value = True
    body = json.loads(
        _api(
            "POST",
            body={"default_id": "wegovy_0.25mg", "favorite_type": "medication"},
        )
        .post()[0]
        .content
    )
    assert body["success"] is True


@patch("clinical_favorites.protocols.hide_default_api.FavoritesService")
def test_delete_unhides_default(mock_service_cls: MagicMock) -> None:
    mock_service_cls.return_value.unhide_default.return_value = True
    body = json.loads(
        _api("DELETE", query={"default_id": "wegovy_0.25mg"}).delete()[0].content
    )
    assert body["success"] is True


def test_post_rejects_missing_staff_header() -> None:
    response = _api(
        "POST",
        body={"default_id": "wegovy_0.25mg", "favorite_type": "medication"},
        staff_id=None,
    ).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Staff ID not found"


def test_delete_rejects_missing_staff_header() -> None:
    response = _api(
        "DELETE", query={"default_id": "wegovy_0.25mg"}, staff_id=None
    ).delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Staff ID not found"


def test_post_rejects_missing_default_id() -> None:
    response = _api("POST", body={"favorite_type": "medication"}).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "default_id is required"


def test_delete_rejects_missing_default_id_in_query() -> None:
    response = _api("DELETE", query={}).delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "default_id is required"


def test_post_malformed_json_returns_400() -> None:
    api = HideDefaultAPI(MagicMock())
    api.request = MagicMock()
    api.request.method = "POST"
    api.request.query_params = {}
    api.request.headers = {"canvas-logged-in-user-id": "staff-uuid-1"}
    api.request.body = b"{not json"
    api.request.json.side_effect = ValueError("not json")

    response = api.post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Invalid JSON" in body["error"]


@patch("clinical_favorites.protocols.hide_default_api.FavoritesService")
def test_post_returns_400_when_service_returns_error_string(
    mock_service_cls: MagicMock,
) -> None:
    mock_service_cls.return_value.hide_default.return_value = "Staff record not found"
    response = _api(
        "POST",
        body={"default_id": "wegovy_0.25mg", "favorite_type": "medication"},
    ).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Staff record not found"


@patch("clinical_favorites.protocols.hide_default_api.FavoritesService")
def test_delete_returns_404_when_default_was_not_hidden(
    mock_service_cls: MagicMock,
) -> None:
    mock_service_cls.return_value.unhide_default.return_value = False
    response = _api("DELETE", query={"default_id": "wegovy_0.25mg"}).delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert body["error"] == "Default was not hidden"


def test_parse_body_falls_back_to_raw_decode_when_request_json_fails() -> None:
    request = MagicMock()
    request.json.side_effect = ValueError("nope")
    request.body = b'{"default_id": "wegovy_0.25mg"}'
    assert _parse_body(request) == {"default_id": "wegovy_0.25mg"}
