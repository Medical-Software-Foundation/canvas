from unittest.mock import MagicMock, patch

from staff_directory.routes.nucc_api import NuccAPI


def _make_handler():
    handler = NuccAPI.__new__(NuccAPI)
    handler.request = MagicMock()
    handler.request.query_params = {}
    return handler


class TestSearch:
    def test_returns_serialized_results(self):
        handler = _make_handler()
        handler.request.query_params = {"q": "cardio", "limit": "10"}

        fake_row = MagicMock()
        with patch("staff_directory.routes.nucc_api.ensure_nucc_seed"):
            with patch("staff_directory.routes.nucc_api.search_nucc") as mock_search:
                with patch("staff_directory.routes.nucc_api.serialize_nucc") as mock_serialize:
                    mock_search.return_value = [fake_row]
                    mock_serialize.return_value = {"code": "X"}
                    resp = handler.search()[0]

        assert resp.data["count"] == 1
        assert resp.data["results"] == [{"code": "X"}]

    def test_invalid_limit_uses_default(self):
        handler = _make_handler()
        handler.request.query_params = {"q": "x", "limit": "bad"}
        with patch("staff_directory.routes.nucc_api.ensure_nucc_seed"):
            with patch("staff_directory.routes.nucc_api.search_nucc") as mock_search:
                mock_search.return_value = []
                handler.search()
                mock_search.assert_called_with("x", limit=25)

    def test_empty_query(self):
        handler = _make_handler()
        handler.request.query_params = {}
        with patch("staff_directory.routes.nucc_api.ensure_nucc_seed"):
            with patch("staff_directory.routes.nucc_api.search_nucc") as mock_search:
                mock_search.return_value = []
                resp = handler.search()[0]
                assert resp.data["count"] == 0
