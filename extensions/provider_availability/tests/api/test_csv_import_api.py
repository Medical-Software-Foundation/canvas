"""Tests for provider_availability.api.csv_import_api."""

from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import DEFAULT, MagicMock, patch

from provider_availability.api.csv_import_api import CSVImportAPI

CSV_MODULE = "provider_availability.api.csv_import_api"

HEADER = (
    "type,staff_key,location,visit_type,day,start,end,all_day,date,reason,"
    "hold_type,buffer_pre,buffer_post,min_lead_hours,slot_minutes,"
    "recurrence_frequency,recurrence_interval,effective_start,effective_end,group_key"
)

STAFF_IDS = {"1234567890"}
LOCATIONS = [{"id": "loc-1", "name": "Main Clinic"}]
VISIT_TYPES = [{"id": "vt-1", "name": "New Patient"}]


def _parse(response) -> tuple[dict, int]:
    body = json.loads(getattr(response, "content"))
    return body, response.status_code


def _handler(json_body: dict | None = None, secrets: dict | None = None) -> CSVImportAPI:
    handler = CSVImportAPI(MagicMock())
    handler.request = MagicMock()
    handler.request.json.return_value = json_body or {}
    handler.secrets = secrets or {}
    return handler


def _file_part(content: str) -> MagicMock:
    fp = MagicMock()
    fp.is_file.return_value = True
    fp.content = content.encode("utf-8")
    return fp


def _set_upload(handler: CSVImportAPI, content: str | None) -> None:
    form = {"file": _file_part(content)} if content is not None else {}
    handler.request.form_data.return_value = form


def _patch_lookups():
    return patch.multiple(
        CSV_MODULE,
        get_active_staff_ids=MagicMock(return_value=STAFF_IDS),
        get_active_locations=MagicMock(return_value=LOCATIONS),
        get_scheduleable_visit_types=MagicMock(return_value=VISIT_TYPES),
    )


# -- template ----------------------------------------------------------------


def test_download_template_returns_csv():
    handler = _handler()
    result = handler.download_template()
    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers["Content-Type"] == "text/csv"
    assert b"staff_key" in resp.content


# -- validate ----------------------------------------------------------------


def test_validate_missing_file_returns_400():
    handler = _handler()
    _set_upload(handler, None)
    body, status = _parse(handler.validate_upload()[0])
    assert status == HTTPStatus.BAD_REQUEST
    assert "No CSV file" in body["error"]


def test_validate_not_a_file_returns_400():
    handler = _handler()
    fp = MagicMock()
    fp.is_file.return_value = False
    handler.request.form_data.return_value = {"file": fp}
    _, status = _parse(handler.validate_upload()[0])
    assert status == HTTPStatus.BAD_REQUEST


def test_validate_groups_rows_into_one_rule():
    handler = _handler()
    csv = (
        HEADER + "\n"
        + "rule,1234567890,Main Clinic,,monday,09:00,12:00,,,,,,,,,weekly,1,,,\n"
        + "rule,1234567890,Main Clinic,,monday,13:00,17:00,,,,,,,,,weekly,1,,,\n"
    )
    _set_upload(handler, csv)
    with _patch_lookups(), patch(CSV_MODULE + ".check_rule_overlap", return_value=None):
        body, _ = _parse(handler.validate_upload()[0])
    assert body["total_rows"] == 2
    assert body["record_count"] == 1
    assert body["rule_count"] == 1
    assert body["error_count"] == 0
    assert body["records"][0]["provider_id"] == "1234567890"


def test_validate_surfaces_structural_error():
    handler = _handler()
    csv = HEADER + "\n" + "rule,1234567890,Main Clinic,,funday,09:00,12:00,,,,,,,,,weekly,1,,,\n"
    _set_upload(handler, csv)
    with _patch_lookups(), patch(CSV_MODULE + ".check_rule_overlap", return_value=None):
        body, _ = _parse(handler.validate_upload()[0])
    assert body["error_count"] == 1
    assert body["errors"][0]["row_number"] == 2
    assert any("day must be one of" in e for e in body["errors"][0]["errors"])


def test_validate_surfaces_unknown_provider():
    handler = _handler()
    csv = HEADER + "\n" + "rule,0000000000,Main Clinic,,monday,09:00,12:00,,,,,,,,,weekly,1,,,\n"
    _set_upload(handler, csv)
    with _patch_lookups(), patch(CSV_MODULE + ".check_rule_overlap", return_value=None):
        body, _ = _parse(handler.validate_upload()[0])
    assert body["record_count"] == 0
    assert "not found" in body["errors"][0]["errors"][0]


def test_validate_flags_overlap_and_excludes_record():
    handler = _handler()
    csv = HEADER + "\n" + "rule,1234567890,Main Clinic,,monday,09:00,12:00,,,,,,,,,weekly,1,,,\n"
    _set_upload(handler, csv)
    with _patch_lookups(), patch(
        CSV_MODULE + ".check_rule_overlap", return_value="Overlapping availability on Monday"
    ):
        body, _ = _parse(handler.validate_upload()[0])
    assert body["record_count"] == 0
    assert body["error_count"] == 1
    assert "Overlapping" in body["errors"][0]["errors"][0]


