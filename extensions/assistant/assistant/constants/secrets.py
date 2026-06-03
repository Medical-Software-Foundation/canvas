from dataclasses import dataclass


@dataclass(frozen=True)
class Secrets:
    """Secret key names used by the assistant plugin."""

    anthropic_key: str = "AnthropicKey"
