"""Tests for Rule 1: coverage_sequence."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from lab_order_validation.rules import coverage_sequence


def test_pass_with_single_primary_coverage(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=1)]

    errors = coverage_sequence.check(patient)

    assert errors == []
    assert patient.mock_calls == [
        ("coverages.all", (), {}),
    ]


def test_pass_with_primary_and_secondary(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1),
        make_coverage(rank=2),
    ]

    errors = coverage_sequence.check(patient)

    assert errors == []


def test_pass_with_no_coverages_at_all():
    """Self-pay patients with zero coverages should pass Rule 1."""
    patient = MagicMock()
    patient.coverages.all.return_value = []

    errors = coverage_sequence.check(patient)

    assert errors == []


def test_pass_when_only_coverage_is_expired(make_coverage):
    """Expired coverage counts as no-active; rule is a no-op."""
    expired = make_coverage(
        rank=1,
        end=date.today() - timedelta(days=10),
    )
    patient = MagicMock()
    patient.coverages.all.return_value = [expired]

    errors = coverage_sequence.check(patient)

    assert errors == []


def test_pass_when_only_coverage_is_future_dated(make_coverage):
    """Future-dated coverage counts as no-active; rule is a no-op."""
    future = make_coverage(
        rank=1,
        start=date.today() + timedelta(days=30),
    )
    patient = MagicMock()
    patient.coverages.all.return_value = [future]

    errors = coverage_sequence.check(patient)

    assert errors == []


def test_fail_no_primary_when_only_secondary(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=2)]

    errors = coverage_sequence.check(patient)

    assert len(errors) == 1
    assert "primary coverage" in errors[0]


def test_fail_duplicate_primary_ranks(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1),
        make_coverage(rank=1),
    ]

    errors = coverage_sequence.check(patient)

    assert len(errors) == 1
    assert "Duplicate coverage ranks" in errors[0]
    assert "1" in errors[0]


def test_fail_duplicate_secondary_ranks(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1),
        make_coverage(rank=2),
        make_coverage(rank=2),
    ]

    errors = coverage_sequence.check(patient)

    assert len(errors) == 1
    assert "Duplicate coverage ranks" in errors[0]
    assert "2" in errors[0]


def test_coverage_with_null_rank_ignored(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1),
        make_coverage(rank=None),
    ]

    errors = coverage_sequence.check(patient)

    assert errors == []


def test_deleted_coverage_treated_as_no_active(make_coverage):
    """A removed (state=deleted) coverage should not trigger Rule 1."""
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, state="deleted"),
    ]

    errors = coverage_sequence.check(patient)

    assert errors == []


def test_only_deleted_alongside_self_pay_passes(make_coverage):
    """A user removed their only coverage; patient is now effectively self-pay."""
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=2, state="deleted"),
    ]

    errors = coverage_sequence.check(patient)

    assert errors == []


def test_active_coverage_alongside_deleted_uses_only_active(make_coverage):
    """Deleted coverage with no rank should not cause a 'missing primary' error."""
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, state="active"),
        make_coverage(rank=None, state="deleted"),
    ]

    errors = coverage_sequence.check(patient)

    assert errors == []
