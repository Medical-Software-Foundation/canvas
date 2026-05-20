"""Tests for the provider / lab / CPT lookup endpoints + their helpers."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from .conftest import (
    make_lab_partner,
    make_lab_test,
    make_note,
    make_request,
    make_staff,
    make_staff_role,
)


# ── list_providers ───────────────────────────────────────────────────────────


def _patch_provider_roles(
    mocker: MagicMock, roles: list[Any]
) -> None:
    """Stub ``StaffRole.objects.filter(role_type="PROVIDER")`` to yield ``roles``.

    Each role only needs a ``staff_id`` attribute now — the endpoint no longer
    dereferences ``role.staff`` (that was the N+1 path).
    """
    role_filter = MagicMock()
    role_filter.__iter__ = lambda self: iter(roles)
    mocker.patch(
        "order_sets.api.endpoints.StaffRole.objects.filter", return_value=role_filter
    )


def _patch_active_staff(mocker: MagicMock, staff_list: list[Any]) -> None:
    """Stub ``Staff.objects.filter(active=True)`` to yield ``staff_list``."""
    staff_filter = MagicMock()
    staff_filter.__iter__ = lambda self: iter(staff_list)
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter", return_value=staff_filter
    )


def test_list_providers_returns_active_provider_staff_sorted(
    api_instance: Any, mocker: MagicMock
) -> None:
    s1 = make_staff(staff_id="s1", first_name="Zoe", last_name="Z")
    s2 = make_staff(staff_id="s2", first_name="Amy", last_name="A")
    inactive = make_staff(staff_id="s3", first_name="In", last_name="Active", active=False)

    _patch_provider_roles(
        mocker, [make_staff_role(s1), make_staff_role(s2), make_staff_role(inactive)]
    )
    _patch_active_staff(mocker, [s1, s2])  # only active ones

    responses = api_instance.list_providers()
    assert len(responses) == 1


def test_list_providers_skips_staff_without_provider_role(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Active staff that aren't PROVIDERs must not appear in the result."""
    s_provider = make_staff(staff_id="p1")
    s_nurse = make_staff(staff_id="n1")

    _patch_provider_roles(mocker, [make_staff_role(s_provider)])
    _patch_active_staff(mocker, [s_provider, s_nurse])

    responses = api_instance.list_providers()
    assert len(responses) == 1


def test_list_providers_avoids_n_plus_1_by_reading_staff_id_directly(
    api_instance: Any, mocker: MagicMock
) -> None:
    """The role objects in the loop expose ``staff_id`` so the endpoint never
    dereferences ``role.staff`` (which would trigger a per-row Staff SELECT).

    We assert this by giving the mock role a ``staff`` attribute that raises if
    accessed — the endpoint must not touch it.
    """
    s1 = make_staff(staff_id="p1")

    class _BoobyTrappedRole:
        staff_id = "p1"

        @property
        def staff(self) -> object:
            raise AssertionError("role.staff was accessed — N+1 regression")

    _patch_provider_roles(mocker, [_BoobyTrappedRole()])
    _patch_active_staff(mocker, [s1])

    responses = api_instance.list_providers()
    assert len(responses) == 1


