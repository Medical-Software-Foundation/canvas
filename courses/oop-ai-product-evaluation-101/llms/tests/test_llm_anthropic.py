"""
Tests for the LlmAnthropic class.

This test suite uses unittest.mock to mock HTTP requests and test the functionality
of the Anthropic Claude LLM wrapper without making actual API calls.
"""

from __future__ import annotations

import json
import unittest
from http import HTTPStatus
from unittest.mock import Mock, patch

import sys
from pathlib import Path

# Add parent directory to path to import the module
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_anthropic import LlmAnthropic


class TestLlmAnthropic(unittest.TestCase):
    """Test cases for LlmAnthropic class."""

    def setUp(self):
        """Set up test fixtures."""
        self.api_key = "test-anthropic-api-key"
        self.model = "claude-3-5-sonnet-20241022"
        self.llm = LlmAnthropic(api_key=self.api_key, model=self.model)

    def test_initialization(self):
        """Test that LlmAnthropic initializes with correct attributes."""
        self.assertEqual(self.llm.api_key, self.api_key)
        self.assertEqual(self.llm.model, self.model)
        self.assertEqual(self.llm.temperature, 0.0)
        self.assertEqual(self.llm.max_tokens, 8192)
        self.assertEqual(self.llm.messages, [])

    def test_initialization_default_model(self):
        """Test initialization with default model."""
        llm = LlmAnthropic(api_key="test-key")
        self.assertEqual(llm.model, "claude-3-5-sonnet-20241022")

    def test_reset_messages(self):
        """Test that reset_messages clears the messages list."""
        self.llm.add_user_message("test message")
        self.assertEqual(len(self.llm.messages), 1)
        self.llm.reset_messages()
        self.assertEqual(len(self.llm.messages), 0)

    def test_add_system_message(self):
        """Test adding a system message (converted to user role for Anthropic)."""
        content = "You are a helpful assistant."
        self.llm.add_system_message(content)
        self.assertEqual(len(self.llm.messages), 1)
        self.assertEqual(self.llm.messages[0]["role"], "user")
        self.assertEqual(self.llm.messages[0]["content"], content)

    def test_add_user_message(self):
        """Test adding a user message."""
        content = "Hello, how are you?"
        self.llm.add_user_message(content)
        self.assertEqual(len(self.llm.messages), 1)
        self.assertEqual(self.llm.messages[0]["role"], "user")
        self.assertEqual(self.llm.messages[0]["content"], content)

    def test_add_assistant_message(self):
        """Test adding an assistant message."""
        content = "I'm doing well, thank you!"
        self.llm.add_assistant_message(content)
        self.assertEqual(len(self.llm.messages), 1)
        self.assertEqual(self.llm.messages[0]["role"], "assistant")
        self.assertEqual(self.llm.messages[0]["content"], content)

    def test_message_sequence(self):
        """Test adding multiple messages in sequence."""
        self.llm.add_system_message("You are helpful.")
        self.llm.add_user_message("Hello")
        self.llm.add_assistant_message("Hi there!")
        self.llm.add_user_message("How are you?")

        self.assertEqual(len(self.llm.messages), 4)
        self.assertEqual(self.llm.messages[0]["role"], "user")  # system -> user
        self.assertEqual(self.llm.messages[1]["role"], "user")
        self.assertEqual(self.llm.messages[2]["role"], "assistant")
        self.assertEqual(self.llm.messages[3]["role"], "user")

    def test_format_messages_for_anthropic_single_message(self):
        """Test message formatting for Anthropic API with single message."""
        self.llm.add_user_message("Hello")
        formatted = self.llm._format_messages_for_anthropic()

        self.assertEqual(len(formatted), 1)
        self.assertEqual(formatted[0]["role"], "user")
        self.assertEqual(len(formatted[0]["content"]), 1)
        self.assertEqual(formatted[0]["content"][0]["type"], "text")
        self.assertEqual(formatted[0]["content"][0]["text"], "Hello")

    def test_format_messages_for_anthropic_merges_contiguous(self):
        """Test that contiguous messages of same role are merged."""
        self.llm.add_user_message("First message")
        self.llm.add_user_message("Second message")
        self.llm.add_assistant_message("Response")
        self.llm.add_user_message("Third message")

        formatted = self.llm._format_messages_for_anthropic()

        # Should have 3 groups: 2 user messages merged, 1 assistant, 1 user
        self.assertEqual(len(formatted), 3)
        self.assertEqual(formatted[0]["role"], "user")
        self.assertEqual(len(formatted[0]["content"]), 2)  # Merged
        self.assertEqual(formatted[1]["role"], "assistant")
        self.assertEqual(len(formatted[1]["content"]), 1)
        self.assertEqual(formatted[2]["role"], "user")
        self.assertEqual(len(formatted[2]["content"]), 1)

    def test_format_messages_for_anthropic_alternating_roles(self):
        """Test message formatting with alternating roles."""
        self.llm.add_user_message("User 1")
        self.llm.add_assistant_message("Assistant 1")
        self.llm.add_user_message("User 2")
        self.llm.add_assistant_message("Assistant 2")

        formatted = self.llm._format_messages_for_anthropic()

        self.assertEqual(len(formatted), 4)
        self.assertEqual(formatted[0]["role"], "user")
        self.assertEqual(formatted[1]["role"], "assistant")
        self.assertEqual(formatted[2]["role"], "user")
        self.assertEqual(formatted[3]["role"], "assistant")

    def test_format_messages_content_structure(self):
        """Test that formatted messages have correct content structure."""
        self.llm.add_user_message("Test message")
        formatted = self.llm._format_messages_for_anthropic()

        content_item = formatted[0]["content"][0]
        self.assertEqual(content_item["type"], "text")
        self.assertEqual(content_item["text"], "Test message")

    @patch("llm_anthropic.requests.post")
    def test_chat_success(self, mock_post):
        """Test successful chat completion."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "content": [{"text": "Hello! How can I assist you today?"}]
        }
        mock_post.return_value = mock_response

        result = self.llm.chat(
            system_prompt="You are helpful.", user_prompt="Hi there"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "Hello! How can I assist you today?")
        self.assertIsNone(result["error"])
        self.assertEqual(result["status_code"], HTTPStatus.OK)

        # Verify the API was called correctly
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("https://api.anthropic.com/v1/messages", call_args[0])

        # Verify headers
        headers = call_args[1]["headers"]
        self.assertEqual(headers["x-api-key"], self.api_key)
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["Content-Type"], "application/json")

    @patch("llm_anthropic.requests.post")
    def test_chat_api_error(self, mock_post):
        """Test chat completion with API error."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.BAD_REQUEST
        mock_response.text = "Invalid request format"
        mock_post.return_value = mock_response

        result = self.llm.chat(user_prompt="Test message")

        self.assertFalse(result["success"])
        self.assertIsNone(result["content"])
        self.assertIn("API request failed", result["error"])
        self.assertEqual(result["status_code"], HTTPStatus.BAD_REQUEST)

    @patch("llm_anthropic.requests.post")
    def test_chat_network_exception(self, mock_post):
        """Test chat completion with network exception."""
        mock_post.side_effect = Exception("Connection refused")

        result = self.llm.chat(user_prompt="Test message")

        self.assertFalse(result["success"])
        self.assertIsNone(result["content"])
        self.assertIn("Request exception", result["error"])
        self.assertIsNone(result["status_code"])

    @patch("llm_anthropic.requests.post")
    def test_chat_without_prompts(self, mock_post):
        """Test chat using pre-added messages without prompt parameters."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {"content": [{"text": "Response"}]}
        mock_post.return_value = mock_response

        self.llm.add_user_message("Pre-added message")
        result = self.llm.chat()

        self.assertTrue(result["success"])
        self.assertEqual(len(self.llm.messages), 1)

    @patch("llm_anthropic.requests.post")
    def test_chat_empty_response(self, mock_post):
        """Test handling of empty response from API causes error."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {"content": []}
        mock_post.return_value = mock_response

        result = self.llm.chat(user_prompt="Test")

        # Empty content list will cause IndexError
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])

    def test_extract_json_success(self):
        """Test successful JSON extraction from markdown."""
        content = """Here is the JSON:
```json
{
    "name": "test",
    "value": 42
}
```
"""
        result = self.llm._extract_json(content)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["name"], "test")
        self.assertEqual(result["data"]["value"], 42)
        self.assertIsNone(result["error"])

    def test_extract_json_with_array(self):
        """Test JSON extraction with array response."""
        content = """```json
[
    {"id": 1, "name": "first"},
    {"id": 2, "name": "second"}
]
```"""
        result = self.llm._extract_json(content)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["id"], 1)

    def test_extract_json_no_markdown_block(self):
        """Test JSON extraction when no markdown block exists."""
        content = '{"name": "test"}'
        result = self.llm._extract_json(content)
        self.assertFalse(result["success"])
        self.assertIsNone(result["data"])
        self.assertIn("No JSON markdown block found", result["error"])

    def test_extract_json_invalid_json(self):
        """Test JSON extraction with invalid JSON."""
        content = """```json
{
    "name": "test",
    "value": 42,
}
```"""
        result = self.llm._extract_json(content)
        self.assertFalse(result["success"])
        self.assertIsNone(result["data"])
        self.assertIn("Invalid JSON", result["error"])

    @patch("llm_anthropic.requests.post")
    def test_chat_with_json_success(self, mock_post):
        """Test successful chat_with_json."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {
            "content": [
                {"text": '```json\n{"result": "success", "count": 5}\n```'}
            ]
        }
        mock_post.return_value = mock_response

        result = self.llm.chat_with_json(
            system_prompt="Return JSON only.",
            user_prompt="Give me a count.",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["result"], "success")
        self.assertEqual(result["data"]["count"], 5)
        self.assertIsNone(result["error"])

    @patch("llm_anthropic.requests.post")
    def test_chat_with_json_retry_on_invalid_json(self, mock_post):
        """Test that chat_with_json retries when JSON is invalid."""
        mock_response_1 = Mock()
        mock_response_1.status_code = HTTPStatus.OK
        mock_response_1.json.return_value = {
            "content": [{"text": "Not a JSON response"}]
        }

        mock_response_2 = Mock()
        mock_response_2.status_code = HTTPStatus.OK
        mock_response_2.json.return_value = {
            "content": [{"text": '```json\n{"fixed": true}\n```'}]
        }

        mock_post.side_effect = [mock_response_1, mock_response_2]

        result = self.llm.chat_with_json(
            system_prompt="Return JSON.",
            user_prompt="Test",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["fixed"], True)
        self.assertEqual(mock_post.call_count, 2)

    @patch("llm_anthropic.requests.post")
    def test_chat_with_json_max_retries_exceeded(self, mock_post):
        """Test that chat_with_json fails after max retries."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {"content": [{"text": "Not JSON"}]}
        mock_post.return_value = mock_response

        result = self.llm.chat_with_json(
            system_prompt="Return JSON.",
            user_prompt="Test",
            max_retries=2,
        )

        self.assertFalse(result["success"])
        self.assertIsNone(result["data"])
        self.assertIn("Failed to get valid JSON after 2 attempts", result["error"])
        self.assertEqual(mock_post.call_count, 2)

    @patch("llm_anthropic.requests.post")
    def test_chat_with_json_api_error(self, mock_post):
        """Test chat_with_json with API error."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.UNAUTHORIZED
        mock_response.text = "Invalid API key"
        mock_post.return_value = mock_response

        result = self.llm.chat_with_json(
            system_prompt="Return JSON.",
            user_prompt="Test",
        )

        self.assertFalse(result["success"])
        self.assertIsNone(result["data"])
        self.assertIn("API request failed", result["error"])

    def test_chat_with_json_resets_messages(self):
        """Test that chat_with_json resets messages before starting."""
        self.llm.add_user_message("Old message")
        self.assertEqual(len(self.llm.messages), 1)

        with patch("llm_anthropic.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = HTTPStatus.OK
            mock_response.json.return_value = {
                "content": [{"text": '```json\n{"test": true}\n```'}]
            }
            mock_post.return_value = mock_response

            self.llm.chat_with_json(
                system_prompt="System",
                user_prompt="User",
            )

        # Should have system + user messages (both as 'user' role), not the old message
        self.assertEqual(len(self.llm.messages), 2)
        self.assertEqual(self.llm.messages[0]["role"], "user")
        self.assertEqual(self.llm.messages[0]["content"], "System")

    @patch("llm_anthropic.requests.post")
    def test_chat_verifies_payload_structure(self, mock_post):
        """Test that the request payload has the correct structure."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {"content": [{"text": "Response"}]}
        mock_post.return_value = mock_response

        self.llm.chat(user_prompt="Test")

        # Get the JSON payload that was sent
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        # Verify structure
        self.assertIn("model", payload)
        self.assertIn("temperature", payload)
        self.assertIn("max_tokens", payload)
        self.assertIn("messages", payload)
        self.assertEqual(payload["model"], self.model)
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["max_tokens"], 8192)
        self.assertIsInstance(payload["messages"], list)

    @patch("llm_anthropic.requests.post")
    def test_chat_rate_limit_error(self, mock_post):
        """Test handling of rate limit error."""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.TOO_MANY_REQUESTS
        mock_response.text = "Rate limit exceeded"
        mock_post.return_value = mock_response

        result = self.llm.chat(user_prompt="Test")

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], HTTPStatus.TOO_MANY_REQUESTS)
        self.assertIn("API request failed", result["error"])


if __name__ == "__main__":
    unittest.main()
