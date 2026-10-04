# To run the tests, use the command `pytest` in the terminal or uv run pytest.

from http import HTTPStatus
from unittest.mock import Mock, patch

import requests

from bp_cpt2.llm_anthropic import LlmAnthropic


def make_response(status_code: int, body: dict | None = None, text: str = "") -> Mock:
    """Build a mock requests response."""
    response = Mock()
    response.status_code = status_code
    response.json.return_value = body or {}
    response.text = text
    return response


@patch("bp_cpt2.llm_anthropic.requests.post")
def test_chat_success(mock_post: Mock) -> None:
    """
    Test that chat sends a Messages API request and returns only the text blocks.
    """
    mock_post.return_value = make_response(HTTPStatus.OK, {
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": "This is a test response."},
        ],
    })

    llm = LlmAnthropic(api_key="test-key")
    result = llm.chat(system_prompt="You are a helpful assistant.", user_prompt="Hello!")

    assert result == {"success": True, "content": "This is a test response.", "error": None, "status_code": HTTPStatus.OK}

    url = mock_post.call_args.args[0]
    headers = mock_post.call_args.kwargs["headers"]
    payload = mock_post.call_args.kwargs["json"]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert payload == {
        "model": "claude-opus-5",
        "max_tokens": 16000,
        "inference_geo": "us",
        "system": "You are a helpful assistant.",
        "messages": [{"role": "user", "content": "Hello!"}],
        "fallbacks": "default",
    }


@patch("bp_cpt2.llm_anthropic.requests.post")
def test_chat_with_model_override_omits_fallbacks(mock_post: Mock) -> None:
    """
    Test that a non-default model is sent without the default model's fallback settings.
    """
    mock_post.return_value = make_response(HTTPStatus.OK, {"stop_reason": "end_turn", "content": [{"type": "text", "text": "OK"}]})

    LlmAnthropic(api_key="test-key", model="claude-sonnet-5").chat(user_prompt="Hello!")

    headers = mock_post.call_args.kwargs["headers"]
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "claude-sonnet-5"
    assert "fallbacks" not in payload
    assert "anthropic-beta" not in headers
    assert "system" not in payload


@patch("bp_cpt2.llm_anthropic.requests.post")
def test_chat_refusal(mock_post: Mock) -> None:
    """
    Test that a declined request is reported as a failure.
    """
    mock_post.return_value = make_response(HTTPStatus.OK, {"stop_reason": "refusal", "content": []})

    result = LlmAnthropic(api_key="test-key").chat(user_prompt="Hello!")

    assert result["success"] is False
    assert result["content"] is None
    assert "declined" in result["error"]


@patch("bp_cpt2.llm_anthropic.requests.post")
def test_chat_api_error(mock_post: Mock) -> None:
    """
    Test that API errors are reported with the response text.
    """
    mock_post.return_value = make_response(HTTPStatus.UNAUTHORIZED, text="invalid x-api-key")

    result = LlmAnthropic(api_key="bad-key").chat(user_prompt="Hello!")

    assert result["success"] is False
    assert "invalid x-api-key" in result["error"]
    assert result["status_code"] == HTTPStatus.UNAUTHORIZED


@patch("bp_cpt2.llm_anthropic.requests.post")
def test_chat_request_exception(mock_post: Mock) -> None:
    """
    Test that network errors are reported as failures.
    """
    mock_post.side_effect = requests.ConnectionError("Network error")

    result = LlmAnthropic(api_key="test-key").chat(user_prompt="Hello!")

    assert result["success"] is False
    assert "Network error" in result["error"]
    assert result["status_code"] is None


@patch("bp_cpt2.llm_anthropic.requests.post")
def test_chat_with_json_retries_with_the_conversation(mock_post: Mock) -> None:
    """
    Test that a JSON retry resends the conversation with the system prompt kept top-level.
    """
    mock_post.side_effect = [
        make_response(HTTPStatus.OK, {"stop_reason": "end_turn", "content": [{"type": "text", "text": "no json here"}]}),
        make_response(HTTPStatus.OK, {"stop_reason": "end_turn", "content": [{"type": "text", "text": '```json\n{"ids": ["a"]}\n```'}]}),
    ]

    result = LlmAnthropic(api_key="test-key").chat_with_json(system_prompt="System", user_prompt="Classify")

    assert result == {"success": True, "data": {"ids": ["a"]}, "error": None}
    retry_payload = mock_post.call_args_list[1].kwargs["json"]
    assert retry_payload["system"] == "System"
    assert [message["role"] for message in retry_payload["messages"]] == ["user", "assistant", "user"]
    assert retry_payload["messages"][1]["content"] == "no json here"
