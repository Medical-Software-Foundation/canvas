import json
from unittest.mock import MagicMock, patch

from canvas_sdk.events import EventType

from new_staff_password.handlers.event_handlers import NewStaffPasswordResetHandler

HANDLER_MODULE = "new_staff_password.handlers.event_handlers"
STAFF_ID = "staff-123"
SECRETS = {
    "CANVAS_FHIR_CLIENT_ID": "test-client-id",
    "CANVAS_FHIR_CLIENT_SECRET": "test-client-secret",
}
ENVIRONMENT = {"CUSTOMER_IDENTIFIER": "myinstance"}


def _build_handler(secrets: dict | None = None, environment: dict | None = None) -> NewStaffPasswordResetHandler:
    event = MagicMock()
    event.target.id = STAFF_ID
    return NewStaffPasswordResetHandler(
        event=event,
        secrets=SECRETS if secrets is None else secrets,
        environment=ENVIRONMENT if environment is None else environment,
    )


def _response(ok: bool, status: int = 200, body: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.ok = ok
    response.status_code = status
    response.json.return_value = body or {}
    return response


def test_activated_staff_sends_reset_email() -> None:
    """An activated staff member triggers a token fetch then the FHIR reset operation."""
    token_response = _response(ok=True, body={"access_token": "test-token"})
    reset_response = _response(ok=True)

    with patch(f"{HANDLER_MODULE}.Http") as mock_http_cls:
        mock_http_cls.return_value.post.side_effect = [token_response, reset_response]

        effects = _build_handler().compute()

    assert effects == []

    post_calls = mock_http_cls.return_value.post.call_args_list
    assert len(post_calls) == 2

    # Token call: EMR instance host, form-encoded client-credentials grant.
    token_args, token_kwargs = post_calls[0]
    assert token_args[0] == "https://myinstance.canvasmedical.com/auth/token/"
    assert token_kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert "grant_type=client_credentials" in token_kwargs["data"]
    assert "client_id=test-client-id" in token_kwargs["data"]
    assert "client_secret=test-client-secret" in token_kwargs["data"]

    # Reset call: fumage host, FHIR operation, Parameters body, bearer token.
    reset_args, reset_kwargs = post_calls[1]
    assert reset_args[0] == (
        "https://fumage-myinstance.canvasmedical.com"
        "/Practitioner/staff-123/$send-reset-password-email"
    )
    assert json.loads(reset_kwargs["data"]) == {"resourceType": "Parameters"}
    assert reset_kwargs["headers"]["Authorization"] == "Bearer test-token"
    assert reset_kwargs["headers"]["Content-Type"] == "application/json"


def test_missing_secrets_skips_without_http() -> None:
    """Missing FHIR credentials fail closed: no HTTP call, empty effects."""
    with patch(f"{HANDLER_MODULE}.Http") as mock_http_cls:
        effects = _build_handler(secrets={"CANVAS_FHIR_CLIENT_ID": "only-id"}).compute()

    assert effects == []
    mock_http_cls.assert_not_called()


def test_missing_customer_identifier_skips_without_http() -> None:
    """An unavailable CUSTOMER_IDENTIFIER fails closed: no HTTP call, empty effects."""
    with patch(f"{HANDLER_MODULE}.Http") as mock_http_cls:
        effects = _build_handler(environment={}).compute()

    assert effects == []
    mock_http_cls.assert_not_called()


def test_token_request_failure_skips_reset() -> None:
    """A non-2xx token response stops before the reset operation."""
    with patch(f"{HANDLER_MODULE}.Http") as mock_http_cls:
        mock_http_cls.return_value.post.return_value = _response(ok=False, status=401)

        effects = _build_handler().compute()

    assert effects == []
    # Only the token call happened; no reset call.
    assert mock_http_cls.return_value.post.call_count == 1


def test_token_response_without_access_token_skips_reset() -> None:
    """A 2xx token response lacking access_token stops before the reset operation."""
    with patch(f"{HANDLER_MODULE}.Http") as mock_http_cls:
        mock_http_cls.return_value.post.return_value = _response(ok=True, body={})

        effects = _build_handler().compute()

    assert effects == []
    assert mock_http_cls.return_value.post.call_count == 1


def test_reset_failure_still_returns_no_effects() -> None:
    """A failed reset operation is logged but the handler still returns empty effects."""
    token_response = _response(ok=True, body={"access_token": "test-token"})
    reset_response = _response(ok=False, status=500)

    with patch(f"{HANDLER_MODULE}.Http") as mock_http_cls:
        mock_http_cls.return_value.post.side_effect = [token_response, reset_response]

        effects = _build_handler().compute()

    assert effects == []
    assert mock_http_cls.return_value.post.call_count == 2


def test_handler_responds_to_staff_activated() -> None:
    """The handler is wired to the STAFF_ACTIVATED event."""
    assert NewStaffPasswordResetHandler.RESPONDS_TO == EventType.Name(EventType.STAFF_ACTIVATED)