def test_validate_counts_blocks_and_rblocks():
    handler = _handler()
    csv = (
        HEADER + "\n"
        + "block,1234567890,,,,,,true,2026-07-04,Holiday,,,,,,,,,,\n"
        + "rblock,1234567890,,,monday,12:00,13:00,,,Lunch,none,,,,,weekly,1,,,\n"
    )
    _set_upload(handler, csv)
    with _patch_lookups(), patch(CSV_MODULE + ".check_rule_overlap", return_value=None):
        body, _ = _parse(handler.validate_upload()[0])
    assert body["block_count"] == 1
    assert body["rblock_count"] == 1
    assert body["record_count"] == 2


# -- commit ------------------------------------------------------------------


def test_commit_denied_when_not_authorized():
    handler = _handler(json_body={"records": [{"kind": "rule"}]})
    denied = [MagicMock()]
    with patch(CSV_MODULE + "._check_write_access", return_value=denied):
        result = handler.commit_records()
    assert result is denied


def test_commit_no_records_returns_400():
    handler = _handler(json_body={"records": []})
    with patch(CSV_MODULE + "._check_write_access", return_value=None):
        body, status = _parse(handler.commit_records()[0])
    assert status == HTTPStatus.BAD_REQUEST


def test_commit_saves_rule_block_rblock_and_syncs():
    rule_rec = {
        "kind": "rule", "provider_id": "prov-1", "location_ids": ["loc-1"],
        "visit_types": [], "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        "time_windows": [], "buffer_minutes": {"pre": 0, "post": 15},
        "booking_interval": {"min_lead_hours": 24, "slot_granularity_minutes": 15},
        "recurrence_frequency": "weekly", "recurrence_interval": 1,
        "effective_start": None, "effective_end": None, "reason": "", "is_active": True,
    }
    block_rec = {
        "kind": "block", "provider_id": "prov-1", "location_ids": [],
        "start": "2026-07-04T00:00:00", "end": "2026-07-04T23:59:59",
        "all_day": True, "reason": "Holiday",
    }
    rblock_rec = {
        "kind": "rblock", "provider_id": "prov-1", "location_ids": [],
        "weekly_schedule": {"monday": [{"start": "12:00", "end": "13:00"}]},
        "time_windows": [], "recurrence_frequency": "weekly", "recurrence_interval": 1,
        "reason": "Lunch", "hold_type": "none", "effective_start": None,
        "effective_end": None, "is_active": True,
    }
    handler = _handler(json_body={"records": [rule_rec, block_rec, rblock_rec]})

    with patch(CSV_MODULE + "._check_write_access", return_value=None), patch.multiple(
        CSV_MODULE,
        save_rule=DEFAULT,
        save_block=DEFAULT,
        save_recurring_block=DEFAULT,
        build_block_event_effects=DEFAULT,
        build_recurring_block_sync_effects=DEFAULT,
        sync_provider_availability=DEFAULT,
        build_lead_time_block_effects=DEFAULT,
        get_rules_for_provider=DEFAULT,
    ) as mocks:
        mocks["build_block_event_effects"].return_value = ["blk-eff"]
        mocks["build_recurring_block_sync_effects"].return_value = ["rb-eff"]
        mocks["sync_provider_availability"].return_value = ["sync-eff"]
        mocks["build_lead_time_block_effects"].return_value = ["lead-eff"]
        mocks["get_rules_for_provider"].return_value = []
        result = handler.commit_records()

    body, _ = _parse(result[-1])
    assert body["created_rules"] == 1
    assert body["created_blocks"] == 1
    assert body["created_recurring_blocks"] == 1

    mocks["save_rule"].assert_called_once()
    mocks["save_block"].assert_called_once()
    mocks["save_recurring_block"].assert_called_once()
    # One provider touched -> synced exactly once
    mocks["sync_provider_availability"].assert_called_once_with("prov-1")

    # Effects from block, rblock, and provider sync are all forwarded
    assert "blk-eff" in result
    assert "rb-eff" in result
    assert "sync-eff" in result


def test_commit_refreshes_lead_time_for_active_rules():
    rule_rec = {
        "kind": "rule", "provider_id": "prov-1", "location_ids": [], "visit_types": [],
        "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]}, "time_windows": [],
        "buffer_minutes": {"pre": 0, "post": 15},
        "booking_interval": {"min_lead_hours": 24, "slot_granularity_minutes": 15},
        "recurrence_frequency": "weekly", "recurrence_interval": 1,
        "effective_start": None, "effective_end": None, "reason": "", "is_active": True,
    }
    handler = _handler(json_body={"records": [rule_rec]})

    saved_rule = MagicMock()
    saved_rule.is_active = True
    saved_rule.booking_interval.min_lead_hours = 24

    with patch(CSV_MODULE + "._check_write_access", return_value=None), patch.multiple(
        CSV_MODULE,
        save_rule=DEFAULT,
        sync_provider_availability=DEFAULT,
        build_lead_time_block_effects=DEFAULT,
        get_rules_for_provider=DEFAULT,
    ) as mocks:
        mocks["sync_provider_availability"].return_value = []
        mocks["build_lead_time_block_effects"].return_value = ["lead-eff"]
        mocks["get_rules_for_provider"].return_value = [saved_rule]
        result = handler.commit_records()

    mocks["build_lead_time_block_effects"].assert_called_once_with(saved_rule)
    assert "lead-eff" in result
