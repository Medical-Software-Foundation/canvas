"""Tests for execute_set / execute_custom and the _execute_order_set helper.

``_execute_order_set`` now takes an OrderSet model instance (mocked via
``make_order_set``) rather than a dict pulled from the cache.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from .conftest import make_order_set, make_request, patch_order_set_query


def _stub_open_note(
    api_instance: Any, mocker: MagicMock, note_uuid: str | None, provider_key: str
) -> None:
    mocker.patch.object(
        api_instance, "_find_open_note", return_value=(note_uuid, provider_key)
    )


def _stub_resolve_provider(
    api_instance: Any, mocker: MagicMock, returns: str | None
) -> None:
    mocker.patch.object(api_instance, "_resolve_provider", return_value=returns)


# ── execute_set ──────────────────────────────────────────────────────────────


def test_execute_set_returns_404_when_set_id_missing(
    api_instance: Any, mocker: MagicMock
) -> None:
    patch_order_set_query(mocker, first=None)
    api_instance.request = make_request(path="/execute/missing", body=b"")

    responses = api_instance.execute_set()
    assert len(responses) == 1


def test_execute_set_with_empty_body_executes_no_items(
    api_instance: Any, mocker: MagicMock
) -> None:
    """A set with an empty items array should short-circuit with a 400."""
    target = make_order_set(set_id="s1", items=[], order_type="lab")
    patch_order_set_query(mocker, first=target)
    # body is empty bytes — code path uses `self.request.body` truthiness
    api_instance.request = make_request(path="/execute/s1", body=b"")

    responses = api_instance.execute_set()
    assert len(responses) == 1


def test_execute_set_calls_helper_with_set_items(
    api_instance: Any, mocker: MagicMock
) -> None:
    """execute_set should delegate to _execute_order_set with the set's items."""
    item = {"code": "CBC", "name": "CBC"}
    target = make_order_set(
        set_id="s1", items=[item], order_type="lab", lab_partner="lp"
    )
    patch_order_set_query(mocker, first=target)
    spy = mocker.patch.object(
        api_instance, "_execute_order_set", return_value=[MagicMock()]
    )
    api_instance.request = make_request(
        path="/execute/s1",
        body=b'{"patient_id":"pt-1","provider_id":"prov"}',
        json_body={"patient_id": "pt-1", "provider_id": "prov"},
    )

    api_instance.execute_set()
    spy.assert_called_once()
    args, _ = spy.call_args
    # args = (order_set, items, patient_id, provider_id)
    assert args[0] is target
    assert args[1] == [item]
    assert args[2] == "pt-1"
    assert args[3] == "prov"


# ── execute_custom ───────────────────────────────────────────────────────────


def test_execute_custom_filters_items_to_selected_codes(
    api_instance: Any, mocker: MagicMock
) -> None:
    target = make_order_set(
        set_id="s1",
        order_type="lab",
        items=[
            {"code": "CBC", "name": "CBC"},
            {"code": "LIPID", "name": "Lipid"},
            {"code": "TSH", "name": "TSH"},
        ],
    )
    patch_order_set_query(mocker, first=target)
    spy = mocker.patch.object(
        api_instance, "_execute_order_set", return_value=[MagicMock()]
    )
    api_instance.request = make_request(
        json_body={
            "set_id": "s1",
            "selected_codes": ["CBC", "TSH"],
            "patient_id": "pt",
            "provider_id": "prov",
        }
    )

    api_instance.execute_custom()
    args, _ = spy.call_args
    selected_codes = {item["code"] for item in args[1]}
    assert selected_codes == {"CBC", "TSH"}


def test_execute_custom_returns_404_when_set_missing(
    api_instance: Any, mocker: MagicMock
) -> None:
    patch_order_set_query(mocker, first=None)
    api_instance.request = make_request(
        json_body={"set_id": "missing", "selected_codes": []}
    )
    responses = api_instance.execute_custom()
    assert len(responses) == 1


# ── _execute_order_set: error paths ──────────────────────────────────────────


def test_execute_order_set_rejects_when_no_items(api_instance: Any) -> None:
    target = make_order_set(order_type="lab")
    out = api_instance._execute_order_set(
        order_set=target, items=[], patient_id="pt", provider_id=""
    )
    assert len(out) == 1  # single error JSONResponse


def test_execute_order_set_rejects_when_no_open_note(
    api_instance: Any, mocker: MagicMock
) -> None:
    _stub_open_note(api_instance, mocker, None, "")
    target = make_order_set(order_type="lab")
    out = api_instance._execute_order_set(
        order_set=target,
        items=[{"code": "CBC"}],
        patient_id="pt",
        provider_id="",
    )
    assert len(out) == 1


def test_execute_order_set_rejects_when_no_valid_provider(
    api_instance: Any, mocker: MagicMock
) -> None:
    _stub_open_note(api_instance, mocker, "nt-1", "")
    _stub_resolve_provider(api_instance, mocker, None)
    target = make_order_set(order_type="lab")
    out = api_instance._execute_order_set(
        order_set=target,
        items=[{"code": "CBC"}],
        patient_id="pt",
        provider_id="bad",
    )
    assert len(out) == 1


