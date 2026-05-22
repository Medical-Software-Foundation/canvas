"""Tests for the admin CRUD SimpleAPI.

Verifies:
  - Admin auth gate (fail-open when ADMIN_STAFF_IDS unset, restricted when set)
  - CDM validation on create and update (422 on invalid)
  - CRUD round-trips
  - Soft-disable via PATCH enabled=False
"""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from canvas_sdk.v1.data import ChargeDescriptionMaster

from curated_cpt_picker.models.curated_cpt_code import CuratedCptCode
from curated_cpt_picker.protocols.admin_api import AdminAPI


TODAY = date.today()


def _make_request(
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
    path_params: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        method=method,
        query_params={},
        headers=headers or {},
        path_params=path_params or {},
        json=lambda: body or {},
    )


def _make_handler(
    request: SimpleNamespace,
    admin_staff_ids: str = "",
) -> AdminAPI:
    handler = AdminAPI.__new__(AdminAPI)
    handler.request = request  # type: ignore[attr-defined]
    handler.secrets = {"ADMIN_STAFF_IDS": admin_staff_ids}  # type: ignore[attr-defined]
    return handler


@pytest.fixture
def active_cdm() -> None:
    ChargeDescriptionMaster.objects.create(
        cpt_code="99213", name="Office 15 min", short_name="Office 15", charge_amount=0,
        effective_date=TODAY - timedelta(days=365), end_date=None,
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="99214", name="Office 25 min", short_name="Office 25", charge_amount=0,
        effective_date=TODAY - timedelta(days=365), end_date=None,
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="EXPIRED", name="Old code", short_name="Old", charge_amount=0,
        effective_date=TODAY - timedelta(days=400), end_date=TODAY - timedelta(days=30),
    )


def _staff_headers(staff_id: str = "staff-uuid-1") -> dict:
    return {"canvas-logged-in-user-id": staff_id}


# --- Auth gating ---

def test_list_returns_403_when_not_logged_in() -> None:
    handler = _make_handler(_make_request(headers={}))
    results = handler.list_codes()
    assert results[0].status_code == 403


def test_list_allowed_when_admin_staff_ids_unset_and_user_logged_in() -> None:
    """Fail-open default: empty secret allows any logged-in staff."""
    CuratedCptCode.objects.create(cpt_code="99213", description="Test")
    handler = _make_handler(_make_request(headers=_staff_headers()), admin_staff_ids="")
    results = handler.list_codes()
    assert results[0].status_code != 403


def test_list_denies_unlisted_staff_when_admin_staff_ids_set() -> None:
    handler = _make_handler(
        _make_request(headers=_staff_headers("rando-uuid")),
        admin_staff_ids="allowed-uuid-1,allowed-uuid-2",
    )
    results = handler.list_codes()
    assert results[0].status_code == 403


def test_list_allows_listed_staff_when_admin_staff_ids_set() -> None:
    handler = _make_handler(
        _make_request(headers=_staff_headers("allowed-uuid-1")),
        admin_staff_ids="allowed-uuid-1,allowed-uuid-2",
    )
    results = handler.list_codes()
    assert results[0].status_code != 403


# --- Create with CDM validation ---

def test_create_rejects_cpt_not_in_cdm(active_cdm) -> None:
    handler = _make_handler(_make_request(
        method="POST",
        body={"cpt_code": "00000", "description": "Bogus"},
        headers=_staff_headers(),
    ))
    results = handler.create_code()
    assert results[0].status_code == 422
    error = json.loads(results[0].content)
    assert "not in the ChargeDescriptionMaster" in error["error"]
    assert CuratedCptCode.objects.count() == 0


def test_create_rejects_cpt_with_only_expired_cdm_row(active_cdm) -> None:
    handler = _make_handler(_make_request(
        method="POST",
        body={"cpt_code": "EXPIRED", "description": "Old"},
        headers=_staff_headers(),
    ))
    results = handler.create_code()
    assert results[0].status_code == 422
    assert CuratedCptCode.objects.count() == 0


def test_create_persists_when_cdm_valid(active_cdm) -> None:
    handler = _make_handler(_make_request(
        method="POST",
        body={
            "cpt_code": "99213",
            "description": "Office 15",
            "default_units": 2,
            "modifiers": [{"code": "25", "system": "http://www.ama-assn.org/go/cpt"}],
            "display_order": 5,
        },
        headers=_staff_headers(),
    ))
    results = handler.create_code()
    assert results[0].status_code == 201
    body = json.loads(results[0].content)
    assert body["cpt_code"] == "99213"
    assert body["default_units"] == 2
    assert body["modifiers"][0]["code"] == "25"

    persisted = CuratedCptCode.objects.get(pk=body["id"])
    assert persisted.display_order == 5
    assert persisted.enabled is True


def test_create_rejects_missing_required_fields(active_cdm) -> None:
    handler = _make_handler(_make_request(
        method="POST",
        body={"cpt_code": "99213"},  # no description
        headers=_staff_headers(),
    ))
    results = handler.create_code()
    assert results[0].status_code == 400


