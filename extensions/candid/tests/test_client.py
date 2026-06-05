"""Tests for CandidClient: token caching, error formatting, secret-driven construction."""

from unittest.mock import MagicMock

from candid.api.client import CandidClient

from tests.conftest import MOCK_SECRETS


def _client() -> CandidClient:
    return CandidClient(
        base_url=MOCK_SECRETS["CANDID_BASE_URL"],
        client_id=MOCK_SECRETS["CANDID_CLIENT_ID"],
        client_secret=MOCK_SECRETS["CANDID_CLIENT_SECRET"],
    )


def _ok_response(json_body: dict) -> MagicMock:
    r = MagicMock()
    r.ok = True
    r.json.return_value = json_body
    r.raise_for_status.return_value = None
    return r


# ---------------------------------------------------------------------------
# from_secrets
# ---------------------------------------------------------------------------


def test_from_secrets_constructs_client_from_dict() -> None:
    client = CandidClient.from_secrets(MOCK_SECRETS)
    assert client.base_url == MOCK_SECRETS["CANDID_BASE_URL"]
    assert client.client_id == MOCK_SECRETS["CANDID_CLIENT_ID"]
    assert client.client_secret == MOCK_SECRETS["CANDID_CLIENT_SECRET"]


def test_base_url_trailing_slash_is_stripped() -> None:
    client = CandidClient(
        base_url="https://api.candid.test/",
        client_id="x",
        client_secret="y",
    )
    assert client.base_url == "https://api.candid.test"


# ---------------------------------------------------------------------------
# Token caching
# ---------------------------------------------------------------------------


def test_token_is_fetched_once_and_reused_across_requests() -> None:
    client = _client()
    client.http = MagicMock()
    # token endpoint
    token_response = _ok_response({"access_token": "tok-abc"})
    # encounter endpoint (used for the second call below)
    encounter_response = _ok_response({"claims": []})
    client.http.post.return_value = token_response
    client.http.get.return_value = encounter_response

    # Two calls that each require auth
    client.get_encounter("enc-1")
    client.get_encounter("enc-2")

    token_calls = [
        c for c in client.http.post.call_args_list
        if c.args and c.args[0].endswith("/api/auth/v2/token")
    ]
    assert len(token_calls) == 1


# ---------------------------------------------------------------------------
# Token fetch failure
# ---------------------------------------------------------------------------


def test_token_missing_in_response_raises() -> None:
    client = _client()
    client.http = MagicMock()
    client.http.post.return_value = _ok_response({})

    try:
        client._fetch_token()
    except RuntimeError as e:
        assert "Could not fetch Candid API token" in str(e)
    else:
        raise AssertionError("Expected RuntimeError")


# ---------------------------------------------------------------------------
# submit_claim
# ---------------------------------------------------------------------------


def test_submit_claim_returns_encounter_id_on_success() -> None:
    client = _client()
    client.http = MagicMock()
    token_response = _ok_response({"access_token": "tok"})
    encounter_response = _ok_response({"encounter_id": "enc-xyz"})
    # First post: token; subsequent post: submit
    client.http.post.side_effect = [token_response, encounter_response]

    success, message = client.submit_claim({"external_id": "canvas:1"})

    assert success is True
    assert message == "enc-xyz"


def test_submit_claim_returns_formatted_error_on_failure() -> None:
    client = _client()
    failure = MagicMock()
    failure.ok = False
    failure.status_code = 400
    failure.json.return_value = {
        "errorName": "HttpRequestValidationError",
        "content": {
            "fieldName": "patient.zip",
            "humanReadableMessage": "is required",
        },
    }

    client.http = MagicMock()
    client.http.post.side_effect = [
        _ok_response({"access_token": "tok"}),
        failure,
    ]

    success, message = client.submit_claim({})

    assert success is False
    assert "400" in message
    assert "HttpRequestValidationError" in message
    assert "patient.zip" in message
    assert "is required" in message


