"""Tests for PrescriberSearchPrioritization and SupervisingProviderSorter."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest


def _make_search_event(results: list, user_id: str | None = "user-1", note_uuid: str | None = None) -> MagicMock:
    event = MagicMock()
    ctx = {"results": results, "user": {"staff": user_id}}
    if note_uuid:
        ctx["note"] = {"uuid": note_uuid}
    event.context = ctx
    return event


# ─────────────────────────────────────────────────────────────
# PrescriberSearchPrioritization.compute
# ─────────────────────────────────────────────────────────────

def test_search_returns_null_when_results_is_none() -> None:
    """compute() emits a null-payload effect when context has no results."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
    tested.event = _make_search_event(None)

    result = tested.compute()

    expected_payload = json.dumps(None)
    assert len(result) == 1
    assert result[0].payload == expected_payload


def test_search_returns_null_when_no_user_staff_key() -> None:
    """compute() emits a null-payload effect when the user has no staff key."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
    tested.event = _make_search_event([{"text": "Dr Smith", "value": "123"}], user_id=None)

    result = tested.compute()

    expected_payload = json.dumps(None)
    assert result[0].payload == expected_payload


def test_search_adds_state_annotation_to_all_providers() -> None:
    """compute() annotates every result with its license state from prefetched staff."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    results = [
        {"text": "Alice Smith", "value": "a"},
        {"text": "Bob Jones", "value": "b"},
    ]

    # No NPIs so compute() can skip the NPI batch query (no DB hit needed).
    fake_user = SimpleNamespace(id="user-uuid", npi_number=None)
    fake_a = SimpleNamespace(id="uuid-a", npi_number=None)
    fake_b = SimpleNamespace(id="uuid-b", npi_number=None)

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"user-1": fake_user, "a": fake_a, "b": fake_b},
        ) as mock_bulk_fetch,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            side_effect=["NY", "CA"],
        ) as mock_license_state,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={},
        ) as mock_delegations,
    ):
        tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        tested.event = _make_search_event(results)

        result = tested.compute()

    payload = json.loads(result[0].payload)
    states = [r.get("annotations", []) for r in payload]
    assert "NY" in str(states) and "CA" in str(states)

    exp_bulk_fetch_calls = [call(["user-1", "a", "b"])]
    exp_license_state_calls = [call(fake_a), call(fake_b)]
    exp_delegations_calls = [call()]
    assert mock_bulk_fetch.mock_calls == exp_bulk_fetch_calls
    assert mock_license_state.mock_calls == exp_license_state_calls
    assert mock_delegations.mock_calls == exp_delegations_calls


def test_search_puts_authorized_providers_before_others() -> None:
    """compute() orders delegated prescribers ahead of non-delegated ones."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    results = [
        {"text": "Other Doc", "value": "other"},
        {"text": "Authorized Doc", "value": "auth"},
    ]

    fake_user = SimpleNamespace(id="user-uuid", npi_number=None)
    fake_other = SimpleNamespace(id="other-uuid", npi_number=None)
    fake_auth = SimpleNamespace(id="auth-uuid", npi_number=None)

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"user-1": fake_user, "other": fake_other, "auth": fake_auth},
        ) as mock_bulk_fetch,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            return_value="NY",
        ) as mock_license_state,
        # Delegations: prescriber "auth-uuid" has "user-uuid" authorized.
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={"auth-uuid": ["user-uuid"]},
        ) as mock_delegations,
    ):
        tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        tested.event = _make_search_event(results)

        result = tested.compute()

    payload = json.loads(result[0].payload)
    assert payload[0]["value"] == "auth"
    assert payload[1]["value"] == "other"

    exp_bulk_fetch_calls = [call(["user-1", "other", "auth"])]
    exp_license_state_calls = [call(fake_other), call(fake_auth)]
    exp_delegations_calls = [call()]
    assert mock_bulk_fetch.mock_calls == exp_bulk_fetch_calls
    assert mock_license_state.mock_calls == exp_license_state_calls
    assert mock_delegations.mock_calls == exp_delegations_calls


def test_search_skips_results_without_staff_key() -> None:
    """compute() keeps results that have no staff key in the unrestricted bucket."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    results = [{"text": "No value"}]  # missing "value"

    fake_user = SimpleNamespace(id="user-uuid", npi_number=None)

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"user-1": fake_user},
        ) as mock_bulk_fetch,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={},
        ) as mock_delegations,
    ):
        tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        tested.event = _make_search_event(results)

        result = tested.compute()

    payload = json.loads(result[0].payload)
    expected_len = 1
    assert len(payload) == expected_len

    exp_bulk_fetch_calls = [call(["user-1"])]
    exp_delegations_calls = [call()]
    assert mock_bulk_fetch.mock_calls == exp_bulk_fetch_calls
    assert mock_delegations.mock_calls == exp_delegations_calls


