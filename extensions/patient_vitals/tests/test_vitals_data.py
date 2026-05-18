"""Unit tests for the pure data layer in patient_vitals.vitals_data.

We patch ``vitals_data._query_vitals`` to return a list of mock observations so
the ORM is never touched. The DB-integration layer is out of scope here.
"""

from datetime import datetime, timedelta, timezone

import pytest

from patient_vitals import vitals_data
from patient_vitals.vitals_data import (
    UnknownVitalCode,
    VITAL_CATALOG,
    _format_display_value,
    _normalize_point,
    _oz_to_lbs,
    _resolve_canonicals,
    _split_bp,
    aggregate_summary,
    history_for_code,
)


# ---------- BP split helper ------------------------------------------------


def test_split_bp_valid() -> None:
    """A clean numeric BP string splits into two floats."""
    assert _split_bp("120/80") == (120.0, 80.0)


def test_split_bp_handles_whitespace() -> None:
    """Whitespace around components is tolerated."""
    assert _split_bp(" 120 / 80 ") == (120.0, 80.0)


@pytest.mark.parametrize("value", ["abc", "", "120", None, "120/", "/80", "120/abc"])
def test_split_bp_invalid_returns_none(value: str | None) -> None:
    """Any unparseable input yields None rather than raising."""
    assert _split_bp(value) is None


# ---------- oz -> lbs ------------------------------------------------------


def test_oz_to_lbs_basic() -> None:
    """184 lb is 2944 oz."""
    assert _oz_to_lbs("2944") == 184.0


def test_oz_to_lbs_handles_numeric_input() -> None:
    """Numeric inputs convert just as strings do."""
    assert _oz_to_lbs(160) == 10.0


@pytest.mark.parametrize("value", [None, "abc", ""])
def test_oz_to_lbs_invalid_returns_none(value: str | None) -> None:
    """Bad input returns None."""
    assert _oz_to_lbs(value) is None


# ---------- format helper --------------------------------------------------


def test_format_display_value_zero_precision() -> None:
    """Zero precision rounds to whole numbers."""
    assert _format_display_value(72.6, 0) == "73"


def test_format_display_value_one_decimal() -> None:
    """One-decimal precision matches catalog convention for weight."""
    assert _format_display_value(184.4, 1) == "184.4"


# ---------- canonical resolution ------------------------------------------


def test_resolve_canonicals_by_loinc(make_observation) -> None:
    """A LOINC-coded obs resolves to the matching catalog key."""
    obs = make_observation(loinc="8867-4")
    assert _resolve_canonicals(obs) == {"pulse"}


def test_resolve_canonicals_by_name_fallback(make_observation) -> None:
    """When no coding is present, fall back to the obs.name field."""
    obs = make_observation(name="pulse")
    assert _resolve_canonicals(obs) == {"pulse"}


def test_resolve_canonicals_name_is_case_insensitive(make_observation) -> None:
    """Name fallback should not be brittle to casing."""
    obs = make_observation(name="Pulse")
    assert _resolve_canonicals(obs) == {"pulse"}


def test_resolve_canonicals_returns_empty_for_unknown(make_observation) -> None:
    """Unknown LOINC + unknown name yields the empty set."""
    obs = make_observation(loinc="99999-9", name="not-a-vital")
    assert _resolve_canonicals(obs) == set()


def test_resolve_canonicals_prefers_loinc_over_name(make_observation) -> None:
    """A correct LOINC wins over a misleading name field."""
    obs = make_observation(loinc="8867-4", name="weight")
    assert _resolve_canonicals(obs) == {"pulse"}


# ---------- normalize point ------------------------------------------------


def test_normalize_point_basic_numeric(make_observation) -> None:
    """A pulse reading of '72' renders as '72' with chart value 72.0."""
    obs = make_observation(loinc="8867-4", value="72")
    point = _normalize_point(obs, "pulse")
    assert point is not None
    assert point["display_value"] == "72"
    assert point["chart_value"] == 72.0


def test_normalize_point_weight_oz_to_lbs(make_observation) -> None:
    """Weight stored as 2944 oz renders as '184.0' lbs."""
    obs = make_observation(loinc="29463-7", value="2944")
    point = _normalize_point(obs, "weight")
    assert point is not None
    assert point["display_value"] == "184.0"
    assert point["chart_value"] == 184.0


def test_normalize_point_bp(make_observation) -> None:
    """BP renders as 'systolic/diastolic' with tuple chart value."""
    obs = make_observation(loinc="85354-9", value="120/80")
    point = _normalize_point(obs, "blood_pressure")
    assert point is not None
    assert point["display_value"] == "120/80"
    assert point["chart_value"] == (120.0, 80.0)


