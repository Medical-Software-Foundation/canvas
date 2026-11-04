"""Tests for the /sync and /sync-patient-payments SimpleAPI routes."""

import json
from unittest.mock import MagicMock, patch

import pytest

from candid import adjudication_sync
from candid.api.sync import CandidSyncAPI, CandidSyncPatientPaymentsAPI, _sync_handler
from tests.conftest import MOCK_SECRETS

ROUTES = [
    (CandidSyncAPI, "sync_claim_adjudications"),
    (CandidSyncPatientPaymentsAPI, "sync_patient_payments"),
]


def _handler(cls, body: dict | None = None, secrets: dict | None = None):
    handler = cls.__new__(cls)
    handler.secrets = MOCK_SECRETS if secrets is None else secrets
    handler.request = MagicMock()
    handler.request.json.return_value = body or {}
    return handler


def test_paths():
    assert CandidSyncAPI.PATH == "/sync"
    assert CandidSyncPatientPaymentsAPI.PATH == "/sync-patient-payments"


@pytest.mark.parametrize("cls", [CandidSyncAPI, CandidSyncPatientPaymentsAPI])
def test_authenticate_accepts_shared_secret(cls):
    handler = _handler(cls)
    assert handler.authenticate(MagicMock(key=MOCK_SECRETS["CANDID_CLIENT_SECRET"])) is True


@pytest.mark.parametrize("cls", [CandidSyncAPI, CandidSyncPatientPaymentsAPI])
def test_authenticate_rejects_wrong_key(cls):
    handler = _handler(cls)
    assert handler.authenticate(MagicMock(key="wrong")) is False


@pytest.mark.parametrize("cls", [CandidSyncAPI, CandidSyncPatientPaymentsAPI])
def test_authenticate_fails_closed_without_secret(cls):
    handler = _handler(cls, secrets={})
    assert handler.authenticate(MagicMock(key="")) is False


@pytest.mark.parametrize("cls,sync_name", ROUTES)
def test_post_requires_claim_id(cls, sync_name):
    handler = _handler(cls, {})
    with patch(f"candid.api.sync.{sync_name}") as mock_sync:
        effects = handler.post()
    assert effects[0].status_code == 400
    assert json.loads(effects[0].content) == {"error": "claim_id is required"}
    mock_sync.assert_not_called()


@pytest.mark.parametrize("cls,sync_name", ROUTES)
def test_post_returns_404_for_unknown_claim(cls, sync_name):
    handler = _handler(cls, {"claim_id": "missing"})
    with (
        patch("candid.api.sync.Claim") as MockClaim,
        patch(f"candid.api.sync.{sync_name}") as mock_sync,
    ):
        MockClaim.objects.filter.return_value.first.return_value = None
        effects = handler.post()
    assert effects[0].status_code == 404
    assert json.loads(effects[0].content) == {"error": "claim not found"}
    MockClaim.objects.filter.assert_called_once_with(id="missing")
    mock_sync.assert_not_called()


def test_post_runs_sync_and_returns_its_effects():
    sync_fn = MagicMock(return_value=["effect-a", "effect-b"])
    route = type("Route", (CandidSyncAPI,), {"post": _sync_handler(sync_fn, "test")})
    handler = _handler(route, {"claim_id": "claim-1"})
    claim = MagicMock()
    with patch("candid.api.sync.Claim") as MockClaim:
        MockClaim.objects.filter.return_value.first.return_value = claim
        effects = handler.post()

    assert effects == ["effect-a", "effect-b"]
    sync_fn.assert_called_once_with(claim, MOCK_SECRETS)


@pytest.mark.parametrize("cls,sync_name", ROUTES)
def test_each_route_is_bound_to_its_own_sync_function(cls, sync_name):
    # _sync_handler closes over the sync function at class creation, so
    # module-level patches can't intercept it; check the binding directly.
    bound = {cell.cell_contents for cell in cls.post.__closure__}
    assert getattr(adjudication_sync, sync_name) in bound
    other = ({name for _, name in ROUTES} - {sync_name}).pop()
    assert getattr(adjudication_sync, other) not in bound