def test_format_error_handles_validations_list() -> None:
    failure = MagicMock()
    failure.ok = False
    failure.status_code = 422
    failure.json.return_value = {
        "errorName": "HttpRequestValidationsError",
        "content": [
            {"fieldName": "f1", "humanReadableMessage": "m1"},
            {"fieldName": "f2", "humanReadableMessage": "m2"},
        ],
    }
    msg = CandidClient._format_error(failure)
    assert "f1: m1" in msg
    assert "f2: m2" in msg


def test_format_error_falls_back_to_text_when_json_unparseable() -> None:
    failure = MagicMock()
    failure.ok = False
    failure.status_code = 502
    failure.json.side_effect = ValueError("not json")
    failure.text = "Bad Gateway"
    msg = CandidClient._format_error(failure)
    assert "502" in msg
    assert "Bad Gateway" in msg


# ---------------------------------------------------------------------------
# get_patient_payments
# ---------------------------------------------------------------------------


def test_get_patient_payments_returns_list_directly() -> None:
    client = _client()
    client.http = MagicMock()
    client.http.post.return_value = _ok_response({"access_token": "tok"})
    client.http.get.return_value = _ok_response(
        [{"patient_payment_id": "p1", "amount_cents": 1000}]
    )

    payments = client.get_patient_payments("candid-claim-1")

    assert payments == [{"patient_payment_id": "p1", "amount_cents": 1000}]


def test_get_patient_payments_unwraps_items_field() -> None:
    """Some Candid responses wrap the list under {'items': [...]}; client unwraps."""
    client = _client()
    client.http = MagicMock()
    client.http.post.return_value = _ok_response({"access_token": "tok"})
    client.http.get.return_value = _ok_response(
        {"items": [{"patient_payment_id": "p2"}]}
    )

    payments = client.get_patient_payments("candid-claim-1")

    assert payments == [{"patient_payment_id": "p2"}]


# ---------------------------------------------------------------------------
# create_service_line / delete_service_line
# ---------------------------------------------------------------------------


def test_create_service_line_posts_to_v2_and_returns_id() -> None:
    client = _client()
    client.http = MagicMock()
    client.http.post.side_effect = [
        _ok_response({"access_token": "tok"}),
        _ok_response({"service_line_id": "sl-new"}),
    ]

    success, message = client.create_service_line(
        {"claim_id": "candid-claim-1", "procedure_code": "G0019"}
    )

    assert success is True
    assert message == "sl-new"
    url = client.http.post.call_args_list[-1].args[0]
    assert url.endswith("/api/service-lines/v2")


def test_create_service_line_returns_formatted_error_on_failure() -> None:
    client = _client()
    failure = MagicMock()
    failure.ok = False
    failure.status_code = 422
    failure.json.return_value = {"errorName": "HttpRequestValidationError", "content": {}}
    client.http = MagicMock()
    client.http.post.side_effect = [_ok_response({"access_token": "tok"}), failure]

    success, message = client.create_service_line({"claim_id": "c1"})

    assert success is False
    assert "422" in message


def test_delete_service_line_calls_delete_with_id() -> None:
    client = _client()
    client.http = MagicMock()
    client.http.post.return_value = _ok_response({"access_token": "tok"})
    client.http.delete.return_value = _ok_response({})

    success, message = client.delete_service_line("sl-1")

    assert success is True
    assert message == "sl-1"
    url = client.http.delete.call_args.args[0]
    assert url.endswith("/api/service-lines/v2/sl-1")


def test_update_service_line_patches_v2_and_returns_id() -> None:
    client = _client()
    client.http = MagicMock()
    client.http.post.return_value = _ok_response({"access_token": "tok"})
    client.http.patch.return_value = _ok_response({"service_line_id": "sl-1"})

    success, message = client.update_service_line("sl-1", {"charge_amount_cents": 6000})

    assert success is True
    assert message == "sl-1"
    url = client.http.patch.call_args.args[0]
    assert url.endswith("/api/service-lines/v2/sl-1")
