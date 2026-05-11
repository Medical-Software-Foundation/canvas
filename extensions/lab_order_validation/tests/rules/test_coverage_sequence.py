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


def test_fail_no_active_coverages():
    patient = MagicMock()
    patient.coverages.all.return_value = []

    errors = coverage_sequence.check(patient)

    assert len(errors) == 1
    assert "No active insurance coverage" in errors[0]


def test_expired_coverage_treated_as_inactive(make_coverage):
    expired = make_coverage(
        rank=1,
        end=date.today() - timedelta(days=10),
    )
    patient = MagicMock()
    patient.coverages.all.return_value = [expired]

    errors = coverage_sequence.check(patient)

    assert len(errors) == 1
    assert "No active insurance coverage" in errors[0]


def test_future_coverage_treated_as_inactive(make_coverage):
    future = make_coverage(
        rank=1,
        start=date.today() + timedelta(days=30),
    )
    patient = MagicMock()
    patient.coverages.all.return_value = [future]

    errors = coverage_sequence.check(patient)

    assert len(errors) == 1
    assert "No active insurance coverage" in errors[0]


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
