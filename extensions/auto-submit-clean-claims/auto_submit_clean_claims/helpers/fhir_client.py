"""
Minimal FHIR client for plugins. Based on the pattern from
https://github.com/canvas-medical/canvas-plugins/pull/1337

Requires CANVAS_FHIR_CLIENT_ID and CANVAS_FHIR_CLIENT_SECRET plugin secrets.
"""

from urllib.parse import urlencode

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils import Http


class FhirClient:
    """Lightweight FHIR client that handles OAuth token exchange and caching."""

    def __init__(self, client_id: str, client_secret: str, customer_identifier: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._customer_identifier = customer_identifier
        self._base_url = f"https://fumage-{customer_identifier}.canvasmedical.com"
        self._token = self._get_token()

    def read(self, resource_type: str, resource_id: str) -> dict:
        response = Http().get(
            f"{self._base_url}/{resource_type}/{resource_id}",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _get_token(self) -> str:
        cache = get_cache()
        cache_key = f"fhir_token_{self._client_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        response = Http().post(
            f"https://{self._customer_identifier}.canvasmedical.com/auth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=urlencode({
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }),
        )
        response.raise_for_status()
        data = response.json()

        cache.set(cache_key, data["access_token"], timeout_seconds=data["expires_in"] - 60)
        return data["access_token"]
