"""
Simplified OpenAI LLM wrapper for BP CPT2 extension.

This module provides a lightweight interface to OpenAI's chat completion API,
designed specifically for analyzing clinical notes to determine treatment plan documentation.
"""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from typing import Any

import requests


class LlmOpenai:
    """Simplified OpenAI LLM client for chat completions."""

    def __init__(self, api_key: str, model: str = "gpt-4"):
        """
        Initialize the OpenAI LLM client.

        Args:
            api_key: OpenAI API key for authentication
            model: OpenAI model to use (default: gpt-4)
        """
        self.api_key = api_key
        self.model = model
        self.temperature = 0.0
        self.messages: list[dict[str, str]] = []

    def reset_messages(self) -> None:
        """Clear all conversation messages."""
        self.messages = []

    def add_system_message(self, content: str) -> None:
        """
        Add a system message to the conversation.

        Args:
            content: The system message content
        """
        # If first message is already system, replace it
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0] = {"role": "system", "content": content}
        else:
            self.messages.insert(0, {"role": "system", "content": content})

    def add_user_message(self, content: str) -> None:
        """
        Add a user message to the conversation.

        Args:
            content: The user message content
        """
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        """
        Add an assistant message to the conversation.

        Args:
            content: The assistant message content
        """
        self.messages.append({"role": "assistant", "content": content})

    def chat(self, system_prompt: str | None = None, user_prompt: str | None = None) -> dict[str, Any]:
        """
        Send a chat completion request to OpenAI.

        Args:
            system_prompt: Optional system prompt to set before the request
            user_prompt: Optional user prompt to add before the request

        Returns:
            dict with keys:
                - success (bool): Whether the request succeeded
                - content (str): The response content if successful
                - error (str): Error message if unsuccessful
                - status_code (int): HTTP status code
        """
        if system_prompt:
            self.add_system_message(system_prompt)
        if user_prompt:
            self.add_user_message(user_prompt)

        url = "https://us.api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)

            if response.status_code == HTTPStatus.OK:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {
                    "success": True,
                    "content": content,
                    "error": None,
                    "status_code": response.status_code,
                }
            else:
                return {
                    "success": False,
                    "content": None,
                    "error": f"API request failed: {response.text}",
                    "status_code": response.status_code,
                }
        except Exception as e:
            return {
                "success": False,
                "content": None,
                "error": f"Request exception: {str(e)}",
                "status_code": None,
            }

    def chat_with_json(
        self, system_prompt: str, user_prompt: str, max_retries: int = 3
    ) -> dict[str, Any]:
        """
        Send a chat request expecting JSON response with automatic retry on JSON errors.

        Args:
            system_prompt: System prompt for the conversation
            user_prompt: User prompt for the conversation
            max_retries: Maximum number of retry attempts for JSON parsing

        Returns:
            dict with keys:
                - success (bool): Whether the request succeeded and JSON was valid
                - data (dict|list): Parsed JSON data if successful
                - error (str): Error message if unsuccessful
        """
        self.reset_messages()
        self.add_system_message(system_prompt)
        self.add_user_message(user_prompt)

        for attempt in range(max_retries):
            response = self.chat()

            if not response["success"]:
                return {
                    "success": False,
                    "data": None,
                    "error": response["error"],
                }

            # Try to extract JSON from the response
            json_result = self._extract_json(response["content"])

            if json_result["success"]:
                return {
                    "success": True,
                    "data": json_result["data"],
                    "error": None,
                }

            # If we haven't exhausted retries, ask the model to fix the JSON
            if attempt < max_retries - 1:
                self.add_assistant_message(response["content"])
                self.add_user_message(
                    f"Your previous response has the following error:\n{json_result['error']}\n\n"
                    "Please provide a valid JSON response enclosed in a markdown code block "
                    "like:\n```json\n{...}\n```"
                )

        return {
            "success": False,
            "data": None,
            "error": f"Failed to get valid JSON after {max_retries} attempts",
        }

    def _extract_json(self, content: str) -> dict[str, Any]:
        """
        Extract JSON from markdown code blocks in the response.

        Args:
            content: The response content to parse

        Returns:
            dict with keys:
                - success (bool): Whether JSON was successfully extracted
                - data (dict|list): Parsed JSON data if successful
                - error (str): Error message if unsuccessful
        """
        # Try to find JSON in markdown code blocks
        pattern = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL | re.IGNORECASE)
        matches = pattern.findall(content)

        if not matches:
            return {
                "success": False,
                "data": None,
                "error": "No JSON markdown block found. Please wrap JSON in ```json``` tags.",
            }

        try:
            # Parse the first JSON block found
            data = json.loads(matches[0])
            return {
                "success": True,
                "data": data,
                "error": None,
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "data": None,
                "error": f"Invalid JSON: {str(e)}",
            }
