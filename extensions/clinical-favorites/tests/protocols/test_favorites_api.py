"""Tests for FavoritesAPI CRUD endpoint."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from clinical_favorites.protocols.favorites_api import FavoritesAPI, _parse_body


def _make_api(
    method: str = "GET",
    body: dict | None = None,
    query: dict | None = None,
    staff_id: str | None = "staff-uuid-1",
) -> FavoritesAPI:
    api = FavoritesAPI(MagicMock())
    api.request = MagicMock()
    api.request.method = method
    api.request.query_params = query or {}
    api.request.headers = {"canvas-logged-in-user-id": staff_id} if staff_id else {}
    if body is not None:
        api.request.body = json.dumps(body).encode("utf-8")
        api.request.json.return_value = body
    return api


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_get_returns_favorites(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_all_favorites.return_value = [{"id": "custom_abc", "favorite_type": "condition"}]

    api = _make_api(query={"filter": "mine", "type": "condition"})
    body = json.loads(api.get()[0].content)

    assert body["count"] == 1
    mock_service.get_all_favorites.assert_called_once_with(
        staff_id="staff-uuid-1",
        visibility_filter="mine",
        favorite_type="condition",
        include_hidden=False,
    )


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_post_creates_condition_favorite(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.save_favorite.return_value = {"id": "custom_abc", "favorite_type": "condition"}

    api = _make_api(
        method="POST",
        body={"favorite_type": "condition", "code": "E11.9", "display_name": "T2DM"},
    )
    body = json.loads(api.post()[0].content)

    assert body["success"] is True
    mock_service.save_favorite.assert_called_once()


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_put_enforces_ownership(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "other-staff",
        "created_by_name": "Steven Magee",
    }

    api = _make_api(method="PUT", body={"id": "custom_abc", "display_name": "new"})
    response = api.put()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert body["success"] is False
    assert body["error"] == "Created by Steven Magee, only the creator can edit"
    mock_service.update_favorite.assert_not_called()


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_put_ownership_message_falls_back_when_creator_name_missing(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "other-staff",
    }

    api = _make_api(method="PUT", body={"id": "custom_abc", "display_name": "new"})
    body = json.loads(api.put()[0].content)

    assert body["error"] == "Created by another staff member, only the creator can edit"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_put_returns_400_when_update_raises_value_error(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "staff-uuid-1",
    }
    mock_service.update_favorite.side_effect = ValueError("days_supply must be an integer")

    api = _make_api(method="PUT", body={"id": "custom_abc", "display_name": "new"})
    response = api.put()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body == {"success": False, "error": "days_supply must be an integer"}


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_post_handles_explicit_null_refills_without_500(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.save_favorite.return_value = {"id": "custom_x"}

    api = _make_api(
        method="POST",
        body={
            "favorite_type": "medication",
            "display_name": "Wegovy",
            "fdb_code": "1234",
            "sig": "weekly",
            "days_supply": 30,
            "quantity_to_dispense": "1",
            "unit": "pen",
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "refills": None,
        },
    )
    response = api.post()[0]
    assert response.status_code != HTTPStatus.INTERNAL_SERVER_ERROR


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_put_handles_explicit_null_refills_without_500(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_x",
        "created_by_id": "staff-uuid-1",
    }
    mock_service.update_favorite.return_value = {"id": "custom_x", "refills": 0}

    api = _make_api(
        method="PUT",
        body={"id": "custom_x", "refills": None},
    )
    response = api.put()[0]
    assert response.status_code != HTTPStatus.INTERNAL_SERVER_ERROR


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_put_race_path_returns_404_when_update_returns_none(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "staff-uuid-1",
    }
    mock_service.update_favorite.return_value = None

    api = _make_api(method="PUT", body={"id": "custom_abc", "display_name": "new"})
    response = api.put()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert body["error"] == "Favorite not found after update"


def test_get_rejects_missing_staff_header() -> None:
    api = _make_api(staff_id=None)
    response = api.get()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body == {"success": False, "error": "Staff ID not found"}


def test_post_rejects_missing_staff_header() -> None:
    api = _make_api(method="POST", body={"favorite_type": "condition"}, staff_id=None)
    response = api.post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Staff ID not found"


def test_put_rejects_missing_staff_header() -> None:
    api = _make_api(method="PUT", body={"id": "custom_abc"}, staff_id=None)
    response = api.put()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Staff ID not found"


def test_delete_rejects_missing_staff_header() -> None:
    api = _make_api(method="DELETE", query={"id": "custom_abc"}, staff_id=None)
    response = api.delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Staff ID not found"


def test_post_rejects_invalid_favorite_type() -> None:
    api = _make_api(method="POST", body={"favorite_type": "procedure"})
    response = api.post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "favorite_type" in body["error"]


def test_post_malformed_json_returns_400() -> None:
    api = FavoritesAPI(MagicMock())
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


def test_put_malformed_json_returns_400() -> None:
    api = FavoritesAPI(MagicMock())
    api.request = MagicMock()
    api.request.method = "PUT"
    api.request.query_params = {}
    api.request.headers = {"canvas-logged-in-user-id": "staff-uuid-1"}
    api.request.body = b"{not json"
    api.request.json.side_effect = ValueError("not json")

    response = api.put()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Invalid JSON" in body["error"]


def test_put_rejects_missing_id_in_body() -> None:
    api = _make_api(method="PUT", body={"display_name": "no id"})
    response = api.put()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "id is required"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_put_returns_404_when_existing_not_found(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = None

    api = _make_api(method="PUT", body={"id": "missing", "display_name": "new"})
    response = api.put()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert body["error"] == "Favorite not found"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_put_success_returns_updated_favorite(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "staff-uuid-1",
    }
    mock_service.update_favorite.return_value = {
        "id": "custom_abc",
        "display_name": "Wegovy 0.5",
    }

    api = _make_api(method="PUT", body={"id": "custom_abc", "display_name": "Wegovy 0.5"})
    body = json.loads(api.put()[0].content)
    assert body["success"] is True
    assert body["favorite"]["display_name"] == "Wegovy 0.5"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_post_returns_400_when_save_raises_value_error(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.save_favorite.side_effect = ValueError("Missing required fields")

    api = _make_api(
        method="POST",
        body={"favorite_type": "medication", "display_name": "Wegovy"},
    )
    response = api.post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Missing required fields"


def test_delete_rejects_missing_id_in_query() -> None:
    api = _make_api(method="DELETE", query={})
    response = api.delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "id is required"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_delete_returns_404_when_existing_not_found(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = None

    api = _make_api(method="DELETE", query={"id": "missing"})
    response = api.delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert body["error"] == "Favorite not found"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_delete_returns_403_when_caller_does_not_own_favorite(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "other-staff",
        "created_by_name": "Steven Magee",
    }

    api = _make_api(method="DELETE", query={"id": "custom_abc"})
    response = api.delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert body["error"] == "Created by Steven Magee, only the creator can delete"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_delete_ownership_message_falls_back_when_creator_name_missing(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "other-staff",
    }

    api = _make_api(method="DELETE", query={"id": "custom_abc"})
    body = json.loads(api.delete()[0].content)
    assert body["error"] == "Created by another staff member, only the creator can delete"


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_delete_success_returns_success_true(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "staff-uuid-1",
    }
    mock_service.delete_favorite.return_value = True

    api = _make_api(method="DELETE", query={"id": "custom_abc"})
    body = json.loads(api.delete()[0].content)
    assert body == {"success": True}


@patch("clinical_favorites.protocols.favorites_api.FavoritesService")
def test_delete_returns_500_when_service_delete_fails(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorite_by_id.return_value = {
        "id": "custom_abc",
        "created_by_id": "staff-uuid-1",
    }
    mock_service.delete_favorite.return_value = False

    api = _make_api(method="DELETE", query={"id": "custom_abc"})
    response = api.delete()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert body["error"] == "Delete failed"


def test_parse_body_falls_back_to_raw_decode_when_request_json_fails() -> None:
    request = MagicMock()
    request.json.side_effect = ValueError("nope")
    request.body = b'{"display_name": "Wegovy"}'
    assert _parse_body(request) == {"display_name": "Wegovy"}


def test_parse_body_returns_empty_dict_when_body_empty() -> None:
    request = MagicMock()
    request.json.side_effect = ValueError("nope")
    request.body = b""
    assert _parse_body(request) == {}
