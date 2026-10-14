"""Tests for the mock Candid API used for end-to-end testing of the candid plugin."""

import copy
import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from mock_candid.api import GENERATION_KEY, MockCandidAPI, MockCandidControlAPI

API_KEY = "test-api-key"
CLAIM_A = "11111111-1111-1111-1111-111111111111"
CLAIM_B = "22222222-2222-2222-2222-222222222222"

PRIMARY_ERA = {
    "era_id": "era-primary",
    "check_number": "CHK1",
    "check_date": "2026-10-15",
}
SECONDARY_ERA = {
    "era_id": "era-secondary",
    "check_number": "CHK2",
    "check_date": "2026-10-16",
}


class FakeCache:
    """Stands in for the plugin cache; copies values like the pickling backend does."""

    def __init__(self) -> None:
        self.data: dict = {}

    def get(self, key, default=None):
        return copy.deepcopy(self.data.get(key, default))

    def set(self, key, value, timeout_seconds=None):
        self.data[key] = copy.deepcopy(value)

    def get_or_set(self, key, default=None, timeout_seconds=None):
        if key not in self.data:
            self.data[key] = default() if callable(default) else default
        return copy.deepcopy(self.data[key])


@pytest.fixture(autouse=True)
def cache():
    fake = FakeCache()
    with patch("mock_candid.api.get_cache", side_effect=lambda: fake):
        yield fake


def _call(cls, route, body=None, path_params=None, query_params=None, headers=None):
    """Run one route on a fresh handler and return (status_code, decoded body)."""
    handler = cls.__new__(cls)
    handler.secrets = {"MOCK_CANDID_API_KEY": API_KEY}
    handler.request = MagicMock()
    handler.request.json.return_value = body or {}
    handler.request.path_params = path_params or {}
    handler.request.query_params = query_params or {}
    handler.request.query_string = ""
    handler.request.headers = headers or {}
    (response,) = getattr(handler, route)()
    return response.status_code, json.loads(response.content)


def _submit(claim_id, external_id=None, lines=1):
    payload = {
        "external_id": external_id or f"canvas:{claim_id}",
        "date_of_service": "2026-10-01",
        "service_lines": [
            {"procedure_code": "99213", "charge_amount_cents": "20000", "quantity": "1"}
            for _ in range(lines)
        ],
    }
    status, body = _call(MockCandidAPI, "create_encounter", body=payload)
    assert status == HTTPStatus.OK
    return body["encounter_id"]


def _get_encounter(encounter_id):
    return _call(
        MockCandidAPI, "get_encounter", path_params={"encounter_id": encounter_id}
    )


def _scenario(**body):
    return _call(MockCandidControlAPI, "set_scenario", body=body)


def _configure(**body):
    return _call(MockCandidControlAPI, "configure", body=body)


# ----------------------------------------------------------------------
# Shared state
# ----------------------------------------------------------------------


def test_state_lives_in_the_plugin_cache(cache):
    encounter_id = _submit(CLAIM_A)

    # Another container reads the same cache rows and finds the encounter
    other_container = FakeCache()
    other_container.data = copy.deepcopy(cache.data)
    with patch("mock_candid.api.get_cache", side_effect=lambda: other_container):
        status, body = _get_encounter(encounter_id)
    assert status == HTTPStatus.OK
    assert body["external_id"] == f"canvas:{CLAIM_A}"

    # Nothing is kept in process memory: an empty cache knows no encounters
    with patch("mock_candid.api.get_cache", side_effect=lambda: FakeCache()):
        status, _ = _get_encounter(encounter_id)
    assert status == HTTPStatus.NOT_FOUND


def test_unknown_encounter_returns_404():
    status, body = _get_encounter("missing")
    assert status == HTTPStatus.NOT_FOUND
    assert body == {"error": "encounter_not_found"}


def test_reset_starts_a_new_generation(cache):
    encounter_id = _submit(CLAIM_A)
    _scenario(claim_id=CLAIM_A, encounter_status="era_received")
    generation = cache.data[GENERATION_KEY]

    status, body = _configure(reset=True, encounter_status="paid")

    assert status == HTTPStatus.OK
    assert cache.data[GENERATION_KEY] != generation
    assert body["config"]["encounter_status"] == "paid"
    assert _get_encounter(encounter_id)[0] == HTTPStatus.NOT_FOUND
    _, state = _call(MockCandidControlAPI, "status")
    assert state["scenarios"] == {}
    assert state["encounters"] == []


