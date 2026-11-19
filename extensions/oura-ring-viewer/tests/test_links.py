"""Tests for the outstanding-link rules shared by staff and portal routes."""

import datetime as dt

from oura_ring_viewer.services.links import (
    link_expired,
    link_expires_at,
    live_link_nonce,
)
from oura_ring_viewer.services.storage import upsert_sync_state

NOW = dt.datetime(2026, 11, 2, 18, 0, tzinfo=dt.UTC)


def _state(**fields: object) -> object:
    defaults: dict[str, object] = {"link_pending": True, "last_link_sent_at": NOW, "last_link_nonce": "n"}
    defaults.update(fields)
    return upsert_sync_state("p1", **defaults)


def test_a_fresh_link_is_live() -> None:
    state = _state()
    assert live_link_nonce(state, NOW) == "n"  # type: ignore[arg-type]
    assert not link_expired(state, NOW)  # type: ignore[arg-type]


def test_an_old_link_is_expired_and_not_reusable() -> None:
    state = _state()
    later = NOW + dt.timedelta(days=3)
    assert link_expired(state, later)  # type: ignore[arg-type]
    assert live_link_nonce(state, later) is None  # type: ignore[arg-type]


def test_nothing_pending_means_nothing_to_reuse() -> None:
    assert live_link_nonce(None, NOW) is None
    assert link_expires_at(_state(link_pending=False)) is None  # type: ignore[arg-type]
    assert live_link_nonce(_state(last_link_nonce=""), NOW) is None  # type: ignore[arg-type]
    assert not link_expired(None, NOW)
