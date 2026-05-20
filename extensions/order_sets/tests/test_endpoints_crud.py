"""Tests for the order-set CRUD endpoints (list/create/update/delete).

After the storage refactor, persistence is via the ``OrderSet`` CustomModel
instead of the plugin cache (which had a 14-day TTL — the wrong tool for
durable reference data).

Auth invariants preserved from the prior round:
  * create_set requires an authenticated staff (else 401).
  * update_set / delete_set require staff + (creator-or-admin) authorization.
  * Handlers do not wrap themselves in ``try / except Exception`` —
    unexpected errors propagate so Sentry sees them.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from .conftest import (
    make_order_set,
    make_request,
    make_staff,
    patch_order_set_query,
)


# Use real-shape staff ids. ``Staff.id`` is stored as ``uuid.uuid4().hex``
# (32-char undashed); using arbitrary strings like "admin-1" let earlier
# rounds slip through bugs where production id math diverged from tests.
DEFAULT_STAFF_ID = uuid.uuid4().hex
ADMIN_ID = uuid.uuid4().hex
OTHER_USER_ID = uuid.uuid4().hex


def _set_staff(api_instance: Any, mocker: MagicMock, staff: Any | None) -> None:
    """Stub ``_current_staff()`` to return the supplied object."""
    mocker.patch.object(api_instance, "_current_staff", return_value=staff)


def _set_admins(api_instance: Any, admin_ids: str = "") -> None:
    """Configure the ADMIN_STAFF_IDS secret on the instance."""
    api_instance.secrets = {"ADMIN_STAFF_IDS": admin_ids}


# ── list_sets ────────────────────────────────────────────────────────────────


def test_list_sets_queries_orderset_with_visibility_filter(
    api_instance: Any, mocker: MagicMock
) -> None:
    """``list_sets`` should issue a single ``OrderSet.objects.filter(...).order_by('name')``
    chain — never load the whole table and filter in Python."""
    _set_staff(api_instance, mocker, make_staff(staff_id="me"))
    rows = [
        make_order_set(set_id="2", name="A-mine", is_shared=False, created_by="me"),
        make_order_set(set_id="1", name="Z-shared", is_shared=True, created_by="other"),
    ]
    filter_mock, chain = patch_order_set_query(mocker, all_results=rows)

    responses = api_instance.list_sets()
    assert len(responses) == 1
    assert filter_mock.call_count == 1
    chain.order_by.assert_called_once_with("name")


def test_list_sets_with_anonymous_caller(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Anonymous caller still gets a single filtered query — the empty
    ``staff_id`` is what we pass into the OR clause, not a Python post-filter."""
    _set_staff(api_instance, mocker, None)
    patch_order_set_query(mocker, all_results=[])

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
    api_instance: Any, mocker: MagicMock
) -> None:
    """Anonymous create is rejected; ``OrderSet.objects.create`` is never called."""
    _set_staff(api_instance, mocker, None)
    create_mock = mocker.patch("order_sets.api.endpoints.OrderSet.objects.create")
    api_instance.request = make_request(json_body={"name": "X"})

    responses = api_instance.create_set()
    assert len(responses) == 1
    create_mock.assert_not_called()


