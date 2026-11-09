import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from requests import ConnectionError as RequestsConnectionError

from tellescope_banner.applications import profile_app
from tellescope_banner.applications.profile_app import (
    MSG_API_ERROR,
    MSG_AUTH,
    MSG_BAD_API_URL,
    MSG_NO_PATIENT,
    MSG_NOT_CONFIGURED,
    MSG_NOT_LINKED,
    MSG_UNREACHABLE,
    TellescopeProfileApp,
)

API_KEY = "test-key"


def open_app(context: dict[str, Any], secrets: dict[str, str]) -> Any:
    event = SimpleNamespace(context=context, target=SimpleNamespace(id="x"))
    return TellescopeProfileApp(event=event, secrets=secrets).on_open()


def payload(effect: Any) -> dict[str, Any]:
    return json.loads(effect.payload)["data"]


def fake_response(
    status: int = 200, body: Any = None, bad_json: bool = False
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    if bad_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body
    return response


@pytest.fixture
def http() -> Any:
    with patch.object(profile_app, "Http") as http_cls:
        yield http_cls.return_value


def test_no_patient_in_context_shows_message(http: Any) -> None:
    data = payload(open_app({}, {"TELLESCOPE_API_KEY": API_KEY}))
    assert MSG_NO_PATIENT in data["content"]
    http.get.assert_not_called()


def test_api_lookup_opens_enduser_profile(http: Any) -> None:
    http.get.return_value = fake_response(body=[{"id": "abc123"}])
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert data["url"] == "https://business.tellescope.com/endusers/abc123"
    assert data["target"] == "right_chart_pane_large"

    url = http.get.call_args.args[0]
    parts = urlsplit(url)
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}"
        == "https://api.tellescope.com/v1/endusers"
    )
    sent_filter = json.loads(parse_qs(parts.query)["mdbFilter"][0])
    assert sent_filter["$or"][0]["$and"] == [
        {"source": "Canvas"},
        {"externalId": "pat-1"},
    ]
    assert sent_filter["$or"][1]["references"]["$elemMatch"] == {
        "type": "Canvas",
        "id": "pat-1",
    }
    assert http.get.call_args.kwargs["headers"]["Authorization"] == f"API_KEY {API_KEY}"


def test_api_lookup_accepts_data_wrapper_and_encodes_id(http: Any) -> None:
    http.get.return_value = fake_response(body={"data": [{"id": "a/b?c"}]})
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert data["url"] == "https://business.tellescope.com/endusers/a%2Fb%3Fc"


def test_custom_api_url_is_used(http: Any) -> None:
    http.get.return_value = fake_response(body=[{"id": "abc"}])
    open_app(
        {"patient": {"id": "pat-1"}},
        {
            "TELLESCOPE_API_KEY": API_KEY,
            "TELLESCOPE_API_URL": "https://staging.example.test/v1/",
        },
    )
    assert http.get.call_args.args[0].startswith(
        "https://staging.example.test/v1/endusers?"
    )


def test_non_https_api_url_is_refused_without_sending_key(http: Any) -> None:
    data = payload(
        open_app(
            {"patient": {"id": "pat-1"}},
            {
                "TELLESCOPE_API_KEY": API_KEY,
                "TELLESCOPE_API_URL": "http://api.example.test",
            },
        )
    )
    assert MSG_BAD_API_URL in data["content"]
    http.get.assert_not_called()


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_message(http: Any, status: int) -> None:
    http.get.return_value = fake_response(status=status)
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert MSG_AUTH in data["content"]


@pytest.mark.parametrize("status", [404, 429, 500, 503])
def test_other_http_errors_show_generic_message(http: Any, status: int) -> None:
    http.get.return_value = fake_response(status=status)
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert MSG_API_ERROR in data["content"]


def test_network_error_shows_unreachable_without_exception_text(http: Any) -> None:
    http.get.side_effect = RequestsConnectionError(
        "secret-detail https://x?mdbFilter=pat-1"
    )
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert MSG_UNREACHABLE in data["content"]
    assert "secret-detail" not in data["content"]


def test_non_json_body_shows_error(http: Any) -> None:
    http.get.return_value = fake_response(bad_json=True)
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert MSG_API_ERROR in data["content"]


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"data": []},
        {},
        None,
        ["x"],
        [{"id": ""}],
        [{"id": "  "}],
        [{"id": 7}],
        [{}],
    ],
)
def test_no_linked_enduser_shows_not_linked(http: Any, body: Any) -> None:
    http.get.return_value = fake_response(body=body)
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert MSG_NOT_LINKED in data["content"]
    assert "url" not in data or not data["url"]


def test_underscore_id_is_accepted(http: Any) -> None:
    http.get.return_value = fake_response(body=[{"_id": "mongo1"}])
    data = payload(
        open_app({"patient": {"id": "pat-1"}}, {"TELLESCOPE_API_KEY": API_KEY})
    )
    assert data["url"] == "https://business.tellescope.com/endusers/mongo1"


def test_without_api_key_uses_template(http: Any) -> None:
    data = payload(
        open_app(
            {"patient": {"id": "pat 1"}},
            {"TELLESCOPE_PROFILE_URL_TEMPLATE": "https://example.test/p/{patient_id}"},
        )
    )
    assert data["url"] == "https://example.test/p/pat%201"
    http.get.assert_not_called()


@pytest.mark.parametrize(
    "secrets",
    [
        {},
        {"TELLESCOPE_API_KEY": "  "},
        {"TELLESCOPE_PROFILE_URL_TEMPLATE": "http://x/{patient_id}"},
    ],
)
def test_nothing_configured_shows_setup_message(
    http: Any, secrets: dict[str, str]
) -> None:
    data = payload(open_app({"patient": {"id": "pat-1"}}, secrets))
    assert MSG_NOT_CONFIGURED in data["content"]
    http.get.assert_not_called()
