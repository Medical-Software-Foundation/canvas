"""Tests for Rule 2: registration_update (duplicate-payer detection)."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from lab_order_validation.rules import registration_update


def _issuer(dbid: int, name: str) -> MagicMock:
    issuer = MagicMock()
    issuer.dbid = dbid
    issuer.name = name
    return issuer


def test_pass_one_active_coverage(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=_issuer(1, "Acme")),
    ]

    assert registration_update.check(patient) == []


def test_pass_two_distinct_payers(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=_issuer(1, "Acme")),
        make_coverage(rank=2, issuer=_issuer(2, "Globex")),
    ]

    assert registration_update.check(patient) == []


def test_fail_two_coverages_same_payer(make_coverage):
    duplicate = _issuer(99, "Acme Health")
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=duplicate),
        make_coverage(rank=2, issuer=duplicate),
    ]

    errors = registration_update.check(patient)

    assert len(errors) == 1
    assert "Acme Health" in errors[0]
    assert "Coverages tab" in errors[0]


def test_expired_duplicate_does_not_trigger(make_coverage):
    duplicate = _issuer(7, "Acme")
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=duplicate),
        make_coverage(
            rank=2,
            issuer=duplicate,
            end=date.today() - timedelta(days=1),
        ),
    ]

    assert registration_update.check(patient) == []


def test_coverage_without_issuer_ignored(make_coverage):
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=_issuer(1, "Acme")),
        make_coverage(rank=2, issuer=None),
    ]

    assert registration_update.check(patient) == []


def test_no_coverages_passes():
    patient = MagicMock()
    patient.coverages.all.return_value = []

    assert registration_update.check(patient) == []


def test_deleted_duplicate_does_not_trigger(make_coverage):
    """If one of the duplicates was removed in the UI, the rule should not fire."""
    payer = _issuer(1, "Acme")
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=payer),
        make_coverage(rank=2, issuer=payer, state="deleted"),
    ]

    assert registration_update.check(patient) == []


def test_payer_name_sanitized_in_error(make_coverage):
    """Duplicate-payer error message should sanitize control chars in the payer name."""
    payer = _issuer(1, "Acme\x00\x1fHealth")
    patient = MagicMock()
    patient.coverages.all.return_value = [
        make_coverage(rank=1, issuer=payer),
        make_coverage(rank=2, issuer=payer),
    ]

    errors = registration_update.check(patient)

    assert len(errors) == 1
    assert "\x00" not in errors[0]
    assert "\x1f" not in errors[0]
    assert "AcmeHealth" in errors[0]
