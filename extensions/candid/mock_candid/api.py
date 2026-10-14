"""Mock Candid Health API endpoints.

Implements the Candid endpoints the candid plugin calls and answers them from
state kept in the plugin cache, so every container on the instance sees the
same encounters, scenarios and payments, and they survive restarts. Point the
candid plugin's ``CANDID_BASE_URL`` at
``https://<instance>/plugin-io/api/mock_candid``.

Adjudication data comes from a per-claim scenario (``POST /scenario``) when the
claim has one, otherwise from the global config (``POST /configure``).

**Passthrough mode:** set ``passthrough_base_url`` via ``POST /configure`` to
proxy all ``/api/*`` requests to a real Candid API (e.g. staging). The candid
plugin's own credentials flow through.
"""

import hmac
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    APIKeyCredentials,
    Credentials,
    SimpleAPI,
    api,
)
from canvas_sdk.utils.http import Http
from logger import log

API_KEY_SECRET = "MOCK_CANDID_API_KEY"
GENERATION_KEY = "generation"

_ADJUDICATION_FIELDS = (
    "primary_paid_amount_cents",
    "secondary_paid_amount_cents",
    "tertiary_paid_amount_cents",
    "allowed_amount_cents",
    "deductible_cents",
    "coinsurance_cents",
    "copay_cents",
    "insurance_balance_cents",
    "patient_balance_cents",
)

# What a scenario controls. Amounts apply to every service line of the encounter.
# ``eras`` is ordered by payer (primary, secondary, tertiary); ``era`` is a single ERA.
SCENARIO_DEFAULTS: dict[str, Any] = {
    "encounter_status": "coded",
    "era": None,
    "eras": None,
    **dict.fromkeys(_ADJUDICATION_FIELDS),
    "next_responsible_party": None,
    # ERA-reported adjustments (from payer) — goes to service_line_era_data
    "service_line_era_adjustments": [],
    # Manual adjustments — goes to service_line_manual_adjustments
    "service_line_manual_adjustments": [],
}

DEFAULT_CONFIG: dict[str, Any] = {
    **SCENARIO_DEFAULTS,
    # Passthrough: set to a real Candid base URL (e.g.
    # "https://api-staging.joincandidhealth.com") to proxy all /api/* requests.
    "passthrough_base_url": None,
    "fail_next_encounter_submit": False,
    "fail_next_payment_submit": False,
    "encounter_submit_error": None,
    "payment_submit_error": None,
    "valid_client_id": None,
    "valid_client_secret": None,
}


class MockStore:
    """Mock state in the plugin cache, shared by every container and kept across restarts.

    Keys live under a generation id, so a reset only has to start a new generation.
    """

    def __init__(self) -> None:
        self.cache = get_cache()
        self.generation = self.cache.get_or_set(
            GENERATION_KEY, lambda: uuid.uuid4().hex
        )

    def _key(self, *parts: str) -> str:
        return ":".join((self.generation, *parts))

    def get(self, *parts: str, default: Any = None) -> Any:
        return self.cache.get(self._key(*parts), default)

    def put(self, value: Any, *parts: str) -> None:
        self.cache.set(self._key(*parts), value)
        # Keep the generation alive as long as the newest data stored under it
        self.cache.set(GENERATION_KEY, self.generation)

    def append(self, value: Any, *parts: str) -> None:
        self.put([*self.get(*parts, default=[]), value], *parts)

    def reset(self) -> None:
        self.generation = uuid.uuid4().hex
        self.cache.set(GENERATION_KEY, self.generation)

    def config(self) -> dict[str, Any]:
        return {**DEFAULT_CONFIG, **self.get("config", default={})}

    def update_config(self, updates: dict[str, Any]) -> None:
        self.put({**self.get("config", default={}), **updates}, "config")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _scenario_key(external_id: str) -> str:
    """The claim-level external id a scenario is stored under.

    A claim split for more than 12 diagnoses submits its main encounter as
    ``<external_id>-1``; a UUID never ends in ``-1``, so this only strips that suffix.
    """
    return external_id[:-2] if external_id.endswith("-1") else external_id