# ----------------------------------------------------------------------
# Per-claim scenarios
# ----------------------------------------------------------------------


def test_scenario_applies_only_to_its_claim():
    encounter_a = _submit(CLAIM_A)
    encounter_b = _submit(CLAIM_B)
    _scenario(
        claim_id=CLAIM_A,
        encounter_status="era_received",
        eras=[PRIMARY_ERA],
        allowed_amount_cents=15000,
        primary_paid_amount_cents=10000,
        deductible_cents=3000,
        next_responsible_party="secondary",
    )

    _, body_a = _get_encounter(encounter_a)
    _, body_b = _get_encounter(encounter_b)

    claim_a = body_a["claims"][0]
    assert claim_a["status"] == "era_received"
    assert claim_a["eras"] == [PRIMARY_ERA]
    assert claim_a["service_lines"][0]["primary_paid_amount_cents"] == 10000
    assert claim_a["service_lines"][0]["deductible_cents"] == 3000
    assert body_a["next_responsible_party"] == "secondary"

    claim_b = body_b["claims"][0]
    assert claim_b["status"] == "coded"
    assert claim_b["eras"] == []
    assert claim_b["service_lines"][0]["primary_paid_amount_cents"] is None


def test_scenario_updates_merge_and_eras_keep_payer_order():
    encounter_id = _submit(CLAIM_A)
    _scenario(
        claim_id=CLAIM_A,
        eras=[PRIMARY_ERA],
        primary_paid_amount_cents=10000,
        coinsurance_cents=2000,
        next_responsible_party="secondary",
    )
    _scenario(
        claim_id=CLAIM_A,
        eras=[PRIMARY_ERA, SECONDARY_ERA],
        secondary_paid_amount_cents=3500,
        next_responsible_party="patient",
    )

    _, body = _get_encounter(encounter_id)

    line = body["claims"][0]["service_lines"][0]
    assert body["claims"][0]["eras"] == [PRIMARY_ERA, SECONDARY_ERA]
    assert line["primary_paid_amount_cents"] == 10000
    assert line["coinsurance_cents"] == 2000
    assert line["secondary_paid_amount_cents"] == 3500
    assert body["next_responsible_party"] == "patient"


def test_scenario_reset_drops_earlier_fields():
    encounter_id = _submit(CLAIM_A)
    _scenario(claim_id=CLAIM_A, eras=[PRIMARY_ERA], primary_paid_amount_cents=10000)
    _scenario(claim_id=CLAIM_A, reset=True, copay_cents=2500)

    _, body = _get_encounter(encounter_id)

    line = body["claims"][0]["service_lines"][0]
    assert body["claims"][0]["eras"] == []
    assert line["primary_paid_amount_cents"] is None
    assert line["copay_cents"] == 2500


def test_scenario_ignores_the_global_config():
    _configure(primary_paid_amount_cents=999, era={"era_id": "era-global"})
    encounter_a = _submit(CLAIM_A)
    encounter_b = _submit(CLAIM_B)
    _scenario(claim_id=CLAIM_A, deductible_cents=3000)

    line_a = _get_encounter(encounter_a)[1]["claims"][0]["service_lines"][0]
    claim_b = _get_encounter(encounter_b)[1]["claims"][0]

    assert line_a["primary_paid_amount_cents"] is None
    assert line_a["deductible_cents"] == 3000
    assert claim_b["eras"] == [{"era_id": "era-global"}]
    assert claim_b["service_lines"][0]["primary_paid_amount_cents"] == 999


def test_scenario_amounts_apply_to_every_service_line():
    encounter_id = _submit(CLAIM_A, lines=2)
    _scenario(claim_id=CLAIM_A, primary_paid_amount_cents=10000)

    lines = _get_encounter(encounter_id)[1]["claims"][0]["service_lines"]

    assert [line["primary_paid_amount_cents"] for line in lines] == [10000, 10000]