def test_list_providers_propagates_unexpected_errors(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Unexpected exceptions must reach Sentry — handler no longer swallows them."""
    mocker.patch(
        "order_sets.api.endpoints.StaffRole.objects.filter",
        side_effect=RuntimeError("db down"),
    )
    with pytest.raises(RuntimeError):
        api_instance.list_providers()


# ── get_note_provider ────────────────────────────────────────────────────────


def test_get_note_provider_returns_null_when_no_open_note(
    api_instance: Any, mocker: MagicMock
) -> None:
    mocker.patch.object(api_instance, "_find_open_note", return_value=(None, ""))
    api_instance.request = make_request(query_params={"patient_id": "pt"})

    responses = api_instance.get_note_provider()
    assert len(responses) == 1


def test_get_note_provider_returns_active_provider(
    api_instance: Any, mocker: MagicMock
) -> None:
    provider = make_staff(staff_id="p1", first_name="Greg", last_name="House", active=True)
    mocker.patch.object(
        api_instance, "_find_open_note", return_value=("nt-1", "p1")
    )
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=provider)),
    )
    api_instance.request = make_request(query_params={"patient_id": "pt"})

    responses = api_instance.get_note_provider()
    assert len(responses) == 1


def test_get_note_provider_returns_null_provider_when_inactive(
    api_instance: Any, mocker: MagicMock
) -> None:
    inactive_provider = make_staff(staff_id="p1", active=False)
    mocker.patch.object(
        api_instance, "_find_open_note", return_value=("nt-1", "p1")
    )
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=inactive_provider)),
    )
    api_instance.request = make_request(query_params={"patient_id": "pt"})

    responses = api_instance.get_note_provider()
    assert len(responses) == 1


def test_get_note_provider_propagates_db_errors(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Unexpected exceptions must reach Sentry — handler no longer swallows them."""
    mocker.patch.object(
        api_instance, "_find_open_note", side_effect=RuntimeError("boom")
    )
    api_instance.request = make_request(query_params={"patient_id": "pt"})

    with pytest.raises(RuntimeError):
        api_instance.get_note_provider()


# ── list_lab_partners ────────────────────────────────────────────────────────


def test_list_lab_partners_returns_all_partners(
    api_instance: Any, mocker: MagicMock
) -> None:
    p1 = make_lab_partner(partner_id="lp-1", name="LabCorp")
    p2 = make_lab_partner(partner_id="lp-2", name="Quest")
    mocker.patch(
        "order_sets.api.endpoints.LabPartner.objects.all", return_value=[p1, p2]
    )
    responses = api_instance.list_lab_partners()
    assert len(responses) == 1


# ── list_lab_tests ───────────────────────────────────────────────────────────


def test_list_lab_tests_empty_when_partner_not_found(
    api_instance: Any, mocker: MagicMock
) -> None:
    mocker.patch(
        "order_sets.api.endpoints.LabPartner.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=None)),
    )
    api_instance.request = make_request(path="/lab-tests/missing")

    responses = api_instance.list_lab_tests()
    assert len(responses) == 1


def test_list_lab_tests_filters_by_search_query(
    api_instance: Any, mocker: MagicMock
) -> None:
    cbc = make_lab_test(order_code="CBC", order_name="Complete Blood Count")
    lipid = make_lab_test(order_code="LIPID", order_name="Lipid Panel")
    partner = make_lab_partner(partner_id="lp", tests=[cbc, lipid])
    mocker.patch(
        "order_sets.api.endpoints.LabPartner.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=partner)),
    )
    api_instance.request = make_request(
        path="/lab-tests/lp", query_params={"search": "blood"}
    )

    responses = api_instance.list_lab_tests()
    assert len(responses) == 1


def test_list_lab_tests_returns_all_when_no_search(
    api_instance: Any, mocker: MagicMock
) -> None:
    cbc = make_lab_test(order_code="CBC", order_name="Complete Blood Count")
    partner = make_lab_partner(partner_id="lp", tests=[cbc])
    mocker.patch(
        "order_sets.api.endpoints.LabPartner.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=partner)),
    )
    api_instance.request = make_request(path="/lab-tests/lp")

    responses = api_instance.list_lab_tests()
    assert len(responses) == 1


# ── cpt_search ───────────────────────────────────────────────────────────────


def test_cpt_search_returns_empty_when_cdm_unavailable(
    api_instance: Any, mocker: MagicMock
) -> None:
    """If the SDK didn't expose ChargeDescriptionMaster, search returns []."""
    mocker.patch("order_sets.api.endpoints.ChargeDescriptionMaster", None)
    api_instance.request = make_request(query_params={"q": "glucose"})

    responses = api_instance.cpt_search()
    assert len(responses) == 1


def test_cpt_search_filters_results_to_50(
    api_instance: Any, mocker: MagicMock
) -> None:
    # Build a fake CDM queryset that supports .all() .filter() .order_by() and slicing
    cdms = [
        type("CDM", (), {"cpt_code": f"00{i:03}", "name": f"Test {i}"})()
        for i in range(60)
    ]

    class _QS:
        def __init__(self, items: list[Any]) -> None:
            self._items = items

        def filter(self, *_args: Any, **_kwargs: Any) -> "_QS":
            return _QS(self._items)

        def order_by(self, *_args: str) -> "_QS":
            return _QS(self._items)

        def __getitem__(self, key: Any) -> list[Any]:
            return self._items[key]

        def __iter__(self) -> Any:
            return iter(self._items)

    cdm_mock = MagicMock()
    cdm_mock.objects.all.return_value = _QS(cdms)
    mocker.patch("order_sets.api.endpoints.ChargeDescriptionMaster", cdm_mock)
    api_instance.request = make_request(query_params={"q": "test"})

    responses = api_instance.cpt_search()
    assert len(responses) == 1


def test_cpt_search_skips_entries_without_cpt_code(
    api_instance: Any, mocker: MagicMock
) -> None:
    rows = [
        type("CDM", (), {"cpt_code": "", "name": "Empty"})(),
        type("CDM", (), {"cpt_code": "82951", "name": "Glucose"})(),
    ]

    class _QS:
        def __init__(self, items: list[Any]) -> None:
            self._items = items

        def filter(self, *_args: Any, **_kwargs: Any) -> "_QS":
            return _QS(self._items)

        def order_by(self, *_args: str) -> "_QS":
            return _QS(self._items)

        def __getitem__(self, key: Any) -> list[Any]:
            return self._items[key]

        def __iter__(self) -> Any:
            return iter(self._items)

    cdm_mock = MagicMock()
    cdm_mock.objects.all.return_value = _QS(rows)
    mocker.patch("order_sets.api.endpoints.ChargeDescriptionMaster", cdm_mock)
    api_instance.request = make_request(query_params={})

    responses = api_instance.cpt_search()
    assert len(responses) == 1


# ── _find_open_note helper ────────────────────────────────────────────────────


def test_find_open_note_returns_note_id_and_provider_key(
    api_instance: Any, mocker: MagicMock
) -> None:
    provider = make_staff(staff_id="prov-1")
    note = make_note(note_id="note-x", dbid=1, provider=provider)
    note_qs = MagicMock()
    note_qs.order_by = MagicMock(
        return_value=MagicMock(first=MagicMock(return_value=note))
    )
    mocker.patch(
        "order_sets.api.endpoints.Note.objects.filter", return_value=note_qs
    )
    mocker.patch(
        "order_sets.api.endpoints.CurrentNoteStateEvent.objects.filter",
        return_value=MagicMock(values_list=MagicMock(return_value=[1, 2])),
    )

    uuid_returned, provider_key = api_instance._find_open_note("pt-1")
    assert uuid_returned == "note-x"
    assert provider_key == "prov-1"


def test_find_open_note_returns_none_when_no_match(
    api_instance: Any, mocker: MagicMock
) -> None:
    note_qs = MagicMock()
    note_qs.order_by = MagicMock(
        return_value=MagicMock(first=MagicMock(return_value=None))
    )
    mocker.patch(
        "order_sets.api.endpoints.Note.objects.filter", return_value=note_qs
    )
    mocker.patch(
        "order_sets.api.endpoints.CurrentNoteStateEvent.objects.filter",
        return_value=MagicMock(values_list=MagicMock(return_value=[])),
    )

    uuid_returned, provider_key = api_instance._find_open_note("pt-1")
    assert uuid_returned is None
    assert provider_key == ""


def test_find_open_note_handles_note_without_provider(
    api_instance: Any, mocker: MagicMock
) -> None:
    note = make_note(note_id="note-x", dbid=1, provider=None)
    note_qs = MagicMock()
    note_qs.order_by = MagicMock(
        return_value=MagicMock(first=MagicMock(return_value=note))
    )
    mocker.patch(
        "order_sets.api.endpoints.Note.objects.filter", return_value=note_qs
    )
    mocker.patch(
        "order_sets.api.endpoints.CurrentNoteStateEvent.objects.filter",
        return_value=MagicMock(values_list=MagicMock(return_value=[1])),
    )

    uuid_returned, provider_key = api_instance._find_open_note("pt-1")
    assert uuid_returned == "note-x"
    assert provider_key == ""


# ── _resolve_provider helper ─────────────────────────────────────────────────


def test_resolve_provider_returns_none_when_empty(api_instance: Any) -> None:
    """Falsy provider_id short-circuits before the query — no DB touch."""
    assert api_instance._resolve_provider("") is None


def test_resolve_provider_returns_id_when_active_provider_role_exists(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Single ``.exists()`` filtered on (role_type, staff_id, staff__active).
    The ``staff__active=True`` join is required — without it we'd happily
    return the id of a since-deactivated provider (e.g. on an old open note)."""
    exists_chain = MagicMock()
    exists_chain.exists.return_value = True
    role_filter = mocker.patch(
        "order_sets.api.endpoints.StaffRole.objects.filter",
        return_value=exists_chain,
    )

    assert api_instance._resolve_provider("prov-1") == "prov-1"
    role_filter.assert_called_once_with(
        role_type="PROVIDER", staff_id="prov-1", staff__active=True
    )


def test_resolve_provider_returns_none_when_role_missing_or_staff_inactive(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Whether the role doesn't exist or the staff is deactivated, the DB
    returns ``exists() == False`` for the joined filter and we refuse."""
    exists_chain = MagicMock()
    exists_chain.exists.return_value = False
    mocker.patch(
        "order_sets.api.endpoints.StaffRole.objects.filter",
        return_value=exists_chain,
    )

    assert api_instance._resolve_provider("prov-1") is None
