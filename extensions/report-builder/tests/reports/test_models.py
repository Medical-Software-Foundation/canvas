"""Round-trip + edge-case tests for the report DTOs and JSON wire format."""

import pytest

from report_builder.reports.models import (
    AggregateColumn,
    AggregateCondition,
    FieldCondition,
    RelativeDate,
    Report,
    report_from_json,
    report_to_json,
)


def _full_payload() -> dict:
    return {
        "id": "abc-123",
        "name": "Care gap",
        "description": "Patients with no completed visit",
        "root_entity": "patient",
        "conditions": [
            {"kind": "field", "field": "active", "op": "eq", "value": True},
            {
                "kind": "aggregate",
                "relationship": "appointments",
                "fn": "count",
                "aggregate_field": None,
                "sub_filters": [
                    {"kind": "field", "field": "status", "op": "eq", "value": "confirmed"},
                    {
                        "kind": "field",
                        "field": "start_time",
                        "op": "gte",
                        "value": {"_type": "relative_date", "offset_days": -90},
                    },
                ],
                "compare_op": "eq",
                "compare_value": 0,
            },
        ],
        "columns": ["first_name", "last_name"],
        "aggregate_columns": [
            {
                "label": "last_appt",
                "relationship": "appointments",
                "fn": "max",
                "aggregate_field": "start_time",
                "sub_filters": [],
            }
        ],
        "created_by": "staff-1",
        "created_at": "2026-05-22T00:00:00",
        "updated_at": "2026-05-22T00:00:00",
    }


def test_round_trip_preserves_payload() -> None:
    payload = _full_payload()
    parsed = report_from_json(payload)
    assert isinstance(parsed, Report)
    assert isinstance(parsed.conditions[0], FieldCondition)
    assert isinstance(parsed.conditions[1], AggregateCondition)
    assert isinstance(parsed.conditions[1].sub_filters[1].value, RelativeDate)

    out = report_to_json(parsed)
    assert out == payload


def test_relative_date_resolves_against_as_of() -> None:
    from datetime import date

    rd = RelativeDate(offset_days=-90)
    assert rd.resolve(date(2026, 5, 22)) == date(2026, 2, 21)


def test_report_from_json_rejects_missing_name() -> None:
    payload = _full_payload()
    payload["name"] = ""
    with pytest.raises(ValueError, match="name"):
        report_from_json(payload)


def test_report_from_json_rejects_missing_root_entity() -> None:
    payload = _full_payload()
    payload["root_entity"] = ""
    with pytest.raises(ValueError, match="root_entity"):
        report_from_json(payload)


def test_report_from_json_rejects_unknown_condition_kind() -> None:
    payload = _full_payload()
    payload["conditions"] = [{"kind": "weird", "field": "active", "op": "eq", "value": True}]
    with pytest.raises(ValueError, match="condition kind"):
        report_from_json(payload)


def test_report_from_json_accepts_minimal_payload() -> None:
    parsed = report_from_json({"name": "X", "root_entity": "patient"})
    assert parsed.name == "X"
    assert parsed.root_entity == "patient"
    assert parsed.conditions == ()
    assert parsed.columns == ()
    assert parsed.aggregate_columns == ()
    assert parsed.id is None


def test_aggregate_column_round_trip() -> None:
    col = AggregateColumn(
        label="last_appt",
        relationship="appointments",
        fn="max",
        aggregate_field="start_time",
        sub_filters=(FieldCondition(field="status", op="eq", value="confirmed"),),
    )
    payload = {
        "id": None,
        "name": "X",
        "description": "",
        "root_entity": "patient",
        "conditions": [],
        "columns": [],
        "aggregate_columns": [
            {
                "label": "last_appt",
                "relationship": "appointments",
                "fn": "max",
                "aggregate_field": "start_time",
                "sub_filters": [
                    {"kind": "field", "field": "status", "op": "eq", "value": "confirmed"}
                ],
            }
        ],
        "created_by": "",
        "created_at": "",
        "updated_at": "",
    }
    parsed = report_from_json(payload)
    assert parsed.aggregate_columns[0] == col
    assert report_to_json(parsed) == payload


def test_report_from_json_rejects_non_dict_payload() -> None:
    with pytest.raises(ValueError, match="object"):
        report_from_json("not a dict")  # type: ignore[arg-type]