def test_split_claim_main_encounter_uses_the_claim_scenario():
    main = _submit(CLAIM_A, external_id=f"canvas:{CLAIM_A}-1")
    supplemental = _submit(CLAIM_A, external_id=f"canvas:{CLAIM_A}-2")
    _scenario(claim_id=CLAIM_A, eras=[PRIMARY_ERA])

    assert _get_encounter(main)[1]["claims"][0]["eras"] == [PRIMARY_ERA]
    assert _get_encounter(supplemental)[1]["claims"][0]["eras"] == []


def test_scenario_can_target_an_external_id():
    encounter_id = _submit(CLAIM_A)

    status, body = _scenario(external_id=f"canvas:{CLAIM_A}", eras=[PRIMARY_ERA])

    assert status == HTTPStatus.OK
    assert body["external_id"] == f"canvas:{CLAIM_A}"
    assert _get_encounter(encounter_id)[1]["claims"][0]["eras"] == [PRIMARY_ERA]


def test_scenario_requires_a_claim():
    status, body = _scenario(eras=[PRIMARY_ERA])
    assert status == HTTPStatus.BAD_REQUEST
    assert "claim_id" in body["error"]


@pytest.mark.parametrize(
    "eras", [[{"check_number": "CHK1"}], {"era_id": "era-1"}, ["era-1"]]
)
def test_scenario_rejects_eras_without_era_ids(eras):
    status, body = _scenario(claim_id=CLAIM_A, eras=eras)
    assert status == HTTPStatus.BAD_REQUEST
    assert "era_id" in body["error"]


def test_scenario_reports_unknown_fields():
    status, body = _scenario(claim_id=CLAIM_A, primary_paid_cents=100, copay_cents=500)

    assert status == HTTPStatus.OK
    assert body["ignored"] == ["primary_paid_cents"]
    assert body["scenario"]["copay_cents"] == 500


# ----------------------------------------------------------------------
# Global config
# ----------------------------------------------------------------------


def test_single_global_era_is_still_supported():
    encounter_id = _submit(CLAIM_A)
    _configure(encounter_status="adjudicated", era=PRIMARY_ERA)

    claim = _get_encounter(encounter_id)[1]["claims"][0]

    assert claim["status"] == "adjudicated"
    assert claim["eras"] == [PRIMARY_ERA]


def test_configure_reports_unknown_fields():
    status, body = _configure(reset=True, primary_paid=1)
    assert status == HTTPStatus.OK
    assert body["ignored"] == ["primary_paid"]


def test_adjustments_are_placed_on_each_line():
    encounter_id = _submit(CLAIM_A)
    era_adjustment = {"adjustment_amount_cents": 500, "adjustment_group_code": "CO"}
    manual_adjustment = {"adjustment_amount_cents": 100, "adjustment_group_code": "OA"}
    _scenario(
        claim_id=CLAIM_A,
        service_line_era_adjustments=[era_adjustment],
        service_line_manual_adjustments=[manual_adjustment],
    )

    line = _get_encounter(encounter_id)[1]["claims"][0]["service_lines"][0]

    assert line["service_line_era_data"]["service_line_adjustments"] == [era_adjustment]
    assert line["service_line_manual_adjustments"] == [manual_adjustment]


def test_failure_flag_fails_only_the_next_submission():
    _configure(
        fail_next_encounter_submit=True,
        encounter_submit_error={
            "status_code": 422,
            "errorName": "HttpRequestValidationError",
        },
    )
    payload = {"external_id": f"canvas:{CLAIM_A}", "service_lines": []}

    first = _call(MockCandidAPI, "create_encounter", body=payload)
    second = _call(MockCandidAPI, "create_encounter", body=payload)

    assert first == (422, {"errorName": "HttpRequestValidationError"})
    assert second[0] == HTTPStatus.OK


def test_payment_failure_flag_fails_only_the_next_payment():
    _configure(fail_next_payment_submit=True)

    first = _call(MockCandidAPI, "create_patient_payment", body={"amount_cents": 100})
    second = _call(MockCandidAPI, "create_patient_payment", body={"amount_cents": 100})

    assert first == (500, {"errorName": "InternalServerError"})
    assert second[0] == HTTPStatus.OK


# ----------------------------------------------------------------------
# Auth token
# ----------------------------------------------------------------------


