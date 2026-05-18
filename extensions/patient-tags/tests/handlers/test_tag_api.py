"""Tests for patient_tags.handlers.tag_api.

Covers the staff-session SimpleAPI surface: label, banner-group, rule CRUD,
patient assignment endpoints, the manage-tabs gate, and actor resolution.
"""
import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from patient_tags.handlers import tag_api
from patient_tags.handlers.tag_api import TagAPI


def _make_handler(
    *,
    body: dict | None = None,
    path_params: dict | None = None,
    headers: dict | None = None,
    secrets: dict | None = None,
) -> TagAPI:
    handler = TagAPI.__new__(TagAPI)
    request = MagicMock()
    request.json.return_value = body or {}
    request.path_params = path_params or {}
    request.headers = headers or {}
    handler.request = request
    handler.secrets = secrets or {}
    return handler


def _decoded(response: object) -> dict:
    content = response.content  # type: ignore[attr-defined]
    return dict(json.loads(content.decode("utf-8")))


class TestAllowedRoleCodes:
    def test_empty_returns_empty_set(self) -> None:
        assert tag_api._allowed_role_codes({}) == set()
        assert tag_api._allowed_role_codes({"MANAGE_TABS_ROLES": "  "}) == set()

    def test_parses_comma_separated(self) -> None:
        result = tag_api._allowed_role_codes({"MANAGE_TABS_ROLES": "admin, ops, "})
        assert result == {"admin", "ops"}


class TestCanManage:
    def test_empty_secret_allows_anyone(self) -> None:
        assert tag_api._can_manage("u1", {}) is True

    def test_no_user_with_restriction_denies(self) -> None:
        assert tag_api._can_manage("", {"MANAGE_TABS_ROLES": "admin"}) is False

    @patch("patient_tags.handlers.tag_api.StaffRole")
    def test_user_with_matching_role_allowed(self, mock_role: MagicMock) -> None:
        mock_role.objects.filter.return_value.values_list.return_value = ["admin"]
        assert tag_api._can_manage("u1", {"MANAGE_TABS_ROLES": "admin"}) is True

    @patch("patient_tags.handlers.tag_api.StaffRole")
    def test_user_without_matching_role_denied(self, mock_role: MagicMock) -> None:
        mock_role.objects.filter.return_value.values_list.return_value = ["nurse"]
        assert tag_api._can_manage("u1", {"MANAGE_TABS_ROLES": "admin"}) is False


class TestResolveActor:
    def test_empty_uuid(self) -> None:
        assert tag_api._resolve_actor("") == ("", "")

    @patch("patient_tags.handlers.tag_api.Staff")
    def test_missing_row(self, mock_staff: MagicMock) -> None:
        mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = None
        assert tag_api._resolve_actor("u1") == ("u1", "")

    @patch("patient_tags.handlers.tag_api.Staff")
    def test_full_name(self, mock_staff: MagicMock) -> None:
        mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = ("A", "B")
        assert tag_api._resolve_actor("u1") == ("u1", "A B")

    @patch("patient_tags.handlers.tag_api.Staff")
    def test_partial_name(self, mock_staff: MagicMock) -> None:
        mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = (None, "Last")
        assert tag_api._resolve_actor("u1") == ("u1", "Last")

    @patch("patient_tags.handlers.tag_api.Staff")
    def test_blank_name(self, mock_staff: MagicMock) -> None:
        mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = (None, None)
        assert tag_api._resolve_actor("u1") == ("u1", "")


