"""Thin client for the Photon Health Clinical (GraphQL) API.

Wraps OAuth client-credentials auth and the GraphQL mutations/queries the
integration needs. All HTTP goes through the Canvas SDK ``Http`` client (30s
timeout, URL validation, metrics) — never raw requests/httpx.

Environment selection (``sandbox`` vs ``production``) drives both the OAuth and
API hosts:

* sandbox (Neutron): https://auth.neutron.health , https://api.neutron.health
* production (Photon): https://auth.photon.health , https://api.photon.health
"""

from __future__ import annotations

from typing import Any, cast

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils.http import Http
from logger import log

# OAuth tokens are valid for 24h; refresh a little early.
_TOKEN_TTL_SECONDS = 23 * 60 * 60

_ENVIRONMENTS = {
    "sandbox": {
        "auth_url": "https://auth.neutron.health/oauth/token",
        "audience": "https://api.neutron.health",
        "graphql_url": "https://api.neutron.health/graphql",
    },
    "production": {
        "auth_url": "https://auth.photon.health/oauth/token",
        "audience": "https://api.photon.health",
        "graphql_url": "https://api.photon.health/graphql",
    },
}


class PhotonError(Exception):
    """Raised for any expected Photon API failure (auth, GraphQL, lookup)."""


class PhotonClient:
    """Minimal Photon GraphQL client scoped to the prescription flow."""

    def __init__(self, client_id: str, client_secret: str, env: str = "sandbox") -> None:
        if not client_id or not client_secret:
            raise PhotonError("Photon credentials are not configured")
        self.client_id = client_id
        self.client_secret = client_secret
        self.env = env if env in _ENVIRONMENTS else "sandbox"
        config = _ENVIRONMENTS[self.env]
        self.auth_url = config["auth_url"]
        self.audience = config["audience"]
        self.graphql_url = config["graphql_url"]
        self._http = Http()

    # -- auth --------------------------------------------------------------

    def _fetch_token(self) -> str:
        """Request a fresh M2M access token from Photon's OAuth endpoint."""
        response = self._http.post(
            self.auth_url,
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "audience": self.audience,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise PhotonError(
                f"Photon auth failed ({response.status_code}): {response.text[:200]}"
            )
        token = response.json().get("access_token")
        if not token:
            raise PhotonError("Photon auth response did not include an access_token")
        return str(token)

    def _get_token(self) -> str:
        """Return a cached token, fetching (and caching) one when absent."""
        cache_key = f"photon_token_{self.env}"
        # get_or_set only invokes the default (and thus the HTTP request) on a
        # cache miss; a failed fetch raises and nothing is cached.
        return str(get_cache().get_or_set(cache_key, self._fetch_token, _TOKEN_TTL_SECONDS))

    # -- graphql -----------------------------------------------------------

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._http.post(
            self.graphql_url,
            json={"query": query, "variables": variables},
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
            },
        )
        if response.status_code != 200:
            raise PhotonError(
                f"Photon GraphQL HTTP {response.status_code}: {response.text[:200]}"
            )
        body = response.json()
        if body.get("errors"):
            raise PhotonError(f"Photon GraphQL error: {body['errors']}")
        data = body.get("data")
        if data is None:
            raise PhotonError("Photon GraphQL response contained no data")
        return cast("dict[str, Any]", data)

    # -- patients ----------------------------------------------------------

    def create_patient(self, patient_input: dict[str, Any]) -> str:
        """Create a Photon patient and return its id.

        ``patient_input`` keys map to the createPatient arguments: externalId,
        name (NameInput), dateOfBirth (AWSDate), sex (SexType), gender, email,
        phone (AWSPhone), address (AddressInput).
        """
        mutation = """
            mutation createPatient(
              $externalId: ID
              $name: NameInput!
              $dateOfBirth: AWSDate!
              $sex: SexType!
              $gender: String
              $email: AWSEmail
              $phone: AWSPhone!
              $address: AddressInput
            ) {
              createPatient(
                externalId: $externalId
                name: $name
                dateOfBirth: $dateOfBirth
                sex: $sex
                gender: $gender
                email: $email
                phone: $phone
                address: $address
              ) { id }
            }
        """
        created = self._graphql(mutation, patient_input).get("createPatient")
        if not created or not created.get("id"):
            raise PhotonError("Photon createPatient did not return an id")
        return str(created["id"])

    # -- treatments (medication catalog) -----------------------------------

    def find_treatment_id(self, term: str) -> str | None:
        """Look up a Photon treatment (medication) id by search ``term``.

        Photon's treatment catalog is searched by free-text term (drug name).
        Direct NDC lookup is not yet generally available, so we match on the
        medication name from the Canvas command and take the top result.
        """
        if not term:
            return None
        query = """
            query treatments($filter: TreatmentFilter!) {
              treatments(filter: $filter) { id name }
            }
        """
        treatments = (
            self._graphql(query, {"filter": {"term": term}}).get("treatments") or []
        )
        if treatments:
            return str(treatments[0]["id"])
        return None

    # -- prescribers -------------------------------------------------------

    def find_prescriber_id_by_external_id(self, external_id: str) -> str | None:
        """Return the Photon provider id whose externalId matches ``external_id``."""
        if not external_id:
            return None
        query = """
            query providers($externalId: ID) {
              providers(filter: { externalId: $externalId }) { id }
            }
        """
        providers = (
            self._graphql(query, {"externalId": external_id}).get("providers") or []
        )
        if providers:
            return str(providers[0]["id"])
        return None

    # -- prescriptions & orders --------------------------------------------

    def create_prescription(self, prescription_input: dict[str, Any]) -> str:
        """Create a Photon prescription and return its id.

        NOTE: Photon expresses refills as ``fillsAllowed`` (total fills =
        Canvas refills + 1). Verify this field name against your sandbox account
        during UAT — it is the most integration-specific detail here.
        """
        # NOTE: prescriberId is passed so the prescription is attributed to the
        # mapped Photon provider. If your Photon account instead infers the
        # prescriber from a user-access token, drop this argument during UAT.
        mutation = """
            mutation createPrescription(
              $externalId: ID
              $patientId: ID!
              $prescriberId: ID
              $medicationId: ID!
              $dispenseAsWritten: Boolean
              $dispenseQuantity: Float!
              $dispenseUnit: String!
              $fillsAllowed: Int!
              $daysSupply: Int
              $instructions: String!
              $notes: String
              $effectiveDate: AWSDate
            ) {
              createPrescription(
                externalId: $externalId
                patientId: $patientId
                prescriberId: $prescriberId
                medicationId: $medicationId
                dispenseAsWritten: $dispenseAsWritten
                dispenseQuantity: $dispenseQuantity
                dispenseUnit: $dispenseUnit
                fillsAllowed: $fillsAllowed
                daysSupply: $daysSupply
                instructions: $instructions
                notes: $notes
                effectiveDate: $effectiveDate
              ) { id }
            }
        """
        created = self._graphql(mutation, prescription_input).get("createPrescription")
        if not created or not created.get("id"):
            raise PhotonError("Photon createPrescription did not return an id")
        return str(created["id"])

    def create_order(
        self,
        patient_id: str,
        prescription_id: str,
        address: dict[str, Any],
        pharmacy_id: str | None = None,
        external_id: str | None = None,
    ) -> str:
        """Create a Photon order for a prescription and return its id.

        When ``pharmacy_id`` is omitted Photon routes to the patient's preferred
        pharmacy.
        """
        mutation = """
            mutation createOrder(
              $externalId: ID
              $patientId: ID!
              $fills: [FillInput!]!
              $address: AddressInput!
              $pharmacyId: ID
            ) {
              createOrder(
                externalId: $externalId
                patientId: $patientId
                fills: $fills
                address: $address
                pharmacyId: $pharmacyId
              ) { id }
            }
        """
        variables: dict[str, Any] = {
            "externalId": external_id,
            "patientId": patient_id,
            "fills": [{"prescriptionId": prescription_id}],
            "address": address,
            "pharmacyId": pharmacy_id,
        }
        created = self._graphql(mutation, variables).get("createOrder")
        if not created or not created.get("id"):
            raise PhotonError("Photon createOrder did not return an id")
        log.info("Photon order %s created for prescription %s", created["id"], prescription_id)
        return str(created["id"])