def _claim_external_id(body: Any) -> str:
    """The external id a control request targets: ``external_id``, or ``canvas:<claim_id>``."""
    if body.get("external_id"):
        return str(body["external_id"])
    if body.get("claim_id"):
        return f"canvas:{body['claim_id']}"
    return ""


def _split_known(
    body: dict, allowed: dict[str, Any], skip: tuple[str, ...]
) -> tuple[dict[str, Any], list[str]]:
    """Split a request body into the settings it may change and the keys it can't."""
    known = {key: value for key, value in body.items() if key in allowed}
    ignored = sorted(key for key in body if key not in allowed and key not in skip)
    return known, ignored


def _eras(settings: dict[str, Any]) -> list[dict]:
    if settings.get("eras") is not None:
        return [dict(era) for era in settings["eras"]]
    return [dict(settings["era"])] if settings.get("era") else []


def _settings_for(store: MockStore, external_id: str) -> dict[str, Any]:
    """The claim's own scenario when it has one, else the global config."""
    scenario = (
        store.get("scenario", _scenario_key(external_id)) if external_id else None
    )
    if scenario is None:
        return store.config()
    return {**SCENARIO_DEFAULTS, **scenario}


def _new_encounter(payload: dict) -> dict:
    """Build the stored encounter for a submitted payload, shaped like Candid's."""
    encounter_id = str(uuid.uuid4())
    candid_claim_id = f"candid-claim-{str(uuid.uuid4())[:8]}"
    now = datetime.now(UTC).isoformat()
    encounter_dos = payload.get("date_of_service")

    # Keep the full submitted payload so /status comparisons can see every field
    encounter = dict(payload)
    encounter.update(
        {
            "encounter_id": encounter_id,
            "candid_claim_id": candid_claim_id,
            "status": "coded",
            "created_at": now,
            "updated_at": now,
        }
    )

    # Normalize service lines to match Candid's real response shape:
    # - charge_amount_cents as int (Candid normalizes even if sent as string)
    # - date_of_service_range populated from encounter-level date_of_service
    # - all adjudication fields present as null
    normalized_lines = []
    for sl in encounter.get("service_lines", []):
        charge = sl.get("charge_amount_cents")
        if isinstance(charge, str):
            charge = int(charge)
        normalized_lines.append(
            {
                "service_line_id": str(uuid.uuid4()),
                "claim_id": candid_claim_id,
                "procedure_code": sl.get("procedure_code"),
                "quantity": sl.get("quantity"),
                "units": sl.get("units", "UN"),
                "charge_amount_cents": charge,
                "modifiers": sl.get("modifiers", []),
                "diagnosis_pointers": sl.get("diagnosis_pointers"),
                "external_id": sl.get("external_id"),
                "date_of_service": encounter_dos,
                "date_of_service_range": {
                    "start_date": encounter_dos,
                    "end_date": None,
                },
                # Adjudication fields — null until enriched
                "allowed_amount_cents": None,
                "insurance_balance_cents": None,
                "patient_balance_cents": 0,
                "paid_amount_cents": None,
                "primary_paid_amount_cents": None,
                "secondary_paid_amount_cents": None,
                "tertiary_paid_amount_cents": None,
                "patient_responsibility_cents": None,
                "copay_cents": None,
                "coinsurance_cents": None,
                "deductible_cents": None,
                "service_line_era_data": {
                    "service_line_adjustments": [],
                    "remittance_advice_remark_codes": [],
                },
                "service_line_manual_adjustments": [],
                "denial_reason": None,
            }
        )
    encounter["service_lines"] = normalized_lines
    return encounter


def _save_encounter(store: MockStore, encounter: dict, payload: dict) -> None:
    encounter_id = encounter["encounter_id"]
    store.put(
        {"encounter": encounter, "submitted_payload": dict(payload)},
        "encounter",
        encounter_id,
    )
    if encounter.get("external_id"):
        store.put(encounter_id, "external", encounter["external_id"])
    store.append(encounter_id, "encounter_ids")


def _encounter_by_external_id(store: MockStore, external_id: str) -> dict | None:
    encounter_id = store.get("external", external_id)
    record = store.get("encounter", encounter_id) if encounter_id else None
    return record["encounter"] if record else None


