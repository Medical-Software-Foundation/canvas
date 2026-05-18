"""
FHIR client helpers for the practitioner bulk loader.

Uses canvas_sdk.utils.http.Http for all HTTP calls — the only
allowed HTTP primitive in the Canvas RestrictedPython sandbox.

Token exchange (client_credentials grant) is done inline and the
bearer token is stored on the FhirClient instance for the lifetime
of the handler invocation. No private-attribute access on SDK
objects, no CanvasFhir, no CUSTOMER_IDENTIFIER import.

Public API:
  make_fhir_client(secrets)  -> FhirClient
  get_location_map(client)   -> dict[str, str]
  read_practitioner(client, id) -> dict
  create_practitioner(client, resource) -> str
  replace_practitioner(client, id, resource) -> None  # PUT (PATCH is unsupported by Canvas)

Duplicate-detection lookups have moved off FHIR — the API handler now
queries Canvas's Staff ORM directly (see ``_build_staff_directory`` in
``api/bulk_upload_api.py``) because Fumage's identifier/name/telecom
search parameters don't actually filter on value, and the Staff table
also catches phantom records that have no Practitioner FHIR resource.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from canvas_sdk.utils.http import Http


class FhirClient:
    """
    Thin FHIR client built on top of canvas_sdk.utils.http.Http.

    Holds the base URL and a bearer token obtained from an OAuth
    client_credentials exchange.  All attributes are plain public attributes
    so there is no sandbox-unsafe private-attribute access.
    """

    def __init__(self, base_url: str, access_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self._http = Http(self.base_url)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """GET {base_url}{path}[?params].  Returns the parsed JSON body."""
        url = self.base_url + path
        if params:
            url = f"{url}?{urlencode(params)}"
        response = self._http.get(url, headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

    def post(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """POST {base_url}{path}.  Returns the full response (for header access)."""
        url = self.base_url + path
        response = self._http.post(url, json=json_body, headers=self._auth_headers())
        response.raise_for_status()
        return response

    def put(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """PUT {base_url}{path}. Used to fully replace a FHIR resource —
        Canvas's Fumage Practitioner endpoint allows GET + PUT but rejects
        PATCH with 405, so qualification updates have to be done via PUT
        of the full resource.
        """
        url = self.base_url + path
        response = self._http.put(url, json=json_body, headers=self._auth_headers())
        response.raise_for_status()
        return response


class MissingSecretError(Exception):
    """Raised when a required plugin secret is missing or blank."""


def make_fhir_client(
    secrets: dict[str, str],
    environment: dict[str, str],
) -> FhirClient:
    """
    Instantiate a FhirClient from plugin secrets + Canvas environment.

    Host is derived from CUSTOMER_IDENTIFIER — the `fumage-host` secret is
    no longer needed. Performs a client_credentials token exchange and
    returns a FhirClient configured for the fumage endpoint.

    Expected secrets: fumage-client-id, fumage-client-secret
    Expected environment: CUSTOMER_IDENTIFIER
    """
    client_id = (secrets.get("fumage-client-id") or "").strip()
    client_secret = (secrets.get("fumage-client-secret") or "").strip()
    customer = (environment.get("CUSTOMER_IDENTIFIER") or "").strip()

    missing = [
        name
        for name, value in (
            ("fumage-client-id", client_id),
            ("fumage-client-secret", client_secret),
            ("CUSTOMER_IDENTIFIER (environment)", customer),
        )
        if not value
    ]
    if missing:
        raise MissingSecretError(
            "Required configuration is missing: " + ", ".join(missing)
        )

    canvas_host = f"{customer}.canvasmedical.com"
    token_url = f"https://{canvas_host}/auth/token/"

    token_http = Http(f"https://{canvas_host}")
    token_response = token_http.post(
        token_url,
        data=urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token_response.raise_for_status()
    access_token: str = token_response.json()["access_token"]

    base_url = f"https://fumage-{customer}.canvasmedical.com"
    return FhirClient(base_url=base_url, access_token=access_token)


def get_location_map(client: FhirClient) -> dict[str, str]:
    """
    Return {location_name_lower -> "Location/<id>"} for all active locations.
    Paginates automatically using the FHIR bundle 'next' link.
    """
    location_map: dict[str, str] = {}
    params: dict[str, str] = {"status": "active", "_count": "200"}

    url: str | None = f"{client.base_url}/Location?{urlencode(params)}"
    while url:
        response = client._http.get(url, headers=client._auth_headers())
        response.raise_for_status()
        bundle = response.json()

        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            rid = resource.get("id", "")
            name = resource.get("name", "")
            if rid and name:
                location_map[name.lower()] = f"Location/{rid}"

        next_url: str | None = None
        for link in bundle.get("link", []):
            if link.get("relation") == "next":
                next_url = link["url"]
                break
        url = next_url

    return location_map


def read_practitioner(client: FhirClient, practitioner_id: str) -> dict[str, Any]:
    """
    Read a Practitioner resource by ID (accepts "Practitioner/<uuid>" or bare UUID).
    """
    clean_id = practitioner_id.replace("Practitioner/", "")
    return dict(client.get(f"/Practitioner/{clean_id}"))


def create_practitioner(
    client: FhirClient, fhir_resource: dict[str, Any]
) -> str:
    """
    POST /Practitioner. Returns the new resource ID as "Practitioner/<uuid>".
    Raises on HTTP error.

    Canvas returns the created ID in the Location response header.
    """
    response = client.post("/Practitioner", json_body=fhir_resource)

    location_header = response.headers.get("Location", "")
    if location_header:
        parts = location_header.rstrip("/").split("/")
        new_id = parts[-1]
        return f"Practitioner/{new_id}"

    return ""


def replace_practitioner(
    client: FhirClient,
    practitioner_id: str,
    resource: dict[str, Any],
) -> None:
    """PUT /Practitioner/{id} with the full resource.

    Canvas's Fumage rejects PATCH (405 Method Not Allowed) on Practitioner,
    so updates have to be done by GETting the current resource, modifying
    it locally (e.g., appending to qualification[]), and PUTting it back.
    Callers are responsible for building a complete resource dict that
    preserves any existing fields that should not be reset.
    """
    clean_id = practitioner_id.replace("Practitioner/", "")
    client.put(f"/Practitioner/{clean_id}", json_body=resource)
