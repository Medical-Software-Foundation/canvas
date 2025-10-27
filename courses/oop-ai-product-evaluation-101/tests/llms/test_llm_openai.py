"""
Unit tests for the LlmOpenai class.

Tests all functionality without making actual API calls using mocks.
"""

import json
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from llms.llm_openai import LlmOpenai


class TestLlmOpenaiInit:
    """Test initialization of LlmOpenai."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        llm = LlmOpenai(api_key="test-key")
        assert llm.api_key == "test-key"
        assert llm.model == "gpt-4"
        assert llm.temperature == 0.0
        assert llm.messages == []

    def test_init_with_custom_model(self):
        """Test initialization with custom model."""
        llm = LlmOpenai(api_key="test-key", model="gpt-4-turbo")
        assert llm.model == "gpt-4-turbo"


class TestLlmOpenaiMessages:
    """Test message management methods."""

    def test_reset_messages(self):
        """Test resetting conversation messages."""
        llm = LlmOpenai(api_key="test-key")
        llm.add_user_message("Hello")
        llm.add_assistant_message("Hi")
        assert len(llm.messages) == 2

        llm.reset_messages()
        assert llm.messages == []

    def test_add_system_message(self):
        """Test adding system message."""
        llm = LlmOpenai(api_key="test-key")
        llm.add_system_message("You are a helpful assistant")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "system"
        assert llm.messages[0]["content"] == "You are a helpful assistant"

    def test_add_system_message_replaces_existing(self):
        """Test that adding system message replaces existing one."""
        llm = LlmOpenai(api_key="test-key")
        llm.add_system_message("First system")
        llm.add_user_message("User message")
        llm.add_system_message("Second system")

        assert len(llm.messages) == 2
        assert llm.messages[0]["role"] == "system"
        assert llm.messages[0]["content"] == "Second system"

    def test_add_user_message(self):
        """Test adding user message."""
        llm = LlmOpenai(api_key="test-key")
        llm.add_user_message("Hello")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "user"
        assert llm.messages[0]["content"] == "Hello"

    def test_add_assistant_message(self):
        """Test adding assistant message."""
        llm = LlmOpenai(api_key="test-key")
        llm.add_assistant_message("Hi there")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "assistant"
        assert llm.messages[0]["content"] == "Hi there"

    def test_system_message_at_start(self):
        """Test that system message is inserted at start."""
        llm = LlmOpenai(api_key="test-key")
        llm.add_user_message("User first")
        llm.add_system_message("System added later")

        assert llm.messages[0]["role"] == "system"
        assert llm.messages[1]["role"] == "user"


class TestLlmOpenaiChat:
    """Test chat method."""

    @patch('llms.llm_openai.requests.post')
    def test_chat_success(self, mock_post):
        """Test successful chat completion."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Hello! How can I help you?"
                }
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is True
        assert result["content"] == "Hello! How can I help you?"
        assert result["error"] is None
        assert result["status_code"] == HTTPStatus.OK

    @patch('llms.llm_openai.requests.post')
    def test_chat_with_system_and_user_prompt(self, mock_post):
        """Test chat with both system and user prompts."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Response"}}]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat(
            system_prompt="You are a helpful assistant",
            user_prompt="Hello"
        )

        assert result["success"] is True
        assert len(llm.messages) == 2
        assert llm.messages[0]["role"] == "system"
        assert llm.messages[1]["role"] == "user"

    @patch('llms.llm_openai.requests.post')
    def test_chat_verifies_api_call(self, mock_post):
        """Test that chat makes correct API call."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Response"}}]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-api-key")
        llm.chat(user_prompt="Test")

        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://us.api.openai.com/v1/chat/completions"
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-api-key"

    @patch('llms.llm_openai.requests.post')
    def test_chat_api_error(self, mock_post):
        """Test chat with API error response."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.UNAUTHORIZED
        mock_response.text = "Invalid API key"
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is False
        assert result["content"] is None
        assert "API request failed" in result["error"]
        assert result["status_code"] == HTTPStatus.UNAUTHORIZED

    @patch('llms.llm_openai.requests.post')
    def test_chat_request_exception(self, mock_post):
        """Test chat with request exception."""
        mock_post.side_effect = Exception("Network error")

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is False
        assert result["content"] is None
        assert "Request exception" in result["error"]
        assert result["status_code"] is None

    @patch('llms.llm_openai.requests.post')
    def test_chat_empty_response(self, mock_post):
        """Test chat with empty choices returns empty string."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{"message": {"content": ""}}]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is True
        assert result["content"] == ""


