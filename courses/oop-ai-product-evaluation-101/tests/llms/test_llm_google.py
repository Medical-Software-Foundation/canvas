"""
Unit tests for the LlmGoogle class.

Tests all functionality without making actual API calls using mocks.
"""

import json
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from llms.llm_google import LlmGoogle


class TestLlmGoogleInit:
    """Test initialization of LlmGoogle."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        llm = LlmGoogle(api_key="test-key")
        assert llm.api_key == "test-key"
        assert llm.model == "models/gemini-1.5-flash"
        assert llm.temperature == 0.0
        assert llm.messages == []

    def test_init_with_custom_model(self):
        """Test initialization with custom model."""
        llm = LlmGoogle(api_key="test-key", model="models/gemini-1.5-pro")
        assert llm.model == "models/gemini-1.5-pro"


class TestLlmGoogleMessages:
    """Test message management methods."""

    def test_reset_messages(self):
        """Test resetting conversation messages."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_user_message("Hello")
        llm.add_assistant_message("Hi")
        assert len(llm.messages) == 2

        llm.reset_messages()
        assert llm.messages == []

    def test_add_system_message(self):
        """Test adding system message."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_system_message("You are a helpful assistant")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "user"  # Google treats system as user
        assert llm.messages[0]["content"] == "You are a helpful assistant"

    def test_add_user_message(self):
        """Test adding user message."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_user_message("Hello")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "user"
        assert llm.messages[0]["content"] == "Hello"

    def test_add_assistant_message(self):
        """Test adding assistant message."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_assistant_message("Hi there")
        assert len(llm.messages) == 1
        assert llm.messages[0]["role"] == "model"  # Google uses 'model' instead of 'assistant'
        assert llm.messages[0]["content"] == "Hi there"

    def test_multiple_messages(self):
        """Test adding multiple messages."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_system_message("System")
        llm.add_user_message("User 1")
        llm.add_assistant_message("Assistant 1")
        llm.add_user_message("User 2")
        assert len(llm.messages) == 4


class TestLlmGoogleFormatMessages:
    """Test message formatting for Google API."""

    def test_format_simple_messages(self):
        """Test formatting simple message sequence."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_user_message("Hello")
        llm.add_assistant_message("Hi")

        formatted = llm._format_messages_for_google()
        assert len(formatted) == 2
        assert formatted[0]["role"] == "user"
        assert formatted[0]["parts"][0]["text"] == "Hello"
        assert formatted[1]["role"] == "model"
        assert formatted[1]["parts"][0]["text"] == "Hi"

    def test_format_merges_contiguous_messages(self):
        """Test that contiguous messages of same role are merged."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_user_message("Message 1")
        llm.add_user_message("Message 2")
        llm.add_assistant_message("Response")

        formatted = llm._format_messages_for_google()
        assert len(formatted) == 2
        assert formatted[0]["role"] == "user"
        assert len(formatted[0]["parts"]) == 2
        assert formatted[0]["parts"][0]["text"] == "Message 1"
        assert formatted[0]["parts"][1]["text"] == "Message 2"

    def test_format_alternating_roles(self):
        """Test formatting alternating user and model messages."""
        llm = LlmGoogle(api_key="test-key")
        llm.add_user_message("Q1")
        llm.add_assistant_message("A1")
        llm.add_user_message("Q2")
        llm.add_assistant_message("A2")

        formatted = llm._format_messages_for_google()
        assert len(formatted) == 4
        assert formatted[0]["role"] == "user"
        assert formatted[1]["role"] == "model"
        assert formatted[2]["role"] == "user"
        assert formatted[3]["role"] == "model"


class TestLlmGoogleChat:
    """Test chat method."""

    @patch('llms.llm_google.requests.post')
    def test_chat_success(self, mock_post):
        """Test successful chat completion."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Hello! How can I help you?"}]
                }
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is True
        assert result["content"] == "Hello! How can I help you?"
        assert result["error"] is None
        assert result["status_code"] == HTTPStatus.OK

    @patch('llms.llm_google.requests.post')
    def test_chat_with_system_and_user_prompt(self, mock_post):
        """Test chat with both system and user prompts."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "Response"}]}
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat(
            system_prompt="You are a helpful assistant",
            user_prompt="Hello"
        )

        assert result["success"] is True
        assert len(llm.messages) == 2

    @patch('llms.llm_google.requests.post')
    def test_chat_verifies_api_url(self, mock_post):
        """Test that chat constructs correct API URL."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Response"}]}}]
        }
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-api-key", model="models/gemini-pro")
        llm.chat(user_prompt="Test")

        # Verify API call URL includes model and key
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "models/gemini-pro" in call_url
        assert "key=test-api-key" in call_url

    @patch('llms.llm_google.requests.post')
    def test_chat_api_error(self, mock_post):
        """Test chat with API error response."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.BAD_REQUEST
        mock_response.text = "Invalid request"
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is False
        assert result["content"] is None
        assert "API request failed" in result["error"]
        assert result["status_code"] == HTTPStatus.BAD_REQUEST

    @patch('llms.llm_google.requests.post')
    def test_chat_request_exception(self, mock_post):
        """Test chat with request exception."""
        mock_post.side_effect = Exception("Network timeout")

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is False
        assert result["content"] is None
        assert "Request exception" in result["error"]
        assert result["status_code"] is None

    @patch('llms.llm_google.requests.post')
    def test_chat_empty_response(self, mock_post):
        """Test chat with empty content returns empty string."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": ""}]}
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat(user_prompt="Hi")

        assert result["success"] is True
        assert result["content"] == ""


class TestLlmGoogleExtractJson:
    """Test JSON extraction from responses."""

    def test_extract_json_success(self):
        """Test successful JSON extraction."""
        llm = LlmGoogle(api_key="test-key")
        content = """
