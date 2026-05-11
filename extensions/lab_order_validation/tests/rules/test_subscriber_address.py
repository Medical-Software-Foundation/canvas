"""Tests for Rule 5: subscriber_address."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from lab_order_validation.rules import subscriber_address


def _subscriber(
    *,
    id: str = "sub-1",
    full_name: str = "Jane Doe",
    addresses: list | None = None,
) -> MagicMock:
    sub = MagicMock()
    sub.id = id
    sub.full_name = full_name
    sub.first_name = "Jane"
    sub.last_name = "Doe"
    sub.addresses.all.return_value = addresses if addresses is not None else [
        _complete_address()
    ]
    return sub


def _complete_address(
    *,
    line1: str = "1 Maple St",
    city: str = "Boston",
    state_code: str = "MA",
    postal_code: str = "02101",
) -> MagicMock:
    addr = MagicMock()
    addr.line1 = line1
    addr.city = city
    addr.state_code = state_code
    addr.postal_code = postal_code
    return addr


def _coverage(*, subscriber, start=None, end=None) -> MagicMock:
    cov = MagicMock()
    cov.coverage_start_date = start if start is not None else date(2020, 1, 1)
    cov.coverage_end_date = end
    cov.subscriber = subscriber
    return cov


def test_pass_when_subscriber_has_complete_address():
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [_coverage(subscriber=_subscriber())]

    assert subscriber_address.check(patient) == []


def test_fail_when_subscriber_has_no_addresses():
    sub = _subscriber(addresses=[])
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [_coverage(subscriber=sub)]

    errors = subscriber_address.check(patient)

    assert len(errors) == 1
    assert "Jane Doe" in errors[0]
    assert "subscriber" in errors[0].lower()


def test_fail_when_subscriber_address_missing_postal_code():
    sub = _subscriber(addresses=[_complete_address(postal_code="")])
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [_coverage(subscriber=sub)]

    errors = subscriber_address.check(patient)

    assert len(errors) == 1


def test_skip_when_subscriber_is_the_patient_themselves():
    """Self-insured patients are covered by Rule 4 — don't double-report."""
    patient = MagicMock()
    patient.id = "patient-1"
    patient.addresses.all.return_value = []  # Rule 4 would catch this
    self_sub = _subscriber(id="patient-1", addresses=[])
    patient.coverages.all.return_value = [_coverage(subscriber=self_sub)]

    assert subscriber_address.check(patient) == []


def test_two_coverages_same_subscriber_only_one_error():
    sub = _subscriber(addresses=[])
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [
        _coverage(subscriber=sub),
        _coverage(subscriber=sub),
    ]

    errors = subscriber_address.check(patient)

    assert len(errors) == 1


def test_two_distinct_subscribers_each_reported():
    sub_a = _subscriber(id="sub-a", full_name="Alice One", addresses=[])
    sub_b = _subscriber(id="sub-b", full_name="Bob Two", addresses=[])
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [
        _coverage(subscriber=sub_a),
        _coverage(subscriber=sub_b),
    ]

    errors = subscriber_address.check(patient)

    assert len(errors) == 2
    assert any("Alice One" in e for e in errors)
    assert any("Bob Two" in e for e in errors)


def test_expired_coverage_skipped():
    sub = _subscriber(addresses=[])
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [
        _coverage(subscriber=sub, end=date.today() - timedelta(days=1)),
    ]

    assert subscriber_address.check(patient) == []


def test_coverage_without_subscriber_skipped():
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [_coverage(subscriber=None)]

    assert subscriber_address.check(patient) == []


def test_subscriber_without_id_skipped():
    sub = MagicMock()
    sub.id = None
    sub.full_name = "No Identity"
    sub.addresses.all.return_value = []
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [_coverage(subscriber=sub)]

    assert subscriber_address.check(patient) == []


def test_fallback_name_when_full_name_missing():
    sub = MagicMock()
    sub.id = "sub-99"
    del sub.full_name
    sub.first_name = "Alex"
    sub.last_name = "Quinn"
    sub.addresses.all.return_value = []
    patient = MagicMock()
    patient.id = "patient-1"
    patient.coverages.all.return_value = [_coverage(subscriber=sub)]

    errors = subscriber_address.check(patient)

    assert len(errors) == 1
    assert "Alex Quinn" in errors[0]
