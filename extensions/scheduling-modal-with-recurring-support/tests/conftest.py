from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_staff_ca():
    staff = MagicMock()
    staff.id = "staff-001"
    staff.full_name = "Dr. Alice Smith"
    staff.npi_number = "1234567890"
    staff.active = True

    lic = MagicMock()
    lic.state = "CA"
    lic.expiration_date = None
    staff.licenses.all.return_value = [lic]

    return staff


@pytest.fixture
def mock_staff_ny():
    staff = MagicMock()
    staff.id = "staff-002"
    staff.full_name = "Dr. Bob Jones"
    staff.npi_number = "0987654321"
    staff.active = True

    lic = MagicMock()
    lic.state = "NY"
    lic.expiration_date = None
    staff.licenses.all.return_value = [lic]

    return staff


@pytest.fixture
def mock_patient_ca():
    patient = MagicMock()
    patient.id = "patient-abc"

    address = MagicMock()
    address.state_code = "CA"
    address.use = "home"

    patient.addresses.filter.return_value.first.return_value = address
    patient.addresses.first.return_value = address

    return patient
