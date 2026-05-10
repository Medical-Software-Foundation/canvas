"""Tests for patient_tags.handlers.external_api.

Covers bearer-token authentication, body resolution (label_ids vs labels by
name), and the four endpoints (list, replace, add, remove).
"""
import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from patient_tags.handlers import external_api
from patient_tags.handlers.external_api import TagExternalAPI


def _make_handler(
    *,
    body: dict | None = None,
    path_params: dict | None = None,
    secrets: dict | None = None,
) -> TagExternalAPI:
    handler = TagExternalAPI.__new__(TagExternalAPI)
    request = MagicMock()
    request.json.return_value = body or {}
    request.path_params = path_params or {}
    handler.request = request
    handler.secrets = secrets or {}
    return handler


def _decoded(response: object) -> dict:
    content = response.content  # type: ignore[attr-defined]
    return dict(json.loads(content.decode("utf-8")))


class TestResolveLabelIds:
    def test_label_ids_happy(self) -> None:
        ids, err = external_api._resolve_label_ids({"label_ids": [1, "2"]})
        assert ids == [1, 2]
        assert err is None

    def test_label_ids_invalid_type_returns_error(self) -> None:
        ids, err = external_api._resolve_label_ids({"label_ids": ["abc"]})
        assert ids is None
        assert err is not None and "must be a list of integers" in err

    @patch("patient_tags.handlers.external_api.Label")
    def test_labels_by_name_happy(self, mock_label: MagicMock) -> None:
        mock_label.objects.filter.return_value.values_list.return_value = [
            ("VIP", 1), ("Banned", 2),
        ]
        ids, err = external_api._resolve_label_ids({"labels": ["VIP", "Banned"]})
        assert ids == [1, 2]
        assert err is None

    def test_labels_not_a_list_returns_error(self) -> None:
        ids, err = external_api._resolve_label_ids({"labels": "VIP"})
        assert ids is None
        assert err is not None and "must be a list" in err

    @patch("patient_tags.handlers.external_api.Label")
    def test_labels_with_unknown_name_returns_error(self, mock_label: MagicMock) -> None:
        mock_label.objects.filter.return_value.values_list.return_value = [("VIP", 1)]
        ids, err = external_api._resolve_label_ids({"labels": ["VIP", "Bogus"]})
        assert ids is None
        assert err is not None and "Bogus" in err

    def test_missing_keys_returns_error(self) -> None:
        ids, err = external_api._resolve_label_ids({})
        assert ids is None
        assert err is not None and "label_ids" in err and "labels" in err


class TestAuthenticate:
    def test_unset_secret_rejects_all(self) -> None:
        handler = _make_handler(secrets={})
        creds = MagicMock(token="anything")
        assert handler.authenticate(creds) is False

    def test_matching_token_accepted(self) -> None:
        handler = _make_handler(secrets={"API_TOKEN": "expected"})
        creds = MagicMock(token="expected")
        assert handler.authenticate(creds) is True

    def test_mismatched_token_rejected(self) -> None:
        handler = _make_handler(secrets={"API_TOKEN": "expected"})
        creds = MagicMock(token="wrong")
        assert handler.authenticate(creds) is False


class TestListLabels:
    @patch("patient_tags.handlers.external_api.list_labels", return_value=[{"id": 1}])
    def test_returns_labels(self, mock_list: MagicMock) -> None:
        handler = _make_handler()
        responses = handler.get_labels()
        assert _decoded(responses[0]) == {"labels": [{"id": 1}]}


class TestGetPatientLabels:
    @patch(
        "patient_tags.handlers.external_api.get_patient_assignment_ids",
        return_value=[1, 2],
    )
    def test_returns_assignment_ids(self, mock_get: MagicMock) -> None:
        handler = _make_handler(path_params={"patient_id": "p1"})
        responses = handler.get_patient_labels()
        assert _decoded(responses[0]) == {"label_ids": [1, 2]}