def test_token_accepts_any_credentials_by_default():
    status, body = _call(
        MockCandidAPI, "auth_token", body={"client_id": "real", "client_secret": "real"}
    )
    assert status == HTTPStatus.OK
    assert body["access_token"] == "mock-token-for-testing"


def test_token_enforces_configured_credentials():
    _configure(valid_client_id="id", valid_client_secret="secret")

    wrong = _call(
        MockCandidAPI, "auth_token", body={"client_id": "id", "client_secret": "x"}
    )
    right = _call(
        MockCandidAPI, "auth_token", body={"client_id": "id", "client_secret": "secret"}
    )

    assert wrong[0] == HTTPStatus.UNAUTHORIZED
    assert right[0] == HTTPStatus.OK


# ----------------------------------------------------------------------
# Patient payments
# ----------------------------------------------------------------------


def test_reported_payment_is_listed_under_the_candid_claim():
    encounter_id = _submit(CLAIM_A)
    candid_claim_id = _get_encounter(encounter_id)[1]["claims"][0]["claim_id"]

    status, created = _call(
        MockCandidAPI,
        "create_patient_payment",
        body={
            "amount_cents": 2500,
            "allocations": [
                {
                    "target": {
                        "type": "claim_by_encounter_external_id",
                        "value": f"canvas:{CLAIM_A}",
                    },
                    "amount_cents": 2500,
                },
                {"target": {"type": "unattributed"}, "amount_cents": 0},
            ],
        },
    )
    _, listed = _call(
        MockCandidAPI,
        "list_patient_payments",
        query_params={"claim_id": candid_claim_id},
    )

    assert status == HTTPStatus.OK
    assert [p["patient_payment_id"] for p in listed["items"]] == [
        created["patient_payment_id"]
    ]
    assert listed["items"][0]["amount_cents"] == 2500


def test_injected_payment_is_listed_under_the_candid_claim():
    encounter_id = _submit(CLAIM_A)
    candid_claim_id = _get_encounter(encounter_id)[1]["claims"][0]["claim_id"]

    status, injected = _call(
        MockCandidControlAPI,
        "inject_patient_payment",
        body={"encounter_external_id": f"canvas:{CLAIM_A}", "amount_cents": 1500},
    )
    _, listed = _call(
        MockCandidAPI,
        "list_patient_payments",
        query_params={"claim_id": candid_claim_id},
    )

    assert status == HTTPStatus.OK
    assert injected["status"] == "injected"
    assert listed["items"][0]["amount_cents"] == 1500


def test_inject_payment_for_unknown_encounter_returns_404():
    status, body = _call(
        MockCandidControlAPI,
        "inject_patient_payment",
        body={"encounter_external_id": "canvas:missing", "amount_cents": 100},
    )
    assert status == HTTPStatus.NOT_FOUND
    assert "canvas:missing" in body["error"]


# ----------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------


def test_status_lists_encounters_scenarios_and_payments():
    encounter_id = _submit(CLAIM_A)
    _scenario(claim_id=CLAIM_A, copay_cents=500)
    _call(MockCandidAPI, "create_patient_payment", body={"amount_cents": 100})

    status, body = _call(MockCandidControlAPI, "status")

    assert status == HTTPStatus.OK
    assert [e["encounter_id"] for e in body["encounters"]] == [encounter_id]
    assert body["encounters"][0]["external_id"] == f"canvas:{CLAIM_A}"
    assert body["scenarios"] == {f"canvas:{CLAIM_A}": {"copay_cents": 500}}
    assert [p["amount_cents"] for p in body["patient_payments"]] == [100]


def test_status_for_a_claim_shows_what_the_plugin_will_see():
    _submit(CLAIM_A, external_id=f"canvas:{CLAIM_A}-1")
    _scenario(claim_id=CLAIM_A, eras=[PRIMARY_ERA], copay_cents=500)
    _call(
        MockCandidControlAPI,
        "inject_patient_payment",
        body={"encounter_external_id": f"canvas:{CLAIM_A}-1", "amount_cents": 700},
    )

    status, body = _call(
        MockCandidControlAPI, "status", query_params={"claim_id": CLAIM_A}
    )

    assert status == HTTPStatus.OK
    assert body["encounter"]["claims"][0]["eras"] == [PRIMARY_ERA]
    assert body["encounter"]["claims"][0]["service_lines"][0]["copay_cents"] == 500
    assert body["submitted_payload"]["external_id"] == f"canvas:{CLAIM_A}-1"
    assert [p["amount_cents"] for p in body["patient_payments"]] == [700]


