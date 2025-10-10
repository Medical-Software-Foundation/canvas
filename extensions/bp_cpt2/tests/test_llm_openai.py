# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import json
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from bp_cpt2.llm_openai import LlmOpenai


def test_initialization() -> None:
    """
    Test that LlmOpenai initializes correctly with required parameters.
    """
    api_key = "test-api-key"
    model = "gpt-4"

    llm = LlmOpenai(api_key=api_key, model=model)

    assert llm.api_key == api_key
    assert llm.model == model
    assert llm.temperature == 0.0
    assert llm.messages == []


def test_initialization_with_default_model() -> None:
    """
    Test that LlmOpenai uses default model when not specified.
    """
    api_key = "test-api-key"

    llm = LlmOpenai(api_key=api_key)

    assert llm.model == "gpt-4"


def test_add_system_message() -> None:
    """
    Test that system messages are added correctly.
    """
    llm = LlmOpenai(api_key="test-key")

    llm.add_system_message("You are a helpful assistant.")

    assert len(llm.messages) == 1
    assert llm.messages[0]["role"] == "system"
    assert llm.messages[0]["content"] == "You are a helpful assistant."


def test_add_system_message_replaces_existing() -> None:
    """
    Test that adding a new system message replaces the existing one.
    """
    llm = LlmOpenai(api_key="test-key")

    llm.add_system_message("First system message.")
    llm.add_system_message("Second system message.")

    assert len(llm.messages) == 1
    assert llm.messages[0]["role"] == "system"
    assert llm.messages[0]["content"] == "Second system message."


def test_add_user_message() -> None:
    """
    Test that user messages are appended to the conversation.
    """
    llm = LlmOpenai(api_key="test-key")

    llm.add_user_message("What is the weather?")
    llm.add_user_message("What is the temperature?")

    assert len(llm.messages) == 2
    assert llm.messages[0]["role"] == "user"
    assert llm.messages[0]["content"] == "What is the weather?"
    assert llm.messages[1]["role"] == "user"
    assert llm.messages[1]["content"] == "What is the temperature?"


def test_add_assistant_message() -> None:
    """
    Test that assistant messages are appended to the conversation.
    """
    llm = LlmOpenai(api_key="test-key")

    llm.add_assistant_message("The weather is sunny.")

    assert len(llm.messages) == 1
    assert llm.messages[0]["role"] == "assistant"
    assert llm.messages[0]["content"] == "The weather is sunny."


def test_reset_messages() -> None:
    """
    Test that reset_messages clears all messages.
    """
    llm = LlmOpenai(api_key="test-key")

    llm.add_system_message("System prompt")
    llm.add_user_message("User message")
    llm.add_assistant_message("Assistant response")

    assert len(llm.messages) == 3

    llm.reset_messages()

    assert len(llm.messages) == 0


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_success(mock_post: Mock) -> None:
    """
    Test that chat method successfully processes a valid API response.
    """
    llm = LlmOpenai(api_key="test-key", model="gpt-4")

    # Mock successful API response
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.OK
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "This is a test response."
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    result = llm.chat(
        system_prompt="You are a helpful assistant.",
        user_prompt="Hello!"
    )

    assert result["success"] is True
    assert result["content"] == "This is a test response."
    assert result["error"] is None
    assert result["status_code"] == HTTPStatus.OK

    # Verify the API was called correctly
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert "headers" in call_kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert call_kwargs["json"]["model"] == "gpt-4"
    assert call_kwargs["json"]["temperature"] == 0.0


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_api_error(mock_post: Mock) -> None:
    """
    Test that chat method handles API errors gracefully.
    """
    llm = LlmOpenai(api_key="test-key")

    # Mock error API response
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.UNAUTHORIZED
    mock_response.text = "Invalid API key"
    mock_post.return_value = mock_response

    result = llm.chat(user_prompt="Hello!")

    assert result["success"] is False
    assert result["content"] is None
    assert "Invalid API key" in result["error"]
    assert result["status_code"] == HTTPStatus.UNAUTHORIZED


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_request_exception(mock_post: Mock) -> None:
    """
    Test that chat method handles request exceptions.
    """
    llm = LlmOpenai(api_key="test-key")

    # Mock request exception
    mock_post.side_effect = Exception("Network error")

    result = llm.chat(user_prompt="Hello!")

    assert result["success"] is False
    assert result["content"] is None
    assert "Network error" in result["error"]
    assert result["status_code"] is None


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_without_prompts(mock_post: Mock) -> None:
    """
    Test that chat method can be called without additional prompts
    if messages were already added.
    """
    llm = LlmOpenai(api_key="test-key")
    llm.add_user_message("Pre-existing message")

    # Mock successful API response
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.OK
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Response"}}]
    }
    mock_post.return_value = mock_response

    result = llm.chat()

    assert result["success"] is True
    assert len(llm.messages) == 1


def test_extract_json_success() -> None:
    """
    Test that _extract_json successfully parses JSON from markdown.
    """
    llm = LlmOpenai(api_key="test-key")

    content = """
    Here is the response:
    ```json
    {"key": "value", "number": 42}
    ```
    """

    result = llm._extract_json(content)

    assert result["success"] is True
    assert result["data"] == {"key": "value", "number": 42}
    assert result["error"] is None


def test_extract_json_no_markdown_block() -> None:
    """
    Test that _extract_json handles missing markdown blocks.
    """
    llm = LlmOpenai(api_key="test-key")

    content = "Just plain text without JSON"

    result = llm._extract_json(content)

    assert result["success"] is False
    assert result["data"] is None
    assert "No JSON markdown block found" in result["error"]


