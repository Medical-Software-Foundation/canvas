"""Tests for the claim-timeline application (right chart pane iframe)."""

import json
from unittest.mock import MagicMock

from canvas_sdk.effects import EffectType

from candid.applications.claim_timeline import APP_URL, CandidClaimTimeline

CLAIM_ID = "00000000-0000-0000-0000-0000000000aa"


def _app(context: dict) -> CandidClaimTimeline:
    app = CandidClaimTimeline.__new__(CandidClaimTimeline)
    app.event = MagicMock()
    app.event.context = context
    return app


def _modal(effect) -> dict:
    assert effect.type == EffectType.LAUNCH_MODAL
    return json.loads(effect.payload)["data"]


def test_on_open_on_claim_page_passes_claim_id():
    data = _modal(_app({"claim": {"id": CLAIM_ID}}).on_open())
    assert data["url"] == f"{APP_URL}?claim_id={CLAIM_ID}"
    assert data["target"] == "right_chart_pane"
    assert data["title"] == "Candid Activity"


def test_on_open_without_claim_shows_placeholder_page():
    data = _modal(_app({}).on_open())
    assert data["url"] == APP_URL


def test_on_open_url_encodes_claim_id():
    data = _modal(_app({"claim": {"id": "a b&c"}}).on_open())
    assert data["url"] == f"{APP_URL}?claim_id=a+b%26c"


def test_on_context_change_to_claim_rerenders():
    data = _modal(_app({"claim": {"id": CLAIM_ID}}).on_context_change())
    assert data["url"] == f"{APP_URL}?claim_id={CLAIM_ID}"


def test_on_context_change_away_from_claim_does_nothing():
    assert _app({"patient": {"id": "p"}}).on_context_change() is None
