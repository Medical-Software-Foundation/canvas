"""Tests for the shared Photon patient-sync helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.v1.data.common import ContactPointSystem

from photon_integration import patient_sync
from photon_integration.client.photon_client import PhotonError

MODULE = "photon_integration.patient_sync"


def _patient(with_phone=True, with_email=True, with_address=True,
             first="Jane", last="Doe", dob=True, sex="F", stored=None):
    patient = MagicMock()
    patient.id = "pt-1"
    patient.first_name = first
    patient.last_name = last
    patient.sex_at_birth = sex
    patient.birth_date = SimpleNamespace(isoformat=lambda: "1990-01-01") if dob else None
    patient.external_identifiers.filter.return_value.first.return_value = (
        SimpleNamespace(value=stored) if stored else None
    )

    def telecom_filter(system):
        result = MagicMock()
        value = None
        if system == ContactPointSystem.PHONE and with_phone:
            value = "+15551234567"
        elif system == ContactPointSystem.EMAIL and with_email:
            value = "jane@example.com"
        result.order_by.return_value.first.return_value = (
            SimpleNamespace(value=value) if value else None
        )
        return result

    patient.telecom.filter.side_effect = telecom_filter
    patient.addresses.first.return_value = (
        SimpleNamespace(line1="1 Main St", line2="", city="Town", state_code="CA",
                        postal_code="90001", country="US")
        if with_address else None
    )
    return patient


def test_build_client_constructs_from_secrets():
    with patch(f"{MODULE}.PhotonClient") as cls:
        patient_sync.build_client(
            {"PHOTON_CLIENT_ID": "c", "PHOTON_CLIENT_SECRET": "s", "PHOTON_ENV": "PRODUCTION"}
        )
    assert cls.call_args.kwargs == {"client_id": "c", "client_secret": "s", "env": "production"}


def test_build_patient_input_happy_path():
    result = patient_sync.build_patient_input(_patient())
    assert result["externalId"] == "pt-1"
    assert result["name"] == {"first": "Jane", "last": "Doe"}
    assert result["sex"] == "FEMALE"
    assert result["phone"] == "+15551234567"
    assert result["email"] == "jane@example.com"
    assert result["address"]["postalCode"] == "90001"


def test_build_patient_input_unknown_sex_when_blank():
    assert patient_sync.build_patient_input(_patient(sex=""))["sex"] == "UNKNOWN"


@pytest.mark.parametrize("kwargs,msg", [
    ({"first": ""}, "name"),
    ({"last": ""}, "name"),
    ({"dob": False}, "date of birth"),
    ({"with_phone": False}, "phone"),
])
def test_build_patient_input_validation(kwargs, msg):
    with pytest.raises(PhotonError, match=msg):
        patient_sync.build_patient_input(_patient(**kwargs))


def test_build_address_none_when_no_address():
    assert patient_sync.build_address(_patient(with_address=False)) is None


def test_resolve_reuses_stored_id_without_creating():
    client = MagicMock()
    photon_id, effect = patient_sync.resolve_photon_patient(_patient(stored="pat_kept"), client)
    assert photon_id == "pat_kept"
    assert effect is None
    client.create_patient.assert_not_called()


def test_resolve_creates_and_persists_when_absent():
    client = MagicMock()
    client.create_patient.return_value = "pat_new"
    with patch(f"{MODULE}.CreatePatientExternalIdentifier") as cpei:
        cpei.return_value.create.return_value = "EXT_EFFECT"
        photon_id, effect = patient_sync.resolve_photon_patient(_patient(), client)
    assert photon_id == "pat_new"
    assert effect == "EXT_EFFECT"
    cpei.assert_called_once_with(
        patient_id="pt-1", system="https://photon.health/patient", value="pat_new"
    )