class TestLabelEndpoints:
    @patch("patient_tags.handlers.tag_api.list_labels", return_value=[{"id": 1}])
    def test_get_labels(self, mock_list: MagicMock) -> None:
        handler = _make_handler()
        responses = handler.get_labels()
        assert _decoded(responses[0]) == {"labels": [{"id": 1}]}

    @patch("patient_tags.handlers.tag_api.create_label", return_value={"id": 1, "name": "VIP"})
    def test_post_label_happy(self, mock_create: MagicMock) -> None:
        handler = _make_handler(body={
            "name": "VIP", "description": "d", "color": "blue",
            "assignable_in_chart": True, "assignable_in_profile": False,
            "banner_group_id": None,
        })
        responses = handler.post_label()
        assert responses[0].status_code == HTTPStatus.CREATED
        mock_create.assert_called_once()

    @patch("patient_tags.handlers.tag_api.create_label", side_effect=ValueError("dup"))
    def test_post_label_validation_error(self, mock_create: MagicMock) -> None:
        handler = _make_handler(body={"name": "VIP"})
        responses = handler.post_label()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert _decoded(responses[0]) == {"error": "dup"}

    @patch("patient_tags.handlers.tag_api.update_label", return_value=({"id": 1}, []))
    def test_patch_label_happy(self, mock_update: MagicMock) -> None:
        handler = _make_handler(body={"name": "X"}, path_params={"label_id": "5"})
        responses = handler.patch_label()
        assert responses[0].status_code == HTTPStatus.OK
        mock_update.assert_called_once_with(5, name="X")

    @patch("patient_tags.handlers.tag_api.update_label", side_effect=ValueError("bad"))
    def test_patch_label_validation_error(self, mock_update: MagicMock) -> None:
        handler = _make_handler(body={"name": "X"}, path_params={"label_id": "5"})
        responses = handler.patch_label()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("patient_tags.handlers.tag_api.delete_label", return_value=[])
    def test_remove_label(self, mock_delete: MagicMock) -> None:
        handler = _make_handler(path_params={"label_id": "5"})
        responses = handler.remove_label()
        mock_delete.assert_called_once_with(5)
        assert _decoded(responses[0]) == {"status": "ok"}


class TestBannerGroupEndpoints:
    @patch("patient_tags.handlers.tag_api.list_banner_groups", return_value=[{"id": 1}])
    def test_get_banner_groups(self, mock_list: MagicMock) -> None:
        handler = _make_handler()
        responses = handler.get_banner_groups()
        assert _decoded(responses[0]) == {"groups": [{"id": 1}]}

    @patch("patient_tags.handlers.tag_api.create_banner_group", return_value={"id": 1})
    def test_post_banner_group_happy(self, mock_create: MagicMock) -> None:
        handler = _make_handler(body={"name": "G", "intent": "info"})
        responses = handler.post_banner_group()
        assert responses[0].status_code == HTTPStatus.CREATED

    @patch("patient_tags.handlers.tag_api.create_banner_group", side_effect=ValueError("bad"))
    def test_post_banner_group_validation_error(self, mock_create: MagicMock) -> None:
        handler = _make_handler(body={"name": ""})
        responses = handler.post_banner_group()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("patient_tags.handlers.tag_api.update_banner_group", return_value={"id": 1})
    def test_patch_banner_group_happy(self, mock_update: MagicMock) -> None:
        handler = _make_handler(body={"name": "X"}, path_params={"group_id": "9"})
        responses = handler.patch_banner_group()
        mock_update.assert_called_once_with(9, name="X")

    @patch("patient_tags.handlers.tag_api.update_banner_group", side_effect=ValueError("bad"))
    def test_patch_banner_group_validation_error(self, mock_update: MagicMock) -> None:
        handler = _make_handler(body={"name": "X"}, path_params={"group_id": "9"})
        responses = handler.patch_banner_group()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("patient_tags.handlers.tag_api.delete_banner_group", return_value=[])
    def test_remove_banner_group(self, mock_delete: MagicMock) -> None:
        handler = _make_handler(path_params={"group_id": "9"})
        responses = handler.remove_banner_group()
        mock_delete.assert_called_once_with(9)
        assert _decoded(responses[0]) == {"status": "ok"}

    @patch("patient_tags.handlers.tag_api.delete_banner_group")
    def test_remove_banner_group_includes_remove_effects(
        self, mock_delete: MagicMock
    ) -> None:
        # Effects from delete_banner_group must flow through to the response
        # so Canvas processes the RemoveBannerAlert cleanup for affected
        # patients (otherwise the orphaned banner stays on charts forever).
        sentinel_effect_a = MagicMock()
        sentinel_effect_b = MagicMock()
        mock_delete.return_value = [sentinel_effect_a, sentinel_effect_b]

        handler = _make_handler(path_params={"group_id": "9"})
        responses = handler.remove_banner_group()

        assert responses[0].status_code == HTTPStatus.OK
        assert responses[1] is sentinel_effect_a
        assert responses[2] is sentinel_effect_b