def test_execute_order_set_falls_back_to_explicit_provider(
    api_instance: Any, mocker: MagicMock
) -> None:
    """If the note has no provider, explicit provider_id is resolved instead."""
    _stub_open_note(api_instance, mocker, "nt-1", "")
    # First call (from note key) returns None, second (explicit) returns prov
    mocker.patch.object(
        api_instance, "_resolve_provider", side_effect=[None, "prov"]
    )
    lab_cmd = mocker.patch("order_sets.api.endpoints.LabOrderCommand")
    lab_cmd.return_value.originate.return_value = MagicMock()

    target = make_order_set(order_type="lab", lab_partner="lp", diagnosis_codes=[])
    out = api_instance._execute_order_set(
        order_set=target,
        items=[{"code": "CBC"}],
        patient_id="pt",
        provider_id="prov",
    )
    assert len(out) == 2  # one Effect + one JSONResponse


# ── _execute_order_set: lab path ─────────────────────────────────────────────


def test_execute_order_set_lab_builds_single_command_for_all_codes(
    api_instance: Any, mocker: MagicMock
) -> None:
    _stub_open_note(api_instance, mocker, "nt-1", "prov")
    _stub_resolve_provider(api_instance, mocker, "prov")
    lab_cmd_cls = mocker.patch("order_sets.api.endpoints.LabOrderCommand")
    lab_cmd_cls.return_value.originate.return_value = MagicMock()

    target = make_order_set(
        order_type="lab",
        lab_partner="lp-1",
        diagnosis_codes=["E11.9"],
        fasting_required=True,
        comment="AM draw",
        name="Diabetes",
    )
    out = api_instance._execute_order_set(
        order_set=target,
        items=[{"code": "CBC"}, {"code": "LIPID"}, {"code": "TSH"}],
        patient_id="pt-1",
        provider_id="",
    )
    # One LabOrderCommand for all items
    assert lab_cmd_cls.call_count == 1
    _, kwargs = lab_cmd_cls.call_args
    assert kwargs["tests_order_codes"] == ["CBC", "LIPID", "TSH"]
    assert kwargs["diagnosis_codes"] == ["E11.9"]
    assert kwargs["fasting_required"] is True
    assert kwargs["comment"] == "AM draw"
    assert kwargs["lab_partner"] == "lp-1"
    assert kwargs["ordering_provider_key"] == "prov"
    assert kwargs["note_uuid"] == "nt-1"
    assert len(out) == 2


# ── _execute_order_set: imaging path ─────────────────────────────────────────


def test_execute_order_set_imaging_creates_one_command_per_item(
    api_instance: Any, mocker: MagicMock
) -> None:
    _stub_open_note(api_instance, mocker, "nt-1", "prov")
    _stub_resolve_provider(api_instance, mocker, "prov")
    img_cmd_cls = mocker.patch("canvas_sdk.commands.ImagingOrderCommand")
    img_cmd_cls.return_value.originate.return_value = MagicMock()

    target = make_order_set(
        order_type="imaging",
        diagnosis_codes=["R07.9"],
        comment="stat",
        name="Chest workup",
    )
    out = api_instance._execute_order_set(
        order_set=target,
        items=[{"code": "71045"}, {"code": "71046"}],
        patient_id="pt-1",
        provider_id="",
    )
    assert img_cmd_cls.call_count == 2
    # 2 effects + 1 JSONResponse
    assert len(out) == 3


# ── _execute_order_set: POC path ─────────────────────────────────────────────


def test_execute_order_set_poc_creates_perform_commands_with_combined_notes(
    api_instance: Any, mocker: MagicMock
) -> None:
    _stub_open_note(api_instance, mocker, "nt-1", "prov")
    _stub_resolve_provider(api_instance, mocker, "prov")
    perf_cmd_cls = mocker.patch("order_sets.api.endpoints.PerformCommand")
    perf_cmd_cls.return_value.originate.return_value = MagicMock()

    target = make_order_set(order_type="poc", comment="in-office", name="POC")
    api_instance._execute_order_set(
        order_set=target,
        items=[
            {"code": "81002", "name": "Urinalysis"},
            {"code": "82962", "name": "Glucose"},
        ],
        patient_id="pt-1",
        provider_id="prov",
    )
    assert perf_cmd_cls.call_count == 2
    first_call_kwargs = perf_cmd_cls.call_args_list[0].kwargs
    assert first_call_kwargs["cpt_code"] == "81002"
    assert "Urinalysis" in first_call_kwargs["notes"]
    assert "in-office" in first_call_kwargs["notes"]


def test_execute_order_set_poc_no_comment_uses_item_name_only(
    api_instance: Any, mocker: MagicMock
) -> None:
    _stub_open_note(api_instance, mocker, "nt-1", "prov")
    _stub_resolve_provider(api_instance, mocker, "prov")
    perf_cmd_cls = mocker.patch("order_sets.api.endpoints.PerformCommand")
    perf_cmd_cls.return_value.originate.return_value = MagicMock()

    target = make_order_set(order_type="poc", comment="", name="POC")
    api_instance._execute_order_set(
        order_set=target,
        items=[{"code": "81002", "name": "Urinalysis"}],
        patient_id="pt-1",
        provider_id="prov",
    )
    kwargs = perf_cmd_cls.call_args.kwargs
    assert kwargs["notes"] == "Urinalysis"