def _enrich_encounter(store: MockStore, encounter: dict) -> dict:
    """Build a GET encounter response matching Candid's actual schema.

    Returns the full encounter with ``claims[]`` containing per-claim
    ``status``, ``eras[]``, and ``service_lines[]`` — the structure
    ``adjudication_sync`` expects. Service lines carry all adjudication
    fields (null when unconfigured, matching real Candid responses).
    """
    settings = _settings_for(store, encounter.get("external_id", ""))

    # Overlay configured adjudication values onto the stored line, which
    # already has null defaults from _new_encounter
    enriched_lines = []
    for sl in encounter.get("service_lines", []):
        enriched_sl = dict(sl)
        for field in _ADJUDICATION_FIELDS:
            if settings[field] is not None:
                enriched_sl[field] = settings[field]
        if settings["service_line_era_adjustments"]:
            enriched_sl["service_line_era_data"] = {
                "service_line_adjustments": list(
                    settings["service_line_era_adjustments"]
                ),
                "remittance_advice_remark_codes": [],
            }
        if settings["service_line_manual_adjustments"]:
            enriched_sl["service_line_manual_adjustments"] = list(
                settings["service_line_manual_adjustments"]
            )
        enriched_lines.append(enriched_sl)

    return {
        "encounter_id": encounter["encounter_id"],
        "external_id": encounter.get("external_id", ""),
        "date_of_service": encounter.get("date_of_service"),
        "patient": encounter.get("patient"),
        "billing_provider": encounter.get("billing_provider"),
        "rendering_provider": encounter.get("rendering_provider"),
        "service_facility": encounter.get("service_facility"),
        "subscriber_primary": encounter.get("subscriber_primary"),
        "subscriber_secondary": encounter.get("subscriber_secondary"),
        "diagnoses": encounter.get("diagnoses"),
        "responsible_party": encounter.get("responsible_party"),
        "place_of_service_code": encounter.get("place_of_service_code"),
        "next_responsible_party": settings["next_responsible_party"],
        "created_at": encounter.get("created_at"),
        "updated_at": datetime.now(UTC).isoformat(),
        "claims": [
            {
                "claim_id": encounter["candid_claim_id"],
                "status": settings["encounter_status"],
                "service_lines": enriched_lines,
                "eras": _eras(settings),
            }
        ],
        "patient_payments": [],
        "tags": [],
    }


def _store_patient_payment(store: MockStore, payload: dict) -> dict:
    now = datetime.now(UTC).isoformat()
    payment = {
        "patient_payment_id": str(uuid.uuid4()),
        "patient_external_id": payload.get("patient_external_id", ""),
        "amount_cents": payload.get("amount_cents", 0),
        "payment_timestamp": payload.get("payment_timestamp", now),
        "payment_note": payload.get("payment_note", ""),
        "allocations": payload.get("allocations", []),
        "created_at": now,
    }
    store.append(payment, "all_payments")

    # Index by Candid claim_id (not encounter_id) to match the real API
    for alloc in payload.get("allocations", []):
        target = alloc.get("target", {})
        if target.get("type") != "claim_by_encounter_external_id":
            continue
        encounter = _encounter_by_external_id(store, target.get("value", ""))
        if encounter:
            store.append(payment, "claim_payments", encounter["candid_claim_id"])

    return payment


# ----------------------------------------------------------------------
# Candid API (called by the candid plugin)
# ----------------------------------------------------------------------


