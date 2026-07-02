"""Tests for the patient demographics snapshot service.

Covers format_date edge cases and the telecom filtering logic inside
patient_demographics. Patient objects are mocked so no database access is
needed for the pure snapshot path. canvas_demographics_by_id is tested via
the ORM.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from canvas_sdk.v1.data.common import ContactPointSystem, ContactPointUse

from salesforce_to_canvas_integration.services.patient_snapshot import (
    format_date,
    patient_demographics,
)


def _mock_cp(
    system: str,
    use: str | None,
    value: str,
    rank: int | None = None,
) -> MagicMock:
    cp = MagicMock()
    cp.system = system
    cp.use = use
    cp.value = value
    cp.rank = rank
    return cp


def _mock_patient(telecom: list = (), addresses: list = ()) -> MagicMock:
    patient = MagicMock()
    patient.telecom.all.return_value = list(telecom)
    patient.addresses.all.return_value = list(addresses)
    patient.first_name = ""
    patient.last_name = ""
    patient.birth_date = None
    patient.sex_at_birth = ""
    return patient


# --- format_date ---


def test_format_date_returns_isoformat_for_date_object() -> None:
    assert format_date(date(1990, 6, 15)) == "1990-06-15"


def test_format_date_returns_empty_string_for_none() -> None:
    assert format_date(None) == ""


def test_format_date_coerces_non_date_to_string() -> None:
    assert format_date("custom-value") == "custom-value"
    assert format_date(12345) == "12345"


# --- patient_demographics ---


def test_patient_demographics_returns_empty_dict_for_none() -> None:
    assert patient_demographics(None) == {}


def test_patient_demographics_handles_telecom_with_null_rank() -> None:
    phone = _mock_cp(ContactPointSystem.PHONE, ContactPointUse.HOME, "555-1234", rank=None)
    patient = _mock_patient(telecom=[phone])
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.birth_date = date(1990, 1, 1)
    patient.sex_at_birth = "F"

    result = patient_demographics(patient)

    assert result["first_name"] == "Jane"
    assert result["phone"] == "555-1234"
    assert result["date_of_birth"] == "1990-01-01"


def test_patient_demographics_splits_phone_and_mobile() -> None:
    phone = _mock_cp(ContactPointSystem.PHONE, ContactPointUse.HOME, "555-home", rank=1)
    mobile = _mock_cp(ContactPointSystem.PHONE, ContactPointUse.MOBILE, "555-mobile", rank=2)
    patient = _mock_patient(telecom=[phone, mobile])

    result = patient_demographics(patient)

    assert result["phone"] == "555-home"
    assert result["mobile"] == "555-mobile"


def test_patient_demographics_returns_empty_phone_when_no_phone_telecom() -> None:
    email = _mock_cp(ContactPointSystem.EMAIL, None, "jane@example.com", rank=1)
    patient = _mock_patient(telecom=[email])

    result = patient_demographics(patient)

    assert result["phone"] == ""
    assert result["mobile"] == ""
    assert result["email"] == "jane@example.com"


def test_patient_demographics_returns_empty_when_no_telecom() -> None:
    patient = _mock_patient(telecom=[])

    result = patient_demographics(patient)

    assert result["phone"] == ""
    assert result["mobile"] == ""
    assert result["email"] == ""