def test_normalize_point_unparseable_bp(make_observation) -> None:
    """A BP obs with a malformed value yields None (skip, do not raise)."""
    obs = make_observation(loinc="85354-9", value="not-a-bp")
    assert _normalize_point(obs, "blood_pressure") is None


# ---------- aggregate_summary ---------------------------------------------


def _patch_query(monkeypatch: pytest.MonkeyPatch, observations: list) -> None:
    """Helper: short-circuit ``_query_vitals`` to return the given list.

    The fake ignores narrowing kwargs (``loincs``/``names``) because the
    in-Python ``_resolve_canonicals`` filter in callers still excludes
    unrelated rows, and these unit tests are about Python-side aggregation,
    not DB-layer narrowing.
    """

    def fake_query(patient_id, limit_hint=None, **_kwargs):
        # Honour the limit_hint so the cap test exercises real bounds.
        return observations if limit_hint is None else observations[:limit_hint]

    monkeypatch.setattr(vitals_data, "_query_vitals", fake_query)


def test_aggregate_summary_basic(make_observation, monkeypatch) -> None:
    """Two distinct vital codes produce two summary entries with right counts."""
    later = datetime(2026, 5, 2, tzinfo=timezone.utc)
    earlier = datetime(2026, 4, 1, tzinfo=timezone.utc)
    obs_list = [
        make_observation(loinc="8867-4", value="72", effective_datetime=later),
        make_observation(loinc="8867-4", value="70", effective_datetime=earlier),
        make_observation(loinc="29463-7", value="2944", effective_datetime=later),
    ]
    _patch_query(monkeypatch, obs_list)

    summary = aggregate_summary("patient-123")

    assert {row["code"] for row in summary} == {"pulse", "weight"}
    pulse = next(row for row in summary if row["code"] == "pulse")
    assert pulse["reading_count"] == 2
    assert pulse["latest_value"] == "72"
    assert pulse["latest_recorded_at"] == later.isoformat()
    weight = next(row for row in summary if row["code"] == "weight")
    assert weight["reading_count"] == 1
    assert weight["latest_value"] == "184.0"


def test_aggregate_summary_bp_combined_string(make_observation, monkeypatch) -> None:
    """Combined-string BP yields the raw value as the tile display."""
    obs_list = [make_observation(loinc="85354-9", value="120/80")]
    _patch_query(monkeypatch, obs_list)

    summary = aggregate_summary("patient-123")

    assert len(summary) == 1
    assert summary[0]["code"] == "blood_pressure"
    assert summary[0]["latest_value"] == "120/80"
    assert summary[0]["latest_unit"] == "mmHg"
    assert summary[0]["reading_count"] == 1


def test_aggregate_summary_caps_each_code_at_100(make_observation, monkeypatch) -> None:
    """A code with 150 readings is truncated to PER_CODE_CAP (100)."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    obs_list = [
        make_observation(
            loinc="8867-4",
            value="72",
            effective_datetime=start + timedelta(days=i),
        )
        for i in range(150)
    ]
    _patch_query(monkeypatch, obs_list)

    summary = aggregate_summary("patient-123")

    assert len(summary) == 1
    assert summary[0]["reading_count"] == vitals_data.PER_CODE_CAP


def test_aggregate_summary_empty_when_no_vitals(monkeypatch) -> None:
    """No readings → empty summary list."""
    _patch_query(monkeypatch, [])
    assert aggregate_summary("patient-123") == []


def test_aggregate_summary_skips_unknown_codes(make_observation, monkeypatch) -> None:
    """Observations whose code/name aren't catalogued are silently skipped."""
    obs_list = [
        make_observation(loinc="99999-9", value="42"),
        make_observation(loinc="8867-4", value="72"),
    ]
    _patch_query(monkeypatch, obs_list)

    summary = aggregate_summary("patient-123")
    assert [row["code"] for row in summary] == ["pulse"]


# ---------- history_for_code ----------------------------------------------


def test_history_unknown_code_raises() -> None:
    """An unknown code raises UnknownVitalCode rather than 500-ing."""
    with pytest.raises(UnknownVitalCode):
        history_for_code("patient-123", "not_a_code")


def test_history_none_code_raises() -> None:
    """A missing code (None) is treated as unknown."""
    with pytest.raises(UnknownVitalCode):
        history_for_code("patient-123", None)


