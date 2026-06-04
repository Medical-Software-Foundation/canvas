"""Tests for the Candid claim-detail API (timeline read + manual sync)."""

import json
from unittest.mock import MagicMock, patch

from candid.api.claim_detail import CandidClaimDetailAPI
from candid.effect_helpers import (
    META_CLAIM_STATUS,
    META_ENCOUNTERS,
    META_LAST_SYNC,
    META_SUBMITTED_AT,
    META_SYNC_HISTORY,
    MAX_SYNC_HISTORY,
)

from tests.conftest import MOCK_SECRETS


def _fake_claim() -> MagicMock:
    """A claim whose timeline relations are all empty by default."""
    claim = MagicMock()
    claim.postings.active.return_value.filter.return_value = []
    claim.banner_alerts.filter.return_value.first.return_value = None
    claim.comments.filter.return_value.order_by.return_value = []
    claim.current_queue.name = "FiledAwaitingResponse"
    return claim


def _run_get(query_params: dict, metadata: dict, claim: MagicMock | None):
    """Run GET /claim-detail and return the decoded JSON body and the response."""
    handler = CandidClaimDetailAPI.__new__(CandidClaimDetailAPI)
    handler.secrets = MOCK_SECRETS
    handler.request = MagicMock()
    handler.request.query_params.get.side_effect = lambda k, d="": query_params.get(k, d)

    with (
        patch("candid.api.claim_detail.Claim") as MockClaim,
        patch(
            "candid.api.claim_detail.get_claim_metadata",
            side_effect=lambda c, key: metadata.get(key),
        ),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        effects = handler.get()

    resp = effects[0]
    return json.loads(resp.content), resp


def test_get_requires_claim_id():
    body, resp = _run_get({"claim_id": ""}, {}, _fake_claim())
    assert resp.status_code == 400
    assert "claim_id" in body["error"]


def test_get_returns_404_when_claim_missing():
    body, resp = _run_get({"claim_id": "nope"}, {}, None)
    assert resp.status_code == 404
    assert body["error"] == "claim not found"


def test_get_returns_sync_history_from_metadata():
    history = [
        {
            "synced_at": "2026-02-01T00:00:00+00:00",
            "log_type": "sync",
            "status": "paid",
            "effects": 1,
            "era_ids": ["era-1"],
            "detail": "era-1: $70.00",
        },
        {
            "synced_at": "2026-01-01T00:00:00+00:00",
            "log_type": "payment_reported",
            "status": "",
            "effects": 0,
            "era_ids": [],
            "detail": "$50.00 | payment_id=pay-1",
        },
    ]
    metadata = {
        META_ENCOUNTERS: [{"candid_encounter_id": "enc-1"}],
        META_SUBMITTED_AT: "2026-01-01T00:00:00+00:00",
        META_LAST_SYNC: "2026-02-01T00:00:00+00:00",
        META_CLAIM_STATUS: "paid",
        META_SYNC_HISTORY: history,
    }

    body, resp = _run_get({"claim_id": "claim-1"}, metadata, _fake_claim())

    assert resp.status_code == 200
    assert body["sync_history"] == history
    assert body["candid_claim_status"] == "paid"


def test_get_sync_history_defaults_to_empty_when_missing():
    body, _ = _run_get({"claim_id": "claim-1"}, {}, _fake_claim())
    assert body["sync_history"] == []


def test_get_sync_history_is_capped():
    history = [
        {"synced_at": f"2026-01-{i:02d}T00:00:00", "log_type": "sync", "detail": str(i)}
        for i in range(1, MAX_SYNC_HISTORY + 6)
    ]
    metadata = {META_SYNC_HISTORY: history}

    body, _ = _run_get({"claim_id": "claim-1"}, metadata, _fake_claim())

    assert len(body["sync_history"]) == MAX_SYNC_HISTORY
    assert body["sync_history"] == history[:MAX_SYNC_HISTORY]


def test_get_ignores_non_list_sync_history():
    body, _ = _run_get(
        {"claim_id": "claim-1"}, {META_SYNC_HISTORY: "corrupt"}, _fake_claim()
    )
    assert body["sync_history"] == []


def test_post_requires_claim_id():
    handler = CandidClaimDetailAPI.__new__(CandidClaimDetailAPI)
    handler.request = MagicMock()
    handler.request.json.return_value = {"claim_id": ""}

    effects = handler.post()

    assert json.loads(effects[0].content)["error"]
    assert effects[0].status_code == 400


def test_post_triggers_sync_and_reports_effect_count():
    handler = CandidClaimDetailAPI.__new__(CandidClaimDetailAPI)
    handler.secrets = MOCK_SECRETS
    handler.request = MagicMock()
    handler.request.json.return_value = {"claim_id": "claim-1"}

    with (
        patch("candid.api.claim_detail.Claim") as MockClaim,
        patch("candid.api.claim_detail.sync_claim_adjudications") as mock_sync,
    ):
        MockClaim.objects.filter.return_value.first.return_value = _fake_claim()
        mock_sync.return_value = ["effect-a", "effect-b"]

        effects = handler.post()

    assert effects[:2] == ["effect-a", "effect-b"]
    body = json.loads(effects[2].content)
    assert body == {"status": "synced", "effects_count": 2}
