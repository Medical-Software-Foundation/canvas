"""Tests for questionnaire_webhook.protocols.questionnaire_webhook.

Covers both branches (CCM and PA), the routing between them, payload shape,
secret handling, and the malformed-context cases that used to raise.
"""

from unittest.mock import MagicMock, patch

import pytest

from questionnaire_webhook.protocols.questionnaire_webhook import (
    QuestionnaireWebhookProtocol,
)

from tests.conftest import make_event


def _make_protocol(event: MagicMock, secrets: dict) -> QuestionnaireWebhookProtocol:
    protocol = QuestionnaireWebhookProtocol.__new__(QuestionnaireWebhookProtocol)
    protocol.event = event
    protocol.secrets = secrets
    return protocol


@pytest.fixture
def mock_http():
    """Patch Http so no real request is made; yields the post() mock."""
    with patch(
        "questionnaire_webhook.protocols.questionnaire_webhook.Http"
    ) as http_class:
        post = http_class.return_value.post
        post.return_value = MagicMock(ok=True, status_code=200)
        yield post


class TestCcmBranch:
    def test_posts_to_ccm_url(self, ccm_event, secrets, mock_http):
        assert _make_protocol(ccm_event, secrets).compute() == []

        args, kwargs = mock_http.call_args
        assert args[0] == "https://example.test/ccm"
        assert kwargs["json"] == {
            "contents": {"note_id": "note-abc-123", "patient_id": "patient-xyz-789"}
        }

    def test_ignores_wrong_answer(self, secrets, mock_http):
        event = make_event("RDP Encounter Type", **{"question-3331": 9999})

        assert _make_protocol(event, secrets).compute() == []
        mock_http.assert_not_called()

    def test_ignores_missing_answer(self, secrets, mock_http):
        event = make_event("RDP Encounter Type")

        assert _make_protocol(event, secrets).compute() == []
        mock_http.assert_not_called()


class TestPaBranch:
    def test_extracts_only_mapped_labels(self, pa_event, secrets, mock_http):
        _make_protocol(pa_event, secrets).compute()

        _, kwargs = mock_http.call_args
        questionnaire = kwargs["json"]["contents"]["questionnaire"]
        assert questionnaire == {
            "drug_name": "Atorvastatin",
            "quantity": "30",
            "strength": None,
        }

    def test_posts_to_pa_url_with_ids(self, pa_event, secrets, mock_http):
        _make_protocol(pa_event, secrets).compute()

        args, kwargs = mock_http.call_args
        contents = kwargs["json"]["contents"]
        assert args[0] == "https://example.test/pa"
        assert contents["note_id"] == "note-abc-123"
        assert contents["patient_id"] == "patient-xyz-789"
        assert contents["questionnaire_id"] == "questionnaire-target-1"

    def test_matches_any_pa_prefixed_title(self, secrets, mock_http):
        event = make_event("PA Anything At All")
        event.context["fields"]["questionnaire"]["extra"] = {"questions": []}

        _make_protocol(event, secrets).compute()

        mock_http.assert_called_once()

    def test_handles_missing_questions_list(self, secrets, mock_http):
        """`extra.questions` absent must not raise."""
        event = make_event("PA Medication Request")

        _make_protocol(event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert kwargs["json"]["contents"]["questionnaire"] == {}


class TestRouting:
    @pytest.mark.parametrize(
        "title", ["Some Other Questionnaire", "Depression Screen", ""]
    )
    def test_unmatched_titles_do_nothing(self, secrets, mock_http, title):
        assert _make_protocol(make_event(title), secrets).compute() == []
        mock_http.assert_not_called()

    def test_no_fields_does_nothing(self, secrets, mock_http):
        event = MagicMock()
        event.context = {"fields": None}

        assert _make_protocol(event, secrets).compute() == []
        mock_http.assert_not_called()

    def test_non_string_title_does_nothing(self, secrets, mock_http):
        assert _make_protocol(make_event(None), secrets).compute() == []
        mock_http.assert_not_called()


class TestSecrets:
    def test_sends_bearer_token(self, pa_event, secrets, mock_http):
        _make_protocol(pa_event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer s3cret"

    def test_omits_auth_header_when_unset(self, pa_event, mock_http):
        _make_protocol(pa_event, {"PA_WEBHOOK_URL": "https://example.test/pa"}).compute()

        _, kwargs = mock_http.call_args
        assert "Authorization" not in kwargs["headers"]

    def test_unset_url_logs_error_and_skips_post(self, pa_event, mock_http):
        with patch(
            "questionnaire_webhook.protocols.questionnaire_webhook.log"
        ) as mock_log:
            assert _make_protocol(pa_event, {}).compute() == []

        mock_http.assert_not_called()
        mock_log.error.assert_called_once()
        assert "PA_WEBHOOK_URL" in mock_log.error.call_args[0][0]

    def test_logs_error_when_webhook_rejects(self, pa_event, secrets, mock_http):
        mock_http.return_value = MagicMock(ok=False, status_code=500)

        with patch(
            "questionnaire_webhook.protocols.questionnaire_webhook.log"
        ) as mock_log:
            _make_protocol(pa_event, secrets).compute()

        mock_log.error.assert_called_once()


class TestMalformedContext:
    def test_missing_note_and_patient_do_not_raise(self, secrets, mock_http):
        """These used to raise AttributeError on `None.get(...)`."""
        event = make_event("PA Medication Request")
        event.context["note"] = None
        event.context["patient"] = None

        _make_protocol(event, secrets).compute()

        _, kwargs = mock_http.call_args
        assert kwargs["json"]["contents"]["note_id"] is None
        assert kwargs["json"]["contents"]["patient_id"] is None
