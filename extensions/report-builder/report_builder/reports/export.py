"""CSV export — streamed, with the same 10K cap as paginated runs.

Yields the header row plus up to `MAX_ROWS` data rows in batches of 500. The
caller is responsible for hooking the generator up to an HTTP streaming
response.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from report_builder.reports.models import Report
from report_builder.reports.query import (
    MAX_ROWS,
    build_queryset,
    serialize_row,
)
from report_builder.schemas.registry import ENTITY_REGISTRY

BATCH_SIZE = 500


def _csv_escape(value: Any) -> str:
    """Escape a single CSV field value."""
    s = "" if value is None else str(value)
    if "," in s or '"' in s or "\n" in s or "\r" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _csv_line(values: list[Any]) -> str:
    return ",".join(_csv_escape(v) for v in values) + "\r\n"


def stream_csv(report: Report, as_of_date: date) -> Iterable[str]:
    """Yield CSV strings for `report`. Aborts with a `# too-large` marker if
    the result set exceeds `MAX_ROWS`."""
    entity = ENTITY_REGISTRY[report.root_entity]

    qs, annotation_columns = build_queryset(report, as_of_date)
    total = qs.count()

    if total > MAX_ROWS:
        yield f"# too-large: result has {total} rows, refine filters (cap {MAX_ROWS})\n"
        return

    header_cols = ["id"] + list(report.columns) + [label for label, _ in annotation_columns]
    yield _csv_line(header_cols)

    iterator = qs.iterator(chunk_size=BATCH_SIZE)
    for row in iterator:
        serialized = serialize_row(row, entity, report.columns, annotation_columns)
        yield _csv_line([serialized.get(col) for col in header_cols])
