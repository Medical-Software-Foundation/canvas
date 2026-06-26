"""Canvas FHIR client used by the audit Mark inactive resolution.

Read modify write against ``/Patient/{id}``. The Canvas FHIR Patient endpoint
does not document PATCH, only GET and PUT, and PUT is a full overwrite, so the
helper GETs the patient body first and PUTs it back with ``active`` flipped to
false. Every other field rides through untouched. See journal cnv-909/082 for
the corrections that fed this shape.
"""

import time
from typing import Any, Protocol

from logger import log

# Refresh a touch before the documented expiry so a token that lapsed mid call
# does not surface a 401 to the route. Mirrors the leeway constant in
# :mod:`salesforce_to_canvas_integration.services.sf_client`.
TOKEN_REFRESH_LEEWAY_SECONDS = 30
DEFAULT_TOKEN_EXPIRES_IN = 3600

_AUTH_TOKEN_PATH = "/auth/token/"
_FUMAGE_HOST_PREFIX = "//fumage-"
_AUTH_HOST_PREFIX = "//"

_RESPONSE_PREVIEW_CHARS = 500

# The SDK writes the Salesforce link with system="salesforce" verbatim through
# :class:`canvas_sdk.effects.patient.PatientExternalIdentifier`, so the FHIR
# Patient resource surfaces the same string in ``identifier[].system``. Pinned
# here so the unlink helper drops the right entry and nothing else.
SALESFORCE_IDENTIFIER_SYSTEM = "salesforce"


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

    def put(
        self,
        url: str,
        json: dict[str, Any] | None = ...,
        headers: dict[str, str] | None = ...,
        **kw: Any,
    ) -> HttpResponse: ...


class CanvasFhirError(RuntimeError):
    """Raised on a non-recoverable Canvas FHIR API failure."""


class CanvasFhirAuthError(CanvasFhirError):
    """Raised when the access token request fails or a retried 401 lingers."""


class CanvasFhirNotConfiguredError(CanvasFhirError):
    """Raised by the factory when any of the three Canvas FHIR secrets is empty."""


def _now() -> float:
    return time.time()


def _derive_token_url(fumage_base_url: str) -> str:
    """Return the OAuth token URL derived from the FHIR base URL.

    Canvas hosts the FHIR API under ``fumage-<instance>.canvasmedical.com`` and
    the auth token endpoint under ``<instance>.canvasmedical.com/auth/token/``.
    Stripping the ``fumage-`` host prefix is the convention the Canvas docs
    document, no URL parsing needed.
    """
    base = fumage_base_url.rstrip("/")
    if _FUMAGE_HOST_PREFIX in base:
        base = base.replace(_FUMAGE_HOST_PREFIX, _AUTH_HOST_PREFIX, 1)
    return f"{base}{_AUTH_TOKEN_PATH}"


