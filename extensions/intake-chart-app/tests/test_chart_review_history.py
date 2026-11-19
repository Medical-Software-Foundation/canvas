"""Tests for chart_review history-command pre-fill (PMH / Surgical / Family / Social)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _cmd(id_: str, schema_key: str, data: dict) -> MagicMock:
    return MagicMock(id=id_, schema_key=schema_key, data=data)


def _qs(rows: list) -> MagicMock:
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    qs.__getitem__.return_value = qs  # support chart_review's ``[:MAX_PREFILL_ROWS]`` cap
    qs.__iter__.return_value = iter(rows)
    return qs


def _empty_condition_qs() -> MagicMock:
    """Return a Condition queryset mock that yields no rows."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.prefetch_related.return_value = qs
    qs.order_by.return_value = qs
    qs.__getitem__.return_value = qs
    qs.__iter__.return_value = iter([])
    return qs


def _make_condition(uid: str, display: str, surgical: bool) -> MagicMock:
    """Build a minimal Condition-like object."""
    coding = MagicMock()
    coding.display = display
    coding.code = "C-" + uid
    codings_mgr = MagicMock()
    codings_mgr.all.return_value = [coding]
    codings_mgr.first.return_value = coding  # keep for legacy callers / other tests
    cond = MagicMock()
    cond.id = uid
    cond.surgical = surgical
    cond.onset_date = None
    cond.resolution_date = None
    cond.codings = codings_mgr
    return cond


