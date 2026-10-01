"""Tests for the cache-backed token store and the content hash helper."""

from __future__ import annotations

from salesforce_to_canvas_integration.services.storage import (
    StoredTokens,
    TokenStore,
    compute_entry_id,
)

from tests.conftest import FakeCache


def test_entry_id_is_stable_across_equal_payloads() -> None:
    payload_a = {"Id": "X", "FirstName": "Jane", "LastName": "Doe"}
    payload_b = {"LastName": "Doe", "Id": "X", "FirstName": "Jane"}
    assert compute_entry_id("X", payload_a) == compute_entry_id("X", payload_b)


def test_token_store_persists_and_clears() -> None:
    tokens = TokenStore(FakeCache())
    payload = StoredTokens(
        access_token="atk",
        refresh_token="rtk",
        instance_url="https://my.salesforce.com",
        issued_at=1.0,
        expires_at=2.0,
    )
    tokens.save(payload)
    assert tokens.load() == payload
    tokens.clear()
    assert tokens.load() is None
