"""Salesforce HTTP client — token refresh and ``Canvas_Patient_ID__c`` writeback.

Uses :class:`canvas_sdk.utils.http.Http` so timeouts, metrics and URL
validation are uniform with the rest of the platform.
"""

import time
from dataclasses import dataclass
from typing import Any, Protocol

from salesforce_to_canvas_integration.services.storage import StoredTokens, TokenStore

REFRESH_LEEWAY_SECONDS = 60
DEFAULT_EXPIRES_IN = 3600  # 1h — Salesforce default


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


class HttpClient(Protocol):
    """Subset of :class:`canvas_sdk.utils.http.Http` we depend on."""

    def get(
        self, url: str, headers: dict[str, str] | None = ..., **kw: Any
    ) -> HttpResponse: ...
    def post(
        self,
        url: str,
        data: dict[str, str] | None = ...,
        json: dict[str, Any] | None = ...,
        headers: dict[str, str] | None = ...,
        **kw: Any,
    ) -> HttpResponse: ...
    def patch(
        self,
        url: str,
        json: dict[str, Any] | None = ...,
        headers: dict[str, str] | None = ...,
        **kw: Any,
    ) -> HttpResponse: ...


class SalesforceError(RuntimeError):
    """Raised on a non-recoverable Salesforce API failure."""


class SalesforceNotConnectedError(SalesforceError):
    """Raised when no OAuth tokens are available and the caller needs them."""


class SalesforceReconnectRequiredError(SalesforceError):
    """Raised when refresh fails — the user must reauthorise."""


@dataclass(frozen=True)
class TokenResponse:
    """Subset of the OAuth token endpoint response we use."""

    access_token: str
    refresh_token: str
    instance_url: str
    issued_at: float
    expires_in: int
    sf_username: str | None = None


def _now() -> float:
    return time.time()


def _build_tokens(response_json: dict[str, Any], fallback_refresh: str | None = None) -> TokenResponse:
    access = str(response_json.get("access_token") or "")
    refresh = str(response_json.get("refresh_token") or fallback_refresh or "")
    instance_url = str(response_json.get("instance_url") or "")
    if not access or not instance_url:
        raise SalesforceError("Salesforce token response missing access_token/instance_url")
    issued_at = float(response_json.get("issued_at", _now() * 1000)) / 1000.0
    expires_in = int(response_json.get("expires_in", DEFAULT_EXPIRES_IN))
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        instance_url=instance_url.rstrip("/"),
        issued_at=issued_at,
        expires_in=expires_in,
        sf_username=str(response_json.get("username")) if response_json.get("username") else None,
    )


class SalesforceClient:
    """Stateful wrapper that auto-refreshes tokens and writes back Canvas IDs."""

    def __init__(
        self,
        *,
        http: HttpClient,
        tokens: TokenStore,
        login_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._http = http
        self._tokens = tokens
        self._login_url = login_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret

    # ── OAuth ──────────────────────────────────────────────────────────────

    def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> StoredTokens:
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        response = self._http.post(
            f"{self._login_url}/services/oauth2/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise SalesforceError(
                f"Salesforce token exchange failed ({response.status_code}): {response.text[:500]}"
            )
        token_response = _build_tokens(response.json())
        return self._persist(token_response)

    def refresh(self) -> StoredTokens:
        stored = self._tokens.load()
        if stored is None or not stored.refresh_token:
            raise SalesforceNotConnectedError("No refresh token stored")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": stored.refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        response = self._http.post(
            f"{self._login_url}/services/oauth2/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            # Refresh failed — almost certainly revoked. Drop tokens so the
            # admin UI surfaces "needs reconnect".
            self._tokens.clear()
            raise SalesforceReconnectRequiredError(
                f"Refresh failed ({response.status_code}): {response.text[:500]}"
            )
        return self._persist(_build_tokens(response.json(), fallback_refresh=stored.refresh_token))

    def disconnect(self) -> None:
        self._tokens.clear()

    def is_connected(self) -> bool:
        return self._tokens.load() is not None

    # ── data plane ─────────────────────────────────────────────────────────

    def write_canvas_id(
        self,
        *,
        sobject: str,
        sf_record_id: str,
        canvas_patient_id: str,
        field_name: str = "Canvas_Patient_ID__c",
    ) -> None:
        """PATCH the Salesforce record to set ``Canvas_Patient_ID__c``."""
        tokens = self._ensure_valid_tokens()
        url = (
            f"{tokens.instance_url}/services/data/v60.0/sobjects/{sobject}/{sf_record_id}"
        )
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "Content-Type": "application/json",
        }
        response = self._http.patch(url, json={field_name: canvas_patient_id}, headers=headers)
        # SF returns 204 on success
        if 200 <= response.status_code < 300:
            return
        if response.status_code == 401:
            tokens = self.refresh()
            headers["Authorization"] = f"Bearer {tokens.access_token}"
            response = self._http.patch(url, json={field_name: canvas_patient_id}, headers=headers)
            if 200 <= response.status_code < 300:
                return
        raise SalesforceError(
            f"Salesforce writeback failed ({response.status_code}): {response.text[:500]}"
        )

    # ── helpers ────────────────────────────────────────────────────────────

    def _persist(self, response: TokenResponse) -> StoredTokens:
        tokens = StoredTokens(
            access_token=response.access_token,
            refresh_token=response.refresh_token,
            instance_url=response.instance_url,
            issued_at=response.issued_at,
            expires_at=response.issued_at + response.expires_in,
            sf_username=response.sf_username,
        )
        return self._tokens.save(tokens)

    def _ensure_valid_tokens(self) -> StoredTokens:
        stored = self._tokens.load()
        if stored is None:
            raise SalesforceNotConnectedError("Plugin is not connected to Salesforce")
        if stored.expires_at - REFRESH_LEEWAY_SECONDS <= _now():
            return self.refresh()
        return stored


__all__ = (
    "HttpClient",
    "HttpResponse",
    "SalesforceClient",
    "SalesforceError",
    "SalesforceNotConnectedError",
    "SalesforceReconnectRequiredError",
)
