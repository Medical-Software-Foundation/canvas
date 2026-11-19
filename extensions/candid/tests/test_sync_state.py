"""Tests for the nightly sync's durable state store (PLUGIN-501)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.db import DatabaseError

from candid.sync_state import HUB_ID, HUB_TYPE, SyncState, _unwrap

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)


@pytest.fixture
def db():
    with (
        patch("candid.sync_state.CustomAttribute") as attr_model,
        patch("candid.sync_state.AttributeHub") as hub_model,
        patch("candid.sync_state.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat
        hub = MagicMock()
        hub_model.objects.get_or_create.return_value = (hub, False)
        yield {"attr": attr_model, "hub_model": hub_model, "hub": hub}


def _stored(value, expires_at):
    attribute = MagicMock()
    attribute.value = json.dumps({"value": value, "expires_at": expires_at})
    return attribute


def test_set_writes_value_and_expiry_to_the_hub(db):
    SyncState().set("cursor", "claim-9", timeout_seconds=3600)

    db["hub_model"].objects.get_or_create.assert_called_once_with(
        type=HUB_TYPE, id=HUB_ID
    )
    name, raw = db["hub"].set_attribute.call_args.args
    assert name == "cursor"
    assert json.loads(raw) == {
        "value": "claim-9",
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }


def test_get_returns_a_live_value(db):
    later = (NOW + timedelta(hours=1)).isoformat()
    db["attr"].objects.filter.return_value.first.return_value = _stored(
        "claim-9", later
    )

    assert SyncState().get("cursor") == "claim-9"
    db["attr"].objects.filter.assert_called_once_with(
        hub__type=HUB_TYPE, hub__id=HUB_ID, name="cursor"
    )


def test_get_ignores_an_expired_value(db):
    earlier = (NOW - timedelta(seconds=1)).isoformat()
    db["attr"].objects.filter.return_value.first.return_value = _stored(
        "claim-9", earlier
    )

    assert SyncState().get("cursor") is None


def test_get_returns_none_when_never_set(db):
    db["attr"].objects.filter.return_value.first.return_value = None

    assert SyncState().get("cursor") is None


def test_delete_clears_the_value(db):
    SyncState().delete("cursor")

    name, raw = db["hub"].set_attribute.call_args.args
    assert name == "cursor"
    assert json.loads(raw)["value"] is None


def test_database_errors_are_raised_not_hidden(db):
    db["attr"].objects.filter.side_effect = DatabaseError(
        'relation "attribute_hub" does not exist'
    )
    db["hub_model"].objects.get_or_create.side_effect = DatabaseError("no namespace")
    state = SyncState()

    with pytest.raises(DatabaseError):
        state.get("cursor")
    with pytest.raises(DatabaseError):
        state.set("cursor", "claim-3", timeout_seconds=600)
    with pytest.raises(DatabaseError):
        state.delete("cursor")


def test_unexpected_errors_are_not_swallowed(db):
    db["attr"].objects.filter.side_effect = RuntimeError("bug")

    with pytest.raises(RuntimeError):
        SyncState().get("cursor")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps([1, 2]),
        json.dumps({"value": "x", "expires_at": "garbage"}),
    ],
)
def test_unwrap_treats_malformed_values_as_missing(raw, db):
    assert _unwrap(raw) is None


def test_unwrap_accepts_a_value_with_no_expiry(db):
    assert _unwrap(json.dumps({"value": "x", "expires_at": None})) == "x"
    assert _unwrap({"value": "x"}) == "x"
