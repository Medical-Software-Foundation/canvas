"""CSV export tests — verify header + row shape and oversized-result handling."""

from datetime import date
from unittest.mock import MagicMock, patch

from report_builder.reports.export import stream_csv
from report_builder.reports.models import Report


def _patient_report() -> Report:
    return Report(
        id="rpt-1",
        name="Care gap",
        description="",
        root_entity="patient",
        columns=("first_name", "last_name"),
    )


@patch("report_builder.reports.export.build_queryset")
def test_stream_csv_emits_header_and_rows(mock_build: MagicMock) -> None:
    fake_row = MagicMock()
    fake_row.id = "abc"
    fake_row.dbid = 1
    fake_row.first_name = "Jane"
    fake_row.last_name = "Doe"

    fake_qs = MagicMock()
    fake_qs.count.return_value = 1
    fake_qs.iterator.return_value = iter([fake_row])
    mock_build.return_value = (fake_qs, [])

    output = "".join(stream_csv(_patient_report(), date(2026, 5, 22)))
    lines = output.strip().splitlines()
    assert lines[0] == "id,first_name,last_name"
    assert lines[1] == "abc,Jane,Doe"


@patch("report_builder.reports.export.build_queryset")
def test_stream_csv_too_large_emits_comment_only(mock_build: MagicMock) -> None:
    fake_qs = MagicMock()
    fake_qs.count.return_value = 999_999
    mock_build.return_value = (fake_qs, [])

    output = "".join(stream_csv(_patient_report(), date(2026, 5, 22)))
    assert output.startswith("# too-large")
    assert "999999" in output


@patch("report_builder.reports.export.build_queryset")
def test_stream_csv_includes_aggregate_columns(mock_build: MagicMock) -> None:
    fake_row = MagicMock()
    fake_row.id = "abc"
    fake_row.dbid = 1
    fake_row.first_name = "Jane"
    fake_row.last_name = "Doe"
    fake_row._agg_xyz = 5

    fake_qs = MagicMock()
    fake_qs.count.return_value = 1
    fake_qs.iterator.return_value = iter([fake_row])
    mock_build.return_value = (fake_qs, [("appt_count", "_agg_xyz")])

    output = "".join(stream_csv(_patient_report(), date(2026, 5, 22)))
    lines = output.strip().splitlines()
    assert lines[0] == "id,first_name,last_name,appt_count"
    assert lines[1] == "abc,Jane,Doe,5"