class MockCandidAPI(SimpleAPI):
    """The Candid API endpoints the candid plugin calls."""

    PREFIX = ""

    def authenticate(self, credentials: Credentials) -> bool:
        # Open so the candid plugin can keep its real (write-only) Candid credentials
        return True

    def _proxy(
        self, config: dict[str, Any], method: str, path: str, body: Any = None
    ) -> JSONResponse:
        """Forward a request to the real Candid API and return the response."""
        url = f"{config['passthrough_base_url'].rstrip('/')}{path}"
        headers: dict[str, str] = {}
        auth = self.request.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth

        http = Http()
        if method == "POST":
            resp = http.post(url, json=body, headers=headers)
        else:
            resp = http.get(url, headers=headers)
        try:
            data = resp.json()
        except ValueError:
            data = {"error": resp.text[:500]}
        return JSONResponse(data, status_code=resp.status_code)

    @api.post("/api/auth/v2/token")
    def auth_token(self) -> list[Response | Effect]:
        body = self.request.json()
        config = MockStore().config()

        if config["passthrough_base_url"]:
            return [self._proxy(config, "POST", "/api/auth/v2/token", body=body)]

        # When valid_client_id/secret are set, enforce them; otherwise accept any
        expected_id = config["valid_client_id"]
        expected_secret = config["valid_client_secret"]
        if expected_id is not None and expected_secret is not None:
            if (
                body.get("client_id") != expected_id
                or body.get("client_secret") != expected_secret
            ):
                return [
                    JSONResponse(
                        {"error": "invalid_credentials"},
                        status_code=HTTPStatus.UNAUTHORIZED,
                    )
                ]

        return [
            JSONResponse(
                {
                    "access_token": "mock-token-for-testing",
                    "expires_in": 18000,
                    "token_type": "Bearer",
                }
            )
        ]

    @api.post("/api/encounters/v4")
    def create_encounter(self) -> list[Response | Effect]:
        body = self.request.json()
        store = MockStore()
        config = store.config()

        if config["passthrough_base_url"]:
            return [self._proxy(config, "POST", "/api/encounters/v4", body=body)]

        if config["fail_next_encounter_submit"]:
            store.update_config({"fail_next_encounter_submit": False})
            error = dict(
                config["encounter_submit_error"] or {"errorName": "InternalServerError"}
            )
            status_code = error.pop("status_code", 500)
            return [JSONResponse(error, status_code=status_code)]

        encounter = _new_encounter(body)
        _save_encounter(store, encounter, body)

        # Real Candid API returns the full encounter; the plugin only reads
        # encounter_id but returning the full shape helps with payload comparison
        return [JSONResponse(_enrich_encounter(store, encounter))]

    @api.get("/api/encounters/v4/<encounter_id>")
    def get_encounter(self) -> list[Response | Effect]:
        encounter_id = self.request.path_params.get("encounter_id", "")
        store = MockStore()
        config = store.config()

        if config["passthrough_base_url"]:
            return [self._proxy(config, "GET", f"/api/encounters/v4/{encounter_id}")]

        record = store.get("encounter", encounter_id)
        if not record:
            return [
                JSONResponse(
                    {"error": "encounter_not_found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        return [JSONResponse(_enrich_encounter(store, record["encounter"]))]

    @api.post("/api/patient-payments/v4")
    def create_patient_payment(self) -> list[Response | Effect]:
        body = self.request.json()
        store = MockStore()
        config = store.config()

        if config["passthrough_base_url"]:
            return [self._proxy(config, "POST", "/api/patient-payments/v4", body=body)]

        if config["fail_next_payment_submit"]:
            store.update_config({"fail_next_payment_submit": False})
            error = dict(
                config["payment_submit_error"] or {"errorName": "InternalServerError"}
            )
            status_code = error.pop("status_code", 500)
            return [JSONResponse(error, status_code=status_code)]

        payment = _store_patient_payment(store, body)
        return [JSONResponse({"patient_payment_id": payment["patient_payment_id"]})]

    @api.get("/api/patient-payments/v4")
    def list_patient_payments(self) -> list[Response | Effect]:
        store = MockStore()
        config = store.config()

        if config["passthrough_base_url"]:
            query = self.request.query_string
            path = (
                f"/api/patient-payments/v4?{query}"
                if query
                else "/api/patient-payments/v4"
            )
            return [self._proxy(config, "GET", path)]

        claim_id = self.request.query_params.get("claim_id", "")
        return [
            JSONResponse({"items": store.get("claim_payments", claim_id, default=[])})
        ]


# ----------------------------------------------------------------------
# Test control (called by testers, requires MOCK_CANDID_API_KEY)
# ----------------------------------------------------------------------


class MockCandidControlAPI(SimpleAPI):
    """Test-control endpoints: global config, per-claim scenarios, payment injection, state."""

    PREFIX = ""

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        expected = self.secrets.get(API_KEY_SECRET, "")
        if not expected:
            log.warning(
                f"mock_candid: {API_KEY_SECRET} is not set, denying control request"
            )
            return False
        return hmac.compare_digest(credentials.key, expected)

    @api.post("/configure")
    def configure(self) -> list[Response | Effect]:
        body = self.request.json()
        store = MockStore()

        if body.get("reset"):
            store.reset()

        updates, ignored = _split_known(body, DEFAULT_CONFIG, skip=("reset",))
        store.update_config(updates)
        return [
            JSONResponse(
                {"status": "configured", "config": store.config(), "ignored": ignored}
            )
        ]

    @api.post("/scenario")
    def set_scenario(self) -> list[Response | Effect]:
        body = self.request.json()
        external_id = _claim_external_id(body)
        if not external_id:
            return [
                JSONResponse(
                    {"error": "Send claim_id (the Canvas claim id) or external_id"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        updates, ignored = _split_known(
            body, SCENARIO_DEFAULTS, skip=("claim_id", "external_id", "reset")
        )
        eras = updates.get("eras")
        if eras is not None and not (
            isinstance(eras, list)
            and all(isinstance(era, dict) and era.get("era_id") for era in eras)
        ):
            return [
                JSONResponse(
                    {
                        "error": "eras must be a list of objects that each have an era_id"
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        store = MockStore()
        key = _scenario_key(external_id)
        current = {} if body.get("reset") else store.get("scenario", key, default={})
        store.put({**current, **updates}, "scenario", key)
        if key not in store.get("scenario_ids", default=[]):
            store.append(key, "scenario_ids")

        return [
            JSONResponse(
                {
                    "status": "configured",
                    "external_id": key,
                    "scenario": _settings_for(store, key),
                    "ignored": ignored,
                }
            )
        ]

    @api.post("/inject-patient-payment")
    def inject_patient_payment(self) -> list[Response | Effect]:
        body = self.request.json()
        encounter_ext_id = body.get("encounter_external_id", "")
        amount_cents = body.get("amount_cents", 0)
        store = MockStore()

        if not _encounter_by_external_id(store, encounter_ext_id):
            return [
                JSONResponse(
                    {"error": f"No encounter with external_id={encounter_ext_id}"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        payment = _store_patient_payment(
            store,
            {
                "patient_external_id": "canvas:injected",
                "amount_cents": amount_cents,
                "payment_note": "Injected for testing",
                "allocations": [
                    {
                        "target": {
                            "type": "claim_by_encounter_external_id",
                            "value": encounter_ext_id,
                        },
                        "amount_cents": amount_cents,
                    }
                ],
            },
        )

        return [
            JSONResponse(
                {
                    "status": "injected",
                    "patient_payment_id": payment["patient_payment_id"],
                }
            )
        ]

    @api.get("/status")
    def status(self) -> list[Response | Effect]:
        store = MockStore()
        external_id = _claim_external_id(self.request.query_params)
        if external_id:
            return [self._claim_status(store, external_id)]

        encounters = []
        for encounter_id in store.get("encounter_ids", default=[]):
            record = store.get("encounter", encounter_id)
            if record:
                encounter = record["encounter"]
                encounters.append(
                    {
                        "encounter_id": encounter_id,
                        "external_id": encounter.get("external_id", ""),
                        "candid_claim_id": encounter["candid_claim_id"],
                        "created_at": encounter.get("created_at"),
                    }
                )

        return [
            JSONResponse(
                {
                    "config": store.config(),
                    "scenarios": {
                        key: store.get("scenario", key)
                        for key in store.get("scenario_ids", default=[])
                    },
                    "encounters": encounters,
                    "patient_payments": store.get("all_payments", default=[]),
                }
            )
        ]

    def _claim_status(self, store: MockStore, external_id: str) -> JSONResponse:
        """One claim's scenario, its encounter as the candid plugin sees it, and its payments."""
        key = _scenario_key(external_id)
        encounter_id = store.get("external", key) or store.get("external", f"{key}-1")
        record = store.get("encounter", encounter_id) if encounter_id else None
        encounter = record["encounter"] if record else None
        return JSONResponse(
            {
                "external_id": key,
                "scenario": _settings_for(store, key),
                "encounter": _enrich_encounter(store, encounter) if encounter else None,
                "submitted_payload": record["submitted_payload"] if record else None,
                "patient_payments": (
                    store.get(
                        "claim_payments", encounter["candid_claim_id"], default=[]
                    )
                    if encounter
                    else []
                ),
            }
        )