def test_status_for_a_claim_not_yet_submitted_shows_its_scenario():
    _scenario(claim_id=CLAIM_B, copay_cents=500)

    _, body = _call(MockCandidControlAPI, "status", query_params={"claim_id": CLAIM_B})

    assert body["encounter"] is None
    assert body["patient_payments"] == []
    assert body["scenario"]["copay_cents"] == 500


# ----------------------------------------------------------------------
# Passthrough
# ----------------------------------------------------------------------


@patch("mock_candid.api.Http")
def test_passthrough_proxies_to_the_real_api(mock_http):
    _configure(passthrough_base_url="https://candid.test/")
    mock_http.return_value.get.return_value.json.return_value = {"encounter_id": "e1"}
    mock_http.return_value.get.return_value.status_code = 200

    status, body = _call(
        MockCandidAPI,
        "get_encounter",
        path_params={"encounter_id": "e1"},
        headers={"Authorization": "Bearer real-token"},
    )

    assert (status, body) == (200, {"encounter_id": "e1"})
    mock_http.return_value.get.assert_called_once_with(
        "https://candid.test/api/encounters/v4/e1",
        headers={"Authorization": "Bearer real-token"},
    )


@pytest.mark.parametrize(
    ("route", "path"),
    [
        ("auth_token", "/api/auth/v2/token"),
        ("create_encounter", "/api/encounters/v4"),
        ("create_patient_payment", "/api/patient-payments/v4"),
    ],
)
@patch("mock_candid.api.Http")
def test_passthrough_forwards_posts(mock_http, route, path):
    _configure(passthrough_base_url="https://candid.test")
    mock_http.return_value.post.return_value.json.return_value = {"ok": True}
    mock_http.return_value.post.return_value.status_code = 201

    status, body = _call(MockCandidAPI, route, body={"a": 1})

    assert (status, body) == (201, {"ok": True})
    mock_http.return_value.post.assert_called_once_with(
        f"https://candid.test{path}", json={"a": 1}, headers={}
    )


@patch("mock_candid.api.Http")
def test_passthrough_keeps_the_query_string_and_wraps_non_json(mock_http):
    _configure(passthrough_base_url="https://candid.test")
    response = mock_http.return_value.get.return_value
    response.json.side_effect = ValueError("not json")
    response.text = "upstream error"
    response.status_code = 502
    handler = MockCandidAPI.__new__(MockCandidAPI)
    handler.secrets = {}
    handler.request = MagicMock()
    handler.request.query_string = "claim_id=c1"
    handler.request.headers = {}

    (resp,) = handler.list_patient_payments()

    assert resp.status_code == 502
    assert json.loads(resp.content) == {"error": "upstream error"}
    mock_http.return_value.get.assert_called_once_with(
        "https://candid.test/api/patient-payments/v4?claim_id=c1", headers={}
    )


# ----------------------------------------------------------------------
# Control API auth
# ----------------------------------------------------------------------


def _control_auth(secrets, key):
    handler = MockCandidControlAPI.__new__(MockCandidControlAPI)
    handler.secrets = secrets
    credentials = MagicMock()
    credentials.key = key
    return handler.authenticate(credentials)


def test_control_api_accepts_the_configured_key():
    assert _control_auth({"MOCK_CANDID_API_KEY": API_KEY}, API_KEY) is True


def test_control_api_rejects_a_wrong_key():
    assert _control_auth({"MOCK_CANDID_API_KEY": API_KEY}, "wrong") is False


@pytest.mark.parametrize("secrets", [{}, {"MOCK_CANDID_API_KEY": ""}])
def test_control_api_fails_closed_without_a_key(secrets):
    assert _control_auth(secrets, "") is False


def test_candid_api_routes_are_open():
    handler = MockCandidAPI.__new__(MockCandidAPI)
    assert handler.authenticate(MagicMock()) is True
