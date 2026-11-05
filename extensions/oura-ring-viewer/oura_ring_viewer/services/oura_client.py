"""Thin sync HTTP client around the Oura API v2.

Covers the OAuth token endpoint and the usercollection summary endpoints. It
does not retry, refresh tokens, or persist anything: refresh-on-401 is composed
in ``services/oauth.py`` and persistence belongs to the sync service.

Outbound HTTP goes through ``canvas_sdk.utils.http.Http``, which adds metrics
tracking, URL validation and the 30 second timeout ceiling. Every request is
path-only against ``OURA_API_HOST``; the authorize URL on cloud.ouraring.com is
built here but only ever visited by the patient's browser, never fetched.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.utils.http import Http

from oura_ring_viewer.services.settings import (
    MAX_PAGES,
    OURA_API_HOST,
    OURA_AUTHORIZE_URL,
    OURA_OAUTH_SCOPE,
    OURA_TOKEN_PATH,
    oura_collection_path,
)


class OuraAPIError(RuntimeError):
    """Raised on a non-2xx Oura response that is not an auth failure."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Oura API error {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body


class OuraAuthError(RuntimeError):
    """The access token was rejected, or a token request was refused.

    On a data call this means "refresh and retry once". On a token request it
    means the code or refresh token is no longer usable.
    """


class OuraForbiddenError(OuraAPIError):
    """Oura returned 403 for a data endpoint.

    Distinct from a dead token: the token is fine, but this data is not
    available to it. Typical causes are a scope the patient unticked at the
    consent screen, or a lapsed Oura membership. The sync skips the affected
    family instead of failing outright, and refreshing would not help.
    """


@dataclass
class TokenSet:
    """Tokens returned by Oura's token endpoint."""

    access_token: str
    refresh_token: str
    expires_in: int  # seconds
    token_type: str
    scope: str = ""

    @property
    def expires_at(self) -> dt.datetime:
        """Best-guess UTC expiry for ``access_token`` from issuance."""
        return dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=self.expires_in)


class OuraClient:
    """Sync HTTP client. The caller owns token storage and refresh."""

    def __init__(
        self,
        environment: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        http: Any | None = None,
    ) -> None:
        self._collection_path = oura_collection_path(environment)
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        # ``http`` is an injection point for tests; the runtime uses
        # ``canvas_sdk.utils.http.Http`` bound to the Oura API host.
        self._http = http if http is not None else Http(OURA_API_HOST)

    @property
    def collection_path(self) -> str:
        """The resolved usercollection path (sandbox or production)."""
        return self._collection_path

    def authorize_url(self, state: str) -> str:
        """Build the hosted-consent URL the patient's browser is sent to."""
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": OURA_OAUTH_SCOPE,
            "state": state,
        }
        return f"{OURA_AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenSet:
        """Trade an authorization code for an access and refresh token pair."""
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        })

    def refresh(self, refresh_token: str) -> TokenSet:
        """Rotate the refresh token and return a fresh access token."""
        return self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        })

    def fetch_collection(
        self,
        access_token: str,
        endpoint: str,
        start_day: dt.date,
        end_day: dt.date,
    ) -> list[dict[str, Any]]:
        """Return every record of ``endpoint`` for ``start_day..end_day``.

        Follows ``next_token`` pagination up to ``MAX_PAGES``. ``end_date`` is
        sent one day past ``end_day`` so the window is inclusive whichever way
        Oura treats the bound; the caller filters by ``day`` regardless.
        """
        base_params = {
            "start_date": start_day.isoformat(),
            "end_date": (end_day + dt.timedelta(days=1)).isoformat(),
        }
        records: list[dict[str, Any]] = []
        next_token: str | None = None
        for _ in range(MAX_PAGES):
            params = dict(base_params)
            if next_token:
                params["next_token"] = next_token
            page = self._authed_get(f"{self._collection_path}/{endpoint}", access_token, params)
            data = page.get("data") if isinstance(page, dict) else None
            if isinstance(data, list):
                records.extend(item for item in data if isinstance(item, dict))
            token = page.get("next_token") if isinstance(page, dict) else None
            if not token or token == next_token:
                break
            next_token = str(token)
        return records

    def _token_request(self, body: dict[str, str]) -> TokenSet:
        response = self._http.post(
            OURA_TOKEN_PATH,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code in (400, 401, 403):
            raise OuraAuthError(f"token request rejected ({response.status_code})")
        if response.status_code >= 400:
            raise OuraAPIError(response.status_code, response.text)
        payload = response.json()
        if not isinstance(payload, dict):
            raise OuraAPIError(response.status_code, "token response was not an object")
        tokens = TokenSet(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_in=_safe_int(payload.get("expires_in")),
            token_type=str(payload.get("token_type") or "Bearer"),
            scope=str(payload.get("scope") or ""),
        )
        # Refresh tokens are single use. Persisting an empty one would lock the
        # patient out on the next refresh, so a response missing either token
        # is treated as a failure rather than stored.
        if not tokens.access_token or not tokens.refresh_token:
            raise OuraAPIError(response.status_code, "token response missing a token")
        return tokens

    def _authed_get(self, path: str, access_token: str, params: dict[str, str]) -> Any:
        # ``Http.get`` takes no ``params`` kwarg, so the query is encoded into
        # the path before joining against the base URL.
        response = self._http.get(
            f"{path}?{urlencode(params)}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code == 401:
            raise OuraAuthError("access token rejected (401)")
        if response.status_code == 403:
            raise OuraForbiddenError(403, response.text)
        if response.status_code >= 400:
            raise OuraAPIError(response.status_code, response.text)
        return response.json()


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