class TestReplacePatientLabels:
    @patch(
        "patient_tags.handlers.external_api.get_patient_assignment_ids",
        return_value=[1, 2],
    )
    @patch("patient_tags.handlers.external_api.compute_banner_effects", return_value=[])
    @patch("patient_tags.handlers.external_api.save_patient_assignments")
    def test_happy_path(
        self,
        mock_save: MagicMock,
        mock_compute: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        handler = _make_handler(
            body={"label_ids": [1, 2]},
            path_params={"patient_id": "p1"},
        )
        responses = handler.replace_patient_labels()

        mock_save.assert_called_once_with("p1", [1, 2], actor_id="", actor_name="API")
        body = _decoded(responses[0])
        assert body == {"status": "ok", "label_ids": [1, 2]}

    def test_invalid_body_returns_400(self) -> None:
        handler = _make_handler(
            body={},
            path_params={"patient_id": "p1"},
        )
        responses = handler.replace_patient_labels()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("patient_tags.handlers.external_api.save_patient_assignments")
    def test_unknown_patient_returns_404(self, mock_save: MagicMock) -> None:
        from patient_tags.models import PatientProxy

        mock_save.side_effect = PatientProxy.DoesNotExist
        handler = _make_handler(
            body={"label_ids": [1]},
            path_params={"patient_id": "ghost"},
        )
        responses = handler.replace_patient_labels()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND
        assert "not found" in _decoded(responses[0])["error"]


class TestAddPatientLabels:
    @patch(
        "patient_tags.handlers.external_api.get_patient_assignment_ids",
        return_value=[1, 2, 3],
    )
    @patch("patient_tags.handlers.external_api.compute_banner_effects", return_value=[])
    @patch(
        "patient_tags.handlers.external_api.add_patient_assignments",
        return_value={"added": [3], "already_present": [1]},
    )
    def test_happy_path(
        self,
        mock_add: MagicMock,
        mock_compute: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        handler = _make_handler(
            body={"label_ids": [1, 3]},
            path_params={"patient_id": "p1"},
        )
        responses = handler.add_patient_labels()

        body = _decoded(responses[0])
        assert body["status"] == "ok"
        assert body["added"] == [3]
        assert body["already_present"] == [1]
        assert body["label_ids"] == [1, 2, 3]

    def test_invalid_body_returns_400(self) -> None:
        handler = _make_handler(body={}, path_params={"patient_id": "p1"})
        responses = handler.add_patient_labels()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    @patch(
        "patient_tags.handlers.external_api.add_patient_assignments",
        side_effect=ValueError("Unknown label IDs: [99]"),
    )
    def test_unknown_label_returns_400(self, mock_add: MagicMock) -> None:
        handler = _make_handler(
            body={"label_ids": [99]},
            path_params={"patient_id": "p1"},
        )
        responses = handler.add_patient_labels()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert "Unknown" in _decoded(responses[0])["error"]


class TestRemovePatientLabels:
    @patch(
        "patient_tags.handlers.external_api.get_patient_assignment_ids",
        return_value=[1],
    )
    @patch("patient_tags.handlers.external_api.compute_banner_effects", return_value=[])
    @patch(
        "patient_tags.handlers.external_api.remove_patient_assignments",
        return_value={"removed": [2], "not_present": [99]},
    )
    def test_happy_path(
        self,
        mock_remove: MagicMock,
        mock_compute: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        handler = _make_handler(
            body={"label_ids": [2, 99]},
            path_params={"patient_id": "p1"},
        )
        responses = handler.remove_patient_labels()

        body = _decoded(responses[0])
        assert body["status"] == "ok"
        assert body["removed"] == [2]
        assert body["not_present"] == [99]
        assert body["label_ids"] == [1]

    def test_invalid_body_returns_400(self) -> None:
        handler = _make_handler(body={}, path_params={"patient_id": "p1"})
        responses = handler.remove_patient_labels()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
