"""Tests for Rule 4: patient_address (must be home + Postal/Both)."""

from unittest.mock import MagicMock

from lab_order_validation.rules import patient_address


def test_pass_home_postal(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="home", type="postal"),
    ]

    assert patient_address.check(patient) == []


def test_pass_home_both(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="home", type="both"),
    ]

    assert patient_address.check(patient) == []


def test_fail_home_physical_only(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="home", type="physical"),
    ]

    errors = patient_address.check(patient)

    assert len(errors) == 1
    assert "Postal" in errors[0]


def test_fail_no_addresses_at_all():
    patient = MagicMock()
    patient.addresses.all.return_value = []

    errors = patient_address.check(patient)

    assert len(errors) == 1
    assert "no address on file" in errors[0].lower()


def test_fail_only_work_postal_no_home(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="work", type="postal"),
    ]

    errors = patient_address.check(patient)

    assert len(errors) == 1
    assert "Postal" in errors[0]


def test_pass_when_one_of_many_qualifies(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="work", type="postal"),
        make_patient_address(use="home", type="physical"),
        make_patient_address(use="home", type="both"),
    ]

    assert patient_address.check(patient) == []


def test_fail_home_postal_missing_line1(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="home", type="postal", line1=""),
    ]

    errors = patient_address.check(patient)

    assert len(errors) == 1


def test_fail_home_postal_missing_postal_code(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="home", type="postal", postal_code=""),
    ]

    errors = patient_address.check(patient)

    assert len(errors) == 1


def test_use_and_type_normalized_case_insensitive(make_patient_address):
    patient = MagicMock()
    patient.addresses.all.return_value = [
        make_patient_address(use="HOME", type="POSTAL"),
    ]

    assert patient_address.check(patient) == []


def test_enum_like_object_with_value_attribute_supported():
    use_enum = MagicMock()
    use_enum.value = "home"
    type_enum = MagicMock()
    type_enum.value = "both"

    addr = MagicMock()
    addr.use = use_enum
    addr.type = type_enum
    addr.line1 = "1 Main St"
    addr.city = "Boston"
    addr.state_code = "MA"
    addr.postal_code = "02101"

    patient = MagicMock()
    patient.addresses.all.return_value = [addr]

    assert patient_address.check(patient) == []