def test_history_bp_two_series_in_ascending_order(
    make_observation, monkeypatch
) -> None:
    """BP history returns systolic + diastolic series, time-ordered ascending."""
    later = datetime(2026, 5, 2, tzinfo=timezone.utc)
    earlier = datetime(2026, 4, 1, tzinfo=timezone.utc)
    obs_list = [
        make_observation(loinc="85354-9", value="124/82", effective_datetime=later),
        make_observation(loinc="85354-9", value="120/80", effective_datetime=earlier),
    ]
    _patch_query(monkeypatch, obs_list)

    payload = history_for_code("patient-123", "blood_pressure")

    assert payload["code"] == "blood_pressure"
    assert payload["unit"] == "mmHg"
    assert [s["label"] for s in payload["series"]] == ["Systolic", "Diastolic"]
    systolic = payload["series"][0]["points"]
    diastolic = payload["series"][1]["points"]
    assert [p["value"] for p in systolic] == [120.0, 124.0]
    assert [p["value"] for p in diastolic] == [80.0, 82.0]


def test_history_single_series_for_pulse(make_observation, monkeypatch) -> None:
    """Non-BP codes produce one series labelled with the catalog display name."""
    obs_list = [
        make_observation(loinc="8867-4", value="72"),
        make_observation(loinc="8867-4", value="70"),
    ]
    _patch_query(monkeypatch, obs_list)

    payload = history_for_code("patient-123", "pulse")

    assert len(payload["series"]) == 1
    assert payload["series"][0]["label"] == "Pulse"
    assert len(payload["series"][0]["points"]) == 2


def test_history_no_readings_returns_empty_points(monkeypatch) -> None:
    """A valid code with no readings yields a single empty series."""
    _patch_query(monkeypatch, [])

    payload = history_for_code("patient-123", "pulse")

    assert payload["series"] == [{"label": "Pulse", "points": []}]


def test_history_excludes_unparseable_bp(make_observation, monkeypatch) -> None:
    """A garbled BP value is filtered out instead of crashing the response."""
    obs_list = [
        make_observation(loinc="85354-9", value="garbage"),
        make_observation(loinc="85354-9", value="120/80"),
    ]
    _patch_query(monkeypatch, obs_list)

    payload = history_for_code("patient-123", "blood_pressure")

    assert len(payload["series"][0]["points"]) == 1
    assert payload["series"][0]["points"][0]["value"] == 120.0


# ---------- DB narrowing --------------------------------------------------


def test_history_narrows_query_to_single_loinc_and_names(monkeypatch) -> None:
    """history_for_code must pass the code's LOINC + names to _query_vitals.

    Without this narrowing, the endpoint would fetch every vital row for the
    patient and then discard all but one code's worth — back to the pre-fix
    behaviour.
    """
    captured: dict = {}

    def fake_query(patient_id, limit_hint=None, *, loincs=None, names=None):
        captured["patient_id"] = patient_id
        captured["limit_hint"] = limit_hint
        captured["loincs"] = loincs
        captured["names"] = names
        return []

    monkeypatch.setattr(vitals_data, "_query_vitals", fake_query)
    history_for_code("patient-123", "pulse")

    assert captured["loincs"] == ["8867-4"]
    assert captured["names"] == ["pulse"]
    assert captured["limit_hint"] == vitals_data.PER_CODE_CAP


def test_aggregate_summary_narrows_query_to_all_catalog_codes(monkeypatch) -> None:
    """aggregate_summary must narrow to every catalogued LOINC + name set.

    The DB is then expected to do the filtering instead of Python fetching
    unrelated vital rows and discarding them.
    """
    captured: dict = {}

    def fake_query(patient_id, limit_hint=None, *, loincs=None, names=None):
        captured["loincs"] = loincs
        captured["names"] = names
        return []

    monkeypatch.setattr(vitals_data, "_query_vitals", fake_query)
    aggregate_summary("patient-123")

    assert set(captured["loincs"] or []) == {cfg["loinc"] for cfg in VITAL_CATALOG.values()}
    expected_names = {n.lower() for cfg in VITAL_CATALOG.values() for n in cfg["names"]}
    assert set(captured["names"] or []) == expected_names


# ---------- catalog sanity -------------------------------------------------


def test_catalog_has_unique_loinc_codes() -> None:
    """Each canonical key maps to a unique LOINC."""
    codes = [cfg["loinc"] for cfg in VITAL_CATALOG.values()]
    assert len(codes) == len(set(codes))


def test_catalog_contains_all_expected_keys() -> None:
    """Catalog should cover the 11 vital types we promised in the README."""
    expected = {
        "blood_pressure",
        "pulse",
        "body_temperature",
        "weight",
        "height",
        "bmi",
        "oxygen_saturation",
        "respiration_rate",
        "waist_circumference",
        "head_circumference",
        "pain_severity",
    }
    assert set(VITAL_CATALOG.keys()) == expected
