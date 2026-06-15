from questionnaire_scoring_dashboard.services.scoring import build_series


def _row(name, value, eff=None, created="2026-01-01T00:00:00+00:00", note_id=None):
    return {
        "name": name,
        "value": value,
        "effective_datetime": eff,
        "created": created,
        "note_id": note_id,
    }


def test_build_series_groups_by_instrument_and_sorts_by_date():
    rows = [
        _row("PHQ-9", "16", eff="2026-01-10T12:00:00+00:00"),
        _row("PHQ-9", "20", eff="2026-01-01T12:00:00+00:00"),
        _row("GAD-7", "8", eff="2026-01-05T12:00:00+00:00"),
    ]
    series = build_series(rows)
    assert set(series.keys()) == {"PHQ-9", "GAD-7"}
    assert [p["value"] for p in series["PHQ-9"]] == [20.0, 16.0]
    assert series["PHQ-9"][0]["date"] == "2026-01-01"
    assert series["GAD-7"][0]["value"] == 8.0


def test_build_series_skips_non_numeric_and_empty_values():
    rows = [
        _row("PHQ-9", "16", eff="2026-01-10T12:00:00+00:00"),
        _row("PHQ-9", "", eff="2026-01-11T12:00:00+00:00"),
        _row("PHQ-9", "n/a", eff="2026-01-12T12:00:00+00:00"),
    ]
    series = build_series(rows)
    assert [p["value"] for p in series["PHQ-9"]] == [16.0]


def test_build_series_uses_effective_then_created_for_date():
    rows = [_row("AUDIT", "5", eff=None, created="2025-12-20T00:00:00+00:00")]
    series = build_series(rows)
    assert series["AUDIT"][0]["date"] == "2025-12-20"


def test_build_series_uses_note_dos_when_no_effective_datetime():
    # Questionnaire-result observations have no effective_datetime; use note DOS.
    row = _row("PHQ-9", "16", eff=None, created="2026-06-15T00:00:00+00:00")
    row["note_dos"] = "2026-03-01T12:00:00+00:00"
    series = build_series([row])
    assert series["PHQ-9"][0]["date"] == "2026-03-01"


def test_build_series_uses_resolved_label():
    rows = [_row("Adult PHQ-9 screen", "9", eff="2026-01-01T00:00:00+00:00")]
    series = build_series(rows)
    assert "PHQ-9" in series


def test_build_series_unknown_instrument_uses_raw_name():
    rows = [_row("Custom Scale X", "3", eff="2026-01-01T00:00:00+00:00")]
    series = build_series(rows)
    assert "Custom Scale X" in series


def test_build_series_dedupes_one_point_per_date():
    # Two PHQ-9 scores on the same date (double-scored) collapse to one point.
    rows = [
        _row("PHQ-9", "16", eff="2026-03-01T09:00:00+00:00"),
        _row("PHQ-9", "15", eff="2026-03-01T17:00:00+00:00"),
        _row("PHQ-9", "12", eff="2026-05-30T09:00:00+00:00"),
    ]
    series = build_series(rows)
    dates = [p["date"] for p in series["PHQ-9"]]
    assert dates == ["2026-03-01", "2026-05-30"]  # one point per date


def test_build_series_resolves_loinc_code_named_observation():
    # If a scored observation is named by its LOINC code, it still maps to the instrument.
    rows = [_row("44249-1", "12", eff="2026-01-01T00:00:00+00:00")]
    series = build_series(rows)
    assert "PHQ-9" in series