def test_create_set_persists_with_generated_id(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(
        api_instance,
        mocker,
        make_staff(staff_id=DEFAULT_STAFF_ID, first_name="A", last_name="B"),
    )
    new_row = make_order_set(set_id="generated", name="Diabetes Workup")
    create_mock = mocker.patch(
        "order_sets.api.endpoints.OrderSet.objects.create", return_value=new_row
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

    create_mock.assert_called_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["name"] == "Diabetes Workup"
    assert kwargs["is_shared"] is True
    assert kwargs["created_by"] == DEFAULT_STAFF_ID
    assert kwargs["created_by_name"] == "A B"
    assert kwargs["fasting_required"] is True
    assert kwargs["items"] == [{"code": "CBC", "name": "CBC"}]
    # A UUID was generated for the public id.
    assert "set_id" in kwargs and len(kwargs["set_id"]) >= 32


def test_create_set_applies_sensible_defaults_for_minimal_body(
    api_instance: Any, mocker: MagicMock
) -> None:
    """A logged-in caller submitting an empty body gets the documented defaults."""
    _set_staff(
        api_instance,
        mocker,
        make_staff(staff_id=DEFAULT_STAFF_ID, first_name="A", last_name="B"),
    )
    create_mock = mocker.patch(
        "order_sets.api.endpoints.OrderSet.objects.create",
        return_value=make_order_set(),
    )
    api_instance.request = make_request(json_body={})

    api_instance.create_set()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["name"] == "Untitled"
    assert kwargs["order_type"] == "lab"
    assert kwargs["is_shared"] is False
    # created_by is always the authenticated staff id — never an empty string.
    assert kwargs["created_by"] == DEFAULT_STAFF_ID
    assert kwargs["items"] == []
    assert kwargs["diagnosis_codes"] == []


def test_create_set_returns_400_when_body_json_fails(
    api_instance: Any, mocker: MagicMock
) -> None:
    """ValueError from request.json() is the only narrowly-caught exception."""
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    create_mock = mocker.patch("order_sets.api.endpoints.OrderSet.objects.create")
    req = make_request()
    req.json = MagicMock(side_effect=ValueError("bad json"))
    api_instance.request = req

    responses = api_instance.create_set()
    assert len(responses) == 1
    create_mock.assert_not_called()


# ── update_set ───────────────────────────────────────────────────────────────


def test_update_set_returns_401_when_no_staff(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, None)
    target = make_order_set(set_id="abc", created_by=DEFAULT_STAFF_ID, name="Old")
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(path="/sets/abc", json_body={"name": "X"})

    responses = api_instance.update_set()
    assert len(responses) == 1
    target.save.assert_not_called()
    assert target.name == "Old"


def test_update_set_returns_400_when_body_json_fails(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    target = make_order_set(set_id="abc", created_by=DEFAULT_STAFF_ID, name="Old")
    patch_order_set_query(mocker, first=target)
    req = make_request(path="/sets/abc")
    req.json = MagicMock(side_effect=ValueError("bad json"))
    api_instance.request = req

    responses = api_instance.update_set()
    assert len(responses) == 1
    target.save.assert_not_called()


def test_update_set_returns_404_when_id_not_found(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    patch_order_set_query(mocker, first=None)
    api_instance.request = make_request(path="/sets/missing", json_body={"name": "X"})

    responses = api_instance.update_set()
    assert len(responses) == 1


def test_update_set_returns_403_when_not_creator_and_not_admin(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Defends shared sets from being overwritten by any random authenticated caller."""
    _set_staff(api_instance, mocker, make_staff(staff_id=OTHER_USER_ID))
    _set_admins(api_instance)  # empty admin list — fail closed
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, is_shared=True, name="Original"
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Hijacked"}
    )

    responses = api_instance.update_set()
    assert len(responses) == 1
    target.save.assert_not_called()
    assert target.name == "Original"


def test_update_set_modifies_matching_set_when_caller_is_creator(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, name="Old", comment=""
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "New Name", "comment": "Updated"}
    )

    api_instance.update_set()
    assert target.name == "New Name"
    assert target.comment == "Updated"
    target.save.assert_called_once()


def test_update_set_only_writes_fields_present_in_body(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Partial updates preserve unmentioned fields — the body is treated as a
    patch, not a put."""
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    target = make_order_set(
        set_id="abc",
        created_by=DEFAULT_STAFF_ID,
        name="Old",
        order_type="lab",
        lab_partner="lp-1",
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Renamed"}
    )

    api_instance.update_set()
    assert target.name == "Renamed"
    # untouched fields keep their values
    assert target.order_type == "lab"
    assert target.lab_partner == "lp-1"
    target.save.assert_called_once()


def test_update_set_allows_admin_to_modify_other_users_set(
    api_instance: Any, mocker: MagicMock
) -> None:
    """An ADMIN_STAFF_IDS member can edit a shared set someone else created."""
    _set_staff(api_instance, mocker, make_staff(staff_id=ADMIN_ID))
    _set_admins(api_instance, admin_ids=ADMIN_ID)
    target = make_order_set(
        set_id="abc",
        created_by=DEFAULT_STAFF_ID,
        is_shared=True,
        name="Practice-wide",
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Practice-wide v2"}
    )

    api_instance.update_set()
    assert target.name == "Practice-wide v2"
    target.save.assert_called_once()


def test_update_set_admin_secret_tolerates_whitespace(
    api_instance: Any, mocker: MagicMock
) -> None:
    """``ADMIN_STAFF_IDS`` tolerates whitespace around each comma-separated id."""
    _set_staff(api_instance, mocker, make_staff(staff_id=ADMIN_ID))
    other_admin = uuid.uuid4().hex
    _set_admins(api_instance, admin_ids=f"  {other_admin}  ,  {ADMIN_ID}  ")
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, is_shared=True
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Edited"}
    )

    api_instance.update_set()
    target.save.assert_called_once()


def test_update_set_admin_secret_accepts_dashed_uuid(
    api_instance: Any, mocker: MagicMock
) -> None:
    """An admin who pastes a dashed UUID into the secret must still match an
    undashed ``Staff.id``. Both sides canonicalize via ``uuid.UUID(...).hex``.

    This is the bug-class the third review pass caught: arbitrary string ids
    in tests masked the production form mismatch.
    """
    admin_uuid = uuid.uuid4()  # has both .hex (undashed) and str() (dashed)
    _set_staff(api_instance, mocker, make_staff(staff_id=admin_uuid.hex))
    _set_admins(api_instance, admin_ids=str(admin_uuid))  # dashed form
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, is_shared=True, name="Original"
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Edited by admin"}
    )

    api_instance.update_set()
    target.save.assert_called_once()
    assert target.name == "Edited by admin"


def test_update_set_admin_secret_passes_non_uuid_values_verbatim(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Non-UUID admin entries (legacy internal codes, free-form ids) are kept
    as-is — ``_canonical_id`` falls back to the input when ``uuid.UUID(...)``
    raises ``ValueError``."""
    legacy_id = "legacy-internal-admin-code"
    _set_staff(api_instance, mocker, make_staff(staff_id=legacy_id))
    _set_admins(api_instance, admin_ids=legacy_id)
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, is_shared=True
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Edited"}
    )

    api_instance.update_set()
    target.save.assert_called_once()


def test_update_set_admin_secret_accepts_undashed_uuid(
    api_instance: Any, mocker: MagicMock
) -> None:
    """The opposite shape of the same canonicalization: undashed in the
    secret, dashed in ``str(staff.id)`` (defense in depth against any future
    Staff model that emits dashed form). Currently ``Staff.id`` is already
    undashed, so both cases must converge."""
    admin_uuid = uuid.uuid4()
    _set_staff(api_instance, mocker, make_staff(staff_id=str(admin_uuid)))
    _set_admins(api_instance, admin_ids=admin_uuid.hex)
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, is_shared=True, name="Original"
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc", json_body={"name": "Edited"}
    )

    api_instance.update_set()
    target.save.assert_called_once()


def test_update_set_strips_querystring_from_path(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    target = make_order_set(set_id="abc", created_by=DEFAULT_STAFF_ID, name="Old")
    filter_mock, _ = patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(
        path="/sets/abc?cache_bust=1", json_body={"name": "Renamed"}
    )

    api_instance.update_set()
    # The querystring was stripped — the query was on `set_id="abc"`.
    filter_mock.assert_called_once_with(set_id="abc")


# ── delete_set ───────────────────────────────────────────────────────────────


def test_delete_set_returns_401_when_no_staff(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, None)
    target = make_order_set(set_id="abc", created_by=DEFAULT_STAFF_ID)
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(path="/sets/abc")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    target.delete.assert_not_called()


def test_delete_set_returns_404_when_not_found(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    patch_order_set_query(mocker, first=None)
    api_instance.request = make_request(path="/sets/missing")

    responses = api_instance.delete_set()
    assert len(responses) == 1


def test_delete_set_returns_403_when_not_creator_and_not_admin(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=OTHER_USER_ID))
    _set_admins(api_instance)
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, is_shared=True
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(path="/sets/abc")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    target.delete.assert_not_called()


def test_delete_set_removes_set_when_caller_is_creator(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=DEFAULT_STAFF_ID))
    _set_admins(api_instance)
    target = make_order_set(set_id="abc", created_by=DEFAULT_STAFF_ID)
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(path="/sets/abc")

    api_instance.delete_set()
    target.delete.assert_called_once()


def test_delete_set_allows_admin_to_remove_other_users_set(
    api_instance: Any, mocker: MagicMock
) -> None:
    _set_staff(api_instance, mocker, make_staff(staff_id=ADMIN_ID))
    _set_admins(api_instance, admin_ids=ADMIN_ID)
    target = make_order_set(
        set_id="abc", created_by=DEFAULT_STAFF_ID, is_shared=True
    )
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(path="/sets/abc")

    api_instance.delete_set()
    target.delete.assert_called_once()


def test_delete_set_rejects_legacy_row_with_empty_created_by(
    api_instance: Any, mocker: MagicMock
) -> None:
    """A row with ``created_by=""`` must not match a caller whose id is also
    ``""`` — defense in depth."""
    _set_staff(api_instance, mocker, make_staff(staff_id=""))
    _set_admins(api_instance)
    target = make_order_set(set_id="x", created_by="")
    patch_order_set_query(mocker, first=target)
    api_instance.request = make_request(path="/sets/x")

    responses = api_instance.delete_set()
    assert len(responses) == 1
    target.delete.assert_not_called()