# --- Update ---

def test_update_validates_new_cpt_against_cdm(active_cdm) -> None:
    entry = CuratedCptCode.objects.create(cpt_code="99213", description="Original")
    handler = _make_handler(_make_request(
        method="PATCH",
        body={"cpt_code": "00000"},
        headers=_staff_headers(),
        path_params={"entry_id": str(entry.pk)},
    ))
    results = handler.update_code()
    assert results[0].status_code == 422
    entry.refresh_from_db()
    assert entry.cpt_code == "99213"  # unchanged


def test_update_skips_validation_when_cpt_unchanged(active_cdm) -> None:
    """Editing description-only should not re-validate the CPT — that allows
    admins to fix typos on entries even if CDM goes stale later."""
    entry = CuratedCptCode.objects.create(cpt_code="EXPIRED", description="Stale code")
    handler = _make_handler(_make_request(
        method="PATCH",
        body={"description": "Updated description"},
        headers=_staff_headers(),
        path_params={"entry_id": str(entry.pk)},
    ))
    results = handler.update_code()
    assert results[0].status_code == 200
    entry.refresh_from_db()
    assert entry.description == "Updated description"


def test_update_soft_disable_via_enabled_flag(active_cdm) -> None:
    entry = CuratedCptCode.objects.create(cpt_code="99213", description="Test", enabled=True)
    handler = _make_handler(_make_request(
        method="PATCH",
        body={"enabled": False},
        headers=_staff_headers(),
        path_params={"entry_id": str(entry.pk)},
    ))
    results = handler.update_code()
    assert results[0].status_code == 200
    entry.refresh_from_db()
    assert entry.enabled is False


def test_update_returns_404_for_unknown_entry() -> None:
    handler = _make_handler(_make_request(
        method="PATCH",
        body={"description": "x"},
        headers=_staff_headers(),
        path_params={"entry_id": "99999999"},
    ))
    results = handler.update_code()
    assert results[0].status_code == 404


# --- Delete ---

def test_delete_removes_entry() -> None:
    entry = CuratedCptCode.objects.create(cpt_code="99213", description="To remove")
    handler = _make_handler(_make_request(
        method="DELETE",
        headers=_staff_headers(),
        path_params={"entry_id": str(entry.pk)},
    ))
    results = handler.delete_code()
    assert results[0].status_code == 200
    assert CuratedCptCode.objects.filter(pk=entry.pk).count() == 0


def test_delete_returns_404_for_unknown_entry() -> None:
    handler = _make_handler(_make_request(
        method="DELETE",
        headers=_staff_headers(),
        path_params={"entry_id": "99999999"},
    ))
    results = handler.delete_code()
    assert results[0].status_code == 404


# --- List ---

def test_list_returns_all_entries_including_disabled() -> None:
    """Admin UI needs to see disabled entries too so admins can re-enable them."""
    CuratedCptCode.objects.create(cpt_code="99213", description="Active", enabled=True)
    CuratedCptCode.objects.create(cpt_code="99214", description="Disabled", enabled=False)
    handler = _make_handler(_make_request(headers=_staff_headers()))
    results = handler.list_codes()
    body = json.loads(results[0].content)
    cpts = {e["cpt_code"] for e in body["entries"]}
    assert cpts == {"99213", "99214"}


# --- CDM lookup endpoint (powers the admin CPT dropdown) ---

def test_cdm_codes_returns_only_currently_active(active_cdm) -> None:
    handler = _make_handler(_make_request(headers=_staff_headers()))
    results = handler.list_cdm_codes()
    body = json.loads(results[0].content)
    cpts = {row["cpt_code"] for row in body["cdm_codes"]}
    assert "99213" in cpts
    assert "99214" in cpts
    assert "EXPIRED" not in cpts


def test_cdm_codes_dedupes_multiple_active_rows_per_cpt(active_cdm) -> None:
    """The same CPT can appear in CDM more than once with different effective
    windows. The dropdown should show one entry per CPT, not per CDM row."""
    ChargeDescriptionMaster.objects.create(
        cpt_code="99213", name="Office 15 min v2", short_name="Office 15 v2", charge_amount=0,
        effective_date=TODAY - timedelta(days=10), end_date=None,
    )
    handler = _make_handler(_make_request(headers=_staff_headers()))
    body = json.loads(handler.list_cdm_codes()[0].content)
    cpt_99213_rows = [row for row in body["cdm_codes"] if row["cpt_code"] == "99213"]
    assert len(cpt_99213_rows) == 1


def test_cdm_codes_includes_label_from_short_name(active_cdm) -> None:
    handler = _make_handler(_make_request(headers=_staff_headers()))
    body = json.loads(handler.list_cdm_codes()[0].content)
    by_code = {row["cpt_code"]: row["label"] for row in body["cdm_codes"]}
    assert by_code["99213"] == "Office 15"
    assert by_code["99214"] == "Office 25"


def test_cdm_codes_denies_unauthenticated() -> None:
    handler = _make_handler(_make_request(headers={}))
    assert handler.list_cdm_codes()[0].status_code == 403
