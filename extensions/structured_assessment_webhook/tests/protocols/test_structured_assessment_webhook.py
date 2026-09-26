"""Tests for structured_assessment_webhook.protocols.structured_assessment_webhook.

Covers the title and answer gates, payload shape, secret handling, and the
malformed-context cases that used to raise.
"""

from unittest.mock import MagicMock, patch

import pytest

from structured_assessment_webhook.protocols.structured_assessment_webhook import (
    StructuredAssessmentWebhookProtocol,
)

from tests.conftest import make_event


def _make_protocol(
    event: MagicMock, secrets: dict
) -> StructuredAssessmentWebhookProtocol:
    protocol = StructuredAssessmentWebhookProtocol.__new__(
        StructuredAssessmentWebhookProtocol
    )
    protocol.event = event
    protocol.secrets = secrets
    return protocol


@pytest.fixture
def mock_http():
    """Patch Http so no real request is made; yields the post() mock."""
    with patch(
        "structured_assessment_webhook.protocols.structured_assessment_webhook.Http"
    ) as http_class:
        post = http_class.return_value.post
        post.return_value = MagicMock(ok=True, status_code=200)
        yield post


class TestMatchingAssessment:
    def test_posts_note_and_patient_id(self, matching_event, secrets, mock_http):
        assert _make_protocol(matching_event, secrets).compute() == []

        args, kwargs = mock_http.call_args
        assert args[0] == "https://example.test/hook"
        assert kwargs["json"] == {
            "contents": {
                "note_id": "note-abc-123",
                "patient_id": "patient-xyz-789",
            }
        }

    def test_sends_bearer_token(self, matching_event, secrets, mock_http):
        _make_protocol(matching_event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer s3cret"

    def test_omits_auth_header_when_unset(self, matching_event, mock_http):
        secrets = {"WEBHOOK_URL": "https://example.test/hook"}

        _make_protocol(matching_event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert "Authorization" not in kwargs["headers"]

    def test_logs_error_when_webhook_rejects(self, matching_event, secrets, mock_http):
        mock_http.return_value = MagicMock(ok=False, status_code=500)

        with patch(
            "structured_assessment_webhook.protocols."
            "structured_assessment_webhook.log"
        ) as mock_log:
            _make_protocol(matching_event, secrets).compute()

        mock_log.error.assert_called_once()


class TestGates:
    @pytest.mark.parametrize(
        "title", ["Some Other Assessment", "health coaching abt", "", None]
    )
    def test_wrong_title_does_nothing(self, secrets, mock_http, title):
        event = make_event(title, **{"question-3973": 7550})

        assert _make_protocol(event, secrets).compute() == []
        mock_http.assert_not_called()

    @pytest.mark.parametrize("answer", [7551, 0, None, "7550"])
    def test_wrong_answer_does_nothing(self, secrets, mock_http, answer):
        event = make_event("Health Coaching ABT", **{"question-3973": answer})

        assert _make_protocol(event, secrets).compute() == []
        mock_http.assert_not_called()

    def test_missing_answer_does_nothing(self, secrets, mock_http):
        event = make_event("Health Coaching ABT")

        assert _make_protocol(event, secrets).compute() == []
        mock_http.assert_not_called()

    def test_no_fields_does_nothing(self, secrets, mock_http):
        event = MagicMock()
        event.context = {"fields": None}

        assert _make_protocol(event, secrets).compute() == []
        mock_http.assert_not_called()


class TestSecrets:
    def test_unset_url_logs_error_and_skips_post(self, matching_event, mock_http):
        with patch(
            "structured_assessment_webhook.protocols."
            "structured_assessment_webhook.log"
        ) as mock_log:
            assert _make_protocol(matching_event, {}).compute() == []

        mock_http.assert_not_called()
        mock_log.error.assert_called_once()
        assert "WEBHOOK_URL" in mock_log.error.call_args[0][0]


class TestMalformedContext:
    def test_missing_note_and_patient_do_not_raise(self, secrets, mock_http):
        """These used to raise AttributeError on `None.get(...)`."""
        event = make_event("Health Coaching ABT", **{"question-3973": 7550})
        event.context["note"] = None
        event.context["patient"] = None

        _make_protocol(event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert kwargs["json"]["contents"]["note_id"] is None
        assert kwargs["json"]["contents"]["patient_id"] is None

    def test_non_matching_assessment_returns_empty_list(self, secrets, mock_http):
        """Used to raise UnboundLocalError building the trailing LOG effect."""
        event = make_event("Unrelated Assessment")

        assert _make_protocol(event, secrets).compute() == []
