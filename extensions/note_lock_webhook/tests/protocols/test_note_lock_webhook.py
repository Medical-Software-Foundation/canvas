"""Tests for note_lock_webhook.protocols.note_lock_webhook.

Covers the signed-state filter, the payload shape, auth header handling, and
logging of a rejected webhook call.
"""

from unittest.mock import MagicMock, patch

import pytest

from note_lock_webhook.protocols.note_lock_webhook import NoteLockWebhookProtocol


def _make_protocol(event: MagicMock, secrets: dict) -> NoteLockWebhookProtocol:
    protocol = NoteLockWebhookProtocol.__new__(NoteLockWebhookProtocol)
    protocol.event = event
    protocol.secrets = secrets
    return protocol


@pytest.fixture
def mock_http():
    """Patch Http so no real request is made; yields the post() mock."""
    with patch(
        "note_lock_webhook.protocols.note_lock_webhook.Http"
    ) as http_class:
        post = http_class.return_value.post
        post.return_value = MagicMock(ok=True, status_code=200)
        yield post


class TestSignedNote:
    def test_posts_note_and_patient_id(self, mock_event, secrets, mock_http):
        effects = _make_protocol(mock_event, secrets).compute()

        assert effects == []
        mock_http.assert_called_once()
        _, kwargs = mock_http.call_args
        assert kwargs["json"] == {
            "state": "SGN",
            "note_id": "note-abc-123",
            "patient_id": "patient-xyz-789",
        }

    def test_posts_to_the_configured_url(self, mock_event, secrets, mock_http):
        _make_protocol(mock_event, secrets).compute()

        args, _ = mock_http.call_args
        assert args[0] == "https://example.test/hook"

    def test_sends_bearer_token_when_configured(
        self, mock_event, secrets, mock_http
    ):
        _make_protocol(mock_event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer s3cret"

    def test_omits_auth_header_when_token_is_unset(self, mock_event, mock_http):
        secrets = {"WEBHOOK_URL": "https://example.test/hook"}

        _make_protocol(mock_event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert "Authorization" not in kwargs["headers"]

    def test_logs_error_when_webhook_rejects(self, mock_event, secrets, mock_http):
        mock_http.return_value = MagicMock(ok=False, status_code=500)

        with patch(
            "note_lock_webhook.protocols.note_lock_webhook.log"
        ) as mock_log:
            _make_protocol(mock_event, secrets).compute()

        mock_log.error.assert_called_once()
        assert "note-abc-123" in mock_log.error.call_args[0][0]


class TestOtherStates:
    @pytest.mark.parametrize("state", ["NEW", "LKD", "ULK", "DEL", None])
    def test_does_not_post(self, mock_event, secrets, mock_http, state):
        mock_event.context["state"] = state

        effects = _make_protocol(mock_event, secrets).compute()

        assert effects == []
        mock_http.assert_not_called()

    def test_does_not_require_secrets_to_be_configured(
        self, mock_event, mock_http
    ):
        """A non-signed state must not raise even with no secrets set."""
        mock_event.context["state"] = "LKD"

        assert _make_protocol(mock_event, {}).compute() == []
        mock_http.assert_not_called()
