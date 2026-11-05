"""Tests for BulkImportAPI."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from clinical_favorites.protocols.bulk_import_api import (
    DEFAULT_MAX_IMPORT_ROWS,
    BulkImportAPI,
)
from clinical_favorites.services import FavoritesService


def _make_api(body: dict | None = None, staff_id: str = "staff-uuid-1") -> BulkImportAPI:
    api = BulkImportAPI(MagicMock())
    api.request = MagicMock()
    api.request.method = "POST"
    api.request.query_params = {}
    api.request.headers = {"canvas-logged-in-user-id": staff_id} if staff_id else {}
    if body is not None:
        api.request.body = json.dumps(body).encode("utf-8")
        api.request.json.return_value = body
    return api


@patch("clinical_favorites.protocols.bulk_import_api.FavoritesService")
def test_post_imports_all_valid_favorites(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.validate_favorite_payload.return_value = None
    mock_service.save_favorite.return_value = {"id": "custom_abc"}

    api = _make_api(body={
        "favorites": [
            {
                "favorite_type": "medication",
                "display_name": "Test Med",
                "fdb_code": "1234",
                "sig": "take once",
                "days_supply": 30,
                "quantity_to_dispense": "30",
                "unit": "tablet",
                "representative_ndc": "ndc",
                "ncpdp_quantity_qualifier_code": "00",
            },
            {
                "favorite_type": "condition",
                "display_name": "Test Condition",
                "code": "Z00.0",
            },
        ],
    })
    body = json.loads(api.post()[0].content)

    assert body["success"] is True
    assert body["imported"] == 2
    assert body["skipped"] == []
    assert mock_service.save_favorite.call_count == 2


@patch("clinical_favorites.protocols.bulk_import_api.FavoritesService")
def test_post_mixed_valid_and_invalid_favorites(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    validation_results = [None, "Missing required fields, sig"]
    mock_service.validate_favorite_payload.side_effect = (
        lambda *a, **kw: validation_results.pop(0)
    )
    mock_service.save_favorite.return_value = {"id": "custom_abc"}

    api = _make_api(body={
        "favorites": [
            {
                "favorite_type": "medication",
                "display_name": "Valid",
                "fdb_code": "1234",
                "sig": "take once",
                "days_supply": 30,
                "quantity_to_dispense": "30",
                "unit": "tablet",
                "representative_ndc": "ndc",
                "ncpdp_quantity_qualifier_code": "00",
            },
            {
                "favorite_type": "medication",
                "display_name": "Invalid",
            },
        ],
    })
    body = json.loads(api.post()[0].content)

    assert body["success"] is True
    assert body["imported"] == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["index"] == 1
    assert body["skipped"][0]["display_name"] == "Invalid"
    assert "Missing required fields" in body["skipped"][0]["reason"]


def test_post_rejects_unknown_favorite_type() -> None:
    api = _make_api(body={
        "favorites": [
            {"favorite_type": "procedure", "display_name": "Not a type"},
        ],
    })
    body = json.loads(api.post()[0].content)

    assert body["success"] is True
    assert body["imported"] == 0
    assert body["skipped"][0]["reason"] == "favorite_type must be medication or condition"


def test_post_rejects_empty_body() -> None:
    api = _make_api(body={})
    response = api.post()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["success"] is False
    assert "favorites" in body["error"]


def test_post_rejects_empty_favorites_list() -> None:
    api = _make_api(body={"favorites": []})
    response = api.post()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["success"] is False


def test_post_rejects_missing_staff_header() -> None:
    api = _make_api(body={"favorites": [{"favorite_type": "medication"}]}, staff_id="")
    response = api.post()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["success"] is False
    assert body["error"] == "Staff ID not found"


def test_post_malformed_json_returns_400() -> None:
    api = BulkImportAPI(MagicMock())
    api.request = MagicMock()
    api.request.method = "POST"
    api.request.query_params = {}
    api.request.headers = {"canvas-logged-in-user-id": "staff-uuid-1"}
    api.request.body = b"{not json"
    api.request.json.side_effect = ValueError("not json")

    response = api.post()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["success"] is False
    assert "Invalid JSON" in body["error"]


def test_post_non_dict_row_is_skipped_with_reason() -> None:
    api = _make_api(body={
        "favorites": [
            "not a dict",
            {"favorite_type": "condition", "display_name": "OK", "code": "Z00.0"},
        ],
    })
    with patch("clinical_favorites.protocols.bulk_import_api.FavoritesService") as mock_service_cls:
        mock_service = mock_service_cls.return_value
        validation_results = ["Row is not an object", None]
        mock_service.validate_favorite_payload.side_effect = (
            lambda *a, **kw: validation_results.pop(0)
        )
        mock_service.save_favorite.return_value = {"id": "custom_ok"}
        body = json.loads(api.post()[0].content)

    assert body["imported"] == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["reason"] == "Row is not an object"


def test_post_dry_run_validates_without_saving() -> None:
    api = _make_api(body={
        "dry_run": True,
        "favorites": [
            {
                "favorite_type": "medication",
                "display_name": "Valid",
                "fdb_code": "1234",
                "sig": "take once",
                "days_supply": 30,
                "quantity_to_dispense": "30",
                "unit": "tablet",
                "representative_ndc": "ndc",
                "ncpdp_quantity_qualifier_code": "00",
            },
            {
                "favorite_type": "medication",
                "display_name": "Bad, missing sig",
                "fdb_code": "1234",
                "days_supply": 30,
                "quantity_to_dispense": "30",
                "unit": "tablet",
                "representative_ndc": "ndc",
                "ncpdp_quantity_qualifier_code": "00",
            },
            {"favorite_type": "procedure", "display_name": "Wrong type"},
        ],
    })
    with patch.object(FavoritesService, "save_favorite") as mock_save:
        body = json.loads(api.post()[0].content)
        mock_save.assert_not_called()

    assert body["success"] is True
    assert body["dry_run"] is True
    assert body["imported"] == 0
    assert len(body["results"]) == 3

    valid_row = body["results"][0]
    assert valid_row["valid"] is True
    assert valid_row["reason"] is None
    assert valid_row["display_name"] == "Valid"

    missing_sig = body["results"][1]
    assert missing_sig["valid"] is False
    assert "sig" in missing_sig["reason"]
    assert missing_sig["display_name"] == "Bad, missing sig"

    wrong_type = body["results"][2]
    assert wrong_type["valid"] is False
    assert wrong_type["reason"] == "favorite_type must be medication or condition"


@patch("clinical_favorites.protocols.bulk_import_api.FavoritesService")
def test_post_real_import_returns_results_with_per_row_status(mock_service_cls: MagicMock) -> None:
    mock_service = mock_service_cls.return_value
    validation_results = [None, "favorite_type must be medication or condition"]
    mock_service.validate_favorite_payload.side_effect = (
        lambda *a, **kw: validation_results.pop(0)
    )
    mock_service.save_favorite.return_value = {"id": "custom_abc"}

    api = _make_api(body={
        "favorites": [
            {
                "favorite_type": "condition",
                "display_name": "Diabetes",
                "code": "E11.9",
            },
            {"favorite_type": "procedure", "display_name": "Wrong type"},
        ],
    })
    body = json.loads(api.post()[0].content)

    assert body["success"] is True
    assert body["dry_run"] is False
    assert body["imported"] == 1
    assert len(body["results"]) == 2
    assert body["results"][0]["valid"] is True
    assert body["results"][1]["valid"] is False
    assert len(body["skipped"]) == 1


@patch("clinical_favorites.protocols.bulk_import_api.FavoritesService")
def test_post_marks_row_invalid_when_save_raises_value_error(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.validate_favorite_payload.return_value = None
    mock_service.save_favorite.side_effect = ValueError("Staff record not found for UUID s1")

    body = json.loads(
        _make_api(body={
            "favorites": [
                {
                    "favorite_type": "condition",
                    "display_name": "Diabetes",
                    "code": "E11.9",
                }
            ]
        }).post()[0].content
    )

    assert body["imported"] == 0
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["valid"] is False
    assert "Staff record not found" in body["skipped"][0]["reason"]


@patch("clinical_favorites.protocols.bulk_import_api.FavoritesService")
def test_post_marks_row_invalid_when_save_raises_unexpected_error(
    mock_service_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.validate_favorite_payload.return_value = None
    mock_service.save_favorite.side_effect = RuntimeError("db connection lost")

    body = json.loads(
        _make_api(body={
            "favorites": [
                {
                    "favorite_type": "condition",
                    "display_name": "Diabetes",
                    "code": "E11.9",
                }
            ]
        }).post()[0].content
    )

    assert body["imported"] == 0
    assert len(body["skipped"]) == 1
    assert "Unexpected error" in body["skipped"][0]["reason"]


def test_max_import_rows_defaults_when_secret_absent() -> None:
    assert _make_api()._max_import_rows() == DEFAULT_MAX_IMPORT_ROWS


def test_max_import_rows_defaults_when_secret_blank() -> None:
    api = _make_api()
    api.secrets = {"BULK_IMPORT_MAX_ROWS": "  "}
    assert api._max_import_rows() == DEFAULT_MAX_IMPORT_ROWS


def test_max_import_rows_defaults_when_secret_not_an_integer() -> None:
    api = _make_api()
    api.secrets = {"BULK_IMPORT_MAX_ROWS": "lots"}
    assert api._max_import_rows() == DEFAULT_MAX_IMPORT_ROWS


def test_max_import_rows_defaults_when_secret_not_positive() -> None:
    api = _make_api()
    api.secrets = {"BULK_IMPORT_MAX_ROWS": "0"}
    assert api._max_import_rows() == DEFAULT_MAX_IMPORT_ROWS


def test_max_import_rows_uses_secret_override() -> None:
    api = _make_api()
    api.secrets = {"BULK_IMPORT_MAX_ROWS": "25"}
    assert api._max_import_rows() == 25


def test_post_rejects_more_rows_than_default_cap() -> None:
    rows = [
        {"favorite_type": "condition", "display_name": f"C{i}", "code": "Z00.0"}
        for i in range(DEFAULT_MAX_IMPORT_ROWS + 1)
    ]
    response = _make_api(body={"favorites": rows}).post()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["success"] is False
    assert f"max {DEFAULT_MAX_IMPORT_ROWS}" in body["error"]


def test_post_rejects_rows_over_secret_override_cap() -> None:
    api = _make_api(body={
        "favorites": [
            {"favorite_type": "condition", "display_name": "A", "code": "Z00.0"},
            {"favorite_type": "condition", "display_name": "B", "code": "Z00.1"},
            {"favorite_type": "condition", "display_name": "C", "code": "Z00.2"},
        ],
    })
    api.secrets = {"BULK_IMPORT_MAX_ROWS": "2"}
    response = api.post()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "max 2" in body["error"]
