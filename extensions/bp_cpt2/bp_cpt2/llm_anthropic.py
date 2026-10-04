"""
Anthropic LLM wrapper for BP CPT2 extension.

This module calls Anthropic's Messages API with the same interface as LlmOpenai,
so either can identify the hypertension-related diagnoses on a clinical note.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import requests

from bp_cpt2.llm_openai import LlmOpenai

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-5"


class LlmAnthropic(LlmOpenai):
    """Anthropic Messages API client that reuses LlmOpenai's conversation and JSON handling."""

    def __init__(self, api_key: str, model: str = ANTHROPIC_DEFAULT_MODEL):
        """
        Initialize the Anthropic LLM client.

        Args:
            api_key: Anthropic API key for authentication
            model: Claude model to use (default: claude-opus-5)
        """
        super().__init__(api_key=api_key, model=model, base_url=ANTHROPIC_API_BASE)

    def chat(self, system_prompt: str | None = None, user_prompt: str | None = None) -> dict[str, Any]:
        """
        Send a Messages API request to Anthropic.

        Args:
            system_prompt: Optional system prompt to set before the request
            user_prompt: Optional user prompt to add before the request

        Returns:
            dict with the same keys as LlmOpenai.chat
        """
        if system_prompt:
            self.add_system_message(system_prompt)
        if user_prompt:
            self.add_user_message(user_prompt)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        # The model's thinking counts toward max_tokens; inference_geo keeps processing in the US
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "inference_geo": "us",
            "messages": [message for message in self.messages if message["role"] != "system"],
        }
        if self.messages and self.messages[0]["role"] == "system":
            payload["system"] = self.messages[0]["content"]
        if self.model == ANTHROPIC_DEFAULT_MODEL:
            # Re-run on Anthropic's recommended fallback model if this model's safety classifiers decline
            headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
            payload["fallbacks"] = "default"

        try:
            response = requests.post(f"{self.base_url}/messages", headers=headers, json=payload, timeout=60)
        except requests.RequestException as e:
            return {
                "success": False,
                "content": None,
                "error": f"Request exception: {str(e)}",
                "status_code": None,
            }

        if response.status_code != HTTPStatus.OK:
            return {
                "success": False,
                "content": None,
                "error": f"API request failed: {response.text}",
                "status_code": response.status_code,
            }

        data = response.json()
        if data.get("stop_reason") == "refusal":
            return {
                "success": False,
                "content": None,
                "error": "API request declined by the model",
                "status_code": response.status_code,
            }

        content = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )
        return {
            "success": True,
            "content": content,
            "error": None,
            "status_code": response.status_code,
        }
