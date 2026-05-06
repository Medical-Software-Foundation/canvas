import requests


class CandidClient:
    """HTTP client for Candid Health's API."""

    def __init__(self, base_url: str, client_id: str, client_secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._cached_token: str | None = None

    @classmethod
    def from_secrets(cls, secrets: dict) -> "CandidClient":
        return cls(
            base_url=secrets["CANDID_BASE_URL"],
            client_id=secrets["CANDID_CLIENT_ID"],
            client_secret=secrets["CANDID_CLIENT_SECRET"],
        )

    def _token(self) -> str:
        if not self._cached_token:
            self._cached_token = self._fetch_token()
        return self._cached_token

    def _fetch_token(self) -> str:
        response = requests.post(
            f"{self.base_url}/api/auth/v2/token",
            json={"client_id": self.client_id, "client_secret": self.client_secret},
            timeout=30,
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
        response = requests.post(
            f"{self.base_url}/api/encounters/v4",
            json=claim_payload,
            headers=self._auth_headers(json_body=True),
            timeout=30,
        )
        if response.ok:
            return True, response.json().get("encounter_id", "")
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
        response = requests.post(
            f"{self.base_url}/api/patient-payments/v4",
            json=payment_payload,
            headers=self._auth_headers(json_body=True),
            timeout=30,
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
        response = requests.get(
            f"{self.base_url}/api/encounters/v4/{encounter_id}",
            headers=self._auth_headers(),
            timeout=30,
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
        response = requests.get(
            f"{self.base_url}/api/patient-payments/v4",
            params={
                "claim_id": claim_id,
                "sort": "payment_timestamp",
                "sort_direction": "desc",
            },
            headers=self._auth_headers(),
            timeout=30,
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
    def _format_error(response: requests.Response) -> str:
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