class TestCanManageEndpoint:
    def test_returns_true_with_no_secret(self) -> None:
        handler = _make_handler(headers={"canvas-logged-in-user-id": "u1"})
        responses = handler.get_me_can_manage()
        assert _decoded(responses[0]) == {"can_manage": True}

    def test_returns_false_when_uuid_missing_and_secret_set(self) -> None:
        handler = _make_handler(headers={}, secrets={"MANAGE_TABS_ROLES": "admin"})
        responses = handler.get_me_can_manage()
        assert _decoded(responses[0]) == {"can_manage": False}


class TestRuleEndpoints:
    @patch("patient_tags.handlers.tag_api.list_rules_for_label", return_value=[{"id": 1}])
    def test_get_label_rules(self, mock_list: MagicMock) -> None:
        handler = _make_handler(path_params={"label_id": "10"})
        responses = handler.get_label_rules()
        mock_list.assert_called_once_with(10)
        assert _decoded(responses[0]) == {"rules": [{"id": 1}]}

    @patch("patient_tags.handlers.tag_api.create_rule", return_value={"id": 1})
    def test_post_label_rule_happy(self, mock_create: MagicMock) -> None:
        handler = _make_handler(
            body={"action": "auto_assign", "target_label_id": 99},
            path_params={"label_id": "10"},
        )
        responses = handler.post_label_rule()
        assert responses[0].status_code == HTTPStatus.CREATED
        mock_create.assert_called_once_with(
            trigger_label_id=10, action="auto_assign", target_label_id=99,
        )

    @patch("patient_tags.handlers.tag_api.create_rule", side_effect=ValueError("conflict"))
    def test_post_label_rule_value_error(self, mock_create: MagicMock) -> None:
        handler = _make_handler(
            body={"action": "auto_assign", "target_label_id": 99},
            path_params={"label_id": "10"},
        )
        responses = handler.post_label_rule()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_post_label_rule_type_error_on_bad_target_id(self) -> None:
        # Non-integer target → int() raises ValueError, returned as 400.
        handler = _make_handler(
            body={"action": "auto_assign", "target_label_id": "bogus"},
            path_params={"label_id": "10"},
        )
        responses = handler.post_label_rule()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("patient_tags.handlers.tag_api.delete_rule")
    def test_remove_rule(self, mock_delete: MagicMock) -> None:
        handler = _make_handler(path_params={"rule_id": "7"})
        responses = handler.remove_rule()
        mock_delete.assert_called_once_with(7)
        assert _decoded(responses[0]) == {"status": "ok"}


class TestPatientLabelEndpoints:
    @patch(
        "patient_tags.handlers.tag_api.get_patient_assignment_ids",
        return_value=[1, 2],
    )
    def test_get_patient_labels(self, mock_get: MagicMock) -> None:
        handler = _make_handler(path_params={"patient_id": "p1"})
        responses = handler.get_patient_labels()
        assert _decoded(responses[0]) == {"label_ids": [1, 2]}

    @patch("patient_tags.handlers.tag_api.compute_banner_effects", return_value=[])
    @patch("patient_tags.handlers.tag_api._resolve_actor", return_value=("u1", "Alice"))
    @patch("patient_tags.handlers.tag_api.save_patient_assignments")
    def test_save_patient_labels(
        self,
        mock_save: MagicMock,
        mock_actor: MagicMock,
        mock_compute: MagicMock,
    ) -> None:
        handler = _make_handler(
            body={"label_ids": [1, "2"]},
            path_params={"patient_id": "p1"},
            headers={"canvas-logged-in-user-id": "u1"},
        )
        responses = handler.save_patient_labels()

        mock_save.assert_called_once_with(
            "p1", [1, 2], actor_id="u1", actor_name="Alice",
        )
        assert _decoded(responses[0]) == {"status": "ok"}

    @patch("patient_tags.handlers.tag_api.list_patient_history", return_value=[])
    def test_get_patient_history(self, mock_history: MagicMock) -> None:
        handler = _make_handler(path_params={"patient_id": "p1"})
        responses = handler.get_patient_history()
        mock_history.assert_called_once_with("p1")
        assert _decoded(responses[0]) == {"history": []}
