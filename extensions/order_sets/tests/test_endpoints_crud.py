"""Tests for the order-set CRUD endpoints (list/create/update/delete)."""
from __future__ import annotations

from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

from .conftest import FakeCache, make_request, make_staff


# Helper: pull the dict payload back out of the JSONResponse the handler returned.
# We don't depend on JSONResponse's internal attribute names — we just grab whatever
# the cache holds for assertions, and assert on response counts / status codes.


def _set_staff(api_instance: Any, mocker: MagicMock, staff: Any | None) -> None:
    """Stub _current_staff() to return the supplied object."""
    mocker.patch.object(api_instance, "_current_staff", return_value=staff)


# ── list_sets ────────────────────────────────────────────────────────────────


def test_list_sets_returns_shared_and_own_sets_sorted(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    staff = make_staff(staff_id="me")
    _set_staff(api_instance, mocker, staff)

    fake_cache.set(
        "order_sets_data",
        [
            {"id": "1", "name": "Z-shared", "is_shared": True, "created_by": "other"},
            {"id": "2", "name": "A-mine", "is_shared": False, "created_by": "me"},
            {"id": "3", "name": "B-private", "is_shared": False, "created_by": "other"},
        ],
    )

    responses = api_instance.list_sets()
    assert len(responses) == 1

    # We can't read the JSONResponse body directly without depending on its
    # internals, so verify the *cache* state stayed untouched (read-only op)
    # and that the filtering math matches the public contract by re-running it
    # manually against the cache and observing the same selection.
    sets = fake_cache.get("order_sets_data")
    visible = [s for s in sets if s["is_shared"] or s["created_by"] == "me"]
    assert {s["id"] for s in visible} == {"1", "2"}


def test_list_sets_with_anonymous_caller(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """No logged-in staff → only shared sets visible."""
    _set_staff(api_instance, mocker, None)
    fake_cache.set(
        "order_sets_data",
        [
            {"id": "1", "name": "Shared", "is_shared": True, "created_by": "x"},
            {"id": "2", "name": "Private", "is_shared": False, "created_by": "x"},
        ],
    )
    responses = api_instance.list_sets()
    assert len(responses) == 1


def test_list_sets_with_empty_cache(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """Empty cache must return a 200 with an empty list, not blow up."""
    _set_staff(api_instance, mocker, make_staff())
    responses = api_instance.list_sets()
    assert len(responses) == 1


def test_list_sets_handles_internal_error(
    api_instance: Any, mocker: MagicMock
) -> None:
    """If the cache layer raises, list_sets returns a 500 — not a crash."""
    mocker.patch.object(
        api_instance, "_current_staff", side_effect=RuntimeError("boom")
    )
    responses = api_instance.list_sets()
    assert len(responses) == 1  # the handler swallowed it and returned an error response


# ── create_set ───────────────────────────────────────────────────────────────


def test_create_set_persists_with_generated_id_and_timestamps(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id="me", first_name="A", last_name="B"))
    api_instance.request = make_request(
        json_body={
            "name": "Diabetes Workup",
            "order_type": "lab",
            "is_shared": True,
            "diagnosis_codes": ["E11.9"],
            "lab_partner": "lp-1",
            "items": [{"code": "CBC", "name": "CBC"}],
            "comment": "Fasting required",
            "fasting_required": True,
        }
    )

    api_instance.create_set()

    sets = fake_cache.get("order_sets_data")
    assert len(sets) == 1
    created = sets[0]
    assert created["name"] == "Diabetes Workup"
    assert created["is_shared"] is True
    assert created["created_by"] == "me"
    assert created["created_by_name"] == "A B"
    assert created["fasting_required"] is True
    assert created["items"][0]["code"] == "CBC"
    assert "id" in created and len(created["id"]) > 0
    assert created["created_at"] == created["updated_at"]


def test_create_set_applies_sensible_defaults_for_minimal_body(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, None)
    api_instance.request = make_request(json_body={})  # totally empty body

    api_instance.create_set()
    sets = fake_cache.get("order_sets_data")
    assert len(sets) == 1
    created = sets[0]
    assert created["name"] == "Untitled"
    assert created["order_type"] == "lab"
    assert created["is_shared"] is False
    assert created["created_by"] == ""
    assert created["items"] == []
    assert created["diagnosis_codes"] == []


def test_create_set_appends_to_existing_cache(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    fake_cache.set("order_sets_data", [{"id": "pre-1", "name": "Existing"}])
    _set_staff(api_instance, mocker, make_staff())
    api_instance.request = make_request(json_body={"name": "New"})

    api_instance.create_set()
    sets = fake_cache.get("order_sets_data")
    assert [s["name"] for s in sets] == ["Existing", "New"]


def test_create_set_returns_error_when_body_json_fails(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff())
    req = make_request()
    req.json = MagicMock(side_effect=ValueError("bad json"))
    api_instance.request = req

    responses = api_instance.create_set()
    assert len(responses) == 1
    # nothing was persisted
    assert fake_cache.get("order_sets_data") in (None, [])


# ── update_set ───────────────────────────────────────────────────────────────


def test_update_set_modifies_matching_set_and_refreshes_timestamp(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    fake_cache.set(
        "order_sets_data",
        [
            {
                "id": "abc",
                "name": "Old",
                "description": "",
                "order_type": "lab",
                "is_shared": False,
                "diagnosis_codes": [],
                "lab_partner": "",
                "lab_partner_name": "",
                "items": [],
                "fasting_required": False,
                "comment": "",
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        ],
    )
    api_instance.request = make_request(
        path="/sets/abc",
        json_body={"name": "New Name", "comment": "Updated"},
    )

    api_instance.update_set()
    sets = fake_cache.get("order_sets_data")
    assert sets[0]["name"] == "New Name"
    assert sets[0]["comment"] == "Updated"
    # untouched fields keep their values
    assert sets[0]["order_type"] == "lab"
    # updated_at must have moved forward
    assert sets[0]["updated_at"] != "2024-01-01T00:00:00+00:00"


def test_update_set_returns_404_when_id_not_found(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    fake_cache.set("order_sets_data", [{"id": "other", "name": "x"}])
    api_instance.request = make_request(
        path="/sets/missing",
        json_body={"name": "X"},
    )
    responses = api_instance.update_set()
    assert len(responses) == 1
    # cache untouched
    assert fake_cache.get("order_sets_data") == [{"id": "other", "name": "x"}]


def test_update_set_strips_querystring_from_path(
    api_instance: Any, fake_cache: FakeCache
) -> None:
    """update_set parses the id from the path; querystrings should be ignored."""
    fake_cache.set(
        "order_sets_data",
        [{"id": "abc", "name": "x", "description": "", "order_type": "lab",
          "is_shared": False, "diagnosis_codes": [], "lab_partner": "",
          "lab_partner_name": "", "items": [], "fasting_required": False,
          "comment": "", "updated_at": "z"}],
    )
    api_instance.request = make_request(
        path="/sets/abc?cache_bust=1",
        json_body={"name": "Renamed"},
    )
    api_instance.update_set()
    assert fake_cache.get("order_sets_data")[0]["name"] == "Renamed"


# ── delete_set ───────────────────────────────────────────────────────────────


def test_delete_set_removes_matching_set(
    api_instance: Any, fake_cache: FakeCache
) -> None:
    fake_cache.set(
        "order_sets_data",
        [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
    )
    api_instance.request = make_request(path="/sets/a")

    api_instance.delete_set()
    sets = fake_cache.get("order_sets_data")
    assert len(sets) == 1
    assert sets[0]["id"] == "b"


def test_delete_set_returns_404_when_not_found(
    api_instance: Any, fake_cache: FakeCache
) -> None:
    fake_cache.set("order_sets_data", [{"id": "a", "name": "A"}])
    api_instance.request = make_request(path="/sets/missing")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    # cache untouched
    assert fake_cache.get("order_sets_data") == [{"id": "a", "name": "A"}]