Here's the data:
```json
{"name": "test", "value": 99}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"] == {"name": "test", "value": 99}
        assert result["error"] is None

    def test_extract_json_no_code_block(self):
        """Test JSON extraction when no code block present."""
        llm = LlmGoogle(api_key="test-key")
        content = '{"name": "test"}'
        result = llm._extract_json(content)
        assert result["success"] is False
        assert "No JSON markdown block found" in result["error"]

    def test_extract_json_invalid_json(self):
        """Test JSON extraction with invalid JSON."""
        llm = LlmGoogle(api_key="test-key")
        content = """
```json
{not valid json}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_extract_json_array(self):
        """Test extracting JSON array."""
        llm = LlmGoogle(api_key="test-key")
        content = """
```json
["apple", "banana", "cherry"]
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"] == ["apple", "banana", "cherry"]

    def test_extract_json_nested_structure(self):
        """Test extracting nested JSON structure."""
        llm = LlmGoogle(api_key="test-key")
        content = """
```json
{
  "user": {
    "name": "Alice",
    "scores": [95, 87, 92]
  }
}
```
"""
        result = llm._extract_json(content)
        assert result["success"] is True
        assert result["data"]["user"]["name"] == "Alice"
        assert len(result["data"]["user"]["scores"]) == 3


class TestLlmGoogleChatWithJson:
    """Test chat_with_json method."""

    @patch('llms.llm_google.requests.post')
    def test_chat_with_json_success(self, mock_post):
        """Test successful JSON chat."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": '```json\n{"result": "success"}\n```'}]
                }
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is True
        assert result["data"] == {"result": "success"}
        assert result["error"] is None

    @patch('llms.llm_google.requests.post')
    def test_chat_with_json_resets_messages(self, mock_post):
        """Test that chat_with_json resets messages."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": '```json\n{"ok": true}\n```'}]}
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        llm.add_user_message("Old message")

        result = llm.chat_with_json(
            system_prompt="System",
            user_prompt="User"
        )

        assert result["success"] is True

    @patch('llms.llm_google.requests.post')
    def test_chat_with_json_retry_on_invalid_json(self, mock_post):
        """Test that invalid JSON triggers retry."""
        # First response: invalid JSON
        mock_response1 = Mock()
        mock_response1.status_code = HTTPStatus.OK
        mock_response1.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "```json\n{broken}\n```"}]}
            }]
        }

        # Second response: valid JSON
        mock_response2 = Mock()
        mock_response2.status_code = HTTPStatus.OK
        mock_response2.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": '```json\n{"fixed": true}\n```'}]}
            }]
        }

        mock_post.side_effect = [mock_response1, mock_response2]

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is True
        assert result["data"] == {"fixed": True}
        assert mock_post.call_count == 2

    @patch('llms.llm_google.requests.post')
    def test_chat_with_json_max_retries_exceeded(self, mock_post):
        """Test failure after max retries."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "No JSON here"}]}
            }]
        }
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
            max_retries=3
        )

        assert result["success"] is False
        assert "Failed to get valid JSON after 3 attempts" in result["error"]
        assert mock_post.call_count == 3

    @patch('llms.llm_google.requests.post')
    def test_chat_with_json_api_error(self, mock_post):
        """Test JSON chat with API error."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.FORBIDDEN
        mock_response.text = "Access denied"
        mock_post.return_value = mock_response

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data"
        )

        assert result["success"] is False
        assert "API request failed" in result["error"]

    @patch('llms.llm_google.requests.post')
    def test_chat_with_json_adds_error_context(self, mock_post):
        """Test that retry includes error context."""
        # First response: no JSON block
        mock_response1 = Mock()
        mock_response1.status_code = HTTPStatus.OK
        mock_response1.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "Just plain text"}]}
            }]
        }

        # Second response: valid JSON
        mock_response2 = Mock()
        mock_response2.status_code = HTTPStatus.OK
        mock_response2.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": '```json\n{"ok": true}\n```'}]}
            }]
        }

        mock_post.side_effect = [mock_response1, mock_response2]

        llm = LlmGoogle(api_key="test-key")
        result = llm.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Data please"
        )

        assert result["success"] is True
        # Verify that the second call included error feedback
        second_call_payload = mock_post.call_args_list[1][1]["json"]
        messages = second_call_payload["contents"]
        # Should have assistant message and error feedback
        assert any("error" in str(msg).lower() for msg in messages)
