from http import HTTPStatus
from unittest.mock import MagicMock, patch

from staff_directory.routes.staff_api import StaffProfileAPI, _parse_int


class TestParseInt:
    def test_none(self):
        assert _parse_int(None) is None

    def test_empty(self):
        assert _parse_int("") is None

    def test_valid(self):
        assert _parse_int("42") == 42

    def test_invalid(self):
        assert _parse_int("abc") is None


def _make_handler(is_admin_value=True):
    """Build a handler instance with secrets, request, and admin behavior mocked."""
    handler = StaffProfileAPI.__new__(StaffProfileAPI)
    handler.secrets = {"ADMIN_ROLE_CODES": "ADMIN"}
    handler.request = MagicMock()
    handler.request.headers = {"canvas-logged-in-user-id": "uid"}
    handler.request.path_params = {}
    handler.request.query_params = {}
    handler.request.json = MagicMock(return_value={})
    handler._is_admin = lambda: is_admin_value
    return handler


class TestRequireAdmin:
    def test_non_admin_returns_forbidden(self):
        handler = _make_handler(is_admin_value=False)
        denial = handler._require_admin()
        assert denial is not None
        assert denial.status_code == HTTPStatus.FORBIDDEN

    def test_admin_passes(self):
        handler = _make_handler(is_admin_value=True)
        assert handler._require_admin() is None


class TestListStaff:
    def test_calls_service_with_search(self):
        handler = _make_handler(is_admin_value=True)
        handler.request.query_params = {"search": "chen", "specialty_code": ""}

        with patch("staff_directory.routes.staff_api.svc_list_staff") as mock_list:
            mock_list.return_value = [{"id": 1}]
            responses = handler.list_staff()
            mock_list.assert_called_with(
                search="chen", specialty_code="", expiring_within_days=None
            )
            assert responses[0].data["count"] == 1
            assert responses[0].data["is_admin"] is True

    def test_expiring_filter_parsed(self):
        handler = _make_handler(is_admin_value=False)
        handler.request.query_params = {"expiring_within_days": "30"}
        with patch("staff_directory.routes.staff_api.svc_list_staff") as mock_list:
            mock_list.return_value = []
            handler.list_staff()
            mock_list.assert_called_with(
                search="", specialty_code="", expiring_within_days=30
            )


class TestGetStaff:
    def test_invalid_id_returns_400(self):
        handler = _make_handler()
        handler.request.path_params = {"staff_dbid": "xyz"}
        resp = handler.get_staff()[0]
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_missing_returns_404(self):
        handler = _make_handler()
        handler.request.path_params = {"staff_dbid": "5"}
        with patch("staff_directory.routes.staff_api.get_staff_profile") as mock_get:
            mock_get.return_value = None
            resp = handler.get_staff()[0]
            assert resp.status_code == HTTPStatus.NOT_FOUND

    def test_found_returns_profile(self):
        handler = _make_handler(is_admin_value=False)
        handler.request.path_params = {"staff_dbid": "5"}
        with patch("staff_directory.routes.staff_api.get_staff_profile") as mock_get:
            mock_get.return_value = {"full_name": "X"}
            resp = handler.get_staff()[0]
            assert resp.data["full_name"] == "X"
            assert resp.data["is_admin"] is False


class TestEducationRoutes:
    def test_add_denied_for_non_admin(self):
        handler = _make_handler(is_admin_value=False)
        handler.request.path_params = {"staff_dbid": "5"}
        responses = handler.add_education()
        assert responses[0].status_code == HTTPStatus.FORBIDDEN

    def test_add_calls_service(self):
        handler = _make_handler(is_admin_value=True)
        handler.request.path_params = {"staff_dbid": "5"}
        handler.request.json = MagicMock(return_value={"institution": "X", "degree": "MD"})
        with patch("staff_directory.routes.staff_api.edu_create") as mock_create:
            with patch("staff_directory.routes.staff_api.edu_serialize") as mock_ser:
                mock_create.return_value = "ENTRY"
                mock_ser.return_value = {"id": 1}
                resp = handler.add_education()[0]
                mock_create.assert_called_with(5, {"institution": "X", "degree": "MD"})
                assert resp.status_code == HTTPStatus.CREATED

    def test_delete_missing(self):
        handler = _make_handler(is_admin_value=True)
        handler.request.path_params = {"staff_dbid": "5", "entry_id": "9"}
        with patch("staff_directory.routes.staff_api.edu_delete") as mock_delete:
            mock_delete.return_value = False
            resp = handler.delete_education()[0]
            assert resp.status_code == HTTPStatus.NOT_FOUND


class TestSpecialtyRoutes:
    def test_add_invalid_code_returns_400(self):
        from staff_directory.services.specialties import SpecialtyError

        handler = _make_handler(is_admin_value=True)
        handler.request.path_params = {"staff_dbid": "5"}
        handler.request.json = MagicMock(return_value={"nucc_code": "BAD"})
        with patch("staff_directory.routes.staff_api.spec_create") as mock_create:
            mock_create.side_effect = SpecialtyError("Unknown NUCC code: BAD")
            resp = handler.add_specialty()[0]
            assert resp.status_code == HTTPStatus.BAD_REQUEST
            assert "Unknown" in resp.data["error"]

    def test_set_primary_missing_404(self):
        handler = _make_handler(is_admin_value=True)
        handler.request.path_params = {"staff_dbid": "5", "entry_id": "9"}
        with patch("staff_directory.routes.staff_api.spec_set_primary") as mock_set:
            mock_set.return_value = None
            resp = handler.set_primary_specialty()[0]
            assert resp.status_code == HTTPStatus.NOT_FOUND
