from typing import TYPE_CHECKING
from urllib.parse import urlencode

from canvas_sdk.utils.http import Http
from logger import log

if TYPE_CHECKING:
    from requests import Response

CACHE_KEY_PREFIX = "candid_bearer_token:"
# Candid tokens expire after 5 hours (18000s). Cache for 4.5 hours to
# refresh before expiry.
CACHE_TTL_SECONDS = 16200


class CandidClient:
    """HTTP client for Candid Health's API."""

    def __init__(self, base_url: str, client_id: str, client_secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._instance_token: str | None = None
        self.http = Http(base_url=self.base_url)

    @classmethod
    def from_secrets(cls, secrets: dict) -> "CandidClient":
        return cls(
            base_url=secrets["CANDID_BASE_URL"],
            client_id=secrets["CANDID_CLIENT_ID"],
            client_secret=secrets["CANDID_CLIENT_SECRET"],
        )

    def _token(self) -> str:
        # Instance-level cache (same CandidClient object reused within a handler)
        if self._instance_token:
            return self._instance_token

        # Per-client_id cache key so secret rotation or multiple Candid environments
        # don't share a stale token across installs.
        cache_key = f"{CACHE_KEY_PREFIX}{self.client_id}"

        # Plugin cache (shared across handler invocations)
        try:
            from canvas_sdk.caching.plugins import get_cache

            cache = get_cache()
            token = cache.get(cache_key)
            if token:
                self._instance_token = token
                return token
        except Exception:
            cache = None

        token = self._fetch_token()
        self._instance_token = token

        if cache:
            try:
                cache.set(cache_key, token, timeout_seconds=CACHE_TTL_SECONDS)
            except Exception:
                log.warning("Candid: failed to cache bearer token")

        return token

    def _fetch_token(self) -> str:
        response = self.http.post(
            f"{self.base_url}/api/auth/v2/token",
            json={"client_id": self.client_id, "client_secret": self.client_secret},
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError(f"Could not fetch Candid API token: {response.text}")
        return token

    # ------------------------------------------------------------------
    # Claim submission
    # ------------------------------------------------------------------

    def submit_claim(self, claim_payload: dict) -> tuple[bool, str]:
        """Submit a claim to Candid's /encounters/v4 endpoint.

        Returns ``(was_successful, message)``. On success, ``message`` is the
        Candid encounter ID. On failure, ``message`` is a human-readable error.
        """
        response = self.http.post(
            f"{self.base_url}/api/encounters/v4",
            json=claim_payload,
            headers=self._auth_headers(json_body=True),
        )
        if response.ok:
            return True, response.json().get("encounter_id", "")
        return False, self._format_error(response)

    def find_encounter_by_external_id(self, external_id: str) -> str | None:
        """Look up an encounter_id by its external_id.

        Uses ``GET /api/encounters/v4?external_id=...``. Returns the
        encounter_id if found, or None.
        """
        query = urlencode({"external_id": external_id, "limit": 1})
        response = self.http.get(
            f"{self.base_url}/api/encounters/v4?{query}",
            headers=self._auth_headers(),
        )
        if not response.ok:
            return None
        data = response.json()
        items = data.get("items", [data] if "encounter_id" in data else [])
        if items:
            return items[0].get("encounter_id")
        return None

    def update_claim(self, encounter_id: str, claim_payload: dict) -> tuple[bool, str]:
        """Update an existing encounter via PATCH /encounters/v4/{encounter_id}.

        Used when re-submitting a claim that was already filed — the encounter
        exists on Candid's side and needs its data updated rather than a new
        encounter created.

        Returns ``(was_successful, message)``. On success, ``message`` is the
        Candid encounter ID. On failure, ``message`` is a human-readable error.
        """
        response = self.http.patch(
            f"{self.base_url}/api/encounters/v4/{encounter_id}",
            json=claim_payload,
            headers=self._auth_headers(json_body=True),
        )
        if response.ok:
            return True, response.json().get("encounter_id", encounter_id)
        return False, self._format_error(response)

    def create_service_line(self, payload: dict) -> tuple[bool, str]:
        """Create a service line via POST /api/service-lines/v2.

        ``payload`` must include ``claim_id`` (the Candid claim UUID) alongside
        the service line fields (procedure_code, quantity, units, ...).

        Returns ``(was_successful, message)``. On success, ``message`` is the
        new service_line_id. On failure, ``message`` is a human-readable error.
        """
        response = self.http.post(
            f"{self.base_url}/api/service-lines/v2",
            json=payload,
            headers=self._auth_headers(json_body=True),
        )
        if response.ok:
            return True, response.json().get("service_line_id", "")
        return False, self._format_error(response)

    def update_service_line(
        self, service_line_id: str, payload: dict
    ) -> tuple[bool, str]:
        """Update a service line via PATCH /api/service-lines/v2/{service_line_id}.

        Returns ``(was_successful, message)``. On success, ``message`` is the
        service_line_id. On failure, ``message`` is a human-readable error.
        """
        response = self.http.patch(
            f"{self.base_url}/api/service-lines/v2/{service_line_id}",
            json=payload,
            headers=self._auth_headers(json_body=True),
        )
        if response.ok:
            return True, response.json().get("service_line_id", service_line_id)
        return False, self._format_error(response)

    def delete_service_line(self, service_line_id: str) -> tuple[bool, str]:
        """Delete a service line via DELETE /api/service-lines/v2/{service_line_id}."""
        response = self.http.delete(
            f"{self.base_url}/api/service-lines/v2/{service_line_id}",
            headers=self._auth_headers(),
        )
        if response.ok:
            return True, service_line_id
        return False, self._format_error(response)

    # ------------------------------------------------------------------
    # Patient payment reporting (Canvas → Candid)
    # ------------------------------------------------------------------

    def submit_payment(self, payment_payload: dict) -> tuple[bool, str]:
        """Report a patient payment to Candid's /patient-payments/v4 endpoint.

        Returns ``(was_successful, message)``. On success, ``message`` is the
        Candid ``patient_payment_id``. On failure, ``message`` is a
        human-readable error.
        """
        response = self.http.post(
            f"{self.base_url}/api/patient-payments/v4",
            json=payment_payload,
            headers=self._auth_headers(json_body=True),
        )
        if response.ok:
            return True, response.json().get("patient_payment_id", "")
        return False, self._format_error(response)

    # ------------------------------------------------------------------
    # Encounter retrieval (for status/banner updates)
    # ------------------------------------------------------------------

    def get_encounter(self, encounter_id: str) -> dict:
        """Fetch a single encounter from Candid by encounter_id.

        The response contains ``claims[]`` with per-claim ``status``,
        ``eras[]``, and ``service_lines[]`` — all the data needed for
        adjudication sync (insurance payments, adjustments, patient
        responsibility).
        """
        response = self.http.get(
            f"{self.base_url}/api/encounters/v4/{encounter_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Patient payments (Candid -> Canvas sync)
    # ------------------------------------------------------------------

    def get_patient_payments(self, claim_id: str) -> list[dict]:
        """Fetch patient payments for a Candid claim.

        Uses ``GET /api/patient-payments/v4?claim_id={claim_id}``, sorted by
        payment_timestamp descending so the most recent payments come first.
        """
        query = urlencode(
            {
                "claim_id": claim_id,
                "sort": "payment_timestamp",
                "sort_direction": "desc",
            }
        )
        response = self.http.get(
            f"{self.base_url}/api/patient-payments/v4?{query}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get("items", [])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _auth_headers(self, json_body: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _format_error(response: "Response") -> str:
        try:
            body = response.json()
        except ValueError:
            return f"<{response.status_code}> {response.text[:500]}"

        error_name = body.get("errorName", "Unknown Error")
        additional_messages = []

        if error_name == "HttpRequestValidationError":
            err = body.get("content", {})
            additional_messages.append(
                f"{err.get('fieldName', '?')}: {err.get('humanReadableMessage', '?')}"
            )
        elif error_name == "HttpRequestValidationsError":
            for err in body.get("content", []):
                additional_messages.append(
                    f"{err.get('fieldName', '?')}: {err.get('humanReadableMessage', '?')}"
                )
        elif isinstance(body.get("detail"), list):
            for err in body["detail"]:
                additional_messages.append(
                    f"{err.get('type', '?')}: {err.get('msg', '?')}. In: {err.get('loc', '?')}"
                )

        suffix = f" {', '.join(additional_messages)}" if additional_messages else ""
        return f"<{response.status_code} {error_name}>{suffix}"
