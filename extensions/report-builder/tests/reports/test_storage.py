"""Storage layer tests — mock the SavedReport ORM, verify CRUD shape."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from report_builder.reports.models import Report
from report_builder.reports.storage import (
    ReportMetadata,
    delete_report,
    get_report,
    list_reports,
    save_report,
    update_report,
)


def _row(**overrides: object) -> MagicMock:
    row = MagicMock()
    row.report_id = overrides.get("report_id", "rpt-1")
    row.name = overrides.get("name", "Care gap")
    row.description = overrides.get("description", "")
    row.root_entity = overrides.get("root_entity", "patient")
    row.config = overrides.get(
        "config",
        {
            "id": "rpt-1",
            "name": "Care gap",
            "description": "",
            "root_entity": "patient",
            "conditions": [],
            "columns": [],
            "aggregate_columns": [],
        },
    )
    row.created_by = overrides.get("created_by", "staff-1")
    row.created_at = overrides.get("created_at", datetime(2026, 5, 22, 0, 0))
    row.updated_at = overrides.get("updated_at", datetime(2026, 5, 22, 0, 0))
    return row


@patch("report_builder.reports.storage.SavedReport")
def test_list_reports_returns_metadata(mock_model: MagicMock) -> None:
    only_qs = mock_model.objects.only.return_value
    only_qs.order_by.return_value = [_row(), _row(report_id="rpt-2")]

    result = list_reports()

    assert all(isinstance(r, ReportMetadata) for r in result)
    assert [r.id for r in result] == ["rpt-1", "rpt-2"]
    assert only_qs.order_by.call_args.args == ("-updated_at",)
    only_fields = mock_model.objects.only.call_args.args
    assert "config" not in only_fields
    assert "name" in only_fields and "updated_at" in only_fields


@patch("report_builder.reports.storage.SavedReport")
def test_get_report_returns_none_when_missing(mock_model: MagicMock) -> None:
    mock_model.objects.filter.return_value.first.return_value = None

    assert get_report("missing") is None
    mock_model.objects.filter.assert_called_once_with(report_id="missing")


@patch("report_builder.reports.storage.SavedReport")
def test_get_report_returns_parsed_report(mock_model: MagicMock) -> None:
    mock_model.objects.filter.return_value.first.return_value = _row()

    report = get_report("rpt-1")

    assert isinstance(report, Report)
    assert report.id == "rpt-1"
    assert report.name == "Care gap"


@patch("report_builder.reports.storage.SavedReport")
def test_save_report_creates_row_and_assigns_uuid_when_missing(mock_model: MagicMock) -> None:
    created_row = _row()
    mock_model.objects.create.return_value = created_row

    report = Report(name="Care gap", description="", root_entity="patient")
    saved = save_report(report, created_by="staff-1")

    assert saved.id == "rpt-1"
    assert mock_model.objects.create.call_count == 1
    call_kwargs = mock_model.objects.create.call_args.kwargs
    assert call_kwargs["name"] == "Care gap"
    assert call_kwargs["root_entity"] == "patient"
    assert call_kwargs["created_by"] == "staff-1"
    assert "report_id" in call_kwargs


@patch("report_builder.reports.storage.SavedReport")
def test_update_report_writes_row(mock_model: MagicMock) -> None:
    existing = _row(name="Old", description="Old")
    mock_model.objects.filter.return_value.first.return_value = existing

    new_report = Report(
        id="rpt-1", name="New", description="New desc", root_entity="patient"
    )
    updated = update_report(new_report)

    assert updated is not None
    assert existing.name == "New"
    assert existing.description == "New desc"
    existing.save.assert_called_once()


@patch("report_builder.reports.storage.SavedReport")
def test_update_report_returns_none_when_missing(mock_model: MagicMock) -> None:
    mock_model.objects.filter.return_value.first.return_value = None
    new_report = Report(id="rpt-x", name="X", description="", root_entity="patient")

    assert update_report(new_report) is None


def test_update_report_requires_id() -> None:
    import pytest

    new_report = Report(name="X", description="", root_entity="patient")
    with pytest.raises(ValueError):
        update_report(new_report)


@patch("report_builder.reports.storage.SavedReport")
def test_delete_report_returns_true_when_deleted(mock_model: MagicMock) -> None:
    mock_model.objects.filter.return_value.delete.return_value = (1, {})
    assert delete_report("rpt-1") is True
    mock_model.objects.filter.assert_called_once_with(report_id="rpt-1")


@patch("report_builder.reports.storage.SavedReport")
def test_delete_report_returns_false_when_missing(mock_model: MagicMock) -> None:
    mock_model.objects.filter.return_value.delete.return_value = (0, {})
    assert delete_report("missing") is False


def test_report_metadata_to_dict_has_expected_keys() -> None:
    md = ReportMetadata(
        id="rpt-1",
        name="Care gap",
        description="",
        root_entity="patient",
        created_by="staff-1",
        created_at="2026-05-22T00:00:00",
        updated_at="2026-05-22T00:00:00",
    )
    out = md.to_dict()
    assert set(out) == {
        "id",
        "name",
        "description",
        "root_entity",
        "created_by",
        "created_at",
        "updated_at",
    }
