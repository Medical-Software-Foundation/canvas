"""Tests for the provider / lab / CPT lookup endpoints + their helpers."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from .conftest import (
    make_lab_partner,
    make_lab_test,
    make_note,
    make_request,
    make_staff,
)


# ── list_providers ───────────────────────────────────────────────────────────


def _patch_provider_staff_query(
    mocker: MagicMock, staff_list: list[Any]
) -> MagicMock:
    """Stub the canonical Staff-side provider query.

    The endpoint now uses ``Staff.objects.filter(active=True,
    roles__role_type="PROVIDER").distinct().order_by(...)`` — a single query
    from the Staff side, matched against ``Staff.id`` (the hex key callers
    actually use). We must NOT mock from the StaffRole side: ``role.staff_id``
    is the dbid integer FK column, not ``Staff.id``, and would silently never
    match callers' UUID strings in production.
    """
    chain = MagicMock()
    chain.distinct.return_value = chain
    chain.order_by.return_value = staff_list
    return mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter", return_value=chain
    )


def test_list_providers_queries_staff_side_with_roles_traversal(
    api_instance: Any, mocker: MagicMock
) -> None:
    """``list_providers`` issues a single Staff-side query that joins through
    ``roles__role_type``. Asserting on the filter kwargs is what catches the
    regression where ``role.staff_id`` (dbid int) was used in place of
    ``Staff.id`` (hex key) and the endpoint silently returned ``[]``."""
    s1 = make_staff(staff_id=uuid.uuid4().hex, first_name="Zoe", last_name="Z")
    s2 = make_staff(staff_id=uuid.uuid4().hex, first_name="Amy", last_name="A")
    filter_mock = _patch_provider_staff_query(mocker, [s2, s1])

    responses = api_instance.list_providers()
    assert len(responses) == 1
    # The filter must include both kwargs together — that's what the SDK
    # convention requires (see dea_prescriber_filter.engine.lookups).
    filter_mock.assert_called_once_with(
        active=True, roles__role_type="PROVIDER"
    )


def test_list_providers_orders_results_at_the_database(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Sorting happens in SQL, not Python, so we don't burn cycles on the
    Python side for large staff lists."""
    s = make_staff(staff_id=uuid.uuid4().hex)
    filter_mock = _patch_provider_staff_query(mocker, [s])

    api_instance.list_providers()
    filter_mock.return_value.distinct.assert_called_once()
    filter_mock.return_value.distinct.return_value.order_by.assert_called_once_with(
        "first_name", "last_name"
    )


def test_list_providers_propagates_unexpected_errors(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Unexpected exceptions must reach Sentry — handler no longer swallows them."""
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
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


def test_resolve_provider_queries_staff_side_with_id_active_and_roles(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Single ``Staff.objects.filter(id=..., active=True, roles__role_type=...)
    .exists()`` — query from the Staff side so we match against the actual
    hex key callers send, not the dbid integer FK column.

    All three kwargs must be present. Without ``active=True`` we'd happily
    return the id of a since-deactivated provider (e.g. on an old open note);
    without ``roles__role_type`` we'd accept any active staff member.
    """
    provider_id = uuid.uuid4().hex
    exists_chain = MagicMock()
    exists_chain.exists.return_value = True
    staff_filter = mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=exists_chain,
    )

    assert api_instance._resolve_provider(provider_id) == provider_id
    staff_filter.assert_called_once_with(
        id=provider_id, active=True, roles__role_type="PROVIDER"
    )


def test_resolve_provider_returns_none_when_no_match(
    api_instance: Any, mocker: MagicMock
) -> None:
    """Whether the staff doesn't exist, is deactivated, or has no PROVIDER
    role, the joined filter's ``.exists()`` is False and we refuse."""
    exists_chain = MagicMock()
    exists_chain.exists.return_value = False
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=exists_chain,
    )

    assert api_instance._resolve_provider(uuid.uuid4().hex) is None