def test_extract_json_invalid_json() -> None:
    """
    Test that _extract_json handles invalid JSON syntax.
    """
    llm = LlmOpenai(api_key="test-key")

    content = """
    ```json
    {invalid json, missing quotes}
    ```
    """

    result = llm._extract_json(content)

    assert result["success"] is False
    assert result["data"] is None
    assert "Invalid JSON" in result["error"]


def test_extract_json_array() -> None:
    """
    Test that _extract_json can parse JSON arrays.
    """
    llm = LlmOpenai(api_key="test-key")

    content = """
    ```json
    [{"id": 1}, {"id": 2}]
    ```
    """

    result = llm._extract_json(content)

    assert result["success"] is True
    assert result["data"] == [{"id": 1}, {"id": 2}]


def test_extract_json_case_insensitive() -> None:
    """
    Test that _extract_json handles different case variations of 'json' tag.
    """
    llm = LlmOpenai(api_key="test-key")

    content = """
    ```JSON
    {"test": "value"}
    ```
    """

    result = llm._extract_json(content)

    assert result["success"] is True
    assert result["data"] == {"test": "value"}


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_with_json_success(mock_post: Mock) -> None:
    """
    Test that chat_with_json successfully processes valid JSON response.
    """
    llm = LlmOpenai(api_key="test-key")

    # Mock successful API response with JSON
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.OK
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '```json\n{"result": "success"}\n```'
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    result = llm.chat_with_json(
        system_prompt="Extract information",
        user_prompt="Process this data"
    )

    assert result["success"] is True
    assert result["data"] == {"result": "success"}
    assert result["error"] is None


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_with_json_retry_on_invalid_json(mock_post: Mock) -> None:
    """
    Test that chat_with_json retries when initial response has invalid JSON.
    """
    llm = LlmOpenai(api_key="test-key")

    # First response: invalid JSON
    mock_response_1 = Mock()
    mock_response_1.status_code = HTTPStatus.OK
    mock_response_1.json.return_value = {
        "choices": [{"message": {"content": "No JSON here"}}]
    }

    # Second response: valid JSON
    mock_response_2 = Mock()
    mock_response_2.status_code = HTTPStatus.OK
    mock_response_2.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '```json\n{"fixed": true}\n```'
                }
            }
        ]
    }

    mock_post.side_effect = [mock_response_1, mock_response_2]

    result = llm.chat_with_json(
        system_prompt="Extract information",
        user_prompt="Process this data",
        max_retries=2
    )

    assert result["success"] is True
    assert result["data"] == {"fixed": True}
    assert mock_post.call_count == 2


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_with_json_max_retries_exceeded(mock_post: Mock) -> None:
    """
    Test that chat_with_json fails after exceeding max retries.
    """
    llm = LlmOpenai(api_key="test-key")

    # All responses return invalid JSON
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.OK
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "No JSON"}}]
    }
    mock_post.return_value = mock_response

    result = llm.chat_with_json(
        system_prompt="Extract information",
        user_prompt="Process this data",
        max_retries=2
    )

    assert result["success"] is False
    assert result["data"] is None
    assert "Failed to get valid JSON after 2 attempts" in result["error"]
    assert mock_post.call_count == 2


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_with_json_api_error(mock_post: Mock) -> None:
    """
    Test that chat_with_json handles API errors.
    """
    llm = LlmOpenai(api_key="test-key")

    # Mock API error
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    mock_response.text = "Server error"
    mock_post.return_value = mock_response

    result = llm.chat_with_json(
        system_prompt="Extract information",
        user_prompt="Process this data"
    )

    assert result["success"] is False
    assert result["data"] is None
    assert "Server error" in result["error"]


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_with_json_resets_messages(mock_post: Mock) -> None:
    """
    Test that chat_with_json resets messages before starting.
    """
    llm = LlmOpenai(api_key="test-key")

    # Add some pre-existing messages
    llm.add_user_message("Old message")
    assert len(llm.messages) == 1

    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.OK
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '```json\n{"test": true}\n```'
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    result = llm.chat_with_json(
        system_prompt="New system",
        user_prompt="New user prompt"
    )

    assert result["success"] is True
    # Messages should be: system, user (old message should be gone)
    assert len(llm.messages) == 2
    assert llm.messages[0]["role"] == "system"
    assert llm.messages[1]["role"] == "user"
    assert llm.messages[1]["content"] == "New user prompt"


@patch("bp_cpt2.llm_openai.requests.post")
def test_chat_preserves_message_history(mock_post: Mock) -> None:
    """
    Test that chat method preserves message history between calls.
    """
    llm = LlmOpenai(api_key="test-key")

    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = HTTPStatus.OK
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Response"}}]
    }
    mock_post.return_value = mock_response

    # First chat
    llm.chat(system_prompt="You are helpful", user_prompt="Question 1")
    assert len(llm.messages) == 2

    # Second chat (without reset)
    llm.chat(user_prompt="Question 2")
    assert len(llm.messages) == 3  # system, user1, user2

    # Add assistant response
    llm.add_assistant_message("Answer")
    assert len(llm.messages) == 4


def test_extract_json_with_whitespace() -> None:
    """
    Test that _extract_json handles various whitespace patterns.
    """
    llm = LlmOpenai(api_key="test-key")

    # Test with extra whitespace
    content = """

    ```json

    {
        "key": "value",
        "nested": {
            "data": 123
        }
    }

    ```

    """

    result = llm._extract_json(content)

    assert result["success"] is True
    assert result["data"]["key"] == "value"
    assert result["data"]["nested"]["data"] == 123
