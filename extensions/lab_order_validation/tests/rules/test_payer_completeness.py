"""Tests for Rule 3: payer_completeness."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from lab_order_validation.rules import payer_completeness


def test_pass_complete_payer(make_coverage, make_issuer):
    issuer = make_issuer(dbid=1, name="Acme")
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=1, issuer=issuer)]

    assert payer_completeness.check(patient) == []


def test_fail_payer_missing_address(
    make_coverage, make_issuer, make_transactor_phone
):
    issuer = make_issuer(
        dbid=1, name="Acme", addresses=[], phones=[make_transactor_phone()]
    )
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=1, issuer=issuer)]

    errors = payer_completeness.check(patient)

    assert len(errors) == 1
    assert "Acme" in errors[0]
    assert "address" in errors[0]


def test_fail_payer_missing_phone(
    make_coverage, make_issuer, make_transactor_address
):
    issuer = make_issuer(
        dbid=1, name="Acme", addresses=[make_transactor_address()], phones=[]
    )
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=1, issuer=issuer)]

    errors = payer_completeness.check(patient)

    assert len(errors) == 1
    assert "phone" in errors[0]


def test_fail_payer_missing_both(make_coverage, make_issuer):
    issuer = make_issuer(dbid=1, name="Acme", addresses=[], phones=[])
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=1, issuer=issuer)]

    errors = payer_completeness.check(patient)

    assert len(errors) == 1
    assert "address" in errors[0]
    assert "phone" in errors[0]


def test_address_with_missing_fields_does_not_count(
    make_coverage, make_issuer, make_transactor_address, make_transactor_phone
):
    incomplete = make_transactor_address(line1="", city="Boston")
    issuer = make_issuer(
        dbid=1,
        name="Acme",
        addresses=[incomplete],
        phones=[make_transactor_phone()],
    )
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=1, issuer=issuer)]

    errors = payer_completeness.check(patient)

    assert len(errors) == 1
    assert "address" in errors[0]


def test_two_distinct_payers_each_evaluated(
    make_coverage, make_issuer, make_transactor_address, make_transactor_phone
):
    good = make_issuer(dbid=1, name="Good Payer")
    bad = make_issuer(dbid=2, name="Bad Payer", addresses=[], phones=[])
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=good),
        make_coverage(rank=2, issuer=bad),
    ]

    errors = payer_completeness.check(patient)

    assert len(errors) == 1
    assert "Bad Payer" in errors[0]


def test_same_payer_on_two_coverages_only_evaluated_once(
    make_coverage, make_issuer
):
    shared = make_issuer(dbid=42, name="Acme", addresses=[], phones=[])
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=shared),
        make_coverage(rank=2, issuer=shared),
    ]

    errors = payer_completeness.check(patient)

    assert len(errors) == 1


def test_expired_coverage_skipped(make_coverage, make_issuer):
    expired_bad = make_issuer(dbid=1, name="Expired", addresses=[], phones=[])
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(
            rank=1,
            issuer=expired_bad,
            end=date.today() - timedelta(days=1),
        ),
    ]

    assert payer_completeness.check(patient) == []


def test_coverage_without_issuer_skipped(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [make_coverage(rank=1, issuer=None)]

    assert payer_completeness.check(patient) == []
