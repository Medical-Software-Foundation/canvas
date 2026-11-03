"""Tests for the HCC problem-list-hygiene protocol."""

from unittest.mock import MagicMock

import arrow
from pytest_mock import MockerFixture

from protocols.hcc001v1_problem_list_hygiene import Hcc001v1


def make_condition(
    icd10: str = "I429",
    assessed_at: str | None = "2018-08-22T13:24:56Z",
    modified_at: str = "2018-08-22T13:24:56Z",
    created_at: str = "2018-05-22T13:24:56Z",
) -> MagicMock:
    """Build a mock Condition with one ICD-10 coding and (optionally) one assessment."""
    coding = MagicMock()
    coding.system = "ICD-10"
    coding.code = icd10

    codings = MagicMock()
    codings.filter.return_value.first.return_value = coding

    assessments = MagicMock()
    assessments.order_by.return_value.values_list.return_value.first.return_value = (
        arrow.get(assessed_at).datetime if assessed_at else None
    )

    condition = MagicMock()
    condition.codings = codings
    condition.assessments = assessments
    condition.modified = arrow.get(modified_at).datetime
    condition.created = arrow.get(created_at).datetime
    return condition


def make_handler(
    mocker: MockerFixture,
    conditions: list[MagicMock],
    override: MagicMock | None = None,
    now: arrow.Arrow | None = None,
) -> Hcc001v1:
    """Construct a Hcc001v1 with patched DB managers."""
    handler = Hcc001v1(event=MagicMock())
    handler.now = now or arrow.get("2018-09-23T13:24:56Z")
    handler._patient_id = "patient-123"

    condition_objects = mocker.patch(
        "protocols.hcc001v1_problem_list_hygiene.Condition.objects"
    )
    condition_objects.for_patient.return_value.find.return_value.active.return_value = (
        conditions
    )

    override_objects = mocker.patch(
        "protocols.hcc001v1_problem_list_hygiene.ProtocolOverride.objects"
    )
    override_objects.for_patient.return_value.committed.return_value.filter.return_value.order_by.return_value.first.return_value = override

    return handler


# --------------------------------------------------------------------------- #
# Meta and RESPONDS_TO
# --------------------------------------------------------------------------- #


def test_meta_description() -> None:
    """The protocol's user-facing description should match the legacy CQM."""
    assert (
        Hcc001v1.Meta.description
        == "All patients with active condition not assessed within the last year."
    )


def test_meta_identifiers() -> None:
    """The protocol should still be identified as HCC001v1."""
    assert Hcc001v1.Meta.identifiers == ["HCC001v1"]


def test_meta_information_link() -> None:
    """The information link should point at the help-center article."""
    assert "9943822292-protocol-problem-list-hygiene" in Hcc001v1.Meta.information


def test_responds_to_condition_and_protocol_override_events() -> None:
    """The legacy CHANGE_CONDITION/CHANGE_PROTOCOL_OVERRIDE map to these SDK event names."""
    assert set(Hcc001v1.RESPONDS_TO) == {
        "CONDITION_CREATED",
        "CONDITION_UPDATED",
        "CONDITION_ASSESSED",
        "CONDITION_RESOLVED",
        "PROTOCOL_OVERRIDE_CREATED",
        "PROTOCOL_OVERRIDE_UPDATED",
        "PROTOCOL_OVERRIDE_DELETED",
    }


# --------------------------------------------------------------------------- #
# hcc_assessments
# --------------------------------------------------------------------------- #


def test_hcc_assessments_extracts_icd10_and_assessment_date(mocker: MockerFixture) -> None:
    """The handler should produce one (ICD-10, date) record per active HCC condition."""
    cond = make_condition(icd10="I429", assessed_at="2018-08-22T23:09:00Z")
    handler = make_handler(mocker, conditions=[cond])

    result = handler.hcc_assessments

    assert len(result) == 1
    assert result[0]["ICD10"] == "I429"
    assert result[0]["date"] == arrow.get("2018-08-22T23:09:00Z")


def test_hcc_assessments_falls_back_to_modified_when_no_assessment(
    mocker: MockerFixture,
) -> None:
    """Conditions without an Assessment fall back to the Condition's modified timestamp."""
    cond = make_condition(
        icd10="I429",
        assessed_at=None,
        modified_at="2018-07-01T00:00:00Z",
    )
    handler = make_handler(mocker, conditions=[cond])

    result = handler.hcc_assessments

    assert len(result) == 1
    assert result[0]["date"] == arrow.get("2018-07-01T00:00:00Z")


def test_hcc_assessments_skips_conditions_without_icd10(mocker: MockerFixture) -> None:
    """Conditions with no ICD-10 coding are ignored."""
    cond = make_condition()
    cond.codings.filter.return_value.first.return_value = None
    handler = make_handler(mocker, conditions=[cond])

    assert handler.hcc_assessments == []


