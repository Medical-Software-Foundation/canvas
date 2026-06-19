from questionnaire_scoring_dashboard.services.scoring import build_series


def _row(name, value, eff=None, created="2026-01-01T00:00:00+00:00", note_id=None, code=None):
    return {
        "name": name,
        "value": value,
        "effective_datetime": eff,
        "created": created,
        "note_id": note_id,
        "code": code,
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


def test_build_series_merges_versioned_questionnaire_names():
    # When a questionnaire is edited, Canvas appends "(vN)" to the name but keeps
    # the code. Both versions must collapse onto one trend, not split into two.
    rows = [
        _row("PHQ-2", "5", eff="2026-01-01T00:00:00+00:00", code="55758-7"),
        _row("PHQ-2 (v28)", "2", eff="2026-02-01T00:00:00+00:00", code="55758-7"),
    ]
    series = build_series(rows)
    assert list(series.keys()) == ["PHQ-2"]
    assert [p["value"] for p in series["PHQ-2"]] == [5.0, 2.0]


def test_build_series_merges_versions_when_name_only_differs_by_suffix():
    # Even with no coding, the version suffix alone is stripped so versions merge.
    rows = [
        _row("Custom Scale", "1", eff="2026-01-01T00:00:00+00:00"),
        _row("Custom Scale (v3)", "2", eff="2026-02-01T00:00:00+00:00"),
    ]
    series = build_series(rows)
    assert list(series.keys()) == ["Custom Scale"]
    assert len(series["Custom Scale"]) == 2


def test_build_series_keeps_instruments_sharing_a_generic_code_separate():
    # Some questionnaires share a generic scoring code (e.g. "default_score").
    # A shared code must NOT merge two distinct instruments into one trend.
    rows = [
        _row("Falls Risk Assessment", "80", eff="2026-01-01T00:00:00+00:00", code="default_score"),
        _row("Insomnia Severity Index", "12", eff="2026-01-01T00:00:00+00:00", code="default_score"),
    ]
    series = build_series(rows)
    assert set(series.keys()) == {"Falls Risk Assessment", "Insomnia Severity Index"}


def test_build_series_resolves_label_by_code_when_name_unknown():
    # Name is unrecognized but the coding maps to a known instrument's max score.
    rows = [_row("Local depression form", "12", eff="2026-01-01T00:00:00+00:00", code="44249-1")]
    series = build_series(rows)
    assert "PHQ-9" in series