def _condition_qs(rows: list) -> MagicMock:
    """Return a Condition queryset mock that yields ``rows``."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.prefetch_related.return_value = qs
    qs.order_by.return_value = qs
    qs.__getitem__.return_value = qs
    qs.__iter__.return_value = iter(rows)
    return qs


# ---------------------------------------------------------------------------
# prior_medical_history
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_filters_by_schema_key_and_state(MockCmd, MockCondition, patient_id):
    """Critical: must filter on ``patient__id=`` (relationship traversal) not
    ``patient_id=`` (FK column = integer PK)."""
    from intake_chart_app.data.chart_review import prior_medical_history
    qs = _qs([])
    MockCmd.objects.filter.return_value = qs
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    prior_medical_history(patient_id)
    MockCmd.objects.filter.assert_called_once_with(
        patient__id=patient_id,
        schema_key="medicalHistory",
        state="committed",
        entered_in_error__isnull=True,
    )


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_summarises_condition_date_and_comments(MockCmd, MockCondition, patient_id):
    from intake_chart_app.data.chart_review import prior_medical_history
    rows = [
        _cmd("c-1", "medicalHistory", {
            "past_medical_history": "Asthma",
            "approximate_start_date": "2015",
            "comments": "well-controlled on inhaler",
        }),
    ]
    MockCmd.objects.filter.return_value = _qs(rows)
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    result = prior_medical_history(patient_id)
    assert len(result) == 1
    row = result[0]
    assert row["id"] == "c-1"
    assert "Asthma" in row["summary"]
    assert "(since 2015)" in row["summary"]
    assert "well-controlled" in row["summary"]
    assert row["data"] == rows[0].data


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_drops_rows_with_empty_condition(MockCmd, MockCondition, patient_id):
    from intake_chart_app.data.chart_review import prior_medical_history
    rows = [
        _cmd("c-1", "medicalHistory", {"past_medical_history": ""}),
        _cmd("c-2", "medicalHistory", {"past_medical_history": "  "}),
        _cmd("c-3", "medicalHistory", {"past_medical_history": "Hypothyroidism"}),
    ]
    MockCmd.objects.filter.return_value = _qs(rows)
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    result = prior_medical_history(patient_id)
    assert [r["id"] for r in result] == ["c-3"]


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_handles_coding_dict_for_condition(MockCmd, MockCondition, patient_id):
    """If past_medical_history is stored as a coding dict, we still extract a
    label."""
    from intake_chart_app.data.chart_review import prior_medical_history
    rows = [
        _cmd("c-1", "medicalHistory", {
            "past_medical_history": {"code": "I10", "display": "Hypertension"},
        }),
    ]
    MockCmd.objects.filter.return_value = _qs(rows)
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    result = prior_medical_history(patient_id)
    assert "Hypertension" in result[0]["summary"]


def test_prior_medical_history_blank_patient_id_returns_empty():
    from intake_chart_app.data.chart_review import prior_medical_history
    assert prior_medical_history("") == []


# ---------------------------------------------------------------------------
# prior_surgical_history
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_surgical_history_filters_by_schema_key(MockCmd, MockCondition, patient_id):
    from intake_chart_app.data.chart_review import prior_surgical_history
    qs = _qs([])
    MockCmd.objects.filter.return_value = qs
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    prior_surgical_history(patient_id)
    assert MockCmd.objects.filter.call_args.kwargs["schema_key"] == "surgicalHistory"


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_surgical_history_summarises_procedure_date_comment(MockCmd, MockCondition, patient_id):
    from intake_chart_app.data.chart_review import prior_surgical_history
    rows = [
        _cmd("s-1", "surgicalHistory", {
            "past_surgical_history": "Appendectomy",
            "approximate_date": "2008",
            "comment": "Outpatient, uncomplicated",
        }),
    ]
    MockCmd.objects.filter.return_value = _qs(rows)
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    result = prior_surgical_history(patient_id)
    assert "Appendectomy" in result[0]["summary"]
    assert "(2008)" in result[0]["summary"]
    assert "Outpatient" in result[0]["summary"]


# Family History pre-fill now lives in
# ``intake_chart_app.data.family_history_fhir`` and is exercised by
# ``tests/test_family_history_fhir.py``. The Command-based path was removed
# because Canvas's chart sidebar sources Family History from the FHIR
# ``FamilyMemberHistory`` resource set, which is disjoint from the Command
# table.


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_surfaces_rows_with_only_dates_or_comments(MockCmd, MockCondition, patient_id):
    from intake_chart_app.data.chart_review import prior_medical_history
    rows = [
        _cmd("c-1", "medicalHistory", {"comments": "carried over from intake form"}),
        _cmd("c-2", "medicalHistory", {"approximate_start_date": "2010"}),
    ]
    MockCmd.objects.filter.return_value = _qs(rows)
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    result = prior_medical_history(patient_id)
    assert len(result) == 2
    assert "carried over" in result[0]["summary"]
    assert "(since 2010)" in result[1]["summary"]


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_surgical_history_surfaces_rows_with_only_date_or_comment(MockCmd, MockCondition, patient_id):
    from intake_chart_app.data.chart_review import prior_surgical_history
    rows = [
        _cmd("s-1", "surgicalHistory", {"comment": "performed at outside hospital"}),
    ]
    MockCmd.objects.filter.return_value = _qs(rows)
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    result = prior_surgical_history(patient_id)
    assert len(result) == 1
    assert "(no procedure recorded)" in result[0]["summary"]
    assert "outside hospital" in result[0]["summary"]


# Social History pre-fill is intentionally absent — the modal's Social
# History section is Add-only and the chart sidebar is the source of
# truth, mirroring the Family History posture.


# ---------------------------------------------------------------------------
# Union tests: Condition model rows merged with Command rows
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_unions_condition_and_command(MockCmd, MockCondition, patient_id):
    """prior_medical_history returns rows from both Condition(surgical=False)
    and Command(schema_key=medicalHistory), deduplicated by id."""
    from intake_chart_app.data.chart_review import prior_medical_history
    MockCmd.objects.filter.return_value = _qs([])
    MockCondition.objects.filter.return_value = _condition_qs([
        _make_condition("cond-1", "Type 2 diabetes mellitus", surgical=False),
    ])
    rows = prior_medical_history(patient_id)
    assert len(rows) == 1
    assert rows[0]["id"] == "cond-1"
    assert "Type 2 diabetes mellitus" in rows[0]["summary"]


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_surgical_history_filters_surgical_true(MockCmd, MockCondition, patient_id):
    """prior_surgical_history pulls Condition(surgical=True) plus
    Command(schema_key=surgicalHistory)."""
    from intake_chart_app.data.chart_review import prior_surgical_history
    MockCmd.objects.filter.return_value = _qs([])
    MockCondition.objects.filter.return_value = _condition_qs([
        _make_condition("cond-99", "Arthroscopy of elbow", surgical=True),
    ])
    rows = prior_surgical_history(patient_id)
    assert len(rows) == 1
    assert rows[0]["id"] == "cond-99"
    assert "Arthroscopy of elbow" in rows[0]["summary"]
    # Confirm the Condition filter included surgical=True.
    call_kwargs = MockCondition.objects.filter.call_args.kwargs
    assert call_kwargs["surgical"] is True


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_deduplicates_by_id(MockCmd, MockCondition, patient_id):
    """If a Condition row has the same id as a Command row (shouldn't happen
    in practice but belt-and-suspenders), it appears only once."""
    from intake_chart_app.data.chart_review import prior_medical_history
    # Command row with id "shared-1"
    MockCmd.objects.filter.return_value = _qs([
        _cmd("shared-1", "medicalHistory", {"past_medical_history": "Asthma"}),
    ])
    # Condition row with the same id — should be skipped
    cond = _make_condition("shared-1", "Asthma (duplicate)", surgical=False)
    MockCondition.objects.filter.return_value = _condition_qs([cond])
    rows = prior_medical_history(patient_id)
    assert len(rows) == 1
    assert rows[0]["id"] == "shared-1"
    assert "Asthma" in rows[0]["summary"]
    # The Condition version must not have replaced the Command version.
    assert "duplicate" not in rows[0]["summary"]


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_condition_filter_excludes_surgical_and_retracted(
    MockCmd, MockCondition, patient_id
):
    """The Condition query must set surgical=False, entered_in_error__isnull=True,
    deleted=False, and committer__isnull=False."""
    from intake_chart_app.data.chart_review import prior_medical_history
    MockCmd.objects.filter.return_value = _qs([])
    MockCondition.objects.filter.return_value = _empty_condition_qs()
    prior_medical_history(patient_id)
    call_kwargs = MockCondition.objects.filter.call_args.kwargs
    assert call_kwargs["surgical"] is False
    assert call_kwargs["entered_in_error__isnull"] is True
    assert call_kwargs["deleted"] is False
    assert call_kwargs["committer__isnull"] is False


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_medical_history_dedupes_by_display_text(
    MockCmd, MockCondition, patient_id
):
    """A Command and a Condition row that share the same display label (with
    different row ids) must surface only once, so the modal doesn't repeat the
    same condition twice."""
    from intake_chart_app.data.chart_review import prior_medical_history
    MockCmd.objects.filter.return_value = _qs([
        _cmd("cmd-1", "medicalHistory", {"past_medical_history": "Mixed hyperlipidemia"}),
    ])
    MockCondition.objects.filter.return_value = _condition_qs([
        _make_condition("cond-9", "Mixed hyperlipidemia", surgical=False),
    ])
    rows = prior_medical_history(patient_id)
    assert len(rows) == 1
    assert rows[0]["id"] == "cmd-1"


@patch("intake_chart_app.data.chart_review.Condition")
@patch("intake_chart_app.data.chart_review.Command")
def test_prior_surgical_history_dedupes_by_display_text(
    MockCmd, MockCondition, patient_id
):
    """Same dedup behaviour for surgical history."""
    from intake_chart_app.data.chart_review import prior_surgical_history
    MockCmd.objects.filter.return_value = _qs([
        _cmd("cmd-1", "surgicalHistory", {"past_surgical_history": "Appendectomy"}),
    ])
    MockCondition.objects.filter.return_value = _condition_qs([
        _make_condition("cond-9", "Appendectomy", surgical=True),
    ])
    rows = prior_surgical_history(patient_id)
    assert len(rows) == 1
    assert rows[0]["id"] == "cmd-1"