def test_search_does_not_use_per_result_helpers() -> None:
    """Regression: compute() must not call per-result helpers (N+1 query guard).

    _get_staff_npi / _get_staff_license_state / _is_authorized are reserved
    for single-prescriber paths (PrescribeActionFilter, PrescribeValidation).
    Calling them in a loop causes the N+1 problem the refactor fixed.
    """
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    results = [
        {"text": "Alice Smith", "value": "a"},
        {"text": "Bob Jones", "value": "b"},
    ]

    fake_user = SimpleNamespace(id="user-uuid", npi_number=None)
    fake_a = SimpleNamespace(id="uuid-a", npi_number=None)
    fake_b = SimpleNamespace(id="uuid-b", npi_number=None)

    def _boom(*_args, **_kwargs):
        raise AssertionError("per-result helper called from search prioritization")

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"user-1": fake_user, "a": fake_a, "b": fake_b},
        ) as mock_bulk_fetch,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            return_value=None,
        ) as mock_license_state,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={},
        ) as mock_delegations,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi",
            side_effect=_boom,
        ) as mock_get_npi,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_staff_license_state",
            side_effect=_boom,
        ) as mock_get_license_state,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._is_authorized",
            side_effect=_boom,
        ) as mock_is_authorized,
    ):
        tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        tested.event = _make_search_event(results)

        # If any per-result helper is called, _boom raises AssertionError and the test fails.
        tested.compute()

    exp_bulk_fetch_calls = [call(["user-1", "a", "b"])]
    exp_license_state_calls = [call(fake_a), call(fake_b)]
    exp_delegations_calls = [call()]
    exp_get_npi_calls: list = []
    exp_get_license_state_calls: list = []
    exp_is_authorized_calls: list = []
    assert mock_bulk_fetch.mock_calls == exp_bulk_fetch_calls
    assert mock_license_state.mock_calls == exp_license_state_calls
    assert mock_delegations.mock_calls == exp_delegations_calls
    assert mock_get_npi.mock_calls == exp_get_npi_calls
    assert mock_get_license_state.mock_calls == exp_get_license_state_calls
    assert mock_is_authorized.mock_calls == exp_is_authorized_calls


def test_extract_staff_key_from_result__prescriber() -> None:
    """_extract_staff_key_from_result coerces int/str/dict values and returns None when missing."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)

    assert tested._extract_staff_key_from_result({"value": 42}) == "42"
    assert tested._extract_staff_key_from_result({"value": "abc"}) == "abc"
    assert tested._extract_staff_key_from_result({"value": {"key": "k1"}}) == "k1"
    assert tested._extract_staff_key_from_result({"value": {"id": "i1"}}) == "i1"
    assert tested._extract_staff_key_from_result({}) is None


# ─────────────────────────────────────────────────────────────
# SupervisingProviderSorter.compute
# ─────────────────────────────────────────────────────────────

def test_supervising_sorter_returns_null_when_no_results() -> None:
    """compute() emits a null-payload effect when context has no results."""
    from dea_prescriber_filter.protocols.prescriber_filter import SupervisingProviderSorter

    tested = SupervisingProviderSorter.__new__(SupervisingProviderSorter)
    tested.event = MagicMock()
    tested.event.context = {"results": None}

    result = tested.compute()

    expected_payload = json.dumps(None)
    assert result[0].payload == expected_payload


def test_supervising_sorter_annotates_and_sorts() -> None:
    """compute() annotates with license state and sorts results by last name."""
    from dea_prescriber_filter.protocols.prescriber_filter import SupervisingProviderSorter

    results = [
        {"text": "Bob Zzz", "value": "b"},
        {"text": "Alice Aaa", "value": "a"},
    ]

    fake_a = SimpleNamespace(id="uuid-a", npi_number=None)
    fake_b = SimpleNamespace(id="uuid-b", npi_number=None)

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"a": fake_a, "b": fake_b},
        ) as mock_bulk_fetch,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            side_effect=lambda s: {"uuid-a": "CA", "uuid-b": "NY"}.get(getattr(s, "id", None)),
        ) as mock_license_state,
    ):
        tested = SupervisingProviderSorter.__new__(SupervisingProviderSorter)
        tested.event = MagicMock()
        tested.event.context = {"results": results}

        result = tested.compute()

    payload = json.loads(result[0].payload)
    # Sorted by last name (Aaa < Zzz)
    assert payload[0]["text"] == "Alice Aaa"
    assert payload[1]["text"] == "Bob Zzz"
    # State annotations applied from prefetched Staff records
    assert "CA" in payload[0].get("annotations", [])
    assert "NY" in payload[1].get("annotations", [])

    exp_bulk_fetch_calls = [call(["b", "a"])]
    exp_license_state_calls = [call(fake_b), call(fake_a)]
    assert mock_bulk_fetch.mock_calls == exp_bulk_fetch_calls
    assert mock_license_state.mock_calls == exp_license_state_calls


def test_supervising_sorter_skips_results_without_staff_key() -> None:
    """compute() keeps results lacking a staff key without raising."""
    from dea_prescriber_filter.protocols.prescriber_filter import SupervisingProviderSorter

    results = [{"text": "No value"}]

    tested = SupervisingProviderSorter.__new__(SupervisingProviderSorter)
    tested.event = MagicMock()
    tested.event.context = {"results": results}

    result = tested.compute()

    payload = json.loads(result[0].payload)
    expected_len = 1
    assert len(payload) == expected_len


def test_extract_staff_key__supervising() -> None:
    """_extract_staff_key_from_result on SupervisingProviderSorter coerces values and handles missing keys."""
    from dea_prescriber_filter.protocols.prescriber_filter import SupervisingProviderSorter

    tested = SupervisingProviderSorter.__new__(SupervisingProviderSorter)

    assert tested._extract_staff_key_from_result({"value": 42}) == "42"
    assert tested._extract_staff_key_from_result({"value": "abc"}) == "abc"
    assert tested._extract_staff_key_from_result({"value": {"key": "k1"}}) == "k1"
    assert tested._extract_staff_key_from_result({}) is None
