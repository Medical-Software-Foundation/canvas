"""Cache-backed storage for the OAuth tokens, plus the content hash helper.

Canvas plugins do not have a private SQL store for ephemeral data; we use the
SDK's plugin cache (Redis) with a 14-day default TTL for the OAuth tokens, which
are short-lived secrets that refresh on their own. Audit-grade inbound data now
lives in the ``IncomingPatientRecord`` custom data model, not the cache. See
journal cnv-909 entries 029 and 030.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

TOKEN_KEY = "oauth:tokens"


class CacheLike(Protocol):
    """Subset of the SDK plugin cache we depend on."""

    def get(self, key: str, default: Any | None = ...) -> Any: ...
    def set(self, key: str, value: Any, timeout_seconds: int | None = ...) -> None: ...
    def delete(self, key: str) -> None: ...


def compute_entry_id(sf_record_id: str, payload: dict[str, Any]) -> str:
    """Stable, content-addressed hash used to dedup inbound webhook events."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{sf_record_id}|{canonical}".encode()).hexdigest()
    return digest[:32]


@dataclass(frozen=True)
class StoredTokens:
    access_token: str
    refresh_token: str
    instance_url: str
    issued_at: float
    expires_at: float
    sf_username: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TokenStore:
    """OAuth access + refresh token storage."""

    def __init__(self, cache: CacheLike) -> None:
        self._cache = cache

    def load(self) -> StoredTokens | None:
        raw = self._cache.get(TOKEN_KEY)
        if not isinstance(raw, dict):
            return None
        return StoredTokens(**raw)

    def save(self, tokens: StoredTokens) -> StoredTokens:
        self._cache.set(TOKEN_KEY, tokens.to_dict())
        return tokens

    def clear(self) -> None:
        self._cache.delete(TOKEN_KEY)


__all__ = (
    "CacheLike",
    "StoredTokens",
    "TokenStore",
    "compute_entry_id",
)
