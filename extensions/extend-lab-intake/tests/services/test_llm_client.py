"""Tests for LLM client."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from extend_lab_intake.services.llm_client import LLMClient


class TestLLMClient:
    """Tests for LLMClient."""

    @pytest.fixture
    def client(self) -> LLMClient:
        """Create an LLMClient instance."""
        return LLMClient(api_key="test-api-key")

    def test_initialization(self, client: LLMClient) -> None:
        """Test client initialization."""
        assert client.api_key == "test-api-key"
        assert client.model == "claude-sonnet-4-5-20250929"
        assert client.temperature == 0.0
        assert client.max_tokens == 4096
        assert client.messages == []

    def test_initialization_custom_model(self) -> None:
        """Test client initialization with custom model."""
        client = LLMClient(api_key="test-key", model="claude-3-opus")
        assert client.model == "claude-3-opus"

    def test_reset_messages(self, client: LLMClient) -> None:
        """Test resetting messages."""
        client.messages = [{"role": "user", "content": "test"}]
        client.reset_messages()
        assert client.messages == []

    def test_add_system_message(self, client: LLMClient) -> None:
        """Test adding system message."""
        client.add_system_message("You are a helpful assistant")
        assert len(client.messages) == 1
        assert client.messages[0]["role"] == "user"
        assert client.messages[0]["content"] == "You are a helpful assistant"

    def test_add_user_message(self, client: LLMClient) -> None:
        """Test adding user message."""
        client.add_user_message("Hello")
        assert len(client.messages) == 1
        assert client.messages[0]["role"] == "user"
        assert client.messages[0]["content"] == "Hello"

    def test_add_assistant_message(self, client: LLMClient) -> None:
        """Test adding assistant message."""
        client.add_assistant_message("Hi there!")
        assert len(client.messages) == 1
        assert client.messages[0]["role"] == "assistant"
        assert client.messages[0]["content"] == "Hi there!"

    def test_format_messages_for_anthropic(self, client: LLMClient) -> None:
        """Test message formatting for Anthropic API."""
        client.add_user_message("Hello")
        client.add_assistant_message("Hi!")
        client.add_user_message("How are you?")

        formatted = client._format_messages_for_anthropic()

        assert len(formatted) == 3
        assert formatted[0]["role"] == "user"
        assert formatted[0]["content"][0]["type"] == "text"
        assert formatted[0]["content"][0]["text"] == "Hello"

    def test_format_messages_merges_contiguous(self, client: LLMClient) -> None:
        """Test that contiguous messages of same role are merged."""
        client.add_user_message("First")
        client.add_user_message("Second")

        formatted = client._format_messages_for_anthropic()

        assert len(formatted) == 1
        assert len(formatted[0]["content"]) == 2

    @patch("requests.post")
    def test_chat_success(self, mock_post: MagicMock, client: LLMClient) -> None:
        """Test successful chat request."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "content": [{"text": "Response from Claude"}],
            },
        )

        result = client.chat(user_prompt="Hello")

        assert result["success"] is True
        assert result["content"] == "Response from Claude"
        assert result["error"] is None

    @patch("requests.post")
    def test_chat_with_system_prompt(
        self, mock_post: MagicMock, client: LLMClient
    ) -> None:
        """Test chat with system prompt."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {"content": [{"text": "Response"}]},
        )

        result = client.chat(
            system_prompt="You are helpful",
            user_prompt="Hello",
        )

        assert result["success"] is True
        assert len(client.messages) == 2

    @patch("requests.post")
    def test_chat_api_error(self, mock_post: MagicMock, client: LLMClient) -> None:
        """Test chat with API error."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.UNAUTHORIZED,
            text="Invalid API key",
        )

        result = client.chat(user_prompt="Hello")

        assert result["success"] is False
        assert "Invalid API key" in result["error"]
        assert result["status_code"] == HTTPStatus.UNAUTHORIZED

    @patch("requests.post")
    def test_chat_exception(self, mock_post: MagicMock, client: LLMClient) -> None:
        """Test chat with request exception."""
        mock_post.side_effect = Exception("Network error")

        result = client.chat(user_prompt="Hello")

        assert result["success"] is False
        assert "Network error" in result["error"]
        assert result["status_code"] is None

    @patch("requests.post")
    def test_chat_with_json_success(
        self, mock_post: MagicMock, client: LLMClient
    ) -> None:
        """Test chat_with_json successful JSON parsing."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "content": [{"text": '```json\n{"key": "value"}\n```'}],
            },
        )

        result = client.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
        )

        assert result["success"] is True
        assert result["data"] == {"key": "value"}
        assert result["error"] is None

    @patch("requests.post")
    def test_chat_with_json_raw_json(
        self, mock_post: MagicMock, client: LLMClient
    ) -> None:
        """Test chat_with_json with raw JSON (no code block)."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "content": [{"text": '{"key": "value"}'}],
            },
        )

        result = client.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
        )

        assert result["success"] is True
        assert result["data"] == {"key": "value"}

    @patch("requests.post")
    def test_chat_with_json_api_error(
        self, mock_post: MagicMock, client: LLMClient
    ) -> None:
        """Test chat_with_json with API error."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            text="Server error",
        )

        result = client.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
        )

        assert result["success"] is False
        assert "Server error" in result["error"]

    @patch("requests.post")
    def test_chat_with_json_retry(
        self, mock_post: MagicMock, client: LLMClient
    ) -> None:
        """Test chat_with_json retry on invalid JSON."""
        mock_post.side_effect = [
            MagicMock(
                status_code=HTTPStatus.OK,
                json=lambda: {"content": [{"text": "Not valid JSON"}]},
            ),
            MagicMock(
                status_code=HTTPStatus.OK,
                json=lambda: {"content": [{"text": '```json\n{"valid": true}\n```'}]},
            ),
        ]

        result = client.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
        )

        assert result["success"] is True
        assert result["data"] == {"valid": True}
        assert mock_post.call_count == 2

    @patch("requests.post")
    def test_chat_with_json_max_retries_exceeded(
        self, mock_post: MagicMock, client: LLMClient
    ) -> None:
        """Test chat_with_json when max retries exceeded."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {"content": [{"text": "Never valid JSON"}]},
        )

        result = client.chat_with_json(
            system_prompt="Return JSON",
            user_prompt="Give me data",
            max_retries=2,
        )

        assert result["success"] is False
        assert "Failed to get valid JSON" in result["error"]
        assert mock_post.call_count == 2

    def test_extract_json_valid_code_block(self, client: LLMClient) -> None:
        """Test extracting JSON from code block."""
        content = 'Some text\n```json\n{"key": "value"}\n```\nMore text'

        result = client._extract_json(content)

        assert result["success"] is True
        assert result["data"] == {"key": "value"}

    def test_extract_json_invalid_json(self, client: LLMClient) -> None:
        """Test extracting invalid JSON from code block."""
        content = '```json\n{invalid json}\n```'

        result = client._extract_json(content)

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_extract_json_no_code_block(self, client: LLMClient) -> None:
        """Test extracting when no code block present."""
        content = "Just plain text response"

        result = client._extract_json(content)

        assert result["success"] is False
        assert "No JSON markdown block" in result["error"]

    def test_extract_json_raw_json(self, client: LLMClient) -> None:
        """Test extracting raw JSON without code block."""
        content = '{"key": "value"}'

        result = client._extract_json(content)

        assert result["success"] is True
        assert result["data"] == {"key": "value"}