class CanvasFhirClient:
    """Stateful Canvas FHIR client with in-memory token caching and 401 retry."""

    def __init__(
        self,
        *,
        http: HttpClient,
        fumage_base_url: str,
        client_id: str,
        client_secret: str,
        instance_url: str = "",
    ) -> None:
        if not (fumage_base_url and client_id and client_secret):
            raise CanvasFhirNotConfiguredError(
                "Canvas FHIR client requires fumage_base_url, client_id, and client_secret"
            )
        self._http = http
        self._fumage_base_url = fumage_base_url.rstrip("/")
        # Optional token host override. See journal cnv-928/002. Production leaves
        # this empty and keeps the fumage prefix derivation. Local stacks set it so
        # the token url points at the auth port while FHIR stays on its own port.
        self._instance_url = (instance_url or "").rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    # ── public API ────────────────────────────────────────────────────────

    def mark_patient_inactive(self, patient_id: str) -> None:
        """Read the patient body, flip ``active`` to false, PUT the body back.

        The PUT is a full overwrite, so the helper preserves every other field
        from the GET. Returns void on success, raises on failure.
        """
        body = self.get_patient(patient_id)
        body["active"] = False
        self.update_patient(patient_id, body)
        log.info("Canvas FHIR mark inactive ok patient=%s", patient_id)

    def remove_salesforce_identifier(
        self, patient_id: str, sf_external_id: str
    ) -> None:
        """Read the patient body, drop the salesforce identifier, PUT it back.

        Filters ``body["identifier"]`` to remove any entry where ``system``
        matches the salesforce link constant and ``value`` matches the supplied
        Salesforce record id. Every other identifier and every other field
        rides through unchanged. The call is idempotent, a patient with no
        matching identifier still PUTs the body back unchanged and the helper
        logs that as a no op.
        """
        body = self.get_patient(patient_id)
        identifiers = body.get("identifier") or []
        if not isinstance(identifiers, list):
            identifiers = []
        filtered = [
            entry
            for entry in identifiers
            if not (
                isinstance(entry, dict)
                and entry.get("system") == SALESFORCE_IDENTIFIER_SYSTEM
                and entry.get("value") == sf_external_id
            )
        ]
        removed = len(identifiers) - len(filtered)
        body["identifier"] = filtered
        self.update_patient(patient_id, body)
        if removed:
            log.info(
                "Canvas FHIR unlink salesforce ok patient=%s removed=%s",
                patient_id,
                removed,
            )
        else:
            log.info(
                "Canvas FHIR unlink salesforce no-op patient=%s sf_id=%s",
                patient_id,
                sf_external_id,
            )

    def get_patient(self, patient_id: str) -> dict[str, Any]:
        """GET ``/Patient/{id}`` and return the parsed JSON body.

        A 401 triggers a token refresh and one retry. If the retry still sees
        401 the failure surfaces as :class:`CanvasFhirAuthError` so the route
        can distinguish auth failure from other 4xx and 5xx responses.
        """
        url = self._patient_url(patient_id)
        response = self._http.get(url, headers=self._headers())
        if response.status_code == 401:
            self._access_token = None
            response = self._http.get(url, headers=self._headers())
            if response.status_code == 401:
                raise CanvasFhirAuthError(
                    self._error_message("GET Patient", response)
                )
        if 200 <= response.status_code < 300:
            return self._decode_body(response)
        raise CanvasFhirError(self._error_message("GET Patient", response))

    def update_patient(self, patient_id: str, body: dict[str, Any]) -> None:
        """PUT ``/Patient/{id}`` with the given body, retrying once on 401.

        A retried 401 surfaces as :class:`CanvasFhirAuthError`, every other
        non-2xx as :class:`CanvasFhirError`.
        """
        url = self._patient_url(patient_id)
        response = self._http.put(url, json=body, headers=self._headers())
        if response.status_code == 401:
            self._access_token = None
            response = self._http.put(url, json=body, headers=self._headers())
            if response.status_code == 401:
                raise CanvasFhirAuthError(
                    self._error_message("PUT Patient", response)
                )
        if 200 <= response.status_code < 300:
            return
        raise CanvasFhirError(self._error_message("PUT Patient", response))

    # ── helpers ───────────────────────────────────────────────────────────

    def _patient_url(self, patient_id: str) -> str:
        return f"{self._fumage_base_url}/Patient/{patient_id}"

    def _token_url(self) -> str:
        # When an instance url override is configured the token endpoint is built
        # from it directly. Otherwise fall back to the fumage prefix derivation so
        # production stays unchanged. See journal cnv-928/002.
        if self._instance_url:
            return f"{self._instance_url}{_AUTH_TOKEN_PATH}"
        return _derive_token_url(self._fumage_base_url)

    def _headers(self) -> dict[str, str]:
        token = self._ensure_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _ensure_token(self) -> str:
        if self._access_token and self._expires_at - TOKEN_REFRESH_LEEWAY_SECONDS > _now():
            return self._access_token
        return self._refresh_token()

    def _refresh_token(self) -> str:
        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        response = self._http.post(
            self._token_url(),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            log.warning(
                "Canvas FHIR token request failed status=%s",
                response.status_code,
            )
            raise CanvasFhirAuthError(
                self._error_message("token request", response)
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise CanvasFhirAuthError(
                f"Canvas FHIR token response was not JSON: {exc}"
            ) from exc
        if not isinstance(body, dict):
            raise CanvasFhirAuthError(
                "Canvas FHIR token response was not a JSON object"
            )
        access = str(body.get("access_token") or "")
        if not access:
            raise CanvasFhirAuthError(
                "Canvas FHIR token response missing access_token"
            )
        expires_in = int(body.get("expires_in") or DEFAULT_TOKEN_EXPIRES_IN)
        self._access_token = access
        self._expires_at = _now() + expires_in
        log.info("Canvas FHIR token refreshed expires_in=%s", expires_in)
        return access

    @staticmethod
    def _decode_body(response: HttpResponse) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise CanvasFhirError(
                f"Canvas FHIR response was not JSON: {exc}"
            ) from exc
        if not isinstance(body, dict):
            raise CanvasFhirError("Canvas FHIR response was not a JSON object")
        return body

    @staticmethod
    def _error_message(action: str, response: HttpResponse) -> str:
        preview = (response.text or "")[:_RESPONSE_PREVIEW_CHARS]
        return f"Canvas FHIR {action} failed ({response.status_code}): {preview}"


def build_canvas_fhir_client(
    *,
    http: HttpClient,
    fumage_base_url: str,
    client_id: str,
    client_secret: str,
    instance_url: str = "",
) -> CanvasFhirClient:
    """Factory that fails fast when any of the three required values is empty.

    The Mark inactive route consults
    :func:`salesforce_to_canvas_integration.services.config.canvas_fhir_configured`
    first, so this factory is the defensive belt and suspenders that surfaces a
    typed error if a caller skips the predicate. The optional instance url
    overrides the token host. See journal cnv-928/002.
    """
    return CanvasFhirClient(
        http=http,
        fumage_base_url=fumage_base_url,
        client_id=client_id,
        client_secret=client_secret,
        instance_url=instance_url,
    )


__all__ = (
    "CanvasFhirAuthError",
    "CanvasFhirClient",
    "CanvasFhirError",
    "CanvasFhirNotConfiguredError",
    "HttpClient",
    "HttpResponse",
    "SALESFORCE_IDENTIFIER_SYSTEM",
    "build_canvas_fhir_client",
)