class TestLlmOpenaiExtractJson:
    """Test JSON extraction from responses."""

    def test_extract_json_success(self):
        """Test successful JSON extraction."""
        llm = LlmOpenai(api_key="test-key")
        content = """
Here's the data:
```json
{"name": "test", "value": 42}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"] == {"name": "test", "value": 42}
        assert result["error"] is None

    def test_extract_json_case_insensitive(self):
        """Test JSON extraction is case insensitive."""
        llm = LlmOpenai(api_key="test-key")
        content = """
```JSON
{"result": "ok"}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"] == {"result": "ok"}

    def test_extract_json_no_code_block(self):
        """Test JSON extraction when no code block present."""
        llm = LlmOpenai(api_key="test-key")
        content = '{"name": "test"}'
        result = llm._extract_json(content)
        assert result["success"] is False
        assert "No JSON markdown block found" in result["error"]

    def test_extract_json_invalid_json(self):
        """Test JSON extraction with invalid JSON."""
        llm = LlmOpenai(api_key="test-key")
        content = """
```json
{invalid: "json"}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_extract_json_complex_object(self):
        """Test extracting complex JSON object."""
        llm = LlmOpenai(api_key="test-key")
        content = """
```json
{
  "name": "test",
  "nested": {
    "value": 123,
    "array": [1, 2, 3]
  }
}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"]["nested"]["array"] == [1, 2, 3]


class TestLlmOpenaiChatWithJson:
    """Test chat_with_json method."""

    @patch('llms.llm_openai.requests.post')
    def test_chat_with_json_success(self, mock_post):
        """Test successful JSON chat."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '```json\n{"result": "success"}\n```'
                }
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is True
        assert result["data"] == {"result": "success"}
        assert result["error"] is None

    @patch('llms.llm_openai.requests.post')
    def test_chat_with_json_resets_messages(self, mock_post):
        """Test that chat_with_json resets messages before starting."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{
                "message": {"content": '```json\n{"ok": true}\n```'}
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        llm.add_user_message("Old message")

        result = llm.chat_with_json(
            system_prompt="System",
            user_prompt="User"
        )

        # Should only have system and user messages, not the old one
        assert result["success"] is True

    @patch('llms.llm_openai.requests.post')
    def test_chat_with_json_retry_on_invalid_json(self, mock_post):
        """Test that invalid JSON triggers retry."""
        # First response: invalid JSON
        mock_response1 = Mock()
        mock_response1.status_code = HTTPStatus.OK
        mock_response1.json.return_value = {
            "choices": [{"message": {"content": "```json\n{bad json}\n```"}}]
        }

        # Second response: valid JSON
        mock_response2 = Mock()
        mock_response2.status_code = HTTPStatus.OK
        mock_response2.json.return_value = {
            "choices": [{"message": {"content": '```json\n{"fixed": true}\n```'}}]
        }

        mock_post.side_effect = [mock_response1, mock_response2]

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is True
        assert result["data"] == {"fixed": True}
        assert mock_post.call_count == 2

    @patch('llms.llm_openai.requests.post')
    def test_chat_with_json_max_retries_exceeded(self, mock_post):
        """Test failure after max retries."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "No JSON here"}}]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
            max_retries=2
        )

        assert result["success"] is False
        assert "Failed to get valid JSON after 2 attempts" in result["error"]

    @patch('llms.llm_openai.requests.post')
    def test_chat_with_json_api_error(self, mock_post):
        """Test JSON chat with API error."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        mock_response.text = "Service unavailable"
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is False
        assert "API request failed" in result["error"]

    @patch('llms.llm_openai.requests.post')
    def test_chat_with_json_custom_retries(self, mock_post):
        """Test custom retry count."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Invalid response"}}]
        }
        mock_post.return_value = mock_response

        llm = LlmOpenai(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="System",
            user_prompt="User",
            max_retries=5
        )

        assert result["success"] is False
        assert "5 attempts" in result["error"]
        assert mock_post.call_count == 5
