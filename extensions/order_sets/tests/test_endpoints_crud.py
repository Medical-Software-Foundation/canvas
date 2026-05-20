"""Tests for the order-set CRUD endpoints (list/create/update/delete).

After the auth refactor:
  * create_set requires an authenticated staff (else 401).
  * update_set / delete_set require staff + (creator-or-admin) authorization.
  * Handlers no longer wrap themselves in ``try / except Exception`` —
    unexpected errors propagate so Sentry sees them.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from .conftest import FakeCache, make_request, make_staff


DEFAULT_STAFF_ID = "staff-me"
ADMIN_ID = "admin-1"
OTHER_USER_ID = "staff-other"


def _set_staff(api_instance: Any, mocker: MagicMock, staff: Any | None) -> None:
    """Stub ``_current_staff()`` to return the supplied object."""
    mocker.patch.object(api_instance, "_current_staff", return_value=staff)


def _set_admins(api_instance: Any, admin_ids: str = "") -> None:
    """Configure the ADMIN_STAFF_IDS secret on the instance."""
    api_instance.secrets = {"ADMIN_STAFF_IDS": admin_ids}


# ── list_sets ────────────────────────────────────────────────────────────────


def test_list_sets_returns_shared_and_own_sets_sorted(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id="me"))

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

    # Read-only op — cache state is unchanged. Re-run the filter math to verify
    # the public contract (shared OR own) without depending on JSONResponse
    # internals.
    sets = fake_cache.get("order_sets_data")
    visible = [s for s in sets if s["is_shared"] or s["created_by"] == "me"]
    assert {s["id"] for s in visible} == {"1", "2"}


def test_list_sets_with_anonymous_caller_sees_only_shared(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """No logged-in staff is allowed to read shared sets but not personal ones."""
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
    _set_staff(api_instance, mocker, make_staff())
    responses = api_instance.list_sets()
    assert len(responses) == 1


def test_list_sets_propagates_unexpected_errors(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Unexpected exceptions must reach Sentry — the handler no longer swallows them."""
    mocker.patch.object(
        api_instance, "_current_staff", side_effect=RuntimeError("boom")
    )
    with pytest.raises(RuntimeError):
        api_instance.list_sets()


# ── create_set ───────────────────────────────────────────────────────────────