# --------------------------------------------------------------------------- #
# overdue_assessments + timeframe overrides
# --------------------------------------------------------------------------- #


def test_overdue_assessments_uses_one_year_window_by_default(mocker: MockerFixture) -> None:
    """Assessments older than one year before ``now`` are overdue."""
    fresh = make_condition(icd10="I429", assessed_at="2018-08-22T13:24:56Z")
    stale = make_condition(icd10="I427", assessed_at="2017-08-22T13:24:56Z")
    handler = make_handler(
        mocker,
        conditions=[fresh, stale],
        now=arrow.get("2018-09-23T13:24:56Z"),
    )

    overdue_codes = {item["ICD10"] for item in handler.overdue_assessments}
    assert overdue_codes == {"I427"}


def test_overdue_assessments_honours_protocol_override_cycle(mocker: MockerFixture) -> None:
    """A 180-day override shrinks the window so more conditions fall outside it."""
    fresh = make_condition(icd10="I429", assessed_at="2018-08-05T13:24:56Z")
    just_outside = make_condition(icd10="I427", assessed_at="2018-01-01T00:00:00Z")
    override = MagicMock()
    override.cycle_in_days = 180

    handler = make_handler(
        mocker,
        conditions=[fresh, just_outside],
        override=override,
        now=arrow.get("2018-08-15T00:00:00Z"),
    )

    overdue_codes = {item["ICD10"] for item in handler.overdue_assessments}
    assert overdue_codes == {"I427"}
    assert handler.timeframe.duration == 180


# --------------------------------------------------------------------------- #
# compute() result branches
# --------------------------------------------------------------------------- #


def test_compute_returns_not_applicable_when_no_active_hcc(mocker: MockerFixture) -> None:
    """Patients with no active HCC conditions get a NOT_APPLICABLE protocol card."""
    handler = make_handler(mocker, conditions=[])

    effects = handler.compute()

    assert len(effects) == 1
    assert '"status": "not_applicable"' in effects[0].payload


def test_compute_returns_satisfied_when_everything_recent(mocker: MockerFixture) -> None:
    """Recent assessments produce a SATISFIED card with a positive due_in."""
    cond = make_condition(icd10="I429", assessed_at="2018-08-22T13:24:56Z")
    handler = make_handler(
        mocker,
        conditions=[cond],
        now=arrow.get("2018-09-23T13:24:56Z"),
    )

    payload = handler.compute()[0].payload

    assert '"status": "satisfied"' in payload
    # 2018-08-22 + 365 days = 2019-08-22; from 2018-09-23 that's 333 days.
    assert '"due_in": 333' in payload


def test_compute_returns_due_with_narrative_and_recommendations(mocker: MockerFixture) -> None:
    """Overdue conditions yield a DUE card with two recommendations."""
    cond = make_condition(icd10="I429", assessed_at="2017-09-22T13:24:56Z")
    handler = make_handler(
        mocker,
        conditions=[cond],
        now=arrow.get("2018-09-23T13:24:56Z"),
    )

    payload = handler.compute()[0].payload

    assert '"status": "due"' in payload
    assert "Cardiomyopathy, unspecified (I429)" in payload
    assert "9/22/17" in payload
    assert "0.368" in payload
    assert payload.count('"type":') == 2
    assert "assess" in payload
    assert "resolveCondition" in payload
    assert '"due_in": -1' in payload


def test_compute_with_override_satisfied(mocker: MockerFixture) -> None:
    """A 180-day override accepts an assessment 80 days old as SATISFIED."""
    cond = make_condition(icd10="I429", assessed_at="2018-08-05T13:24:56Z")
    override = MagicMock()
    override.cycle_in_days = 180
    handler = make_handler(
        mocker,
        conditions=[cond],
        override=override,
        now=arrow.get("2018-08-05T13:24:56Z").shift(days=80),
    )

    payload = handler.compute()[0].payload

    assert '"status": "satisfied"' in payload
    assert '"due_in": 100' in payload  # 180 - 80


def test_compute_with_override_due(mocker: MockerFixture) -> None:
    """A 180-day override flags an assessment 181 days old as DUE."""
    cond = make_condition(icd10="I429", assessed_at="2018-08-05T13:24:56Z")
    override = MagicMock()
    override.cycle_in_days = 180
    handler = make_handler(
        mocker,
        conditions=[cond],
        override=override,
        now=arrow.get("2018-08-05T13:24:56Z").shift(days=181),
    )

    payload = handler.compute()[0].payload

    assert '"status": "due"' in payload
    assert '"due_in": -1' in payload
