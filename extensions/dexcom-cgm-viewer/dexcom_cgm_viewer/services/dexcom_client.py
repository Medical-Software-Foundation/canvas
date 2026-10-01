"""Thin sync HTTP client around the Dexcom Developer API v3.

Only the OAuth and ``egvs`` / ``dataRange`` endpoints are exercised. The
client is intentionally small: it does not retry, it does not refresh tokens,
and it does not persist anything. Refresh-on-401 is composed in
``lib/oauth.py``; persistence is the API handler's job.

Per REVIEW.md §8 outbound HTTP goes through ``canvas_sdk.utils.http.Http``,
which adds metrics tracking, URL validation, and the 30s timeout ceiling.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.utils.http import Http

from dexcom_cgm_viewer.services.settings import DEXCOM_OAUTH_SCOPE, dexcom_base_url


class DexcomAuthError(RuntimeError):
    """Raised when Dexcom returns 401/403 from a request that needed auth."""


class DexcomAPIError(RuntimeError):
    """Raised on any other non-2xx Dexcom response."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Dexcom API error {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body


@dataclass
class TokenSet:
    """Tokens returned by Dexcom's ``/v3/oauth2/token`` endpoint."""

    access_token: str
    refresh_token: str
    expires_in: int  # seconds
    token_type: str
    dexcom_user_id: str = ""

    @property
    def expires_at(self) -> dt.datetime:
        """Best-guess UTC expiry for ``access_token`` from issuance."""
        return dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=self.expires_in)


class DexcomClient:
    """Sync HTTP client. Caller is responsible for token storage and refresh."""

    def __init__(
        self,
        environment: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        http: Any | None = None,
    ) -> None:
        self._base = dexcom_base_url(environment)
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        # ``http`` is an injection point for tests; the real runtime uses
        # ``canvas_sdk.utils.http.Http`` (REVIEW.md §8) which enforces a 30s
        # timeout ceiling, adds metrics tracking, and validates the URL is
        # within the configured base.
        self._http = http if http is not None else Http(self._base)

    @property
    def base_url(self) -> str:
        """Public accessor for the resolved environment base URL."""
        return self._base

    def authorize_url(self, state: str) -> str:
        """Build the URL the patient should be redirected to for hosted login."""
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": DEXCOM_OAUTH_SCOPE,
            "state": state,
        }
        return f"{self._base}/v3/oauth2/login?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenSet:
        """Trade an authorization code for an access/refresh token pair."""
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self._redirect_uri,
        }
        return self._token_request(body)

    def refresh(self, refresh_token: str) -> TokenSet:
        """Rotate the refresh token and return a fresh access token."""
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "redirect_uri": self._redirect_uri,
        }
        return self._token_request(body)

    def fetch_egvs(
        self,
        access_token: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[dict[str, Any]]:
        """Pull egv records between ``start`` and ``end`` (UTC)."""
        params = {
            "startDate": _format_dexcom_dt(start),
            "endDate": _format_dexcom_dt(end),
        }
        data = self._authed_get("/v3/users/self/egvs", access_token, params=params)
        records = data.get("records") if isinstance(data, dict) else None
        return list(records) if isinstance(records, list) else []

    def fetch_data_range(self, access_token: str) -> dict[str, Any]:
        """Return the available data range for the connected user."""
        data = self._authed_get("/v3/users/self/dataRange", access_token, params=None)
        return data if isinstance(data, dict) else {}

    def _token_request(self, body: dict[str, str]) -> TokenSet:
        response = self._http.post(
            "/v3/oauth2/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code in (400, 401, 403):
            raise DexcomAuthError(f"token request rejected ({response.status_code})")
        if response.status_code >= 400:
            raise DexcomAPIError(response.status_code, response.text)
        payload = response.json()
        return TokenSet(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_in=int(payload.get("expires_in") or 0),
            token_type=str(payload.get("token_type") or "Bearer"),
            dexcom_user_id=str(payload.get("userId") or ""),
        )

    def _authed_get(
        self,
        path: str,
        access_token: str,
        *,
        params: dict[str, str] | None,
    ) -> Any:
        # ``canvas_sdk.utils.http.Http.get`` doesn't accept a ``params``
        # kwarg, so query params are encoded into the path before joining.
        url = f"{path}?{urlencode(params)}" if params else path
        response = self._http.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code == 401:
            raise DexcomAuthError("access token rejected (401)")
        if response.status_code >= 400:
            raise DexcomAPIError(response.status_code, response.text)
        return response.json()


def _format_dexcom_dt(value: dt.datetime) -> str:
    """Dexcom expects ISO-8601 in UTC without sub-second precision."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    value = value.astimezone(dt.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S")