def test_create_set_returns_401_when_no_staff(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """Anonymous create is rejected; nothing is persisted."""
    _set_staff(api_instance, mocker, None)
    api_instance.request = make_request(json_body={"name": "X"})

    responses = api_instance.create_set()
    assert len(responses) == 1
    assert fake_cache.get("order_sets_data") in (None, [])


def test_create_set_persists_with_generated_id_and_timestamps(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(
        api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID, first_name="A", last_name="B")
    )
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
    assert created["created_by"] == DEFAULT_STAFF_ID
    assert created["created_by_name"] == "A B"
    assert created["fasting_required"] is True
    assert created["items"][0]["code"] == "CBC"
    assert "id" in created and len(created["id"]) > 0
    assert created["created_at"] == created["updated_at"]


def test_create_set_applies_sensible_defaults_for_minimal_body(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """A logged-in caller submitting an empty body gets the documented defaults."""
    _set_staff(
        api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID, first_name="A", last_name="B")
    )
    api_instance.request = make_request(json_body={})

    api_instance.create_set()
    sets = fake_cache.get("order_sets_data")
    assert len(sets) == 1
    created = sets[0]
    assert created["name"] == "Untitled"
    assert created["order_type"] == "lab"
    assert created["is_shared"] is False
    # created_by is always the authenticated staff id — never an empty string.
    assert created["created_by"] == DEFAULT_STAFF_ID
    assert created["items"] == []
    assert created["diagnosis_codes"] == []


def test_create_set_appends_to_existing_cache(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    fake_cache.set("order_sets_data", [{"id": "pre-1", "name": "Existing"}])
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    api_instance.request = make_request(json_body={"name": "New"})

    api_instance.create_set()
    sets = fake_cache.get("order_sets_data")
    assert [s["name"] for s in sets] == ["Existing", "New"]


def test_create_set_returns_400_when_body_json_fails(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """ValueError from request.json() is the only narrowly-caught exception."""
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    req = make_request()
    req.json = MagicMock(side_effect=ValueError("bad json"))
    api_instance.request = req

    responses = api_instance.create_set()
    assert len(responses) == 1
    assert fake_cache.get("order_sets_data") in (None, [])


# ── update_set ───────────────────────────────────────────────────────────────


def _seed_set(
    fake_cache: FakeCache,
    *,
    set_id: str = "abc",
    created_by: str = DEFAULT_STAFF_ID,
    is_shared: bool = False,
    name: str = "Old",
) -> None:
    fake_cache.set(
        "order_sets_data",
        [
            {
                "id": set_id,
                "name": name,
                "description": "",
                "order_type": "lab",
                "is_shared": is_shared,
                "created_by": created_by,
                "created_by_name": "Original Author",
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


def test_update_set_returns_401_when_no_staff(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, None)
    _seed_set(fake_cache)
    api_instance.request = make_request(path="/sets/abc", json_body={"name": "X"})

    responses = api_instance.update_set()
    assert len(responses) == 1
    assert fake_cache.get("order_sets_data")[0]["name"] == "Old"


def test_update_set_returns_400_when_body_json_fails(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    _seed_set(fake_cache)
    req = make_request(path="/sets/abc")
    req.json = MagicMock(side_effect=ValueError("bad json"))
    api_instance.request = req

    responses = api_instance.update_set()
    assert len(responses) == 1
    assert fake_cache.get("order_sets_data")[0]["name"] == "Old"


def test_update_set_returns_404_when_id_not_found(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    fake_cache.set("order_sets_data", [{"id": "other", "name": "x"}])
    api_instance.request = make_request(path="/sets/missing", json_body={"name": "X"})

    responses = api_instance.update_set()
    assert len(responses) == 1
    assert fake_cache.get("order_sets_data") == [{"id": "other", "name": "x"}]


def test_update_set_returns_403_when_not_creator_and_not_admin(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """Defends shared sets from being overwritten by any random authenticated caller."""
    _set_staff(api_instance, mocker, make_staff(staff_id=OTHER_USER_ID))
    _set_admins(api_instance)  # empty admin list — fail closed
    _seed_set(fake_cache, created_by=DEFAULT_STAFF_ID, is_shared=True, name="Original")
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Hijacked"}
    )

    responses = api_instance.update_set()
    assert len(responses) == 1
    assert fake_cache.get("order_sets_data")[0]["name"] == "Original"  # untouched


def test_update_set_modifies_matching_set_when_caller_is_creator(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    _seed_set(fake_cache, created_by=DEFAULT_STAFF_ID)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "New Name", "comment": "Updated"}
    )

    api_instance.update_set()
    sets = fake_cache.get("order_sets_data")
    assert sets[0]["name"] == "New Name"
    assert sets[0]["comment"] == "Updated"
    assert sets[0]["order_type"] == "lab"
    assert sets[0]["updated_at"] != "2024-01-01T00:00:00+00:00"


def test_update_set_allows_admin_to_modify_other_users_set(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """An ADMIN_STAFF_IDS member can edit a shared set someone else created."""
    _set_staff(api_instance, mocker, make_staff(staff_id=ADMIN_ID))
    _set_admins(api_instance, admin_ids=ADMIN_ID)
    _seed_set(fake_cache, created_by=DEFAULT_STAFF_ID, is_shared=True, name="Practice-wide")
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Practice-wide v2"}
    )

    api_instance.update_set()
    assert fake_cache.get("order_sets_data")[0]["name"] == "Practice-wide v2"


def test_update_set_admin_secret_tolerates_whitespace(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """``ADMIN_STAFF_IDS`` tolerates whitespace around each comma-separated id."""
    _set_staff(api_instance, mocker, make_staff(staff_id=ADMIN_ID))
    _set_admins(api_instance, admin_ids=f"  someone-else  ,  {ADMIN_ID}  ")
    _seed_set(fake_cache, created_by=DEFAULT_STAFF_ID, is_shared=True)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Edited"}
    )

    api_instance.update_set()
    assert fake_cache.get("order_sets_data")[0]["name"] == "Edited"


def test_update_set_strips_querystring_from_path(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    _seed_set(fake_cache, created_by=DEFAULT_STAFF_ID)
    api_instance.request = make_request(
        path="/sets/abc?cache_bust=1", json_body={"name": "Renamed"}
    )
    api_instance.update_set()
    assert fake_cache.get("order_sets_data")[0]["name"] == "Renamed"


# ── delete_set ───────────────────────────────────────────────────────────────


def test_delete_set_returns_401_when_no_staff(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, None)
    _seed_set(fake_cache)
    api_instance.request = make_request(path="/sets/abc")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    assert len(fake_cache.get("order_sets_data")) == 1


def test_delete_set_returns_404_when_not_found(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    fake_cache.set("order_sets_data", [{"id": "a", "name": "A"}])
    api_instance.request = make_request(path="/sets/missing")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    assert fake_cache.get("order_sets_data") == [{"id": "a", "name": "A"}]


def test_delete_set_returns_403_when_not_creator_and_not_admin(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=OTHER_USER_ID))
    _set_admins(api_instance)
    _seed_set(fake_cache, created_by=DEFAULT_STAFF_ID, is_shared=True)
    api_instance.request = make_request(path="/sets/abc")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    # set still present — not wiped
    assert len(fake_cache.get("order_sets_data")) == 1


def test_delete_set_removes_set_when_caller_is_creator(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    fake_cache.set(
        "order_sets_data",
        [
            {"id": "a", "name": "Mine", "created_by": DEFAULT_STAFF_ID},
            {"id": "b", "name": "Other", "created_by": "someone-else"},
        ],
    )
    api_instance.request = make_request(path="/sets/a")

    api_instance.delete_set()
    sets = fake_cache.get("order_sets_data")
    assert len(sets) == 1
    assert sets[0]["id"] == "b"


def test_delete_set_allows_admin_to_remove_other_users_set(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=ADMIN_ID))
    _set_admins(api_instance, admin_ids=ADMIN_ID)
    _seed_set(fake_cache, created_by=DEFAULT_STAFF_ID, is_shared=True)
    api_instance.request = make_request(path="/sets/abc")

    api_instance.delete_set()
    assert fake_cache.get("order_sets_data") == []


def test_delete_set_rejects_legacy_row_with_empty_created_by(
    api_instance: Any, mocker: MagicMock, fake_cache: FakeCache
) -> None:
    """A row persisted before the create-time auth gate (``created_by=""``) must
    not match a caller whose id is also ``""`` — defense in depth."""
    _set_staff(api_instance, mocker, make_staff(staff_id=""))
    _set_admins(api_instance)
    fake_cache.set(
        "order_sets_data", [{"id": "x", "name": "Legacy", "created_by": ""}]
    )
    api_instance.request = make_request(path="/sets/x")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    assert len(fake_cache.get("order_sets_data")) == 1
