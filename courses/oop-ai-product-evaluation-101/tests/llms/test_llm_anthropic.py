"""
Unit tests for the LlmAnthropic class.

Tests all functionality without making actual API calls using mocks.
"""

import json
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from llms.llm_anthropic import LlmAnthropic


class TestLlmAnthropicInit:
    """Test initialization of LlmAnthropic."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        llm = LlmAnthropic(api_key="test-key")
        assert llm.api_key == "test-key"
        assert llm.model == "claude-3-5-sonnet-20241022"
        assert llm.temperature == 0.0
        assert llm.max_tokens == 8192
        assert llm.messages == []

    def test_init_with_custom_model(self):
        """Test initialization with custom model."""
        llm = LlmAnthropic(api_key="test-key", model="claude-3-opus-20240229")
        assert llm.model == "claude-3-opus-20240229"


class TestLlmAnthropicMessages:
    """Test message management methods."""

    def test_reset_messages(self):
        """Test resetting conversation messages."""
        llm = LlmAnthropic(api_key="test-key")
        llm.add_user_message("Hello")
        llm.add_assistant_message("Hi")
        assert len(llm.messages) == 2

        llm.reset_messages()
        assert llm.messages == []

    def test_add_system_message(self):
        """Test adding system message."""
        llm = LlmAnthropic(api_key="test-key")
        llm.add_system_message("You are a helpful assistant")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "user"  # Anthropic treats system as user
        assert llm.messages[0]["content"] == "You are a helpful assistant"

    def test_add_user_message(self):
        """Test adding user message."""
        llm = LlmAnthropic(api_key="test-key")
        llm.add_user_message("Hello")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "user"
        assert llm.messages[0]["content"] == "Hello"

    def test_add_assistant_message(self):
        """Test adding assistant message."""
        llm = LlmAnthropic(api_key="test-key")
        llm.add_assistant_message("Hi there")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "assistant"
        assert llm.messages[0]["content"] == "Hi there"

    def test_multiple_messages(self):
        """Test adding multiple messages."""
        llm = LlmAnthropic(api_key="test-key")
        llm.add_system_message("System")
        llm.add_user_message("User 1")
        llm.add_assistant_message("Assistant 1")
        llm.add_user_message("User 2")
        assert len(llm.messages) == 4


class TestLlmAnthropicFormatMessages:
    """Test message formatting for Anthropic API."""

    def test_format_simple_messages(self):
        """Test formatting simple message sequence."""
        llm = LlmAnthropic(api_key="test-key")
        llm.add_user_message("Hello")
        llm.add_assistant_message("Hi")

        formatted = llm._format_messages_for_anthropic()
        assert len(formatted) == 2
        assert formatted[0]["role"] == "user"
        assert formatted[0]["content"][0]["text"] == "Hello"
        assert formatted[1]["role"] == "assistant"
        assert formatted[1]["content"][0]["text"] == "Hi"

    def test_format_merges_contiguous_messages(self):
        """Test that contiguous messages of same role are merged."""
        llm = LlmAnthropic(api_key="test-key")
        llm.add_user_message("Message 1")
        llm.add_user_message("Message 2")
        llm.add_assistant_message("Response")

        formatted = llm._format_messages_for_anthropic()
        assert len(formatted) == 2
        assert formatted[0]["role"] == "user"
        assert len(formatted[0]["content"]) == 2
        assert formatted[0]["content"][0]["text"] == "Message 1"
        assert formatted[0]["content"][1]["text"] == "Message 2"


class TestLlmAnthropicChat:
    """Test chat method."""

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_success(self, mock_post):
        """Test successful chat completion."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "content": [{"text": "Hello! How can I help you?"}]
        }
        mock_post.return_value = mock_response

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is True
        assert result["content"] == "Hello! How can I help you?"
        assert result["error"] is None
        assert result["status_code"] == HTTPStatus.OK

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_with_system_and_user_prompt(self, mock_post):
        """Test chat with both system and user prompts."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "content": [{"text": "Response"}]
        }
        mock_post.return_value = mock_response

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat(
            system_prompt="You are a helpful assistant",
            user_prompt="Hello"
        )

        assert result["success"] is True
        assert len(llm.messages) == 2

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_api_error(self, mock_post):
        """Test chat with API error response."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.BAD_REQUEST
        mock_response.text = "Invalid request"
        mock_post.return_value = mock_response

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is False
        assert result["content"] is None
        assert "API request failed" in result["error"]
        assert result["status_code"] == HTTPStatus.BAD_REQUEST

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_request_exception(self, mock_post):
        """Test chat with request exception."""
        mock_post.side_effect = Exception("Network error")

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is False
        assert result["content"] is None
        assert "Request exception" in result["error"]
        assert result["status_code"] is None


class TestLlmAnthropicExtractJson:
    """Test JSON extraction from responses."""

    def test_extract_json_success(self):
        """Test successful JSON extraction."""
        llm = LlmAnthropic(api_key="test-key")
        content = """
Here's the JSON:
```json
{"name": "test", "value": 123}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"] == {"name": "test", "value": 123}
        assert result["error"] is None

    def test_extract_json_no_code_block(self):
        """Test JSON extraction when no code block present."""
        llm = LlmAnthropic(api_key="test-key")
        content = '{"name": "test"}'
        result = llm._extract_json(content)
        assert result["success"] is False
        assert "No JSON markdown block found" in result["error"]

    def test_extract_json_invalid_json(self):
        """Test JSON extraction with invalid JSON."""
        llm = LlmAnthropic(api_key="test-key")
        content = """
```json
{invalid json}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_extract_json_array(self):
        """Test extracting JSON array."""
        llm = LlmAnthropic(api_key="test-key")
        content = """
```json
[1, 2, 3]
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"] == [1, 2, 3]


class TestLlmAnthropicChatWithJson:
    """Test chat_with_json method."""

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_with_json_success(self, mock_post):
        """Test successful JSON chat."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "content": [{
                "text": '```json\n{"result": "success"}\n```'
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is True
        assert result["data"] == {"result": "success"}
        assert result["error"] is None

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_with_json_retry_on_invalid_json(self, mock_post):
        """Test that invalid JSON triggers retry."""
        # First response: invalid JSON
        mock_response1 = Mock()
        mock_response1.status_code = HTTPStatus.OK
        mock_response1.json.return_value = {
            "content": [{"text": "```json\n{invalid}\n```"}]
        }

        # Second response: valid JSON
        mock_response2 = Mock()
        mock_response2.status_code = HTTPStatus.OK
        mock_response2.json.return_value = {
            "content": [{"text": '```json\n{"fixed": true}\n```'}]
        }

        mock_post.side_effect = [mock_response1, mock_response2]

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is True
        assert result["data"] == {"fixed": True}
        assert mock_post.call_count == 2

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_with_json_max_retries_exceeded(self, mock_post):
        """Test failure after max retries."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "content": [{"text": "No JSON here"}]
        }
        mock_post.return_value = mock_response

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
            max_retries=2
        )

        assert result["success"] is False
        assert "Failed to get valid JSON after 2 attempts" in result["error"]

    @patch('llms.llm_anthropic.requests.post')
    def test_chat_with_json_api_error(self, mock_post):
        """Test JSON chat with API error."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        mock_response.text = "Server error"
        mock_post.return_value = mock_response

        llm = LlmAnthropic(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is False
        assert "API request failed" in result["error"]
