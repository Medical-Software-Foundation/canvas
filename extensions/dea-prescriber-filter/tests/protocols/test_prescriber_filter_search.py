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


def test_search_returns_null_when_results_is_none() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    handler = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
    handler.event = _make_search_event(None)

    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].payload == json.dumps(None)


def test_search_returns_null_when_no_user_staff_key() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    handler = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
    handler.event = _make_search_event([{"text": "Dr Smith", "value": "123"}], user_id=None)

    effects = handler.compute()

    assert effects[0].payload == json.dumps(None)


def test_search_adds_state_annotation_to_all_providers() -> None:
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
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            side_effect=["NY", "CA"],
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={},
        ),
    ):
        handler = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        handler.event = _make_search_event(results)

        effects = handler.compute()

    payload = json.loads(effects[0].payload)
    states = [r.get("annotations", []) for r in payload]
    assert "NY" in str(states) and "CA" in str(states)


def test_search_puts_authorized_providers_before_others() -> None:
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
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            return_value="NY",
        ),
        # Delegations: prescriber "auth-uuid" has "user-uuid" authorized.
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={"auth-uuid": ["user-uuid"]},
        ),
    ):
        handler = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        handler.event = _make_search_event(results)

        effects = handler.compute()

    payload = json.loads(effects[0].payload)
    assert payload[0]["value"] == "auth"
    assert payload[1]["value"] == "other"


def test_search_skips_results_without_staff_key() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    results = [{"text": "No value"}]  # missing "value"

    fake_user = SimpleNamespace(id="user-uuid", npi_number=None)

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"user-1": fake_user},
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={},
        ),
    ):
        handler = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        handler.event = _make_search_event(results)

        effects = handler.compute()

    payload = json.loads(effects[0].payload)
    assert len(payload) == 1


def test_search_does_not_use_per_result_helpers() -> None:
    """Regression: compute() must not call _get_staff_npi / _get_staff_license_state /
    _is_authorized per result. Those helpers are reserved for single-prescriber
    paths (PrescribeActionFilter, PrescribeValidation). Calling them in a loop
    causes the N+1 query problem the refactor was meant to fix.
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
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            return_value=None,
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={},
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi", side_effect=_boom),
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_license_state", side_effect=_boom),
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized", side_effect=_boom),
    ):
        handler = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        handler.event = _make_search_event(results)

        # If any per-result helper is called, _boom raises AssertionError and the test fails.
        handler.compute()


def test_extract_staff_key_from_result_handles_int() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    handler = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)

    assert handler._extract_staff_key_from_result({"value": 42}) == "42"
    assert handler._extract_staff_key_from_result({"value": "abc"}) == "abc"
    assert handler._extract_staff_key_from_result({"value": {"key": "k1"}}) == "k1"
    assert handler._extract_staff_key_from_result({"value": {"id": "i1"}}) == "i1"
    assert handler._extract_staff_key_from_result({}) is None


# ─────────────────────────────────────────────────────────────
# SupervisingProviderSorter
# ─────────────────────────────────────────────────────────────

def test_supervising_sorter_returns_null_when_no_results() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import SupervisingProviderSorter

    handler = SupervisingProviderSorter.__new__(SupervisingProviderSorter)
    handler.event = MagicMock()
    handler.event.context = {"results": None}

    effects = handler.compute()

    assert effects[0].payload == json.dumps(None)


def test_supervising_sorter_annotates_and_sorts() -> None:
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
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._license_state_of_staff",
            side_effect=lambda s: {"uuid-a": "CA", "uuid-b": "NY"}.get(getattr(s, "id", None)),
        ),
    ):
        handler = SupervisingProviderSorter.__new__(SupervisingProviderSorter)
        handler.event = MagicMock()
        handler.event.context = {"results": results}

        effects = handler.compute()

    payload = json.loads(effects[0].payload)
    # Sorted by last name (Aaa < Zzz)
    assert payload[0]["text"] == "Alice Aaa"
    assert payload[1]["text"] == "Bob Zzz"
    # State annotations applied from prefetched Staff records
    assert "CA" in payload[0].get("annotations", [])
    assert "NY" in payload[1].get("annotations", [])


def test_supervising_sorter_skips_results_without_staff_key() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import SupervisingProviderSorter

    results = [{"text": "No value"}]

    handler = SupervisingProviderSorter.__new__(SupervisingProviderSorter)
    handler.event = MagicMock()
    handler.event.context = {"results": results}

    effects = handler.compute()

    payload = json.loads(effects[0].payload)
    assert len(payload) == 1


def test_supervising_extract_staff_key() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import SupervisingProviderSorter

    handler = SupervisingProviderSorter.__new__(SupervisingProviderSorter)

    assert handler._extract_staff_key_from_result({"value": 42}) == "42"
    assert handler._extract_staff_key_from_result({"value": "abc"}) == "abc"
    assert handler._extract_staff_key_from_result({"value": {"key": "k1"}}) == "k1"
    assert handler._extract_staff_key_from_result({}) is None
